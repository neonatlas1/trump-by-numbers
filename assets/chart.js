/* Presentation layer, tabs, expandable cards, and the three chart templates.
 *
 * Inlined into site/index.html by build.py (assets/ is source; site/ is a build
 * artifact). Hand-rolled SVG, no libraries, no keys, no storage of any kind.
 * Tab + expanded-card state live in the URL hash only.
 *
 * Honesty rules encoded here, not left to taste:
 *  - gaps in a series render as line BREAKS (never interpolated), with a note;
 *  - definition changes render as labelled dashed markers (never smoothed);
 *  - bars are always zero-based; %-change and index views baseline at 0/100;
 *  - every chart has a Table view twin and a link to the raw stored series.
 *
 * Charts fetch their payload (site/d/<id>.json) on first expand, the homepage
 * stays light; history loads only when someone asks for it.
 */
(function () {
  'use strict';
  document.documentElement.classList.remove('no-js');

  /* ---------- theme-aware palette ----------
   * Chart chrome, the four president colours and the baked-in series colours all
   * resolve from CSS variables, so the SVG charts follow the active theme (system
   * default or toggled) with the light values re-tuned for contrast on a light
   * background. refreshTheme() is called on boot and on every theme change; charts
   * render from these cached values. mapColor() re-points the payload's baked hex
   * (dark palette, written by build.py) to the current theme's value — in dark it
   * resolves to the same hex, so dark output is byte-for-byte unchanged. */
  var ROOT = document.documentElement;
  function css(name, fb) { var v = getComputedStyle(ROOT).getPropertyValue(name); return (v && v.trim()) || fb; }
  var CLR = {}, PAY = {};
  function refreshTheme() {
    CLR.ink = css('--chart-ink', '#ffffff');   CLR.sec = css('--chart-sec', '#c3c2b7');
    CLR.mut = css('--chart-mut', '#898781');   CLR.grid = css('--chart-grid', '#2c2c2a');
    CLR.axis = css('--chart-axis', '#4a4a47'); CLR.surface = css('--chart-surface', '#1a1a19');
    CLR.dash = css('--chart-dash', '#6b6965');
    ERA[0].c = css('--pres-obama', '#c98500'); ERA[1].c = css('--pres-t17', '#199e70');
    ERA[2].c = css('--pres-biden', '#3987e5'); ERA[3].c = css('--pres-t25', '#e66767');
    ERA_GREY = css('--era-grey', '#6c7280');
    PAY = {
      '#c98500': ERA[0].c, '#199e70': ERA[1].c, '#3987e5': ERA[2].c, '#e66767': ERA[3].c,
      '#6c7280': ERA_GREY, '#d95926': css('--series-2', '#d95926'),
      '#8b9198': css('--bar-g1', '#8b9198'), '#4a4d53': css('--bar-g3', '#4a4d53')
    };
  }
  function mapColor(c) { return (c && PAY[c]) || c; }
  var MONTH = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  /* ---------- formatting ---------- */
  function fnum(v) { return Math.round(v).toLocaleString('en-US'); }
  function fmt(v, kind, axis) {
    if (v == null || isNaN(v)) return 'n/a';
    var a = Math.abs(v), s = v < 0 ? '−' : '';
    switch (kind) {
      case 'pct':     return (Math.round(v * 10) / 10) + '%';
      case 'pct2':    return (Math.round(v * 100) / 100) + '%';
      case 'pctsign': return (v > 0 ? '+' : (v < 0 ? '−' : '')) +
                             (axis ? '' + Math.round(a * 10) / 10 : a.toFixed(1)) + '%';
      case 'usd2':    return s + '$' + a.toFixed(2);
      case 'usdB':    return s + '$' + fnum(a) + 'B';
      case 'usd':
        if (a >= 1e12) return s + '$' + (a / 1e12).toFixed(axis ? 0 : 1) + 'T';
        if (a >= 1e9)  return s + '$' + (a / 1e9).toFixed(0) + 'B';
        return s + '$' + fnum(a);
      case 'count':   return axis ? (a >= 1e6 ? (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M'
                                   : a >= 1e4 ? Math.round(v / 1e3) + 'k'
                                   : a >= 1e3 ? (v / 1e3).toFixed(1).replace(/\.0$/, '') + 'k' : fnum(v))
                                  : fnum(v);
      case 'thou': {  /* value is STORED in thousands (e.g. federal employment): show k / M */
        var n = a * 1000;
        var body = n >= 1e6 ? (n / 1e6).toFixed(axis ? 1 : 2).replace(/\.?0+$/, '') + 'M'
                 : n >= 1e3 ? Math.round(n / 1e3) + 'k' : fnum(n);
        return s + body;
      }
      case 'idx':     return (Math.round(v * 10) / 10) + '';
      default:        return '' + v;
    }
  }
  function ticks(lo, hi, n) {
    var span = (hi - lo) || 1, step = Math.pow(10, Math.floor(Math.log(span / n) / Math.LN10));
    var err = span / n / step; step *= err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1;
    var out = [], v = Math.ceil(lo / step) * step;
    for (; v <= hi + 1e-9; v += step) out.push(Math.round(v * 1e9) / 1e9);
    return out;
  }
  function el(tag, attrs) {
    var e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function halo(attrs) {  /* surface-colored text halo: legible over any line */
    attrs.stroke = CLR.surface; attrs['stroke-width'] = 3;
    attrs['paint-order'] = 'stroke'; attrs['stroke-linejoin'] = 'round';
    return attrs;
  }
  function div(cls, parent) {
    var d = document.createElement('div'); if (cls) d.className = cls;
    if (parent) parent.appendChild(d); return d;
  }
  function txt(node, s) { node.textContent = s; return node; }
  function dLab(x) { var d = new Date(x); return MONTH[d.getUTCMonth()] + ' ' + d.getUTCFullYear(); }

  /* ---------- share (brief 09) ----------
   * One message = typed hook text (per card, from data-share-text) + the link.
   * On phones navigator.share opens the OS sheet (WhatsApp, iMessage, …). On
   * desktop we fall back to a small popover with X + copy. No storage, no keys. */
  var SHARE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="5" r="3"></circle>' +
    '<circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle>' +
    '<path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"></path></svg>';
  var _sharePanel = null;
  function _closeShare() {
    if (_sharePanel && _sharePanel.parentNode) _sharePanel.parentNode.removeChild(_sharePanel);
    _sharePanel = null;
    document.removeEventListener('mousedown', _shareOutside, true);
  }
  function _shareOutside(e) { if (_sharePanel && !_sharePanel.contains(e.target)) _closeShare(); }
  function _copyFallback(s) {
    var ta = document.createElement('textarea');
    ta.value = s; ta.setAttribute('readonly', '');
    ta.style.position = 'fixed'; ta.style.top = '-1000px'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
  }
  function _copy(s, btn, okMsg) {
    var restore = btn.textContent, done = function () {
      btn.textContent = okMsg;
      setTimeout(function () { btn.textContent = restore; }, 1400);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(s).then(done, function () { _copyFallback(s); done(); });
    } else { _copyFallback(s); done(); }
  }
  function _openSharePanel(text, url, anchor) {
    _closeShare();
    var p = document.createElement('div'); p.className = 'share-panel';
    var full = text + '\n' + url;
    // Direct WhatsApp (desktop): wa.me carries the FULL message in its text param,
    // unlike the Windows share sheet which drops it. Opens WhatsApp web/app.
    var wa = document.createElement('a'); wa.className = 'share-opt share-opt-primary';
    wa.textContent = 'Share on WhatsApp';
    wa.href = 'https://wa.me/?text=' + encodeURIComponent(full);
    wa.target = '_blank'; wa.rel = 'noopener';
    wa.addEventListener('click', function () { _closeShare(); });
    p.appendChild(wa);
    // Copy the whole message (hook text + link) to paste anywhere else.
    var cm = document.createElement('button'); cm.type = 'button';
    cm.className = 'share-opt'; cm.textContent = 'Copy message';
    cm.addEventListener('click', function () { _copy(full, cm, 'Copied — paste it in'); });
    p.appendChild(cm);
    var x = document.createElement('a'); x.className = 'share-opt'; x.textContent = 'Post on X';
    x.href = 'https://twitter.com/intent/tweet?text=' + encodeURIComponent(text) + '&url=' + encodeURIComponent(url);
    x.target = '_blank'; x.rel = 'noopener';
    x.addEventListener('click', function () { _closeShare(); });
    p.appendChild(x);
    document.body.appendChild(p);
    var r = anchor.getBoundingClientRect();
    p.style.top = (r.bottom + window.pageYOffset + 6) + 'px';
    p.style.left = Math.max(8, r.right + window.pageXOffset - p.offsetWidth) + 'px';
    _sharePanel = p;
    setTimeout(function () { document.addEventListener('mousedown', _shareOutside, true); }, 0);
  }
  // Use the OS share sheet whenever the browser offers it (mobile and desktop
  // alike) — its app targets carry the typed text; our panel is the fallback for
  // browsers without the Web Share API.
  function shareWith(text, url, anchor) {
    if (!text || !url) return;
    if (navigator.share) { navigator.share({ text: text, url: url }).catch(function () {}); return; }
    _openSharePanel(text, url, anchor);
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') _closeShare(); });

  function xTicks(fx, x0, x1) {
    if (fx.xLabels) return fx.xLabels.filter(function (t) { return t.x >= x0 - 0.001 && t.x <= x1 + 0.001; });
    var out = [];
    if (fx.xType === 'months') {
      for (var m = 0; m <= x1; m += 6) out.push({ x: m, lab: '' + m });
      return out;
    }
    var y0 = new Date(x0).getUTCFullYear(), y1 = new Date(x1).getUTCFullYear(), span = y1 - y0;
    if (span >= 3) {
      var step = Math.max(1, Math.ceil(span / 6));
      for (var y = Math.ceil(y0 / step) * step; y <= y1; y += step) {
        var t = Date.UTC(y, 0, 1); if (t >= x0 - 1 && t <= x1) out.push({ x: t, lab: '' + y });
      }
    } else {
      var d = new Date(x0); d.setUTCDate(1);
      var stepM = span >= 1 ? 4 : 2;
      while (+d < x0) d.setUTCMonth(d.getUTCMonth() + 1);
      while (+d <= x1) {
        out.push({ x: +d, lab: MONTH[d.getUTCMonth()] + ' ’' + ('' + d.getUTCFullYear()).slice(2) });
        d.setUTCMonth(d.getUTCMonth() + stepM);
      }
    }
    return out.filter(function (t) { return t.x >= x0 - 1; });
  }

  /* split a series into gap-free segments, holes render as breaks, never bridged */
  function segments(pts) {
    if (!pts.length) return [];
    var xs = pts.map(function (p) { return p[0]; }), steps = [];
    for (var i = 1; i < xs.length; i++) steps.push(xs[i] - xs[i - 1]);
    steps.sort(function (a, b) { return a - b; });
    var med = steps.length ? steps[Math.floor(steps.length / 2)] : 0;
    /* A break marks a genuinely missing period, never the normal cadence. Daily series
       breathe on a 1,1,1,1,3(weekend),4(holiday)-day rhythm, so a few days' gap must NOT
       fragment the line — only a real multi-day hole does. The 6-day floor applies to
       date series (ms x); month-indexed views (small integer x) keep the plain 1.75×med. */
    var isTime = xs.length && xs[xs.length - 1] > 1e11;
    var brk = isTime ? Math.max(1.75 * med, med + 6 * 864e5) : 1.75 * med;
    var segs = [], cur = [pts[0]];
    for (var j = 1; j < pts.length; j++) {
      if (med && (xs[j] - xs[j - 1]) > brk) { segs.push(cur); cur = []; }
      cur.push(pts[j]);
    }
    segs.push(cur);
    return segs;
  }

  /* ---------- line template (own-history · term-aligned · vs-benchmark) ---------- */
  /* president identity eras, colour long histories: 4 palette presidents, rest grey */
  var ERA = [
    { t: Date.UTC(2009, 0, 20), c: '#c98500', label: 'Obama' },
    { t: Date.UTC(2017, 0, 20), c: '#199e70', label: 'Trump ’17' },
    { t: Date.UTC(2021, 0, 20), c: '#3987e5', label: 'Biden' },
    { t: Date.UTC(2025, 0, 20), c: '#e66767', label: 'Trump ’25' }
  ];
  var ERA_GREY = '#6c7280';
  function eraColor(x) { var c = ERA_GREY; for (var i = 0; i < ERA.length; i++) { if (x >= ERA[i].t) c = ERA[i].c; } return c; }
  /* full president list for hover labels (incl. pre-Obama, shown in neutral grey) */
  var PRESLIST = [
    { t: Date.UTC(1929, 2, 4), n: 'Hoover' }, { t: Date.UTC(1933, 2, 4), n: 'F. Roosevelt' },
    { t: Date.UTC(1945, 3, 12), n: 'Truman' }, { t: Date.UTC(1953, 0, 20), n: 'Eisenhower' },
    { t: Date.UTC(1961, 0, 20), n: 'Kennedy' }, { t: Date.UTC(1963, 10, 22), n: 'L. Johnson' },
    { t: Date.UTC(1969, 0, 20), n: 'Nixon' }, { t: Date.UTC(1974, 7, 9), n: 'Ford' },
    { t: Date.UTC(1977, 0, 20), n: 'Carter' }, { t: Date.UTC(1981, 0, 20), n: 'Reagan' },
    { t: Date.UTC(1989, 0, 20), n: 'G.H.W. Bush' }, { t: Date.UTC(1993, 0, 20), n: 'Clinton' },
    { t: Date.UTC(2001, 0, 20), n: 'G.W. Bush' }, { t: Date.UTC(2009, 0, 20), n: 'Obama' },
    { t: Date.UTC(2017, 0, 20), n: 'Trump ’17' }, { t: Date.UTC(2021, 0, 20), n: 'Biden' },
    { t: Date.UTC(2025, 0, 20), n: 'Trump ’25' }
  ];
  function presAt(t) { var n = ''; for (var i = 0; i < PRESLIST.length; i++) { if (t >= PRESLIST[i].t) n = PRESLIST[i].n; } return n; }

  function lineChart(box, fx, state) {
    box.innerHTML = '';
    var W = Math.max(300, box.clientWidth), narrow = W < 540;
    var H = narrow ? 240 : 305;
    var capH = (fx.xType === 'months') ? 16 : 0;

    var sers = fx.series.map(function (s) {
      var pts = s.pts;
      if (state.range === 'term' && fx.termStart) pts = pts.filter(function (p) { return p[0] >= fx.termStart; });
      return { label: s.label, color: s.color, pts: pts };
    }).filter(function (s) { return s.pts.length; });

    var presMode = fx.presEras && sers.length === 1 && fx.xType !== 'months';

    var allY = [], allX = [];
    sers.forEach(function (s) { s.pts.forEach(function (p) { allX.push(p[0]); allY.push(p[1]); }); });
    (fx.dots || []).forEach(function (d) { allX.push(d.x); allY.push(d.y); });
    if (fx.benchmark != null) allY.push(fx.benchmark);
    var x0 = fx.xType === 'months' ? 0 : Math.min.apply(null, allX);
    var x1 = fx.xType === 'months' ? (fx.xMax || 48) : Math.max.apply(null, allX);
    var yMin = Math.min.apply(null, allY), yMax = Math.max.apply(null, allY);
    /* Fit levels, anchor rates: charts in absolute units ($ / counts / production /
       index) fit tightly to their data; rate and %-change views (pct, pctsign) keep the
       zero baseline so small moves aren't visually exaggerated. */
    var levelFmt = { usd: 1, usd2: 1, usdB: 1, count: 1, thou: 1, idx: 1 }[fx.fmt];
    var anchorZero = fx.zeroBase !== false && !levelFmt;
    if (anchorZero) { if (yMin > 0) yMin = 0; if (yMax < 0) yMax = 0; }
    if (fx.baseline != null) { yMin = Math.min(yMin, fx.baseline); yMax = Math.max(yMax, fx.baseline); }
    var origMin = yMin, pad = (yMax - yMin) * 0.07 || 1;
    yMax += pad;
    if (anchorZero) { if (yMin < 0) yMin -= pad; }
    else { yMin -= pad; if (origMin >= 0 && yMin < 0) yMin = 0; }   /* don't push a non-negative level below 0 */

    var yT = ticks(yMin, yMax, narrow ? 4 : 5);
    var maxYLab = yT.reduce(function (m, v) { return Math.max(m, fmt(v, fx.fmtAxis || fx.fmt, true).length); }, 0);
    var endLab = fx.direct && sers.length > 1 && !narrow;
    var endW = 0;
    if (endLab) sers.forEach(function (s) {
      var lastx = s.pts[s.pts.length - 1][0];
      if ((x1 - lastx) / (x1 - x0 || 1) > 0.06) return;  /* short lines label at their own dot */
      var L = (s.label + '  ' + fmt(s.pts[s.pts.length - 1][1], fx.fmt)).length * 7.2 + 20;
      endW = Math.max(endW, L);
    });
    var ml = maxYLab * 6.8 + 14, mr = endLab ? Math.min(170, Math.max(14, endW)) : 14, mt = 14, mb = 26 + capH;
    var pw = W - ml - mr, ph = H - mt - mb;
    var X = function (v) { return ml + (v - x0) / (x1 - x0 || 1) * pw; };
    var Y = function (v) { return mt + (yMax - v) / (yMax - yMin || 1) * ph; };

    var svg = el('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, role: 'img',
                          'aria-label': fx.chartTitle });
    yT.forEach(function (v) {
      svg.appendChild(el('line', { x1: ml, x2: ml + pw, y1: Y(v), y2: Y(v), stroke: CLR.grid, 'stroke-width': 1 }));
      var t = el('text', { x: ml - 8, y: Y(v) + 4, 'text-anchor': 'end', fill: CLR.mut,
                           'font-size': '11', style: 'font-variant-numeric:tabular-nums' });
      t.textContent = fmt(v, fx.fmtAxis || fx.fmt, true);
      svg.appendChild(t);
    });
    if (yMin < 0 && yMax > 0)
      svg.appendChild(el('line', { x1: ml, x2: ml + pw, y1: Y(0), y2: Y(0), stroke: CLR.axis, 'stroke-width': 1 }));
    xTicks(fx, x0, x1).forEach(function (tk) {
      var tx = X(tk.x), anchor = 'middle';
      if (tx < ml + 16) anchor = 'start';
      if (tx > ml + pw - 16) anchor = 'end';
      var t = el('text', { x: tx, y: H - 10 - capH, 'text-anchor': anchor, fill: CLR.mut, 'font-size': '11' });
      t.textContent = tk.lab; svg.appendChild(t);
    });
    if (capH) {
      var cap = el('text', { x: ml + pw / 2, y: H - 4, 'text-anchor': 'middle', fill: CLR.mut, 'font-size': '10.5' });
      cap.textContent = fx.xCaption || 'Months in office'; svg.appendChild(cap);
    }
    /* vertical markers: inauguration (solid) · definition breaks (dashed), marked, never smoothed */
    (fx.markers || []).forEach(function (mk) {
      if (mk.x < x0 || mk.x > x1) return;
      var lx = X(mk.x);
      svg.appendChild(el('line', { x1: lx, x2: lx, y1: mt, y2: mt + ph, stroke: CLR.dash,
        'stroke-width': 1, 'stroke-dasharray': mk.kind === 'break' ? '4 4' : 'none', opacity: .85 }));
      var right = lx > ml + pw * 0.62;
      var t = el('text', halo({ x: right ? lx - 5 : lx + 5, y: mt + 10, 'text-anchor': right ? 'end' : 'start',
                           fill: CLR.mut, 'font-size': '10.5', 'font-weight': '600' }));
      t.textContent = mk.label; svg.appendChild(t);
    });
    (fx.gaps || []).forEach(function (g) {
      if (g.x < x0 || g.x > x1) return;
      var gx = X(g.x), right = gx > ml + pw * 0.6;
      var t = el('text', halo({ x: right ? gx - 5 : gx + 5, y: mt + ph * 0.16, 'text-anchor': right ? 'end' : 'start',
                           fill: CLR.mut, 'font-size': '10.5', 'font-style': 'italic' }));
      t.textContent = g.label; svg.appendChild(t);
    });
    if (fx.area !== false) {
      var base = Y(Math.max(0, yMin));
      var areaSeg = function (seg, col, op) {
        if (seg.length < 2) return;
        var d = 'M' + X(seg[0][0]) + ' ' + base;
        seg.forEach(function (p) { d += ' L' + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); });
        d += ' L' + X(seg[seg.length - 1][0]) + ' ' + base + ' Z';
        svg.appendChild(el('path', { d: d, fill: col, opacity: op }));
      };
      if (sers.length === 1 && presMode) {
        segments(sers[0].pts).forEach(function (seg) {
          var run = [seg[0]], curC = eraColor(seg[0][0]);
          for (var i2 = 1; i2 < seg.length; i2++) {
            var c2 = eraColor(seg[i2][0]);
            run.push(seg[i2]);
            if (c2 !== curC) { areaSeg(run, curC, 0.10); run = [seg[i2]]; curC = c2; }
          }
          areaSeg(run, curC, 0.10);
        });
      } else if (sers.length === 1) {
        segments(sers[0].pts).forEach(function (seg) { areaSeg(seg, mapColor(sers[0].color), 0.09); });
      } else {
        sers.forEach(function (s) { segments(s.pts).forEach(function (seg) { areaSeg(seg, mapColor(s.color), 0.05); }); });
      }
    }
    if (fx.benchmark != null) {
      svg.appendChild(el('line', { x1: ml, x2: ml + pw, y1: Y(fx.benchmark), y2: Y(fx.benchmark),
        stroke: CLR.sec, 'stroke-width': 1.5, 'stroke-dasharray': '5 4' }));
      var bt = el('text', halo({ x: ml + pw - 4, y: Y(fx.benchmark) - 6, 'text-anchor': 'end',
                            fill: CLR.sec, 'font-size': '11', 'font-weight': '600' }));
      bt.textContent = fx.benchmarkLabel || ('' + fx.benchmark); svg.appendChild(bt);
    }
    sers.forEach(function (s) {
      segments(s.pts).forEach(function (seg) {
        if (seg.length === 1) {
          svg.appendChild(el('circle', { cx: X(seg[0][0]), cy: Y(seg[0][1]), r: 3,
            fill: presMode ? eraColor(seg[0][0]) : mapColor(s.color) }));
          return;
        }
        if (presMode) {
          var run = [seg[0]], curC = eraColor(seg[0][0]);
          var flush = function () {
            if (run.length < 2) return;
            var dd = '';
            run.forEach(function (p, i) { dd += (i ? ' L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); });
            svg.appendChild(el('path', { d: dd, fill: 'none', stroke: curC, 'stroke-width': 2,
              'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
          };
          for (var j = 1; j < seg.length; j++) {
            var c = eraColor(seg[j][0]);
            run.push(seg[j]);
            if (c !== curC) { flush(); run = [seg[j]]; curC = c; }
          }
          flush();
          return;
        }
        var d = '';
        seg.forEach(function (p, i) { d += (i ? ' L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); });
        svg.appendChild(el('path', { d: d, fill: 'none', stroke: mapColor(s.color), 'stroke-width': 2,
          'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
      });
    });
    /* standalone comparison dots (e.g. a prior president's same-point total pending full backfill) */
    (fx.dots || []).forEach(function (dt) {
      svg.appendChild(el('circle', { cx: X(dt.x), cy: Y(dt.y), r: 4.5, fill: mapColor(dt.color),
        stroke: CLR.surface, 'stroke-width': 2 }));
      if (!narrow) {
        var right = X(dt.x) > ml + pw * 0.6;
        var t = el('text', halo({ x: right ? X(dt.x) - 9 : X(dt.x) + 9, y: Y(dt.y) + 4,
          'text-anchor': right ? 'end' : 'start', fill: CLR.sec, 'font-size': '11', 'font-weight': '600' }));
        t.textContent = dt.label; svg.appendChild(t);
      }
    });
    var ends = sers.map(function (s) {
      var p = s.pts[s.pts.length - 1];
      return { s: s, x: X(p[0]), y: Y(p[1]), v: p[1], px: p[0] };
    });
    ends.forEach(function (e) {
      svg.appendChild(el('circle', { cx: e.x, cy: e.y, r: 4.5, fill: presMode ? eraColor(e.px) : mapColor(e.s.color),
        stroke: CLR.surface, 'stroke-width': 2 }));
    });
    if (endLab) {
      var slots = ends.slice().sort(function (a, b) { return a.y - b.y; });
      slots.forEach(function (e) { e.ly = e.y; });
      for (var k = 1; k < slots.length; k++) {
        var prev = slots[k - 1], cur = slots[k];
        if (Math.abs(cur.x - prev.x) < 80 && cur.ly - prev.ly < 15) cur.ly = prev.ly + 15;
      }
      var over = slots.length ? slots[slots.length - 1].ly - (mt + ph + 4) : 0;
      if (over > 0) slots.forEach(function (e) { if (e.ly > mt + 10) e.ly -= over; });
      slots.forEach(function (e) {
        var text = e.s.label + '  ' + fmt(e.v, fx.fmt);
        var tw = text.length * 6.9, lx = e.x + 9, anchor = 'start';
        if (lx + tw > W - 4) { lx = e.x - 9; anchor = 'end'; }
        if (Math.abs(e.ly - e.y) > 8)
          svg.appendChild(el('line', { x1: e.x + (anchor === 'start' ? 6 : -6), y1: e.y,
            x2: lx + (anchor === 'start' ? -2 : 2), y2: e.ly, stroke: CLR.axis, 'stroke-width': 1 }));
        var t = el('text', halo({ x: lx, y: e.ly + 4, 'text-anchor': anchor, fill: CLR.sec,
          'font-size': '11.5', 'font-weight': '600' }));
        t.textContent = text;
        svg.appendChild(t);
      });
    }
    box.appendChild(svg);
    attachHover(box, svg, fx, sers, { X: X, Y: Y, ml: ml, pw: pw, mt: mt, ph: ph, x0: x0, x1: x1 });
  }

  /* ---------- bar template (annual counts) ---------- */
  function barChart(box, fx, state) {
    box.innerHTML = '';
    var W = Math.max(300, box.clientWidth), narrow = W < 540;
    var H = narrow ? 240 : 305;
    var pts = fx.series[0].pts, color = fx.series[0].color;
    var yMax = Math.max.apply(null, pts.map(function (p) { return p[1] || 0; })) * 1.12;
    var yT = ticks(0, yMax, narrow ? 4 : 5);
    var maxYLab = yT.reduce(function (m, v) { return Math.max(m, fmt(v, fx.fmt, true).length); }, 0);
    var ml = maxYLab * 6.8 + 14, mr = 8, mt = 16, mb = 26;
    var pw = W - ml - mr, ph = H - mt - mb;
    var Y = function (v) { return mt + (yMax - v) / yMax * ph; };
    var band = pw / pts.length, bw = Math.min(24, band * 0.62);
    var svg = el('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': fx.chartTitle });
    yT.forEach(function (v) {
      svg.appendChild(el('line', { x1: ml, x2: ml + pw, y1: Y(v), y2: Y(v), stroke: CLR.grid, 'stroke-width': 1 }));
      var t = el('text', { x: ml - 8, y: Y(v) + 4, 'text-anchor': 'end', fill: CLR.mut, 'font-size': '11',
                           style: 'font-variant-numeric:tabular-nums' });
      t.textContent = fmt(v, fx.fmt, true); svg.appendChild(t);
    });
    var bars = [];
    pts.forEach(function (p, i) {
      var cx = ml + band * i + band / 2;
      if (p[1] == null) {  /* a year with no published figure: labelled hole, never a zero bar */
        var gl = el('text', { x: cx, y: mt + ph + 16, 'text-anchor': 'middle', fill: CLR.mut, 'font-size': '10.5' });
        gl.textContent = p[2]; svg.appendChild(gl);
        var gm = el('text', { x: cx, y: mt + ph - 6, 'text-anchor': 'middle', fill: CLR.mut,
                              'font-size': '10', 'font-style': 'italic' });
        gm.textContent = '·'; svg.appendChild(gm);
        bars.push({ el: gm, cx: cx, y: mt + ph - 20, p: p, hole: true });
        return;
      }
      var x = cx - bw / 2, y = Y(p[1]), h = mt + ph - y;
      var r = Math.min(4, h);
      var d = 'M' + x + ' ' + (mt + ph) + ' L' + x + ' ' + (y + r) + ' Q' + x + ' ' + y + ' ' + (x + r) + ' ' + y +
              ' L' + (x + bw - r) + ' ' + y + ' Q' + (x + bw) + ' ' + y + ' ' + (x + bw) + ' ' + (y + r) +
              ' L' + (x + bw) + ' ' + (mt + ph) + ' Z';
      var bar = el('path', { d: d, fill: mapColor(p[4] || color) });
      svg.appendChild(bar);
      bars.push({ el: bar, cx: cx, y: y, p: p });
      var lab = el('text', { x: cx, y: mt + ph + 16, 'text-anchor': 'middle', fill: CLR.mut, 'font-size': '10.5' });
      lab.textContent = (narrow && i % 2 && pts.length > 8) ? '' : p[2];
      svg.appendChild(lab);
      if ((fx.labelIdx || []).indexOf(i) >= 0) {
        var vt = el('text', halo({ x: cx, y: y - 7, 'text-anchor': 'middle', fill: CLR.sec, 'font-size': '11', 'font-weight': '650' }));
        vt.textContent = fmt(p[1], fx.fmt); svg.appendChild(vt);
      }
    });
    box.appendChild(svg);
    var tip = div('tooltip', box);
    function showBar(i) {
      var b = bars[i]; if (!b) return;
      bars.forEach(function (o) { if (!o.hole) o.el.setAttribute('opacity', o === b ? '1' : '0.55'); });
      tip.innerHTML = '';
      txt(div('tt-x', tip), b.p[3] || b.p[2]);
      var row = div('tt-row', tip);
      var key = div('tt-key', row); key.style.borderColor = color;
      txt(div('tt-val', row), b.hole ? 'not yet published' : fmt(b.p[1], fx.fmt));
      tip.style.display = 'block';
      var tw = tip.offsetWidth;
      tip.style.left = Math.min(Math.max(4, b.cx - tw / 2), W - tw - 4) + 'px';
      tip.style.top = Math.max(2, b.y - tip.offsetHeight - 12) + 'px';
    }
    function hideBar() { tip.style.display = 'none'; bars.forEach(function (o) { if (!o.hole) o.el.setAttribute('opacity', '1'); }); }
    var idx = -1;
    svg.addEventListener('pointermove', function (ev) {
      var r = svg.getBoundingClientRect();
      var i = Math.floor((ev.clientX - r.left - ml) / band);
      if (i >= 0 && i < bars.length) { idx = i; showBar(i); } else hideBar();
    });
    svg.addEventListener('pointerleave', hideBar);
    box.tabIndex = 0;
    box.addEventListener('keydown', function (ev) {
      if (ev.key === 'ArrowRight') { idx = Math.min(bars.length - 1, idx + 1); showBar(idx); ev.preventDefault(); }
      else if (ev.key === 'ArrowLeft') { idx = Math.max(0, idx - 1); showBar(idx); ev.preventDefault(); }
      else if (ev.key === 'Escape') hideBar();
    });
  }

  /* ---------- crosshair + tooltip: snaps to nearest X, lists every series ---------- */
  function attachHover(box, svg, fx, sers, g) {
    var union = {};
    sers.forEach(function (s) { s.pts.forEach(function (p) { union[fx.xType === 'months' ? Math.round(p[0]) : p[0]] = 1; }); });
    var xs = Object.keys(union).map(Number).sort(function (a, b) { return a - b; });
    if (!xs.length) return;
    var steps = []; for (var i = 1; i < xs.length; i++) steps.push(xs[i] - xs[i - 1]);
    steps.sort(function (a, b) { return a - b; });
    var tol = (steps[Math.floor(steps.length / 2)] || 1) * 0.55;
    var cross = el('line', { y1: g.mt, y2: g.mt + g.ph, stroke: CLR.axis, 'stroke-width': 1, visibility: 'hidden' });
    svg.appendChild(cross);
    var tip = div('tooltip', box);
    var idx = -1;
    function show(i) {
      var x = xs[i]; if (x == null) return;
      idx = i;
      cross.setAttribute('x1', g.X(x)); cross.setAttribute('x2', g.X(x));
      cross.setAttribute('visibility', 'visible');
      tip.innerHTML = '';
      txt(div('tt-x', tip), fx.xType === 'months' ? ('Month ' + x + ' of term') : dLab(x));
      var presMode = fx.presEras && sers.length === 1 && fx.xType !== 'months';
      sers.forEach(function (s) {
        var best = null, bd = Infinity;
        s.pts.forEach(function (p) { var d = Math.abs(p[0] - x); if (d < bd) { bd = d; best = p; } });
        if (!best || bd > tol) return;
        var row = div('tt-row', tip);
        var key = div('tt-key', row); key.style.borderColor = presMode ? eraColor(best[0]) : mapColor(s.color);
        txt(div('tt-val', row), fmt(best[1], fx.fmt));
        if (sers.length > 1) txt(div('tt-lab', row), s.label);
        else if (presMode) txt(div('tt-lab', row), presAt(best[0]));
      });
      tip.style.display = 'block';
      var px = g.X(x), left = px + 14;
      if (left + tip.offsetWidth > box.clientWidth - 4) left = px - tip.offsetWidth - 14;
      tip.style.left = Math.max(4, left) + 'px';
      tip.style.top = (g.mt + 8) + 'px';
    }
    function hide() { cross.setAttribute('visibility', 'hidden'); tip.style.display = 'none'; }
    function move(ev) {
      var r = svg.getBoundingClientRect();
      var vx = (ev.clientX - r.left - g.ml) / (g.pw || 1) * (g.x1 - g.x0) + g.x0;
      var bi = 0, bd = Infinity;
      xs.forEach(function (x, i) { var d = Math.abs(x - vx); if (d < bd) { bd = d; bi = i; } });
      show(bi);
    }
    // Touch: claim the gesture so the browser doesn't scroll/select/long-press it
    // away, and capture the pointer so a hold-and-drag keeps tracking the curve.
    svg.addEventListener('pointerdown', function (ev) {
      if (ev.pointerType === 'touch') {
        ev.preventDefault();
        try { svg.setPointerCapture(ev.pointerId); } catch (e) {}
      }
      move(ev);
    });
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerleave', hide);
    svg.addEventListener('pointerup', function (ev) { if (ev.pointerType === 'touch') hide(); });
    svg.addEventListener('pointercancel', hide);
    box.tabIndex = 0;
    box.addEventListener('keydown', function (ev) {
      if (ev.key === 'ArrowRight') { show(Math.min(xs.length - 1, (idx < 0 ? xs.length - 1 : idx + 1))); ev.preventDefault(); }
      else if (ev.key === 'ArrowLeft') { show(Math.max(0, (idx < 0 ? xs.length - 1 : idx - 1))); ev.preventDefault(); }
      else if (ev.key === 'Escape') hide();
    });
    box.addEventListener('focus', function () { if (idx < 0) show(xs.length - 1); });
  }

  /* ---------- table view: the no-hover, screen-reader-clean twin ---------- */
  function buildTable(box, fx) {
    box.innerHTML = '';
    var wrapT = div('dtable', box);
    var table = document.createElement('table');
    var thead = document.createElement('thead'), trh = document.createElement('tr');
    var h0 = document.createElement('th');
    h0.textContent = fx.template === 'bars' ? 'Period' : (fx.xType === 'months' ? 'Month of term' : 'Date');
    trh.appendChild(h0);
    fx.series.forEach(function (s) {
      var th = document.createElement('th');
      th.textContent = fx.series.length > 1 ? s.label : (fx.unitLabel || 'Value');
      trh.appendChild(th);
    });
    thead.appendChild(trh); table.appendChild(thead);
    var tbody = document.createElement('tbody');
    if (fx.template === 'bars') {
      fx.series[0].pts.slice().reverse().forEach(function (p) {
        var tr = document.createElement('tr');
        var td0 = document.createElement('td'); td0.textContent = p[3] || p[2]; tr.appendChild(td0);
        var td = document.createElement('td'); td.textContent = fmt(p[1], fx.fmt); tr.appendChild(td);
        tbody.appendChild(tr);
      });
    } else {
      var union = {};
      fx.series.forEach(function (s, si) {
        s.pts.forEach(function (p) {
          var k = fx.xType === 'months' ? Math.round(p[0]) : p[0];
          (union[k] = union[k] || {})[si] = p[1];
        });
      });
      Object.keys(union).map(Number).sort(function (a, b) { return b - a; }).forEach(function (k) {
        var tr = document.createElement('tr');
        var td0 = document.createElement('td');
        td0.textContent = fx.xType === 'months' ? ('Month ' + k) : dLab(k);
        tr.appendChild(td0);
        fx.series.forEach(function (s, si) {
          var td = document.createElement('td');
          td.textContent = union[k][si] != null ? fmt(union[k][si], fx.fmt) : 'n/a';
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    }
    table.appendChild(tbody); wrapT.appendChild(table);
  }

  /* ---------- snapshot: an honest point-in-time visual for single-point metrics ----------
     Shown until a metric accrues enough history to plot a line. Two shapes: a
     composition bar (parts summing to 100%) and a value-vs-target bar. */
  function snapTone(t) {
    return t === 'muted' ? 'var(--bar-g1)' : t === 'mid' ? 'var(--series-2)' : 'var(--series-1)';
  }
  function renderSnapshot(box, sp) {
    box.innerHTML = '';
    var wrap = div('snap', box);
    if (sp.highlight) txt(div('snap-hl', wrap), sp.highlight);
    if (sp.kind === 'proportion') {
      var bar = div('snap-bar', wrap);
      (sp.parts || []).forEach(function (p) {
        if (!p.pct) return;
        var seg = div('snap-seg', bar);
        seg.style.width = p.pct + '%'; seg.style.background = snapTone(p.tone);
        seg.title = p.label + ' — ' + p.pct + '%';
      });
      var leg = div('snap-legend', wrap);
      (sp.parts || []).forEach(function (p) {
        var row = div('snap-row', leg);
        div('snap-key', row).style.background = snapTone(p.tone);
        txt(div('snap-lab', row), p.label);
        txt(div('snap-val', row), p.pct + '%' + (p.value != null ? '  ·  ' + fnum(p.value) : ''));
      });
    } else if (sp.kind === 'vsTarget') {
      // Neutral by design: the bar extending past the marker already shows "over";
      // we don't colour it as good/bad (going over a low ceiling isn't a value cue).
      var over = sp.target != null && sp.value > sp.target;
      var max = (Math.max(sp.value, sp.target || 0) * 1.14) || 1;
      var track = div('snap-track', wrap);
      var fill = div('snap-fill', track);
      fill.style.width = (sp.value / max * 100) + '%';
      fill.style.background = 'var(--series-1)';
      if (sp.target != null) {
        div('snap-mark', track).style.left = (sp.target / max * 100) + '%';
        var ml = div('snap-mark-lab', track);
        ml.style.left = (sp.target / max * 100) + '%';
        ml.textContent = (sp.targetLabel || 'Target') + ': ' + fnum(sp.target);
      }
      var leg2 = div('snap-legend', wrap);
      var r1 = div('snap-row', leg2);
      div('snap-key', r1).style.background = 'var(--series-1)';
      txt(div('snap-lab', r1), sp.valueLabel || 'Current');
      txt(div('snap-val', r1), fnum(sp.value));
      if (over) txt(div('snap-over', wrap), 'Arrivals have passed the ceiling.');
    }
    if (sp.caption) txt(div('snap-cap', wrap), sp.caption);
  }

  /* ---------- expanded-card assembly (shared by all three templates) ---------- */
  /* ---------- export helpers (CSV built from the active view; JSON = raw payload) ---------- */
  function csvCell(v) { v = '' + (v == null ? '' : v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
  function csvFromView(afx) {
    var head, rows = [];
    if (afx.template === 'bars') {
      head = ['Period', afx.unitLabel || 'Value'];
      afx.series[0].pts.forEach(function (p) { rows.push([p[3] || p[2], p[1] == null ? '' : p[1]]); });
    } else {
      var union = {};
      afx.series.forEach(function (s, si) {
        s.pts.forEach(function (p) { var k = afx.xType === 'months' ? Math.round(p[0]) : p[0]; (union[k] = union[k] || {})[si] = p[1]; });
      });
      head = [afx.xType === 'months' ? 'Month of term' : 'Date'].concat(afx.series.map(function (s) { return s.label; }));
      Object.keys(union).map(Number).sort(function (a, b) { return a - b; }).forEach(function (k) {
        var row = [afx.xType === 'months' ? ('Month ' + k) : dLab(k)];
        afx.series.forEach(function (s, si) { row.push(union[k][si] != null ? union[k][si] : ''); });
        rows.push(row);
      });
    }
    return [head].concat(rows).map(function (r) { return r.map(csvCell).join(','); }).join('\n');
  }
  function saveFile(name, text, type) {
    var url = URL.createObjectURL(new Blob([text], { type: type }));
    var a = document.createElement('a'); a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }
  var DL_ICON = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-1px">' +
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline>' +
    '<line x1="12" y1="15" x2="12" y2="3"></line></svg>';

  function buildDetail(card, fx) {
    var detail = card._detail || card.querySelector('.detail');
    detail.innerHTML = '';
    var hasChart = fx.series && fx.series.length;
    var views = hasChart && fx.views && fx.views.length ? fx.views : null;
    var threeView = !views && hasChart && fx.ownHist && fx.aligned && fx.aligned.series && fx.aligned.series.length;
    var defView = views ? (views.filter(function (v) { return v.def; })[0] || views[views.length - 1]).key : 'full';
    var state = { mode: defView, view: 'chart', real: false };   // mode: term | moi | full, or a custom view key

    /* A sub-view (full history / a named view) is its own chart with its own units and
       scale. Object.assign carries the parent's axis hints along, so drop any fmtAxis /
       baseline the sub-view doesn't set itself — otherwise a $-level axis inherits the
       primary view's %-formatter (debt) or its 100 index-baseline (GDP). */
    function unleak(out, override) {
      if (!('fmtAxis' in override)) delete out.fmtAxis;
      if (!('baseline' in override)) delete out.baseline;
      return out;
    }
    function ownFx() {
      var oh = fx.ownHist || {};
      var ser = (state.real && state.mode === 'full' && oh.seriesReal) ? oh.seriesReal : oh.series;
      return unleak(Object.assign({}, fx, oh, { series: ser, template: 'line', aligned: null }), oh);
    }
    function viewFx() {
      var v = views.filter(function (x) { return x.key === state.mode; })[0] || views[0];
      return unleak(Object.assign({}, fx, v, { views: null }), v);
    }
    function activeFx() {
      if (views) return viewFx();
      if (!threeView) return fx;
      if (state.mode === 'moi') {
        return Object.assign({}, fx, fx.aligned, { template: 'line', presEras: false, ownHist: null,
          markers: fx.aligned.markers || [], gaps: fx.aligned.gaps || [], termStart: null, rangeToggle: false });
      }
      return ownFx();
    }
    function activeRange() { return (!views && state.mode === 'term') ? 'term' : 'full'; }

    var head = div('chart-head', detail);
    var titleNode = div('chart-title', head);
    var ctrl = div('chart-ctrl', head);
    var btns = [];
    function mkBtn(lab, on, active) {
      var b = document.createElement('button'); b.className = 'ctrl-btn' + (active ? ' active' : '');
      b.type = 'button'; b.textContent = lab; b.addEventListener('click', on); ctrl.appendChild(b); return b;
    }
    if (views) {
      views.forEach(function (v) {
        var bb = mkBtn(v.label, function () { state.mode = v.key; sync(); }, v.key === defView);
        btns.push([bb, 'mode', v.key]);
      });
    } else if (threeView) {
      var v1 = mkBtn('This term', function () { state.mode = 'term'; sync(); }, false);
      var v2 = mkBtn(fx.moiLabel || 'Months in office', function () { state.mode = 'moi'; sync(); }, false);
      var v3 = mkBtn('Full history', function () { state.mode = 'full'; sync(); }, true);
      btns.push([v1, 'mode', 'term'], [v2, 'mode', 'moi'], [v3, 'mode', 'full']);
    } else if (hasChart && fx.rangeToggle) {
      var bT = mkBtn('This term', function () { state.mode = 'term'; sync(); }, false);
      var bF = mkBtn('Full history', function () { state.mode = 'full'; sync(); }, true);
      btns.push([bT, 'mode', 'term'], [bF, 'mode', 'full']);
    }

    // Nominal/Real slider: a sub-control of Full history, sits BELOW the view filters
    var realBar = null, rNom = null, rReal = null, rKnob = null;
    if (fx.realToggle && fx.ownHist && fx.ownHist.seriesReal) {
      realBar = div('realbar', detail);
      txt(div('rlbl', realBar), 'Adjust for inflation');
      var rsw = div('rswitch', realBar);
      rKnob = div('rknob', rsw);
      rNom = document.createElement('button'); rNom.type = 'button'; rNom.textContent = 'Nominal $';
      rReal = document.createElement('button'); rReal.type = 'button'; rReal.textContent = 'Real ($' + (fx.realBase || '') + ')';
      rsw.appendChild(rNom); rsw.appendChild(rReal);
      rNom.addEventListener('click', function () { state.real = false; sync(); });
      rReal.addEventListener('click', function () { state.real = true; sync(); });
    }
    // Table is demoted (card-design pass): no longer a peer toggle, it's a quiet
    // "values" link in the footer meta (built below), toggling this same view state.

    var legendBox = div('legend', detail);

    var box = div('chart-box', detail);
    box.setAttribute('role', 'application');
    box.setAttribute('aria-label', (fx.chartTitle || 'chart') + ', arrow keys read values');

    function drawLegend(afx) {
      legendBox.innerHTML = '';
      if (!hasChart) return;
      if (afx.series && afx.series.length > 1) {
        afx.series.forEach(function (s) {
          var item = div('lg', legendBox);
          var key = div('key', item); key.style.borderTopColor = mapColor(s.color);
          item.appendChild(document.createTextNode(s.label));
        });
      } else if (afx.presEras && afx.series && afx.series[0]) {
        // only presidents actually present in the visible data; grey "earlier" omitted
        var pts = afx.series[0].pts;
        if (activeRange() === 'term' && afx.termStart) pts = pts.filter(function (p) { return p[0] >= afx.termStart; });
        var present = {}; pts.forEach(function (p) { present[eraColor(p[0])] = 1; });
        var eras = ERA.filter(function (e) { return present[e.c]; });
        if (eras.length >= 2) {
          eras.forEach(function (e) {
            var item = div('lg', legendBox);
            var key = div('key', item); key.style.borderTopColor = e.c;
            item.appendChild(document.createTextNode(e.label));
          });
        }
      }
    }

    function sync() {
      btns.forEach(function (b) { b[0].classList.toggle('active', state[b[1]] === b[2]); });
      if (realBar) {   // Real is a sub-control of Full history only
        realBar.style.display = (state.mode === 'full') ? '' : 'none';
        rNom.setAttribute('aria-pressed', String(!state.real));
        rReal.setAttribute('aria-pressed', String(state.real));
        rKnob.parentNode.classList.toggle('on', state.real);   // knob slides via CSS, no measurement
      }
      if (!hasChart) {
        legendBox.innerHTML = '';
        box.innerHTML = '';
        if (fx.snapshot) { renderSnapshot(box, fx.snapshot); return; }
        var ac = div('accrue', box);   /* sparse metric: the honest empty state */
        var b1 = document.createElement('b'); b1.textContent = fx.accrueTitle || 'History accrues from here';
        ac.appendChild(b1);
        ac.appendChild(document.createTextNode(fx.accrueBody || ''));
        return;
      }
      var afx = activeFx();
      titleNode.textContent = fx.chartTitle || '';   // constant across views (the filter names the view)
      drawLegend(afx);
      if (state.view === 'table') buildTable(box, afx);
      else if (afx.template === 'bars') barChart(box, afx, { range: activeRange() });
      else lineChart(box, afx, { range: activeRange() });
    }
    card._sync = sync;   // exposed so a theme change can re-render this card's chart
    sync();

    var fur = div('furniture', detail);
    var f1 = div('fbox', fur);
    var h41 = document.createElement('h4'); h41.textContent = 'How the presidency influences this'; f1.appendChild(h41);
    var pc = document.createElement('p');
    var lc = document.createElement('span'); lc.className = 'flabel'; lc.textContent = 'Channels: ';
    pc.appendChild(lc); pc.appendChild(document.createTextNode(fx.channels || '')); f1.appendChild(pc);
    var pl = document.createElement('p');
    var ll = document.createElement('span'); ll.className = 'flabel'; ll.textContent = 'Limits: ';
    pl.appendChild(ll); pl.appendChild(document.createTextNode(fx.limits || '')); f1.appendChild(pl);
    var f2 = div('fbox', fur);
    var h42 = document.createElement('h4'); h42.textContent = 'Read this number carefully'; f2.appendChild(h42);
    (fx.caveats || []).forEach(function (c) {
      var p = document.createElement('p'); p.textContent = c; f2.appendChild(p);
    });

    // Footer meta: source + cadence already live on the collapsed card, so they are not
    // repeated here. Just a colourless graph/table toggle and a clear raw-data link.
    var meta = div('detail-meta', detail);
    if (hasChart) {
      var vtoggle = document.createElement('a'); vtoggle.href = '#'; vtoggle.className = 'vtoggle';
      vtoggle.textContent = 'Table'; vtoggle.title = 'Switch between the chart and the underlying values';
      vtoggle.addEventListener('click', function (ev) {
        ev.preventDefault();
        state.view = state.view === 'table' ? 'chart' : 'table';
        vtoggle.textContent = state.view === 'table' ? 'Graph' : 'Table';
        sync();
      });
      meta.appendChild(vtoggle);
    }
    if (hasChart) {
      var exp = div('exp-group', meta);
      var lbl = div('exp-lbl', exp); lbl.innerHTML = DL_ICON + ' Export';
      var csvL = document.createElement('a'); csvL.href = '#'; csvL.className = 'exp-link';
      csvL.textContent = 'CSV'; csvL.title = 'Download the current view as a spreadsheet (CSV)';
      csvL.addEventListener('click', function (ev) {
        ev.preventDefault();
        saveFile(fx.id + (state.mode ? '-' + state.mode : '') + '.csv', csvFromView(activeFx()), 'text/csv');
      });
      exp.appendChild(csvL);
      var jsonL = document.createElement('a'); jsonL.href = 'd/' + fx.id + '.json'; jsonL.download = fx.id + '.json';
      jsonL.className = 'exp-link'; jsonL.textContent = 'JSON'; jsonL.title = 'The exact data payload behind this chart (JSON)';
      exp.appendChild(jsonL);
    }

    // share button, pushed to the bottom-right of the drawer (brief 09)
    var shareBtn = document.createElement('button');
    shareBtn.type = 'button'; shareBtn.className = 'detail-share';
    shareBtn.innerHTML = SHARE_ICON + '<span>Share</span>';
    shareBtn.setAttribute('aria-label', 'Share this metric');
    shareBtn.addEventListener('click', function () {
      shareWith(card.dataset.shareText, card.dataset.shareUrl, shareBtn);
    });
    meta.appendChild(shareBtn);

    if (window.ResizeObserver) {
      var t; new ResizeObserver(function () {
        clearTimeout(t); t = setTimeout(function () {
          if (!detail.hidden && state.view === 'chart' && hasChart) sync();
        }, 160);
      }).observe(detail);
    }
  }

  /* ---------- expand / collapse (payload fetched on first expand) ---------- */
  var inflight = {};
  function loadDetail(card, cb) {
    var id = card.getAttribute('data-id');
    if (card._fx) return cb(card._fx);
    if (inflight[id]) return;
    inflight[id] = true;
    fetch('d/' + id + '.json').then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    }).then(function (fx) {
      card._fx = fx; inflight[id] = false; cb(fx);
    }).catch(function () {
      inflight[id] = false;
      var detail = card._detail || card.querySelector('.detail');
      detail.innerHTML = '';
      var p = div('accrue', detail);
      txt(p, 'History couldn’t load just now. The figures above are complete; reload to try again.');
      detail.hidden = false; card.classList.add('open'); setLabel(card, true);
    });
  }
  function setLabel(card, open) {
    var span = card.querySelector('.expand-btn span');
    if (span) span.textContent = open ? 'See less' : 'See more';
    var b = card.querySelector('.expand-btn');
    if (b) b.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  /* Drawer expansion: the collapsed card stays in its grid slot; its detail opens
     full-width directly beneath that card's row. One card open at a time. */
  var openCard = null, openDrawer = null;
  function rowLastPeer(card) {
    var grid = card.closest('.grid'); if (!grid) return card;
    var tiles = Array.prototype.slice.call(grid.querySelectorAll(':scope > .tile'));
    var top = card.offsetTop, last = card;
    tiles.forEach(function (t) { if (Math.abs(t.offsetTop - top) < 4) last = t; });
    return last;
  }
  function placeDrawer(card) {
    if (openDrawer) rowLastPeer(card).insertAdjacentElement('afterend', openDrawer);
  }
  function closeOpen(instant) {
    if (!openCard) return;
    var card = openCard, drawer = openDrawer, det = card._detail;
    card.classList.remove('open'); setLabel(card, false);
    openCard = null; openDrawer = null;
    function finish() {
      if (det && det.parentNode === drawer) { det.hidden = true; card.appendChild(det); }
      if (drawer && drawer.parentNode) drawer.parentNode.removeChild(drawer);
    }
    if (instant) { finish(); return; }
    drawer.style.maxHeight = '0';
    setTimeout(finish, 340);
  }
  function openCardDrawer(card, scroll) {
    if (openCard === card) return;
    closeOpen(true);
    loadDetail(card, function (fx) {
      var det = card._detail;
      openDrawer = document.createElement('div');
      openDrawer.className = 'detail-drawer';
      placeDrawer(card);
      det.hidden = false; openDrawer.appendChild(det);           // move into full-width drawer first
      if (!det.dataset.built) { buildDetail(card, fx); det.dataset.built = '1'; }  // then build at full width
      else if (card._sync) card._sync();   // rebuilt already: re-render for the current theme/width
      openCard = card; card.classList.add('open'); setLabel(card, true);
      var h = det.offsetHeight;
      requestAnimationFrame(function () { openDrawer.style.maxHeight = (h + 48) + 'px'; });
      setTimeout(function () { if (openCard === card && openDrawer) openDrawer.style.maxHeight = 'none'; }, 360);
      if (scroll) setTimeout(function () {
        var sb = document.getElementById('stickybar');
        var off = (sb ? sb.offsetHeight : 0) + 12;   // clear the sticky bar
        var y = card.getBoundingClientRect().top + window.pageYOffset - off;
        window.scrollTo({ top: y, behavior: 'smooth' });
      }, 60);
    });
  }
  function toggleDrawer(card) {
    // opening scrolls the card up so the drawer that opens beneath it is in view
    if (openCard === card) closeOpen(false); else openCardDrawer(card, true);
  }
  document.querySelectorAll('.tile[data-id]').forEach(function (card) {
    card._detail = card.querySelector('.detail');
    card.addEventListener('click', function (e) {
      if (e.target.closest('a')) return;                                  // let source links work
      if (e.target.closest('.tile-share')) return;                        // share button handles itself
      if (window.getSelection && String(window.getSelection())) return;   // ignore click that ends a text selection
      toggleDrawer(card);
    });
    var sh = card.querySelector('.tile-share');
    if (sh) sh.addEventListener('click', function (e) {
      e.stopPropagation();
      shareWith(card.dataset.shareText, card.dataset.shareUrl, sh);
    });
  });
  var _rt; window.addEventListener('resize', function () {
    if (!openCard) return;
    clearTimeout(_rt); _rt = setTimeout(function () { placeDrawer(openCard); }, 150);
  });

  /* ---------- category tabs = section nav (scroll-to, not a filter) ----------
     Every category is always in the page. A tab click scrolls to that section
     (its heading is the anchor) and the active tab follows the scroll position. */
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab'));
  var sections = Array.prototype.slice.call(document.querySelectorAll('.category'));
  function barH() { var sb = document.getElementById('stickybar'); return sb ? sb.offsetHeight : 0; }
  // Keep the active tab in view: scroll the tab bar so it's centred (clamped to the
  // ends). Only fires when the active tab actually changes, so vertical scrolling
  // doesn't fight the user's own horizontal scroll.
  function centerTab(t) {
    var bar = document.getElementById('tabs');
    if (!bar || !t || bar.scrollWidth <= bar.clientWidth) return;
    var br = bar.getBoundingClientRect(), tr = t.getBoundingClientRect();
    var target = bar.scrollLeft + (tr.left - br.left) - (bar.clientWidth - t.offsetWidth) / 2;
    target = Math.max(0, Math.min(target, bar.scrollWidth - bar.clientWidth));
    bar.scrollTo({ left: target, behavior: 'smooth' });
  }
  var _activeTab = null;
  function setActiveTab(slug) {
    if (slug === _activeTab) return;
    _activeTab = slug;
    var on = null;
    tabs.forEach(function (t) {
      var a = t.dataset.tab === slug;
      t.classList.toggle('active', a);
      if (a) on = t;
    });
    centerTab(on);
  }
  function scrollToCat(slug, smooth) {
    var sec = document.getElementById(slug);
    if (!sec) return;
    setActiveTab(slug);
    var y = sec.getBoundingClientRect().top + window.pageYOffset - barH() - 10;
    window.scrollTo({ top: Math.max(0, y), behavior: smooth ? 'smooth' : 'auto' });
  }
  tabs.forEach(function (t) {
    t.addEventListener('click', function () {
      var slug = t.dataset.tab;
      if (history.replaceState) history.replaceState(null, '', '#t/' + slug);
      scrollToCat(slug, true);
    });
  });
  /* scroll-spy: the active tab is the last section whose top has passed under the bar */
  var spyPend = false;
  function spy() {
    if (spyPend) return; spyPend = true;
    requestAnimationFrame(function () {
      spyPend = false;
      if (!sections.length) return;
      var line = barH() + 16, cur = sections[0].dataset.tab;
      sections.forEach(function (s) { if (s.getBoundingClientRect().top <= line) cur = s.dataset.tab; });
      setActiveTab(cur);
    });
  }
  window.addEventListener('scroll', spy, { passive: true });
  spy();

  /* ---------- "i" button: jump to the footer page-links ---------- */
  var infoBtn = document.getElementById('infoScroll');
  if (infoBtn) infoBtn.addEventListener('click', function () {
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  });

  /* ---------- board-level share (brief 09) ---------- */
  var boardShareBtn = document.getElementById('boardShare');
  if (boardShareBtn) boardShareBtn.addEventListener('click', function () {
    shareWith(boardShareBtn.dataset.shareText, boardShareBtn.dataset.shareUrl, boardShareBtn);
  });

  /* ---------- sticky header: condense once the hero scrolls past ---------- */
  (function () {
    var sb = document.getElementById('stickybar');
    var hero = document.getElementById('hero');
    var mini = document.getElementById('miniTitle');
    var ctrls = document.getElementById('headCtrls');
    var sbTop = sb ? sb.querySelector('.sb-top') : null;
    var sentinel = document.getElementById('sbSentinel');
    var isStuck = null;
    function place(stuck) {
      if (stuck === isStuck) return;
      isStuck = stuck;
      sb.classList.toggle('stuck', stuck);
      // controls ride in the hero (top-right of the big title) at rest, and drop
      // into the pinned bar once it sticks — one set of buttons, moved in place.
      if (ctrls) {
        if (stuck) { if (ctrls.parentNode !== sbTop) sbTop.appendChild(ctrls); }
        else if (ctrls.parentNode !== hero) { hero.insertBefore(ctrls, hero.firstChild); }
      }
    }
    if (sb && hero) {
      place(false);   // start with controls in the hero
      if (sentinel && 'IntersectionObserver' in window) {
        new IntersectionObserver(function (es) {
          place(!es[0].isIntersecting);
        }, { threshold: 0 }).observe(sentinel);
      } else {
        var ticking = false;
        window.addEventListener('scroll', function () {
          if (ticking) return;
          ticking = true;
          requestAnimationFrame(function () {
            place(window.pageYOffset > sb.offsetTop + 4);
            ticking = false;
          });
        }, { passive: true });
      }
    }
    if (mini) mini.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  })();

  /* ---------- tab bar overflow cue: fade the edge(s) that have more tabs ---------- */
  (function () {
    var bar = document.getElementById('tabs');
    if (!bar || !bar.parentNode) return;
    var wrap = bar.parentNode;
    function upd() {
      var max = bar.scrollWidth - bar.clientWidth;
      wrap.classList.toggle('more-right', bar.scrollLeft < max - 1);
      wrap.classList.toggle('more-left', bar.scrollLeft > 1);
    }
    bar.addEventListener('scroll', upd, { passive: true });
    window.addEventListener('resize', upd);
    upd();
  })();
  function route() {
    var h = location.hash || '';
    if (h.indexOf('#m/') === 0) {
      var id = h.slice(3), card = document.getElementById('card-' + id);
      if (card && card.getAttribute('data-id')) { openCardDrawer(card, true); return; }
    }
    if (h.indexOf('#t/') === 0) { scrollToCat(h.slice(3), false); return; }
  }
  /* ---------- colour theme: system-follow by default, on-page toggle, no storage ----------
     CSS drives the palette (dark default, light via prefers-color-scheme even with JS off).
     The toggle forces a theme for this visit only by setting data-theme; a reload clears it
     and control returns to the system setting. Charts re-render on any change. */
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;
  function effectiveTheme() {
    var t = ROOT.getAttribute('data-theme');
    if (t === 'light' || t === 'dark') return t;
    return (mq && mq.matches) ? 'light' : 'dark';
  }
  var ICON_SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle>' +
    '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path></svg>';
  var ICON_MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"></path></svg>';
  var toggleBtn = document.getElementById('themeToggle');
  function updateToggle() {
    if (!toggleBtn) return;
    var light = effectiveTheme() === 'light';
    toggleBtn.innerHTML = light ? ICON_MOON : ICON_SUN;   // icon = the theme you'd switch TO
    toggleBtn.setAttribute('aria-label', light ? 'Switch to dark theme' : 'Switch to light theme');
    toggleBtn.setAttribute('aria-pressed', light ? 'true' : 'false');
  }
  function applyTheme() {
    refreshTheme();
    updateToggle();
    if (openCard && openCard._sync) openCard._sync();     // live re-render of the open chart
  }
  if (toggleBtn) toggleBtn.addEventListener('click', function () {
    var next = effectiveTheme() === 'dark' ? 'light' : 'dark';
    ROOT.setAttribute('data-theme', next);
    try { localStorage.setItem('tbn-theme', next); } catch (e) {}   // one value, no cookie, stays in-browser
    applyTheme();
  });
  if (mq) {
    var onSys = function () { if (!ROOT.getAttribute('data-theme')) applyTheme(); };
    if (mq.addEventListener) mq.addEventListener('change', onSys);
    else if (mq.addListener) mq.addListener(onSys);       // older Safari
  }
  refreshTheme();   // populate CLR / ERA / PAY before the first chart can render
  updateToggle();

  window.addEventListener('hashchange', route);
  route();

  /* ---------- shared-link landing: /?c=<id> opens that card (brief 09) ----------
     Query form (not a #fragment) so link previews and analytics see a real URL.
     Runs once on load; deep-link #m/<id> still works via route(). */
  (function () {
    var mm = /[?&]c=([^&]+)/.exec(location.search || '');
    if (!mm) return;
    var id = decodeURIComponent(mm[1]).replace(/[^a-z0-9_]/gi, '');
    var card = document.getElementById('card-' + id);
    if (card && card.getAttribute('data-id')) setTimeout(function () { openCardDrawer(card, true); }, 0);
  })();

  /* ---------- client-side freshness (unchanged behavior from v1 board) ---------- */
  var now = new Date();
  document.querySelectorAll('.tile[data-stale-after]').forEach(function (elx) {
    var sa = new Date(elx.getAttribute('data-stale-after') + 'T23:59:59Z');
    if (isNaN(sa)) return;
    if (now > sa) {
      elx.classList.add('is-stale');
      var f = elx.querySelector('.stale-flag');
      if (f) f.hidden = false;
    }
  });
})();
