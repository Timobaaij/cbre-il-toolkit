/* content.js - the ONLY component that touches authenticated Kato endpoints.
 *
 * WHY THIS EXISTS AT ALL: Kato is a Laravel app (the XSRF-TOKEN cookie is Laravel's signature) and
 * Laravel defaults to SESSION_SAME_SITE=lax. A fetch issued from the service worker or from the
 * runner page is CROSS-SITE, so a Lax session cookie is not attached and every call 401s. A content
 * script runs in the page's own origin, so its requests are same-site and the session attaches
 * exactly as it does for the app itself.
 *
 * WHAT IT CANNOT DO: read the session cookie. That cookie is httpOnly, so it is invisible to all
 * script including this. The only cookie read here is XSRF-TOKEN, which is deliberately NOT httpOnly
 * because reading it and echoing it back as a header is its entire purpose - the same thing
 * kato_fetch.py:56 does in Python. No credential is copied, stored, or transmitted anywhere.
 *
 * It answers exactly one message type and never initiates anything on its own.
 */

const RETRY_STATUS = new Set([429, 500, 502, 503]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function xsrfToken() {
  const m = /(?:^|;\s*)XSRF-TOKEN=([^;]+)/.exec(document.cookie || '');
  return m ? decodeURIComponent(m[1]) : null;
}

/** Mirrors kato_fetch.py get_json(): 4 attempts, backoff on 429/500/502/503. */
async function getJson(url) {
  const headers = {
    Accept: 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  };
  const token = xsrfToken();
  if (token) headers['X-XSRF-TOKEN'] = token;

  let last = { ok: false, status: 0, error: 'no attempt' };
  for (let attempt = 0; attempt < 4; attempt++) {
    let resp;
    try {
      resp = await fetch(url, { credentials: 'include', headers, cache: 'no-store' });
    } catch (e) {
      last = { ok: false, status: 0, error: String(e) };
      if (attempt < 3) { await sleep(1500 * (attempt + 1)); continue; }
      return last;
    }
    if (resp.ok) {
      try {
        return { ok: true, status: resp.status, json: await resp.json() };
      } catch (e) {
        // A 200 that is not JSON almost always means an auth redirect to an HTML login page.
        return { ok: false, status: resp.status, error: `response was not JSON (${e}) - are you still signed in?` };
      }
    }
    last = { ok: false, status: resp.status, error: (await resp.text().catch(() => '')).slice(0, 300) };
    if (RETRY_STATUS.has(resp.status) && attempt < 3) { await sleep(1500 * (attempt + 1)); continue; }
    return last;
  }
  return last;
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (!msg || msg.type !== 'KATO_JSON') return false;
  // Only ever fetch kato.app URLs, even though the caller is our own runner page.
  let host = '';
  try { host = new URL(msg.url).hostname; } catch { host = ''; }
  if (!/(^|\.)kato\.app$/.test(host)) {
    reply({ ok: false, status: 0, error: `refused non-Kato URL: ${msg.url}` });
    return true;
  }
  getJson(msg.url).then(reply);
  return true; // async reply
});
