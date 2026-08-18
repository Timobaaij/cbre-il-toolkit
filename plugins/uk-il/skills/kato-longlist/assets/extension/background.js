/* background.js - a launcher, nothing more.
 *
 * Deliberately thin. It does no fetching: authenticated reads belong to the content script (SameSite)
 * and media reads belong to the runner page (which shares the extension origin and so gets the same
 * host_permissions CORS bypass a service worker would, without shuttling megabytes through message
 * passing).
 *
 * It also avoids needing the "tabs" permission: chrome.action.onClicked hands us the tab directly, so
 * we pass its id to the runner rather than querying for it later.
 */

const REQUIREMENT_RE = /\/requirements\/(\d+)/;

function openRunner(params) {
  const qs = new URLSearchParams(params).toString();
  return chrome.tabs.create({ url: chrome.runtime.getURL(`runner.html?${qs}`) });
}

chrome.action.onClicked.addListener(async (tab) => {
  const url = tab?.url || '';
  let host = '';
  try { host = new URL(url).hostname; } catch { host = ''; }

  if (!/(^|\.)kato\.app$/.test(host)) {
    await openRunner({ error: 'not_kato' });
    return;
  }
  const m = REQUIREMENT_RE.exec(url);
  if (!m) {
    await openRunner({ error: 'no_requirement' });
    return;
  }
  await openRunner({
    tabId: String(tab.id),
    reqid: m[1],
    origin: new URL(url).origin,
    pageUrl: url,
  });
});
