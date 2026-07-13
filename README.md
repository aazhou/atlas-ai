# Atlas AI

龙哥的智能投资助手 — AI 驱动的多市场实时盯盘与量化策略系统。

## 模块

| 模块 | 页面 | 数据源 |
|:--|:--|:--|
| **A股** | 仪表盘 · 板块资金流 · 选股 · 持仓 | DuckDB (`atlas.duckdb`) |
| **加密** | 策略回测 · V11模拟交易 | DuckDB (`market.duckdb`) |
| **足球** | 世界杯/中超预测 · 成绩单 · 晋级图 | JSON + The Odds API |
| **系统** | Cron看板 | — |

## 架构

```
DuckDB ← cron脚本(每5-10分钟采集) → JSON导出 → GitHub Pages 网站
```

- **数据底座**: DuckDB 存储所有时序数据（板块涨跌、资金流、持仓、K线）
- **采集层**: Python 脚本通过 cron 定时运行，拉取新浪/东方财富/Binance API
- **展示层**: 静态 HTML，从 JSON 文件读取，GitHub Pages 自动部署

## 目录

```
atlas-ai/
├── index.html              # 首页
├── style.css               # 全局样式
├── header.js               # 全局导航
├── system.html             # 系统看板
├── stock/                  # A股模块
│   ├── index.html          # 仪表盘
│   ├── sectors.html        # 板块资金流
│   ├── scanner.html        # 选股
│   └── portfolio.html      # 持仓
├── crypto/                 # 加密模块
│   ├── index.html          # 策略回测
│   └── live.html           # 模拟交易
├── football/               # 足球模块
│   ├── predict.html        # 预测
│   ├── results.html        # 成绩单
│   ├── bracket.html        # 晋级图
│   └── csl.html            # 中超
├── data/                   # 数据文件
│   ├── atlas.duckdb        # A股数据
│   ├── crypto/market.duckdb # 加密K线
│   ├── stock/              # A股JSON导出
│   ├── crypto/             # 加密JSON导出
│   └── football/           # 足球数据
└── scripts/                # 采集脚本
    ├── backtest_final.py   # 加密回测
    ├── v11_sim_trading.py  # V11模拟交易引擎
    ├── v11_trading_cron.py # V11 cron入口
    ├── sector_logger_v2.py # 板块数据采集
    └── archive/            # 历史脚本归档
```

## 数据表 (atlas.duckdb)

| 表 | 说明 | 频率 |
|:--|:--|:--|
| `stock_sectors` | 30个行业ETF涨跌幅 | 每5分钟 |
| `stock_fund_flows` | 50个东财板块主力净流入 | 每5分钟 |
| `stock_portfolio` | A股持仓快照 | 每10分钟 |

## 定时任务

| 任务 | 频率 | 时段 |
|:--|:--|:--|
| 板块数据采集 | 每5分钟 | 交易日 9:30-15:00 |
| 持仓哨兵 | 每10分钟 | 交易日 9:30-15:00 |
| 港股盯盘 | 每整点 | 交易日 9:30-16:00 |
| 美股监控 | 每整点 | 22:00-次日4:00 |
| 每日早报 | 8:00 | 每天 |
| V11加密交易 | 每10分钟 | 7×24 |

## 部署

推送即部署：`git push` → GitHub Pages 自动构建 (https://aazhou.github.io/atlas-ai/)
