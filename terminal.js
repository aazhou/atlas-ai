/**
 * Atlas Terminal v2 — 全球金融投研终端
 * Shared JS: data fetching, rendering, navigation
 * 诸葛设计 · 鲁班实现 · 2026-07-23
 */

const T = {
  _data: {},

  // ── Utils ──
  fmt(n, d) { return Number(n||0).toFixed(d||0); },
  sign(n) { return (n||0) >= 0 ? '+' : ''; },
  upDn(v) { return (v||0) >= 0 ? 'up' : 'down'; },
  pct(v) { return (v||0) >= 0 ? '+' + T.fmt(v,2) + '%' : T.fmt(v,2) + '%'; },
  fmtMoney(n) {
    if (Math.abs(n) >= 1e8) return T.fmt(n/1e8,2) + '亿';
    if (Math.abs(n) >= 1e4) return T.fmt(n/1e4,1) + '万';
    return T.fmt(n,0);
  },
  w(v) { return v >= 0 ? '+' + v : '' + v; },
  cw(v) { return v >= 0 ? 'up' : 'down'; },

  // ── Fetch with fallback ──
  async fetchJSON(url, fallback) {
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return await r.json();
    } catch(e) {
      console.warn('Fetch failed for', url, ', using fallback. ', e.message);
      return fallback;
    }
  },

  // ── Render: Global Status Bar ──
  renderStatusBar(indices) {
    const el = document.getElementById('globalStatus');
    if (!el || !indices) return;
    let h = '';
    // A-share indices
    (indices.a||[]).forEach(i => {
      h += T._mktPill('🇨🇳', i.name, i.val, i.chg, 'live');
    });
    // HK
    if (indices.hk) h += T._mktPill('🇭🇰', indices.hk.name, indices.hk.val, indices.hk.chg, 'live');
    // US
    (indices.us||[]).forEach(i => {
      h += T._mktPill('🇺🇸', i.name, i.val, i.chg, 'closed');
    });
    // Crypto
    (indices.crypto||[]).forEach(i => {
      h += T._mktPill('₿', i.name, i.val, i.chg, 'live');
    });
    el.innerHTML = h;
  },
  _mktPill(flag, name, val, chg, status) {
    const cls = chg >= 0 ? 'up' : 'down';
    return `<button class="mkt-pill">
      <span class="mkt-dot ${status}"></span>
      <span class="mkt-flag">${flag}</span>
      <span class="mkt-name">${name}</span>
      <span class="mkt-val">${val}</span>
      <span class="mkt-chg ${cls}">${T.w(chg)}%</span>
    </button>`;
  },

  // ── Render: Alert Strip ──
  renderAlertStrip(alerts) {
    const el = document.getElementById('alertStrip');
    if (!el || !alerts || !alerts.length) { if(el) el.style.display='none'; return; }
    const a = alerts[0];
    const type = a.priority === 'high' ? '' : ' warn';
    el.className = 'alert-strip' + type;
    el.innerHTML = `<span class="alert-icon">⚡</span>
      <div class="alert-body">
        <strong>${a.title}</strong><br>
        <span class="muted">${a.desc} | ${a.time}</span>
      </div>`;
    el.style.display = '';
    el.onclick = () => { window.location.href = 'signals.html'; };
  },

  // ── Render: Portfolio Total Card ──
  renderTotalCard(pt) {
    const el = document.getElementById('totalCard');
    if (!el || !pt) return;
    el.innerHTML = `<div class="card-top">
        <span class="card-title">💰 总资产</span>
        <span class="card-badge" style="background:var(--bull-dim);color:var(--accent-bull)">今日</span>
      </div>
      <div class="card-body">
        <div class="card-main">¥${T.fmtMoney(pt.value)}<span class="chg ${T.cw(pt.daily_pnl_pct)}">${T.w(pt.daily_pnl_pct)}%</span></div>
        <div class="card-stats">
          <div>日盈亏 <span class="${T.cw(pt.daily_pnl)}">${T.sign(pt.daily_pnl)}¥${T.fmtMoney(Math.abs(pt.daily_pnl))}</span></div>
          <div>周盈亏 <span class="${T.cw(pt.weekly_pnl)}">${T.sign(pt.weekly_pnl)}¥${T.fmtMoney(Math.abs(pt.weekly_pnl))}</span></div>
        </div>
      </div>`;
  },

  // ── Render: Holdings Mini Grid ──
  renderHoldingsGrid(holdings) {
    if (!holdings) return;
    const mkts = [
      { key:'a_stock', label:'🇨🇳 A股 持仓' },
      { key:'hk', label:'🇭🇰 港股' },
      { key:'us', label:'🇺🇸 美股' },
      { key:'crypto', label:'₿ 加密' },
    ];
    const container = document.getElementById('holdingsGrid');
    if (!container) return;
    let h = '';
    mkts.forEach(m => {
      const items = holdings[m.key];
      if (!items || !items.length) return;
      h += `<div class="term-divider">${m.label}</div><div class="mini-grid">`;
      items.forEach(it => {
        h += `<div class="mini-item" onclick="location.href='portfolio.html'">
          <div class="sym">${it.sym}</div>
          <div class="price ${T.cw(it.chg)}">${it.price}</div>
          <div class="chg ${T.cw(it.chg)}">${T.w(it.chg)}%</div>
        </div>`;
      });
      h += '</div>';
    });
    container.innerHTML = h;
  },

  // ── Render: Signals List ──
  renderSignalsList(signals, containerId) {
    const el = document.getElementById(containerId||'signalsList');
    if (!el || !signals || !signals.length) return;
    let h = '';
    signals.forEach(s => {
      const cls = s.priority === 'high' ? '' : s.priority === 'medium' ? ' warn' : ' info';
      const tagCls = s.priority === 'high' ? 'red' : s.priority === 'medium' ? 'amber' : 'blue';
      h += `<div class="sig-card${cls}">
        <div class="sig-head">
          <span class="sig-tag ${tagCls}">${s.tag}</span>
          <span class="sig-time">${s.time}</span>
        </div>
        <div class="sig-title">${s.title}</div>
        <div class="sig-desc">${s.desc}</div>
        ${s.action ? `<div class="sig-action">💡 ${s.action}</div>` : ''}
      </div>`;
    });
    el.innerHTML = h;
  },

  // ── Render: Sector Flows ──
  renderSectorFlows(flows) {
    const el = document.getElementById('sectorFlows');
    if (!el || !flows) return;
    let h = '<div class="term-divider">📊 板块资金异动（Top/Bottom 3）</div>';
    (flows.top3||[]).forEach(f => {
      h += `<div class="detail-row"><span class="label">🏆 ${f.name}</span><span class="value up">+${T.fmt(f.flow,1)}亿</span><span class="sub up">+${T.fmt(f.chg,1)}%</span></div>`;
    });
    (flows.bottom3||[]).forEach(f => {
      h += `<div class="detail-row"><span class="label">⚠️ ${f.name}</span><span class="value down">${T.fmt(f.flow,1)}亿</span><span class="sub down">${T.fmt(f.chg,1)}%</span></div>`;
    });
    el.innerHTML = h;
  },

  // ── Render: Priority Summary ──
  renderPrioritySummary(summary) {
    const el = document.getElementById('prioritySummary');
    if (!el || !summary) return;
    el.innerHTML = `<div class="card-top">
        <span class="card-title">🔴 需要行动 · ${summary.high}条</span>
      </div>
      <div class="card-body" style="font-size:12px;color:var(--text-muted)">
        🔴 ${summary.high}条高优 · 🟡 ${summary.medium}条中优 · 🔵 ${summary.info}条提示 · 共${summary.total}条信号
      </div>`;
  },

  // ── Render: Positions (by market) ──
  renderPositions(marketKey, marketData) {
    const el = document.getElementById('positionsContent');
    if (!el || !marketData) return;
    const positions = marketData.positions || [];
    let h = '';
    positions.forEach(p => {
      const hasAlert = p.alerts && p.alerts.length > 0;
      const badgeHTML = hasAlert
        ? `<span class="card-badge" style="background:var(--bear-dim);color:var(--accent-bear)">⚠️ ${p.alerts[0]}</span>`
        : `<span class="card-badge" style="background:var(--bull-dim);color:var(--accent-bull)">持仓</span>`;
      const indCls = hasAlert ? 'down' : '';
      h += `<div class="term-card">
        <div class="card-top">
          <span class="card-title">${p.sym}</span>${badgeHTML}
        </div>
        <div class="card-body">
          <div class="card-main">${p.price}<span class="chg ${T.cw(p.chg)}">${T.w(p.chg)}%</span></div>
          <div class="card-stats">
            <div>成本 ${p.cost}</div>
            <div>盈亏 <span class="${T.cw(p.pnl_pct)}">${T.w(p.pnl_pct)}%</span></div>
          </div>
        </div>
        <div style="font-size:10px;color:${hasAlert?'var(--accent-bear)':'var(--text-muted)'};margin-top:4px">${p.indicators}</div>
      </div>`;
    });
    // AI analysis
    if (marketData.ai_analysis) {
      h += `<div class="term-card ai-block">
        <div class="card-top"><span class="card-title">🤖 AI 持仓研判</span></div>
        <div class="ai-body">${marketData.ai_analysis}</div>
      </div>`;
    }
    el.innerHTML = h;
  },

  // ── Switch market tab (portfolio page) ──
  switchMarket(key) {
    document.querySelectorAll('.mkt-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.market === key);
    });
    const data = T._data.portfolio;
    if (data && data.markets && data.markets[key]) {
      T.renderPositions(key, data.markets[key]);
    }
  },

  // ── Render: Tools ──
  renderTools(data) {
    // Review card
    const rEl = document.getElementById('reviewCard');
    if (rEl && data.review) {
      rEl.innerHTML = `<div class="card-top">
          <span class="card-title">📋 今日复盘</span>
          <span class="card-badge" style="background:var(--blue-dim);color:var(--accent-blue)">${data.review.time}生成</span>
        </div>
        <div class="tool-card desc">${data.review.date} 复盘${data.review.available?'已':''}生成。${data.review.summary}</div>`;
    }
    // DuckDB
    const dEl = document.getElementById('duckdbCard');
    if (dEl && data.duckdb) {
      const stat = data.duckdb.status === 'normal' ? '<span style="color:var(--accent-bull)">● 正常运行</span>' : '<span style="color:var(--accent-bear)">● 异常</span>';
      dEl.innerHTML = `<div class="card-top"><span class="card-title">🗄️ DuckDB 数据底座</span></div>
        <div class="tool-card desc">${data.duckdb.atlas_db}<br>${data.duckdb.market_db}<br>今日采集: ${stat} · ${data.duckdb.today_records}条记录</div>`;
    }
    // Backtest
    const bEl = document.getElementById('backtestCard');
    if (bEl && data.backtest) {
      const fr = data.backtest.funding_rate;
      const oi = data.backtest.oi_divergence;
      bEl.innerHTML = `<div class="card-top">
          <span class="card-title">📈 策略回测</span>
          <span class="card-badge" style="background:var(--gold-dim);color:var(--accent-gold)">加密量化</span>
        </div>
        <div class="tool-card desc">${fr.name} · 最近30天胜率 ${fr.win_rate}% · 平均收益 +${fr.avg_return}%<br>${oi.name} · 最近30天信号 ${oi.signals_30d}次 · 胜率 ${oi.win_rate}%</div>`;
    }
    // System
    const sEl = document.getElementById('systemCard');
    if (sEl && data.system) {
      const sys = data.system;
      sEl.innerHTML = `<div class="card-top"><span class="card-title">⚙️ 系统状态</span></div>
        <div class="tool-card desc">Cron: ${sys.cron.active}活跃 · ${sys.cron.error}异常 · ${sys.cron.paused}暂停<br>数据: A股${sys.data.a_stock?'✅':'❌'} 美股${sys.data.us?'✅':'❌'} 港股${sys.data.hk?'✅':'❌'} 加密${sys.data.crypto?'✅':'❌'}<br>部署: 阿里云${sys.deploy.aliyun?'✅':'❌'} Vercel${sys.deploy.vercel?'✅':'❌'} GH Pages${sys.deploy.github_pages?'✅':'❌'}<br>上次采集: ${sys.last_collect} · 下次: ${sys.next_collect}</div>`;
    }
  },

  // ── Load Data ──
  async loadData(page) {
    const dataDir = 'data/terminal/';
    try {
      // Always load overview for status bar
      T._data.overview = await T.fetchJSON(dataDir + 'overview.json', T._fallbackOverview());

      if (page === 'pano' || page === 'all') {
        const ov = T._data.overview;
        T.renderStatusBar(ov.indices);
        T.renderAlertStrip(ov.alerts);
        T.renderTotalCard(ov.portfolio_total);
        T.renderHoldingsGrid(ov.holdings);
      }

      if (page === 'signal' || page === 'all') {
        T._data.signals = await T.fetchJSON(dataDir + 'signals.json', T._fallbackSignals());
        const sg = T._data.signals;
        T.renderPrioritySummary(sg.summary);
        T.renderSignalsList(sg.signals);
        T.renderSectorFlows(sg.sector_flows);
      }

      if (page === 'pos' || page === 'portfolio' || page === 'all') {
        T._data.portfolio = await T.fetchJSON(dataDir + 'portfolio.json', T._fallbackPortfolio());
        // Default to a_stock
        if (T._data.portfolio && T._data.portfolio.markets) {
          T.switchMarket('a_stock');
        }
      }

      if (page === 'tool' || page === 'tools' || page === 'all') {
        T._data.tools = await T.fetchJSON(dataDir + 'tools.json', T._fallbackTools());
        T.renderTools(T._data.tools);
      }
    } catch(e) {
      console.error('Data loading error:', e);
    }
  },

  // ── Fallback data (offline / first load) ──
  _fallbackOverview() {
    return {
      indices: { a:[{name:'上证',val:3258,chg:0.8},{name:'深证',val:11240,chg:1.2}], hk:{name:'恒指',val:19842,chg:1.2}, us:[{name:'SPY',val:592.4,chg:-0.3}], crypto:[{name:'BTC',val:67250,chg:2.1}] },
      alerts: [{priority:'high',title:'数据加载中...',desc:'请稍候',time:'--'}],
      portfolio_total: {value:1847200,daily_pnl:33800,daily_pnl_pct:1.86,weekly_pnl:52100},
      holdings: { a_stock:[{sym:'创业板ETF',price:2.486,chg:1.88},{sym:'科创50ETF',price:1.092,chg:2.15},{sym:'半导体ETF',price:0.874,chg:-0.68}], hk:[{sym:'腾讯',price:385.2,chg:2.3},{sym:'阿里',price:92.5,chg:1.8}], us:[{sym:'NVDA',price:142.8,chg:-1.5},{sym:'TSLA',price:248.6,chg:-2.8}], crypto:[{sym:'BTC',price:67250,chg:2.1}] }
    };
  },
  _fallbackSignals() {
    return { summary:{high:1,medium:2,info:2,total:5}, signals:[{priority:'high',tag:'高优先级',time:'14:35',title:'BTC 费率反转信号',desc:'数据加载中...'}], sector_flows:{top3:[],bottom3:[]} };
  },
  _fallbackPortfolio() {
    return { markets:{a_stock:{positions:[{sym:'创业板ETF',price:2.486,chg:1.88,cost:2.312,pnl_pct:7.5,indicators:'MACD金叉',alerts:[]}],ai_analysis:'数据加载中...'}} };
  },
  _fallbackTools() {
    return { review:{available:true,date:'2026-07-23',time:'16:30',summary:'加载中...'}, duckdb:{status:'normal',today_records:0,atlas_db:'',market_db:''}, backtest:{funding_rate:{name:'费率反转',win_rate:64,avg_return:2.3},oi_divergence:{name:'OI背离',win_rate:58,avg_return:1.8}}, system:{cron:{active:0,error:0,paused:0},data:{a_stock:false,us:false,hk:false,crypto:false},deploy:{aliyun:false,vercel:false,github_pages:false},last_collect:'--',next_collect:'--'} };
  },

  // ── Init: called by each page ──
  init(page) {
    document.addEventListener('DOMContentLoaded', () => T.loadData(page));
  }
};
