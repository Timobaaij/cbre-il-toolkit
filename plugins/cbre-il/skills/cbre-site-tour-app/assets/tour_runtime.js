/* ===================================================================
   CBRE site tour app - runtime
   Inlined into tour_template.html by build_tour.py at the runtime
   placeholder. Reads the TOUR object and renders two views: a
   day-by-day schedule (each opening on its own Leaflet map) and a
   flat options list. Map tiles are the only network dependency.

   Note for editors: never write the build placeholders (two leading
   and trailing underscores around a capitalised name) as literal text
   in this file. They survive injection and trip the build's
   unfilled-placeholder check.
   =================================================================== */

/* ------------------------------------------------------------ helpers */
var $ = function (s) { return document.querySelector(s); };

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

/* Named LBL, not L: Leaflet owns the global L and a `var L` here would
   shadow it for the whole script, silently disabling every map. */
var LBL = TOUR.labels || {};
function t(key, fallback) {
  return LBL[key] != null ? LBL[key] : fallback;
}

var META = TOUR.meta || {};
var PROPS = TOUR.properties || [];
var DAYS = TOUR.days || [];
var MARKETS = TOUR.markets || {};
var TBC = t('tbc', 'To be confirmed');

var byId = {};
PROPS.forEach(function (p) { byId[p.id] = p; });

/* Google Maps deep link. Explicit link wins, then coordinates, then a
   text query. Coordinates are preferred over names because a warehouse
   scheme often has no searchable address. */
function mapsUrl(o) {
  if (!o) return null;
  if (o.mapsUrl) return o.mapsUrl;
  if (o.lat != null && o.lng != null) {
    return 'https://www.google.com/maps/search/?api=1&query=' + o.lat + ',' + o.lng;
  }
  var q = o.query || [o.name, o.city].filter(Boolean).join(', ');
  if (!q) return null;
  return 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(q);
}

function coordText(o) {
  if (!o || o.lat == null || o.lng == null) return null;
  return o.lat + ', ' + o.lng;
}

/* --------------------------------------------------------------- icons */
var PIN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0116 0z"/><circle cx="12" cy="10" r="3"/></svg>';
var COPY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="1"/><path d="M5 15V5a2 2 0 012-2h10"/></svg>';
var CHEV = '<svg class="chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>';
var DOCICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>';
var CAL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="16" y1="2" x2="16" y2="6"/></svg>';
var GRID = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>';

/* ----------------------------------------------------------- app state */
var view = 'schedule';
var dayIx = 0;
var searchQ = '';
var dayMap = null;      // live Leaflet instance for the current day
var dayMarkers = {};    // stop index -> marker

/* ------------------------------------------------------------- day map */
/* ---------------------------------------------------------- basemaps */
/* Named presets, all keyless. Default is `osm`: the standard OpenStreetMap
   Leaflet style. CARTO is deliberately absent: its free tier now requires an
   API key and stamps a watermark on the tiles, which is not acceptable on a
   client artefact.
     osm          OpenStreetMap standard  <- default
     osm-grey     the same tiles filtered to near-greyscale
     esri-street  plain road map, closest to default Google Maps
     esri-grey    very quiet grey canvas, fewest labels, pins dominate
   Pick with tour.json  "map": { "style": "osm-grey" }
   or override outright with "tiles" + "attribution". */
var BASEMAPS = {
  'esri-street': {
    tiles: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri',
    maxZoom: 19,
    desaturate: false,
  },
  'esri-grey': {
    tiles: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri',
    maxZoom: 16,
    desaturate: false,
  },
  'osm': {
    tiles: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
    desaturate: false,
  },
  'osm-grey': {
    tiles: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
    desaturate: true,
  },
};

var _cfg = TOUR.map || {};
var _base = BASEMAPS[_cfg.style] || BASEMAPS['osm'];
var MAP_CFG = Object.assign({
  subdomains: 'abc',
  route: true,      // dashed line through the stops in running order
  height: null,     // 'tall' for a taller map
}, _base, _cfg);

var HAS_LEAFLET = typeof L !== 'undefined' && !!L && typeof L.map === 'function';

/* Stops that can actually be placed. Order is preserved: the pin number is
   the position in the day, not the position among geocoded stops, so a stop
   with no coordinates leaves a visible gap in the numbering rather than
   silently renumbering the day. */
function locatable(day) {
  var out = [];
  (day.stops || []).forEach(function (s, i) {
    var p = s.prop ? byId[s.prop] : null;
    var lat = s.lat != null ? s.lat : (p && p.lat != null ? p.lat : null);
    var lng = s.lng != null ? s.lng : (p && p.lng != null ? p.lng : null);
    if (lat != null && lng != null) {
      out.push({ i: i, n: i + 1, stop: s, prop: p, lat: +lat, lng: +lng });
    }
  });
  return out;
}

function destroyMap() {
  if (dayMap) {
    dayMap.remove();
    dayMap = null;
  }
  dayMarkers = {};
}

function popupHtml(pt) {
  var s = pt.stop, p = pt.prop;
  var name = s.name || (p ? p.name : '');
  var url = mapsUrl(p || s);
  var out = '<div class="pop-t">' + esc((s.t || '') + (s.t && p && p.city ? ' · ' : '') +
    (p && p.city ? p.city : '')) + '</div>' +
    '<h4 class="pop-n">' + esc(name) + '</h4><div class="pop-a">';
  if (url) {
    out += '<a class="pop-b" href="' + esc(url) + '" target="_blank" rel="noopener">' +
      esc(t('maps', 'Google Maps')) + '</a>';
  }
  var hasDetail = !!(p && (p.desc || (p.facts && p.facts.length) ||
                          (p.terms && p.terms.length) || (p.docs && p.docs.length)));
  if (hasDetail) {
    out += '<button class="pop-b ghost" data-pop-prop="' + esc(p.id) + '">' +
      esc(t('details', 'Details')) + '</button>';
  }
  return out + '</div>';
}

function renderDayMap(day) {
  var pts = locatable(day);
  if (!pts.length) return;               // nothing to place: no map at all
  var el = document.getElementById('daymap');
  if (!el) return;

  if (!HAS_LEAFLET) {
    el.parentNode.removeChild(el);
    return;
  }

  if (MAP_CFG.desaturate) el.classList.add('muted-tiles');

  dayMap = L.map(el, {
    scrollWheelZoom: false,              // the page scrolls; the map must not steal it
    zoomControl: true,
    attributionControl: true,
  });

  var tiles = L.tileLayer(MAP_CFG.tiles, {
    maxZoom: MAP_CFG.maxZoom,
    attribution: MAP_CFG.attribution,
    subdomains: MAP_CFG.subdomains || 'abc',
  });

  // Tiles are the one thing here that needs a connection. Say so plainly
  // rather than leaving the user staring at a grey box.
  var flagged = false;
  tiles.on('tileerror', function () {
    if (flagged) return;
    flagged = true;
    var cap = document.getElementById('daymap-warn');
    if (cap) cap.textContent = t('tiles_offline',
      'Map tiles need a connection. Pins and links still work offline.');
  });
  tiles.addTo(dayMap);

  var latlngs = pts.map(function (pt) { return [pt.lat, pt.lng]; });

  if (MAP_CFG.route && latlngs.length > 1) {
    L.polyline(latlngs, {
      color: '#003F2D', weight: 2, opacity: .55, dashArray: '5,6',
    }).addTo(dayMap);
  }

  pts.forEach(function (pt) {
    var kind = pt.stop.kind || (pt.prop ? 'view' : 'travel');
    var m = L.marker([pt.lat, pt.lng], {
      icon: L.divIcon({
        className: '',
        html: '<div class="mk k-' + esc(kind) + '">' + pt.n + '</div>',
        iconSize: [26, 26],
        iconAnchor: [13, 13],
        popupAnchor: [0, -14],
      }),
      title: pt.stop.name || (pt.prop ? pt.prop.name : ''),
      keyboard: true,
    }).addTo(dayMap);
    m.bindPopup(popupHtml(pt), { closeButton: true, minWidth: 150 });
    dayMarkers[pt.i] = m;
  });

  /* Fitting the view is deferred. Leaflet caches the container size when the
     map is constructed, and the container was written by innerHTML moments
     ago, so that cached size can still be zero. Fitting against a zero-size
     map silently yields max zoom, which lands you on a blank tile in the
     middle of a field. Measure first, then fit. */
  function fitDay() {
    if (!dayMap) return;
    dayMap.invalidateSize({ animate: false });
    if (latlngs.length === 1) {
      dayMap.setView(latlngs[0], 13);
    } else {
      dayMap.fitBounds(L.latLngBounds(latlngs), { padding: [28, 28] });
    }
  }
  dayMap._fitDay = fitDay;

  if (window.requestAnimationFrame) {
    requestAnimationFrame(function () { requestAnimationFrame(fitDay); });
  } else {
    setTimeout(fitDay, 60);
  }

  // Popup buttons are rebuilt by Leaflet on each open, so wire on open.
  dayMap.on('popupopen', function (e) {
    var node = e.popup.getElement();
    if (!node) return;
    Array.prototype.forEach.call(node.querySelectorAll('[data-pop-prop]'), function (b) {
      b.onclick = function () { openSheet(b.getAttribute('data-pop-prop')); };
    });
  });

}

/* The layout is genuinely responsive, so the map box changes size when the
   window crosses a breakpoint or a phone rotates. Leaflet does not notice on
   its own: re-measure and re-fit, debounced. */
var _rsTimer = null;
window.addEventListener('resize', function () {
  if (!dayMap) return;
  clearTimeout(_rsTimer);
  _rsTimer = setTimeout(function () {
    if (dayMap && dayMap._fitDay) dayMap._fitDay();
  }, 180);
});

/* Focusing a stop card pans the map to it: the list and the map stay in step. */
function focusStop(ix) {
  if (!dayMap || !dayMarkers[ix]) return;
  var m = dayMarkers[ix];
  dayMap.panTo(m.getLatLng(), { animate: true });
  m.openPopup();
}

/* -------------------------------------------------------------- header */
function renderHeader() {
  var title = esc(META.title || '');
  if (META.titleEm) {
    // titleEm is highlighted in accent green, matching the dashboard h1 em.
    title = title.replace(esc(META.titleEm), '<em>' + esc(META.titleEm) + '</em>');
  }
  $('#apptitle').innerHTML = title;

  var bits = [];
  if (META.subtitle) bits.push(esc(META.subtitle));
  if (META.dateRange) bits.push('<b>' + esc(META.dateRange) + '</b>');
  $('#appsub').innerHTML = bits.join('<br>');

  document.documentElement.lang = META.lang || 'en';
}

/* ------------------------------------------------------------ KPI band */
function renderKpis() {
  var kpis = META.kpis;
  if (!kpis) {
    // Auto-compute a sensible default band when none is supplied.
    var stops = 0;
    DAYS.forEach(function (d) { stops += (d.stops || []).length; });
    var onTour = PROPS.filter(function (p) { return p.tour; }).length;
    var mk = Object.keys(MARKETS);
    kpis = [];
    // "Days: 1" is noise on a single-day tour. Lead with the date instead.
    if (DAYS.length > 1) {
      kpis.push({ label: t('kpi_days', 'Days'), value: String(DAYS.length), sub: t('kpi_days_sub', 'On tour') });
    } else if (DAYS[0] && DAYS[0].label) {
      kpis.push({ label: t('kpi_date', 'Date'), value: DAYS[0].label, sub: DAYS[0].dow || '' });
    }
    kpis.push({ label: t('kpi_stops', 'Stops'), value: String(stops), sub: t('kpi_stops_sub', 'Scheduled') });
    kpis.push({ label: t('kpi_props', 'Properties'), value: String(onTour || PROPS.length), sub: t('kpi_props_sub', 'Viewed') });
    if (mk.length > 1) {
      kpis.push({
        label: t('kpi_markets', 'Markets'),
        value: String(mk.length),
        sub: mk.map(function (k) { return (MARKETS[k].code || k).toUpperCase(); }).join(' · '),
      });
    }
  }
  $('#kpis').innerHTML = kpis.map(function (k) {
    // A worded value ("Wed 26 Aug") needs a smaller size than a bare number.
    var wordy = String(k.value).length > 6;
    return '<div class="kpi">' +
      '<div class="kpi-label">' + esc(k.label) + '</div>' +
      '<div class="kpi-value' + (wordy ? ' txt' : '') + '">' + esc(k.value) + '</div>' +
      (k.sub ? '<div class="kpi-sub">' + esc(k.sub) + '</div>' : '') +
      '</div>';
  }).join('');
}

/* ----------------------------------------------------------- countdown */
function dayDate(d) {
  // Parse as local midnight so comparisons are calendar-day, not UTC.
  if (!d.date) return null;
  var p = String(d.date).split('-');
  if (p.length !== 3) return null;
  return new Date(+p[0], +p[1] - 1, +p[2]);
}

function todayIndex() {
  var now = new Date();
  var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  for (var i = 0; i < DAYS.length; i++) {
    var dd = dayDate(DAYS[i]);
    if (dd && dd.getTime() >= today.getTime()) return i;
  }
  return 0;
}

function countdown() {
  var el = $('#countdown');
  if (!el || !DAYS.length) return;
  var now = new Date();
  var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  var first = dayDate(DAYS[0]);
  var last = dayDate(DAYS[DAYS.length - 1]);
  if (!first || !last) { el.textContent = ''; return; }

  var DAY_MS = 864e5;
  if (today < first) {
    var n = Math.round((first - today) / DAY_MS);
    el.textContent = n === 1
      ? t('cd_tomorrow', 'Tomorrow')
      : (t('cd_in', 'In') + ' ' + n + ' ' + t('cd_days', 'days'));
  } else if (today > last) {
    el.textContent = t('cd_done', 'Tour complete');
  } else {
    el.textContent = t('cd_live', 'Tour live');
  }
}

/* --------------------------------------------------------------- pills */
function buildPills() {
  var now = new Date();
  var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  // One-day tour: no rail, and reclaim the padding it left behind.
  var solo = DAYS.length <= 1;
  $('#pills').className = 'pills' + (solo ? ' solo' : '');
  document.querySelector('.top').className = 'top' + (solo ? ' solo' : '');
  if (solo) { $('#pills').innerHTML = ''; return; }
  $('#pills').innerHTML = DAYS.map(function (d, i) {
    var dd = dayDate(d);
    var past = dd && dd < today;
    return '<button class="pill' + (i === dayIx ? ' on' : '') + (past && i !== dayIx ? ' past' : '') + '"' +
      ' role="tab" aria-selected="' + (i === dayIx) + '" data-i="' + i + '">' +
      '<span class="pill-k">' + esc(t('day', 'Day') + ' ' + (d.n != null ? d.n : i + 1)) + '</span>' +
      '<span class="pill-v">' + esc(d.label || d.date || '') + '</span>' +
      '</button>';
  }).join('');
  Array.prototype.forEach.call($('#pills').querySelectorAll('.pill'), function (b) {
    b.onclick = function () {
      dayIx = +b.getAttribute('data-i');
      view = 'schedule';
      render();
    };
  });
}

/* --------------------------------------------------------- stop pieces */
function chipsHtml(stop, prop) {
  var out = [];
  if (prop && prop.dev) out.push('<span class="chip dev">' + esc(prop.dev) + '</span>');
  if (prop && prop.size) out.push('<span class="chip">' + esc(prop.size) + '</span>');
  if (prop && prop.rent) out.push('<span class="chip">' + esc(prop.rent) + '</span>');
  (((stop && stop.chips) || (prop && prop.chips) || [])).forEach(function (c) {
    out.push('<span class="chip">' + esc(c) + '</span>');
  });
  if (stop && stop.attend === true) {
    out.push('<span class="chip attend">' + esc(t('attending', 'Developer attending')) + '</span>');
  } else if (stop && stop.attend === 'tbc') {
    out.push('<span class="chip tbc">' + esc(t('attend_tbc', 'Attendance tbc')) + '</span>');
  }
  if (stop && stop.tbc) out.push('<span class="chip tbc">' + esc(t('to_confirm', 'To confirm')) + '</span>');
  return out.length ? '<div class="chips">' + out.join('') + '</div>' : '';
}

function actionsHtml(target, extra) {
  var out = [];
  var url = mapsUrl(target);
  if (url) {
    out.push('<a class="btn" href="' + esc(url) + '" target="_blank" rel="noopener">' +
      PIN + esc(t('maps', 'Google Maps')) + '</a>');
  }
  var c = coordText(target);
  if (c) {
    out.push('<button class="btn ghost copy" data-c="' + esc(c) + '">' +
      COPY + esc(t('coords', 'Coordinates')) + '</button>');
  }
  if (extra) {
    var url2 = mapsUrl(extra);
    if (url2) {
      out.push('<a class="btn ghost" href="' + esc(url2) + '" target="_blank" rel="noopener">' +
        PIN + esc(extra.name || t('maps', 'Google Maps')) + '</a>');
    }
  }
  return out.length ? '<div class="acts">' + out.join('') + '</div>' : '';
}

/* --------------------------------------------------------- detail sheet */
function specList(rows) {
  if (!rows || !rows.length) return '';
  return '<div class="spec-grid">' + rows.map(function (r) {
    var v = r[1];
    var isTbc = v == null || v === '' || v === TBC;
    return '<div class="spec"><div class="spec-k">' + esc(r[0]) + '</div>' +
      '<div class="spec-v' + (isTbc ? ' tbc' : '') + '">' + esc(isTbc ? TBC : v) + '</div></div>';
  }).join('') + '</div>';
}

function docsHtml(p) {
  if (!p.docs || !p.docs.length) return '';
  return '<div class="section-title">' + esc(t('documents', 'Documents')) + '</div>' +
    '<div class="docs">' + p.docs.map(function (d) {
      return '<a class="doc" href="' + esc(d.href) + '" target="_blank" rel="noopener">' + DOCICON +
        '<span>' + esc(d.label) + '</span>' +
        (d.size ? '<span class="dsize">' + esc(d.size) + '</span>' : '') + '</a>';
    }).join('') + '</div>';
}

function openSheet(propId) {
  var p = byId[propId];
  if (!p) return;
  var loc = [p.city, p.region, (MARKETS[p.market] || {}).name].filter(Boolean).join(' · ');
  $('#sheet').innerHTML =
    '<div class="sheet-h">' +
      '<button class="sheet-x" id="sheet-x" aria-label="' + esc(t('close', 'Close')) + '">×</button>' +
      (p.dev ? '<div class="dev-line">' + esc(p.dev) + '</div>' : '') +
      '<h3>' + esc(p.name) + '</h3>' +
      (loc ? '<div class="loc">' + esc(loc) + '</div>' : '') +
    '</div>' +
    '<div class="sheet-b">' +
      actionsHtml(p) +
      (p.desc ? '<div class="section-title">' + esc(t('overview', 'Overview')) + '</div>' +
        '<p class="desc">' + esc(p.desc) + '</p>' : '') +
      (p.facts && p.facts.length ? '<div class="section-title">' + esc(t('specification', 'Specification')) + '</div>' +
        specList(p.facts) : '') +
      (p.terms && p.terms.length ? '<div class="section-title">' + esc(t('terms', 'Commercial terms')) + '</div>' +
        specList(p.terms) : '') +
      docsHtml(p) +
    '</div>';

  $('#sheet').classList.add('on');
  $('#sheet-bd').classList.add('on');
  document.body.classList.add('locked');
  $('#sheet').scrollTop = 0;
  var x = $('#sheet-x');
  if (x) { x.onclick = closeSheet; x.focus(); }
  wireCopy($('#sheet'));
}

function closeSheet() {
  $('#sheet').classList.remove('on');
  $('#sheet-bd').classList.remove('on');
  document.body.classList.remove('locked');
}

/* ------------------------------------------------------ schedule view */
function renderDay(day) {
  var props = {};
  (day.stops || []).forEach(function (s) {
    if (s.prop) props[s.prop] = 1;
    if (s.also) props[s.also] = 1;
  });
  var nProps = Object.keys(props).length;

  var meta = [];
  meta.push('<span><b>' + (day.stops || []).length + '</b> ' + esc(t('stops', 'stops')) + '</span>');
  if (nProps) meta.push('<span><b>' + nProps + '</b> ' + esc(t('properties', 'properties')) + '</span>');
  if (day.region) meta.push('<span>' + esc(day.region) + '</span>');

  // A one-day tour needs no "Day 1 of 1" eyebrow; lead with the weekday.
  var solo = DAYS.length === 1;
  var eyebrow = solo
    ? [day.dow, day.region].filter(Boolean).join(' · ')
    : (t('day', 'Day') + ' ' + (day.n != null ? day.n : dayIx + 1) +
       (day.dow ? ' · ' + day.dow : ''));

  var head = '<div class="dayhead">' +
    (eyebrow ? '<div class="eyebrow">' + esc(eyebrow) + '</div>' : '') +
    '<h2>' + esc(day.title || day.label || day.date || '') + '</h2>' +
    (day.note ? '<p>' + esc(day.note) + '</p>' : '') +
    '<div class="daymeta">' + meta.join('') + '</div>' +
    '</div>';

  // Map slot. Only emitted when at least one stop can be placed.
  var pts = locatable(day);
  var mapHtml = '';
  if (pts.length && HAS_LEAFLET) {
    var missing = (day.stops || []).length - pts.length;
    var cap = [];
    cap.push('<span>' + pts.length + ' ' + esc(t('mapped', 'stops mapped')) + '</span>');
    if (missing > 0) {
      cap.push('<span>' + missing + ' ' + esc(t('unmapped', 'without coordinates')) + '</span>');
    }
    cap.push('<span class="warn" id="daymap-warn"></span>');
    mapHtml = '<div class="daymap-wrap">' +
      '<div class="daymap' + (MAP_CFG.height === 'tall' ? ' tall' : '') + '" id="daymap"></div>' +
      '<div class="daymap-cap">' + cap.join('') + '</div>' +
      '</div>';
  }

  // Pin numbers only mean something next to a rendered map.
  var placed = {};
  if (mapHtml) pts.forEach(function (pt) { placed[pt.i] = pt.n; });

  var stops = (day.stops || []).map(function (s, ix) {
    var p = s.prop ? byId[s.prop] : null;
    var also = s.also ? byId[s.also] : null;
    var kind = s.kind || (p ? 'view' : 'travel');
    var hasDetail = !!(p && (p.desc || (p.facts && p.facts.length) ||
                            (p.terms && p.terms.length) || (p.docs && p.docs.length)));
    // Link target: the property record if there is one, else the stop itself.
    var target = p || s;
    var pin = placed[ix];

    return '<article class="stop k-' + esc(kind) + (hasDetail ? ' has-detail' : '') + '">' +
      '<' + (hasDetail ? 'button' : 'div') + ' class="stop-main"' +
        (hasDetail ? ' data-prop="' + esc(p.id) + '"' : '') + '>' +
        '<div class="stop-t">' +
          (pin ? '<span class="stop-pin" data-focus="' + ix + '">' + pin + '</span>' : '') +
          esc(s.t || '') +
        '</div>' +
        '<div class="stop-b">' +
          '<h3 class="stop-n">' + esc(s.name || (p ? p.name : '')) + '</h3>' +
          (s.note ? '<p class="stop-note">' + esc(s.note) + '</p>' : '') +
          chipsHtml(s, p) +
        '</div>' +
        (hasDetail ? CHEV : '') +
      '</' + (hasDetail ? 'button' : 'div') + '>' +
      actionsHtml(target, also) +
      '</article>';
  }).join('');

  var body = stops || '<div class="empty"><h3>' + esc(t('no_stops', 'No stops listed')) + '</h3></div>';

  /* Three siblings, not nested: on a phone they stack (head, map, stops) and
     on a desktop the same three fall into a grid with the map sticky beside
     the timeline. One DOM, two genuinely different layouts. */
  return '<div class="daygrid">' +
      '<div class="dayhead-slot">' + head + '</div>' +
      (mapHtml ? '<aside class="mapcol">' + mapHtml + '</aside>' : '') +
      '<div class="stopcol">' + body + '</div>' +
    '</div>';
}

/* ------------------------------------------------------- options view */
function renderOptions(q) {
  q = (q || '').trim().toLowerCase();
  var hits = PROPS.filter(function (p) {
    if (!q) return true;
    return [p.name, p.city, p.dev, p.region, p.size, p.rent,
            (MARKETS[p.market] || {}).name].filter(Boolean)
      .join(' ').toLowerCase().indexOf(q) !== -1;
  });

  if (!hits.length) {
    return '<div class="empty"><h3>' + esc(t('empty_title', 'Nothing matches that search')) + '</h3>' +
      '<p>' + esc(t('empty_body', 'Try a park name, a city or a developer.')) + '</p></div>';
  }

  // Group by market, preserving the order markets are declared in.
  var order = Object.keys(MARKETS);
  var groups = {};
  hits.forEach(function (p) {
    var k = p.market || '_';
    (groups[k] = groups[k] || []).push(p);
  });
  var keys = order.filter(function (k) { return groups[k]; })
    .concat(Object.keys(groups).filter(function (k) { return order.indexOf(k) === -1; }));

  return keys.map(function (k) {
    var m = MARKETS[k] || {};
    var list = groups[k];
    return '<section class="market">' +
      '<div class="market-h">' +
        '<h2>' + esc(m.name || k) + '</h2>' +
        (m.sub ? '<span class="market-k">' + esc(m.sub) + '</span>' : '') +
        '<span class="market-k">' + list.length + ' ' + esc(t('options', 'options')) + '</span>' +
      '</div>' +
      (m.pack ? '<p class="market-pack">' + esc(t('source', 'Source') + ': ' + m.pack) + '</p>' : '') +
      '<div class="optgrid">' +
      list.map(function (p) {
        var hasDetail = !!(p.desc || (p.facts && p.facts.length) || (p.docs && p.docs.length));
        return '<article class="stop' + (hasDetail ? ' has-detail' : '') + '">' +
          '<' + (hasDetail ? 'button' : 'div') + ' class="stop-main"' +
            (hasDetail ? ' data-prop="' + esc(p.id) + '"' : '') + '>' +
            '<div class="ref">' + esc(p.no != null ? (t('opt', 'Opt') + ' ' + p.no) : '') + '</div>' +
            '<div class="stop-b">' +
              '<h3 class="stop-n">' + esc(p.name) + '</h3>' +
              (p.city ? '<p class="stop-note">' + esc(p.city) + '</p>' : '') +
              chipsHtml(null, p) +
              '<div class="chips">' + (p.tour
                ? '<span class="chip attend">' + esc(t('on_tour', 'On the tour')) + '</span>'
                : '<span class="chip off">' + esc(t('off_tour', 'Not on the tour')) + '</span>') +
              '</div>' +
            '</div>' +
            (hasDetail ? CHEV : '') +
          '</' + (hasDetail ? 'button' : 'div') + '>' +
          actionsHtml(p) +
          '</article>';
      }).join('') +
      '</div>' +
      '</section>';
  }).join('');
}

/* --------------------------------------------------------------- tabs */
function renderTabs() {
  var tabs = [
    { id: 'schedule', icon: CAL, label: t('tab_schedule', 'Schedule') },
    { id: 'options', icon: GRID, label: t('tab_options', 'All options') },
  ];
  if (!PROPS.length) tabs = [tabs[0]];
  $('#tabbar').style.setProperty('--tabs', tabs.length);
  $('#tabbar').innerHTML = tabs.map(function (x) {
    return '<button data-v="' + x.id + '" class="' + (view === x.id ? 'on' : '') + '"' +
      ' role="tab" aria-selected="' + (view === x.id) + '">' +
      x.icon + '<span>' + esc(x.label) + '</span></button>';
  }).join('');
  Array.prototype.forEach.call($('#tabbar').querySelectorAll('button'), function (b) {
    b.onclick = function () { view = b.getAttribute('data-v'); render(); };
  });
}

/* ------------------------------------------------------------- footer */
function renderFooter() {
  var out = [];
  if (META.disclaimer) out.push('<p>' + esc(META.disclaimer) + '</p>');
  var line2 = [];
  if (META.copyright) line2.push(META.copyright);
  if (META.compiled) line2.push(t('compiled', 'Compiled') + ' ' + META.compiled);
  if (line2.length) out.push('<p>' + esc(line2.join(' · ')) + '</p>');
  $('#foot').innerHTML = out.join('');
  // No disclaimer and no copyright means no footer. Keeping the band would
  // leave a tall empty dark-green bar at the end of the page.
  var band = document.getElementById('footband');
  if (band) band.style.display = out.length ? '' : 'none';
}

/* --------------------------------------------------------- copy button */
function wireCopy(scope) {
  Array.prototype.forEach.call(scope.querySelectorAll('.copy'), function (b) {
    b.onclick = function (e) {
      e.stopPropagation();
      var txt = b.getAttribute('data-c');
      var was = b.innerHTML;
      var done = function () {
        b.innerHTML = COPY + esc(t('copied', 'Copied'));
        setTimeout(function () { b.innerHTML = was; }, 1400);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(txt).then(done, done);
      } else {
        // Fallback for older iOS Safari and non-secure contexts.
        var ta = document.createElement('textarea');
        ta.value = txt;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); } catch (err) {}
        document.body.removeChild(ta);
        done();
      }
    };
  });
}

/* --------------------------------------------------------------- render */
function render() {
  // Always tear the old map down first: Leaflet leaks handlers otherwise.
  destroyMap();
  buildPills();
  renderTabs();
  var main = $('#main');

  if (view === 'options') {
    main.innerHTML =
      '<div class="search"><input type="search" id="search" ' +
      'placeholder="' + esc(t('search_ph', 'Search options, cities, developers')) + '" ' +
      'autocomplete="off" value="' + esc(searchQ) + '"></div>' +
      '<div id="optlist">' + renderOptions(searchQ) + '</div>';
    var si = $('#search');
    si.addEventListener('input', function () {
      searchQ = si.value;
      $('#optlist').innerHTML = renderOptions(searchQ);
      wireStops($('#optlist'));
      wireCopy($('#optlist'));
    });
  } else {
    main.innerHTML = DAYS.length
      ? renderDay(DAYS[dayIx])
      : '<div class="empty"><h3>' + esc(t('no_days', 'No schedule loaded')) + '</h3></div>';
    if (DAYS.length) renderDayMap(DAYS[dayIx]);
  }

  wireStops(main);
  wireCopy(main);
  window.scrollTo(0, 0);
}

function wireStops(scope) {
  Array.prototype.forEach.call(scope.querySelectorAll('[data-prop]'), function (b) {
    b.onclick = function () { openSheet(b.getAttribute('data-prop')); };
  });
  // Tapping the pin number jumps the map to that stop instead of opening it.
  Array.prototype.forEach.call(scope.querySelectorAll('[data-focus]'), function (b) {
    b.onclick = function (e) {
      e.stopPropagation();
      e.preventDefault();
      focusStop(+b.getAttribute('data-focus'));
      var m = document.getElementById('daymap');
      if (m && m.scrollIntoView) m.scrollIntoView({ block: 'center', behavior: 'smooth' });
    };
  });
}

/* ----------------------------------------------------------------- boot */
$('#sheet-bd').onclick = closeSheet;
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') closeSheet();
});

renderHeader();
renderKpis();
renderFooter();
dayIx = todayIndex();
countdown();
render();
