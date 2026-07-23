// Atlas Terminal v3 — Shared data fetching & rendering
const T = window.T || {};

// Config
T.DATA_BASE = '../data';
T.TODAY = new Date().toISOString().slice(0,10);

// Fetch JSON with fallback
T.fetchJSON = async function(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch(e) {
    console.warn('Data fetch failed:', path, e.message);
    return null;
  }
};

// Format: +1.23% or -0.45%
T.fmtPct = function(v) {
  if (v == null) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(2)}%`;
};

// Format money: 12.8亿 or 542亿
T.fmtMoney = function(v) {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}亿`;
};

// Chg class: 'up' or 'down'
T.chgClass = function(v) {
  if (v == null) return '';
  return v >= 0 ? 'up' : 'down';
};

// Render a "no data" state
T.noData = function(msg) {
  return `<div class="no-data">${msg || '数据收集中'}</div>`;
};

// Render global bar (top)
T.renderGlobalBar = function(overview) {
  if (!overview || !overview.indices) return '';
  const idx = overview.indices;
  let pills = [];

  // A-share
  (idx.a || []).forEach(function(x) {
    pills.push(`<span class="pill live"><span class="flag">🇨🇳</span><span class="name">${x.name}</span><span class="val">${x.val}</span><span class="chg ${T.chgClass(x.chg)}">${T.fmtPct(x.chg)}</span></span>`);
  });
  // HK
  if (idx.hk) {
    pills.push(`<span class="pill live"><span class="flag">🇭🇰</span><span class="name">${idx.hk.name}</span><span class="val">${idx.hk.val}</span><span class="chg ${T.chgClass(idx.hk.chg)}">${T.fmtPct(idx.hk.chg)}</span></span>`);
  }
  // US (closed during Asia hours)
  (idx.us || []).forEach(function(x) {
    pills.push(`<span class="pill closed"><span class="flag">🇺🇸</span><span class="name">${x.name}</span><span class="val">${x.val}</span><span class="chg ${T.chgClass(x.chg)}">${T.fmtPct(x.chg)}</span></span>`);
  });
  // Crypto (always live)
  (idx.crypto || []).forEach(function(x) {
    pills.push(`<span class="pill live"><span class="flag">₿</span><span class="name">${x.name}</span><span class="val">${T.formatCrypto(x.val)}</span><span class="chg ${T.chgClass(x.chg)}">${T.fmtPct(x.chg)}</span></span>`);
  });

  return `<div class="global-bar"><div class="wrap">${pills.join('')}</div></div>`;
};

// Format crypto price (comma-separated)
T.formatCrypto = function(v) {
  if (v == null) return '—';
  return v.toLocaleString('en-US');
};

// Render alert strip
T.renderAlerts = function(alerts) {
  if (!alerts || !alerts.length) return '';
  const a = alerts[0];
  const cls = a.priority === 'high' ? 'high' : a.priority === 'medium' ? 'medium' : 'info';
  const ico = a.priority === 'high' ? '⚡' : a.priority === 'medium' ? '⚠' : 'ℹ';
  return `<div class="alert-strip ${cls}" onclick="this.style.display='none'">
    <span class="icon">${ico}</span>
    <span class="body">
      <div class="title">${a.title}</div>
      ${a.desc ? '<div class="desc">'+a.desc+'</div>' : ''}
    </span>
    ${a.action ? '<span class="action">'+a.action+'</span>' : ''}
  </div>`;
};

// Render bottom navigation
T.renderBottomNav = function(active) {
  var tabs = [
    {id:'global', ico:'🌍', label:'全局', href:'../index.html'},
    {id:'stock',   ico:'🇨🇳', label:'A股', href:'../stock/index.html'},
    {id:'hk',      ico:'🇭🇰', label:'港股', href:'../hk/index.html'},
    {id:'us',      ico:'🇺🇸', label:'美股', href:'../us/index.html'},
    {id:'crypto',  ico:'₿', label:'加密', href:'../crypto/index.html'},
  ];
  return '<div class="bottom-nav">' + tabs.map(function(t) {
    var cls = t.id === active ? 'tab active' : 'tab';
    return '<a class="'+cls+'" href="'+t.href+'"><span class="ico">'+t.ico+'</span>'+t.label+'</a>';
  }).join('') + '</div>';
};

// Update time display
T.updateTime = function() {
  var el = document.getElementById('update-time');
  if (el) {
    var now = new Date();
    el.textContent = now.toTimeString().slice(0,5) + ' CST';
    setTimeout(T.updateTime, 30000);
  }
};

// Load and render a page
T.loadPage = async function(options) {
  var opts = options || {};
  var dataPath = opts.dataPath || '';
  var activeTab = opts.activeTab || 'global';
  var renderFn = opts.render || function(){};

  // Show loading
  var root = document.getElementById(opts.rootId || 'app');
  if (!root) return;

  var overview = null;

  // Load overview for global bar (all pages)
  try {
    var base = activeTab === 'global' ? 'data' : '../data';
    overview = await T.fetchJSON(base + '/terminal/overview.json');
  } catch(e) {}

  // Render global bar
  var barHTML = T.renderGlobalBar(overview);

  // Render alert strip (if alerts exist)
  var alertHTML = '';
  if (overview && overview.alerts && overview.alerts.length) {
    alertHTML = T.renderAlerts(overview.alerts);
  }

  // Load page-specific data
  var pageData = null;
  if (dataPath) {
    pageData = await T.fetchJSON(dataPath);
  }

  // Render content
  var contentHTML = renderFn(pageData, overview);

  // Render bottom nav
  var navHTML = T.renderBottomNav(activeTab);

  root.innerHTML = barHTML + alertHTML + '<div class="page-wrap">' + contentHTML + '</div>' + navHTML;

  // Start time updater
  T.updateTime();
};
