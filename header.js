// Atlas AI — 单栏统一导航 v3 (相对路径)
document.addEventListener('DOMContentLoaded', () => {
  const path = window.location.pathname;
  const inStock = path.includes('/stock/');
  const inFootball = path.includes('/football/');
  const inCrypto = path.includes('/crypto/');
  const inCron = path === '/system.html' || path.endsWith('/system.html');

  // Detect depth: pages in subdirectories need ../ prefix
  const depth = (path.match(/\//g) || []).length - 1; // minus trailing slash
  const base = depth > 0 ? '../' : '';

  const svg = {
    trending: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>',
    football: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>',
    crypto: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M16 8h-4a2 2 0 0 0 0 4h1a1.5 1.5 0 0 1 0 3h-5"/><path d="M12 3v2"/><path d="M12 19v2"/></svg>',
    settings: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    dashboard:'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>',
    sectors:  '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    search:   '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    briefcase:'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>',
    trophy:   '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5C6 4 6 4 8 4h8c2 0 2 0 3.5 0a2.5 2.5 0 0 1 0 5H18"/><path d="M6 9v2a6 6 0 0 0 12 0V9"/><line x1="12" y1="15" x2="12" y2="21"/><line x1="8" y1="21" x2="16" y2="21"/></svg>',
    clock:    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    clipboard:'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><line x1="9" y1="14" x2="15" y2="14"/><line x1="9" y1="18" x2="13" y2="18"/></svg>',
    bracket:  '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9H4a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-8a2 2 0 0 0-2-2h-2"/><path d="M6 9V5a2 2 0 0 1 2-2h2"/><path d="M12 3v6"/><path d="M15 9V5a2 2 0 0 1 2-2h2"/><line x1="9" y1="14" x2="11" y2="14"/><line x1="13" y1="14" x2="15" y2="14"/></svg>',
    flask:    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6"/><path d="M10 3v6.5L4 18a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2L14 9.5V3"/><path d="M9 14h6"/></svg>',
  };

  const isActive = (p) => path === p || (p !== '/' && path.startsWith(p));

  let items = [];

  if (inStock) {
    items = [
      { id:'dashboard', href:base+'stock/',             icon:svg.dashboard, label:'仪表盘', active:isActive('/stock/') && !isActive('/stock/sectors.html') && !isActive('/stock/scanner.html') && !isActive('/stock/portfolio.html') && !inCron },
      { id:'sectors',   href:base+'stock/sectors.html',  icon:svg.sectors,   label:'板块',   active:isActive('/stock/sectors.html') },
      { id:'scanner',   href:base+'stock/scanner.html',  icon:svg.search,    label:'选股',   active:isActive('/stock/scanner.html') },
      { id:'portfolio', href:base+'stock/portfolio.html',icon:svg.briefcase, label:'持仓',   active:isActive('/stock/portfolio.html') },
    ];
  } else if (inFootball) {
    items = [
      { id:'predict',   href:base+'football/predict.html',     icon:svg.clock,     label:'预测',   active:path === '/football/predict.html' },
      { id:'results',   href:base+'football/results.html',icon:svg.clipboard, label:'成绩单', active:isActive('/football/results.html') },
      { id:'bracket',   href:base+'football/bracket.html',icon:svg.bracket,   label:'晋级图', active:isActive('/football/bracket.html') },
    ];
  } else if (inCrypto) {
    items = [
      { id:'backtest',  href:base+'crypto/',           icon:svg.flask,     label:'回测',   active:path === '/crypto/' || path === '/crypto/index.html' },
      { id:'live',      href:base+'crypto/live.html',  icon:svg.briefcase, label:'实盘',   active:isActive('/crypto/live.html') },
    ];
  }

  function itemHtml(item) {
    var cls = item.active ? 'an-item active' : 'an-item';
    return '<a href="'+item.href+'" class="'+cls+'">'+item.icon+'<span>'+item.label+'</span></a>';
  }

  var subNavHtml = items.map(itemHtml).join('');

  // Build header
  var header = '<header class="an-bar">';
  header += '<div class="an-bar-inner">';
  header += '<a href="'+base+'" class="an-brand">Atlas AI</a>';
  header += '<nav class="an-nav">' + subNavHtml + '</nav>';
  header += '<div class="an-switch">';
  header += '<a href="'+base+'stock/" class="an-sw-item'+(inStock?' active':'')+'">'+svg.trending+'<span>A股</span></a>';
  header += '<a href="'+base+'football/predict.html" class="an-sw-item'+(inFootball?' active':'')+'">'+svg.football+'<span>足球</span></a>';
  header += '<a href="'+base+'crypto/" class="an-sw-item'+(inCrypto?' active':'')+'">'+svg.crypto+'<span>加密</span></a>';
  header += '<a href="'+base+'system.html" class="an-sw-item'+(inCron?' active':'')+'">'+svg.settings+'<span>看板</span></a>';
  header += '</div>';
  header += '</div></header>';

  document.body.insertAdjacentHTML('afterbegin', header);
});
