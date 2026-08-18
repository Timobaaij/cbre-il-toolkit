/* runner.js - orchestration, media fetching, and bundle writing.
 *
 * DIVISION OF LABOUR (each half does the one thing only it can):
 *   - Authenticated Kato JSON goes through the CONTENT SCRIPT, because only a request issued from
 *     the page's own origin is same-site enough for Kato's Lax session cookie.
 *   - Media goes through THIS PAGE. It shares the extension origin, so host_permissions grant it the
 *     same CORS bypass a service worker would - and S3 sends no Access-Control-Allow-Origin, so that
 *     bypass is mandatory for brochures. Fetching here rather than in the worker avoids shuttling
 *     megabytes through message passing, which would force base64 and roughly double the cost.
 *
 * GOVERNING RULE: this file ships raw API responses verbatim and interprets nothing about Kato's
 * schema. It locates media by HOST, not by field name, recording the JSON path where each URL was
 * found. derive() in common.py decides which of those URLs actually matter. So when Kato adds or
 * renames a media field, the bytes are already in the bundle and only Python needs a change.
 */

import { ZipWriter, BufferSink } from './zipwriter.js';
import { IMGIX_HOST, isMediaUrl, isImageHost, imgixResize, pickExt } from './mediahosts.js';

// ---------------------------------------------------------------- constants

const EXT_VERSION = chrome.runtime.getManifest().version;
const IMAGE_MAX_PX = 1200;
const IMAGE_MAX_BYTES = 500 * 1024;
const QUALITY_LADDER = [70, 60, 50, 40, 32, 25];
const CONCURRENCY = 4;
const FALLBACK_API_BASE = 'https://agency.kato.app';

// Host rules, resizing and in-zip naming live in mediahosts.js so they can be unit-tested.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmtMB = (b) => `${(b / 1048576).toFixed(1)} MB`;

// ---------------------------------------------------------------- dom

const $ = (id) => document.getElementById(id);
const ui = {
  main: $('main'), errorCard: $('errorCard'), errorText: $('errorText'),
  mReq: $('mReq'), mOrigin: $('mOrigin'), mApi: $('mApi'),
  optionsCard: $('optionsCard'), optDocs: $('optDocs'), optAllRaw: $('optAllRaw'), optPart: $('optPart'),
  start: $('start'), progressCard: $('progressCard'), phase: $('phase'), bar: $('bar'),
  cProps: $('cProps'), cMedia: $('cMedia'), cBytes: $('cBytes'), cFail: $('cFail'),
  savePart: $('savePart'), doneCard: $('doneCard'), doneTitle: $('doneTitle'), doneText: $('doneText'),
  log: $('log'),
};

let failures = 0;
function log(msg, cls) {
  const line = document.createElement('div');
  if (cls) line.className = cls;
  line.textContent = msg;
  ui.log.appendChild(line);
  ui.log.scrollTop = ui.log.scrollHeight;
}
function fail(msg) { failures++; ui.cFail.textContent = String(failures); log(msg, 'bad'); }

// ---------------------------------------------------------------- params

const P = new URLSearchParams(location.search);
const START_ERROR = P.get('error');
const TAB_ID = Number(P.get('tabId'));
const REQ_ID = Number(P.get('reqid'));
const PAGE_ORIGIN = P.get('origin') || '';
const PAGE_URL = P.get('pageUrl') || '';

const ERROR_TEXT = {
  not_kato: 'Open a Kato requirement page first, then click the extension icon. This tab is not on kato.app.',
  no_requirement: 'That Kato page is not a requirement. Open the requirement whose longlist you want, so the address contains /requirements/<number>/, then click the icon again.',
};

if (START_ERROR) {
  ui.errorCard.classList.remove('hidden');
  ui.errorText.textContent = ERROR_TEXT[START_ERROR] || START_ERROR;
} else {
  ui.main.classList.remove('hidden');
  ui.mReq.textContent = String(REQ_ID);
  ui.mOrigin.textContent = PAGE_ORIGIN;
}

// ---------------------------------------------------------------- kato json via content script

async function katoJson(url) {
  try {
    const r = await chrome.tabs.sendMessage(TAB_ID, { type: 'KATO_JSON', url });
    if (!r) return { ok: false, status: 0, error: 'no response from the Kato tab' };
    return r;
  } catch (e) {
    // Most common cause by far: the extension was installed AFTER the Kato tab was loaded, so no
    // content script is running in it yet. A reload fixes it.
    return {
      ok: false, status: 0,
      error: `cannot reach the Kato tab - reload the Kato page and click the icon again (${e})`,
    };
  }
}

const listUrl = (base) => `${base}/api/acquisitions/${REQ_ID}/availability-schedule?order=group_position`;
const detailUrl = (base, id) => `${base}/api/acquisitions/availability-schedule/${id}`;

/** Kato has moved frontends (agency.kato.app -> os.agency.kato.app); probe rather than assume. */
async function resolveApiBase() {
  const candidates = [...new Set([PAGE_ORIGIN, FALLBACK_API_BASE].filter(Boolean))];
  const tried = [];
  for (const base of candidates) {
    const r = await katoJson(listUrl(base));
    tried.push(`${base} -> ${r.ok ? 'ok' : `${r.status || 'error'} ${r.error || ''}`.trim()}`);
    if (r.ok) return { base, list: r.json, tried };
  }
  return { base: null, list: null, tried };
}

// ---------------------------------------------------------------- media discovery (host-based, schema-blind)

/**
 * Walk any JSON shape and collect every URL that lives on a known media host, remembering the sibling
 * "name"/"ext" when the containing object has them and every JSON path the URL appeared at. No Kato
 * field name is hardcoded anywhere in here.
 */
function sweepMedia(node, path, found) {
  if (node === null || typeof node !== 'object') return;
  if (Array.isArray(node)) {
    node.forEach((v, i) => sweepMedia(v, `${path}[${i}]`, found));
    return;
  }
  const name = typeof node.name === 'string' ? node.name : null;
  const ext = typeof node.ext === 'string' ? node.ext : null;
  for (const [k, v] of Object.entries(node)) {
    const p = path ? `${path}.${k}` : k;
    if (typeof v === 'string' && isMediaUrl(v)) {
      const hit = found.get(v);
      if (hit) hit.paths.push(p);
      else found.set(v, { url: v, name, ext, paths: [p] });
    } else {
      sweepMedia(v, p, found);
    }
  }
}

// ---------------------------------------------------------------- media fetching

async function fetchBytes(url) {
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      const r = await fetch(url, { cache: 'no-store', credentials: 'omit' });
      if (r.ok) {
        return {
          ok: true, status: r.status, requestUrl: url,
          bytes: new Uint8Array(await r.arrayBuffer()),
          contentType: (r.headers.get('content-type') || '').split(';')[0].trim(),
        };
      }
      if ([429, 500, 502, 503].includes(r.status) && attempt < 3) { await sleep(1500 * (attempt + 1)); continue; }
      return { ok: false, status: r.status, requestUrl: url, error: `HTTP ${r.status}` };
    } catch (e) {
      if (attempt < 3) { await sleep(1500 * (attempt + 1)); continue; }
      return { ok: false, status: 0, requestUrl: url, error: String(e) };
    }
  }
  return { ok: false, status: 0, requestUrl: url, error: 'exhausted retries' };
}

/** Images: resized at source by imgix, stepping quality down until under 500KB - the same ladder as
 *  kato_fetch.download_image. Documents: fetched as-is. */
async function fetchMedia(entry) {
  if (new URL(entry.url).hostname !== IMGIX_HOST) {
    return { ...(await fetchBytes(entry.url)), kind: 'doc' };
  }
  let last = null;
  for (const q of QUALITY_LADDER) {
    last = await fetchBytes(imgixResize(entry.url, IMAGE_MAX_PX, q));
    if (!last.ok) break;
    if (last.bytes.length <= IMAGE_MAX_BYTES) return { ...last, kind: 'image', quality: q };
  }
  if (last && last.ok) return { ...last, kind: 'image', quality: QUALITY_LADDER[QUALITY_LADDER.length - 1] };
  return { ...(last || { ok: false, status: 0, error: 'no attempt' }), kind: 'image' };
}

// ---------------------------------------------------------------- part / sink management

function bundleName(index, final) {
  const date = new Date().toISOString().slice(0, 10);
  const base = `kato_bundle_${REQ_ID}_${date}`;
  return index === 1 && final ? `${base}.zip` : `${base}_part${index}.zip`;
}

async function openSink(suggestedName) {
  if (typeof window.showSaveFilePicker === 'function') {
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName,
        types: [{ description: 'Kato bundle', accept: { 'application/zip': ['.zip'] } }],
      });
      const stream = await handle.createWritable();
      return { sink: stream, label: handle.name, streamed: true };
    } catch (e) {
      if (e && e.name === 'AbortError') return null;      // user cancelled
      log(`Save dialog unavailable (${e}); falling back to a download.`, 'warn');
    }
  }
  const buf = new BufferSink();
  return { sink: buf, label: suggestedName, streamed: false, buffer: buf };
}

function triggerDownload(buffer, name) {
  const url = URL.createObjectURL(buffer.blob());
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

/** Resolves on the next click of the "Save next part" button, so showSaveFilePicker keeps the user
 *  activation it requires. */
function awaitPartClick() {
  return new Promise((resolve) => {
    ui.savePart.classList.remove('hidden');
    ui.savePart.onclick = () => { ui.savePart.classList.add('hidden'); ui.savePart.onclick = null; resolve(); };
  });
}

// ---------------------------------------------------------------- main capture

async function capture() {
  ui.start.disabled = true;
  ui.optionsCard.classList.add('hidden');
  ui.progressCard.classList.remove('hidden');

  const includeDocs = ui.optDocs.checked;
  const allRaw = ui.optAllRaw.checked;
  const maxPartBytes = Math.max(0, Number(ui.optPart.value) || 0) * 1048576;
  const capturedAt = new Date().toISOString();

  // ---- 1. resolve the API and pull the list
  ui.phase.textContent = 'Resolving the Kato API…';
  const { base, list, tried } = await resolveApiBase();
  if (!base) {
    ui.phase.textContent = 'Could not reach the Kato API.';
    tried.forEach((t) => log(t, 'bad'));
    log('If you were signed out, sign in again and retry. If Kato has changed its API, send this log on.', 'warn');
    return;
  }
  ui.mApi.textContent = base;
  log(`API base: ${base}`);

  const validation = { list_shape_ok: true, detail_shape_ok: null, notes: [] };
  const all = Array.isArray(list?.data) ? list.data : null;
  if (!all) {
    validation.list_shape_ok = false;
    validation.notes.push('list response had no data[] array');
    fail('The list response has no data[] array. Kato may have changed its API; saving what was received.');
  }
  const matches = all || [];
  if (matches.length && !('status' in matches[0] && 'id' in matches[0])) {
    validation.list_shape_ok = false;
    validation.notes.push('list entries lack id/status');
    fail('List entries have no id/status fields. Saving anyway so the change can be diagnosed.');
  }
  const longlist = matches.filter((m) => m?.status === 1);
  const rawTargets = allRaw ? matches : longlist;
  log(`${matches.length} matches, ${longlist.length} on the longlist (status==1).`);

  // ---- 2. open part 1
  let partIndex = 1;
  let opened = await openSink(bundleName(1, maxPartBytes === 0));
  if (!opened) { ui.phase.textContent = 'Cancelled.'; ui.start.disabled = false; ui.optionsCard.classList.remove('hidden'); return; }
  let zip = new ZipWriter(opened.sink);
  const partsSaved = [];
  let bytesBase = 0;

  const finishPart = async (final) => {
    await zip.addJson('part.json', { schema_version: 1, requirement_id: REQ_ID, index: partIndex, final });
    if (final) {
      await zip.addJson('media_index.json', mediaIndex);
      await zip.addJson('manifest.json', buildManifest());
    }
    await zip.close();
    if (!opened.streamed) triggerDownload(opened.buffer, opened.label);
    partsSaved.push(opened.label);
    bytesBase += zip.bytesWritten;
  };

  // ---- 3. details
  await zip.addJson('list.json', list);
  const mediaJobs = [];
  const mediaIndex = {};
  const matchStatus = {};
  const byId = new Map(matches.map((m) => [m.id, m]));

  ui.bar.max = rawTargets.length || 1;
  let doneProps = 0;
  for (const li of rawTargets) {
    ui.phase.textContent = `Reading property details… (${doneProps + 1}/${rawTargets.length})`;
    const r = await katoJson(detailUrl(base, li.id));
    matchStatus[li.id] = { raw: r.ok ? 200 : (r.status || 0) };
    if (!r.ok) {
      fail(`match ${li.id}: detail fetch failed (${r.status || 'error'}) ${r.error || ''}`);
    } else {
      await zip.add(`raw/${li.id}.json`, new TextEncoder().encode(JSON.stringify(r.json)));
      if (validation.detail_shape_ok === null) {
        validation.detail_shape_ok = !!r.json?.society_disposal;
        if (!validation.detail_shape_ok) {
          validation.notes.push('detail response had no society_disposal node');
          fail('Detail responses have no society_disposal node. Kato may have changed its API.');
        }
      }
      if (li.status === 1) {
        const found = new Map();
        sweepMedia(r.json, '', found);
        let n = 0;
        for (const entry of found.values()) {
          const isDoc = new URL(entry.url).hostname !== IMGIX_HOST;
          if (isDoc && !includeDocs) continue;
          mediaJobs.push({ matchId: li.id, idx: ++n, entry });
        }
      }
    }
    doneProps++;
    ui.cProps.textContent = `${doneProps}/${rawTargets.length}`;
    ui.bar.value = doneProps;
  }

  // ---- 4. media
  let mediaDone = 0, mediaOk = 0;
  ui.bar.max = mediaJobs.length || 1;
  ui.bar.value = 0;
  ui.cMedia.textContent = `0/${mediaJobs.length}`;

  function buildManifest() {
    return {
      schema_version: 1,
      generator: 'kato-longlist-capture',
      extension_version: EXT_VERSION,
      requirement_id: REQ_ID,
      page_url: PAGE_URL,
      kato_origin: PAGE_ORIGIN,
      api_base: base,
      api_probe: tried,
      endpoints: { list: listUrl(base), detail_template: detailUrl(base, '<match_id>') },
      captured_at: capturedAt,
      raw_capture_rule: allRaw ? 'all' : 'status==1',
      media_capture_rule: includeDocs ? 'status==1' : 'status==1, images only (documents excluded)',
      imgix_params: { w: IMAGE_MAX_PX, h: IMAGE_MAX_PX, fit: 'max', fm: 'jpg', auto: 'compress', quality_ladder: QUALITY_LADDER },
      image_max_bytes: IMAGE_MAX_BYTES,
      counts: {
        matches_total: matches.length,
        matches_longlist: longlist.length,
        raw_attempted: rawTargets.length,
        raw_ok: Object.values(matchStatus).filter((s) => s.raw === 200).length,
        media_attempted: mediaJobs.length,
        media_ok: mediaOk,
      },
      match_status: matchStatus,
      validation,
      complete: failures === 0,
      parts_saved: partsSaved.length + 1,
    };
  }

  for (let i = 0; i < mediaJobs.length; i += CONCURRENCY) {
    const chunk = mediaJobs.slice(i, i + CONCURRENCY);
    ui.phase.textContent = `Downloading media… (${mediaDone}/${mediaJobs.length})`;
    const results = await Promise.all(chunk.map((j) => fetchMedia(j.entry)));
    for (let k = 0; k < chunk.length; k++) {
      const job = chunk[k];
      const res = results[k];
      mediaDone++;
      if (!res.ok) {
        fail(`match ${job.matchId}: media failed (${res.status || 'error'}) ${job.entry.url}`);
      } else {
        const file = `media/${job.matchId}/${String(job.idx).padStart(2, '0')}${pickExt(job.entry, res)}`;
        await zip.add(file, res.bytes);
        (mediaIndex[job.matchId] ||= []).push({
          file,
          url: job.entry.url,
          request_url: res.requestUrl,
          name: job.entry.name,
          ext: job.entry.ext,
          bytes: res.bytes.length,
          content_type: res.contentType,
          imgix_quality: res.quality ?? null,
          paths: job.entry.paths,
        });
        mediaOk++;
      }
      ui.cMedia.textContent = `${mediaDone}/${mediaJobs.length}`;
      ui.cBytes.textContent = fmtMB(bytesBase + zip.bytesWritten);
      ui.bar.value = mediaDone;

      const more = mediaDone < mediaJobs.length;
      if (maxPartBytes > 0 && zip.bytesWritten > maxPartBytes && more) {
        ui.phase.textContent = `Part ${partIndex} is full. Click to save it and continue.`;
        await finishPart(false);
        await awaitPartClick();
        partIndex++;
        const next = await openSink(bundleName(partIndex, false));
        if (!next) { log('Cancelled before the remaining parts were saved. The bundle is incomplete.', 'bad'); return; }
        opened = next;
        zip = new ZipWriter(opened.sink);
      }
    }
  }

  // ---- 5. finalise
  ui.phase.textContent = 'Writing the bundle index…';
  await finishPart(true);

  ui.doneCard.classList.remove('hidden');
  const total = fmtMB(bytesBase);
  if (failures === 0) {
    ui.doneTitle.textContent = `Bundle saved (${total})`;
    ui.doneText.textContent = `${partsSaved.join(', ')} - ${longlist.length} properties, ${mediaOk} media files.`;
    ui.phase.textContent = 'Done.';
  } else {
    ui.doneTitle.textContent = `Bundle saved with ${failures} failure${failures === 1 ? '' : 's'} (${total})`;
    ui.doneText.textContent = `${partsSaved.join(', ')} - ${longlist.length} properties, ${mediaOk} of ${mediaJobs.length} media files. `
      + 'The failures are recorded in the bundle and will show up in the Gaps Report, so nothing is silently missing.';
    ui.phase.textContent = 'Done, with failures.';
  }
}

ui.start?.addEventListener('click', () => {
  capture().catch((e) => {
    ui.phase.textContent = 'Stopped by an unexpected error.';
    fail(String(e && e.stack ? e.stack : e));
  });
});
