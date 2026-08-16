# 📈 AI 股票投研助手

基于 **AkShare + FastAPI + LLM** 的 A 股投研 Web 应用：行情图表、技术指标、多因子量化评分、AI 智能研报，一站式完成。

## ✨ 功能

| 模块 | 说明 |
|---|---|
| 📊 K线图表 | **klinecharts 9** 专业K线（蜡烛/MA/成交量/MACD 副图、十字光标、缩放平移），库加载失败自动降级 Canvas 自绘 |
| 🔍 智能搜索 | 代码/名称联想，全市场快照索引 |
| 📈 技术指标 | 自研：MACD / RSI / KDJ / BOLL / ATR / 均线系统，含金叉死叉、超买超卖信号 |
| ➕ 扩展指标 | **pandas-ta**：OBV 能量潮 / CCI / 威廉 WR / MFI 资金流 / ADX 趋势强度 / CMF（缺失时自动跳过） |
| 🧮 量化评分 | 趋势/动量/波动/量能资金 四因子 0-100 评分 + 评级 + 归因解读 |
| 💰 资金流向 | 主力近 10 日净流入柱状图 |
| 🤖 AI 研报 | 聚合全部分析上下文 → LLM 生成结构化投研简报（Markdown 渲染） |
| 📰 消息面（妙想） | 东方财富妙想 MCP：资讯/公告语义检索卡片，AI 研报自动引用；AkShare 自动回退 |
| 🗜️ 磁盘缓存 | pickle + TTL，行情 5min / 日线 2h / 新闻 1h，大幅减少重复请求 |

## 🚀 快速开始

```bash
# 1. 安装依赖（Python 3.10+）
pip install -r requirements.txt

# 2. 配置 LLM（可选，不配则 AI 研报不可用，其余功能正常）
copy .env.example .env
# 编辑 .env 填入 LLM_API_KEY（支持 DeepSeek / OpenAI / Kimi 等兼容接口）

# 3. 启动
python run.py
# 打开 http://127.0.0.1:8000
```

> 本仓库自带 `vendor/` 目录时无需 pip 安装，`run.py` 会自动加载。

## ⚙️ 配置（.env）

| 变量 | 说明 | 默认 |
|---|---|---|
| `LLM_API_KEY` | OpenAI 兼容接口密钥 | 无（必填才可用 AI 研报） |
| `EM_API_KEY` | 妙想（东方财富）API KEY，启用消息面与 11 个金融工具 | 无（可选，缺失时回退 AkShare） |
| `LLM_BASE_URL` | 接口地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | 模型名 | `deepseek-chat` |
| `HOST` / `PORT` | 监听地址 | `127.0.0.1` / `8000` |

## 🔌 API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 前端页面 |
| GET | `/api/health` | 健康检查 + LLM 配置状态 |
| GET | `/api/search?q=` | 股票搜索联想 |
| GET | `/api/index-brief` | 上证/深成/创业板指数概览 |
| GET | `/api/kline?symbol=600519&days=120` | 日K + 逐行指标（MA/MACD/RSI） |
| GET | `/api/analysis?symbol=600519` | 指标汇总 + 量化评分 + 资金流 |
| POST | `/api/report` body `{"symbol":"600519"}` | AI 生成投研简报（Markdown） |
| GET | `/api/mx/status` | 妙想配置状态与可用工具清单 |
| GET | `/api/mx/news?symbol=600519` | 妙想资讯检索（自动降级 AkShare） |
| GET | `/api/mx/notices?symbol=600519` | 妙想公告检索 |
| POST | `/api/mx/call` body `{"tool":"mx_macro_data","query":"中国CPI"}` | 妙想 11 工具通用调用（A股/港美股/基金/债券/宏观/选股器…） |

## 🧪 测试

```bash
python tests/test_analysis.py   # 30 项离线断言：指标数值/边界/评分单调性/LLM容错
```

## 📁 结构

```
app/
├── main.py            # FastAPI 路由
├── config.py          # 配置（.env）
├── web/index.html     # 前端单页（Canvas K线 + 评分面板 + Markdown 渲染）
├── data/
│   ├── source.py      # AkShare 封装（行情/资料/资金流/新闻/指数）
│   └── cache.py       # 磁盘缓存装饰器
├── analysis/
│   ├── indicators.py  # 技术指标（纯 pandas）
│   └── scoring.py     # 四因子评分引擎
└── ai/
    ├── llm.py         # OpenAI 兼容客户端（httpx）
    └── research.py    # 研报 Prompt + 上下文聚合
```

## ⚠️ 免责声明

本项目仅供学习研究，数据来自公开接口，AI 生成的分析不构成任何投资建议。

## 🧩 可扩展方向

- **TradingAgents 式多智能体**：多空辩论生成更深度研报
- **Tushare/Baostock** 备用数据源与财务报表分析

## 📡 妙想（MX）数据集成

项目内置妙想 MCP 客户端（`app/data/mx.py`），直连东方财富妙想端点（无状态 JSON-RPC）：

- **启用**：`.env` 中设置 `EM_API_KEY`（mx.eastmoney.com 申请），不设置则自动回退 AkShare
- **能力**：资讯/公告语义检索（前端「消息面」卡片 + AI 研报上下文）、
  A股/港美股/基金/债券/指数/宏观数据查询、选股器 —— 全部通过 `POST /api/mx/call` 透传
- **缓存**：资讯/公告 1 小时、通用查询 30 分钟（磁盘缓存）

## 📌 集成与网络说明

- **pandas-ta 0.4.71b0**：官方仅支持 Python≥3.12，本项目通过 wheel 解包安装并修补一处 py3.12 f-string 语法，在 3.10 可用；numba 为其 JIT 依赖。
- **klinecharts**：已本地化到 `app/web/vendor/`，不走 CDN。
- **数据源多级回退**：日线 东财→新浪；指数 新浪源；搜索 代码名称表（24h 缓存）。东财接口对高频请求有 IP 限流（RemoteDisconnected），本机系统代理也可能拦截，`run.py` 已默认设置 `NO_PROXY=*`。
