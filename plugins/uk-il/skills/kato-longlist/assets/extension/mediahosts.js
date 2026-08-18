/* mediahosts.js - which URLs count as Kato media, and how to name/resize them.
 *
 * EXTRACTED SO IT CAN BE TESTED. The live run on requirement 1708520 failed on exactly this logic:
 * Kato serves assets from TWO S3 buckets and only one was allowed, so three floor plans were silently
 * skipped. Host rules are the most change-prone part of the extension and the part whose failure is
 * quietest, so they live in their own module with a unit test (tests/mediahosts_test.mjs) rather than
 * inline in the runner where nothing can reach them.
 *
 * Anything changed here must be mirrored in manifest.json host_permissions, or the fetch is blocked
 * by Chrome regardless of what this function says.
 */

export const IMGIX_HOST = 'as-images.imgix.net';
export const S3_HOST = 's3-eu-west-1.amazonaws.com';

/** Brochures and PDFs live in ...-assets-FILES; some floor plans and marked-up images live in
 *  ...-assets with no suffix. Both are needed. */
export const S3_PREFIXES = ['/agents-society-assets/', '/agents-society-assets-files/'];

export function isMediaUrl(u) {
  let x;
  try { x = new URL(u); } catch { return false; }
  if (x.protocol !== 'https:') return false;
  if (x.hostname === IMGIX_HOST) return true;
  if (x.hostname === S3_HOST && S3_PREFIXES.some((p) => x.pathname.startsWith(p))) return true;
  return false;
}

export function isImageHost(u) {
  try { return new URL(u).hostname === IMGIX_HOST; } catch { return false; }
}

/** Mirrors common.py imgix_resize, but PINS fm=jpg. imgix_resize() relies on the client not
 *  advertising webp, which holds for Python's requests and fails for Chrome: auto=format would return
 *  webp bytes where the pipeline expects the jpeg the Python path receives. */
export function imgixResize(url, maxPx, quality) {
  const u = new URL(url);
  u.searchParams.set('w', String(maxPx));
  u.searchParams.set('h', String(maxPx));
  u.searchParams.set('fit', 'max');
  u.searchParams.set('fm', 'jpg');
  u.searchParams.set('auto', 'compress');
  u.searchParams.set('q', String(quality));
  return u.toString();
}

const CT_EXT = {
  'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif', 'image/webp': '.webp',
  'application/pdf': '.pdf',
};

/** Extension for the file INSIDE the bundle. Only ever affects the zip's internal naming: Python
 *  renames from media_index's original name via sanitize(), so this needs to be sane, not pretty. */
export function pickExt(entry, result) {
  if (result?.kind === 'image') return '.jpg';           // fm=jpg guarantees this
  let fromUrl = null;
  try { fromUrl = /\.([a-z0-9]{2,5})(?:$|\?)/i.exec(new URL(entry.url).pathname); } catch { /* ignore */ }
  if (fromUrl) return `.${fromUrl[1].toLowerCase()}`;
  if (entry.ext) return `.${String(entry.ext).replace(/^\./, '').toLowerCase()}`;
  return CT_EXT[result?.contentType] || '.bin';
}
