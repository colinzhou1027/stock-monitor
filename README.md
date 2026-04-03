# 🎮 多市场股票监控机器人

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 自动推送韩股、美股、港股日报和月报到企业微信群，自动获取相关新闻

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 📊 **三市场日报** | 每个工作日自动发送韩股、港股、美股日报 |
| 📈 **月度趋势报告** | 每月初自动生成上月股价趋势图 + 新闻汇总 |
| 📰 **新闻自动获取** | 从 Google News 获取各股票相关新闻（免费） |
| 🔔 **Shift Up 预警** | 涨跌超过 10% 时 @所有人 |
| 🌍 **休市日处理** | 自动识别各市场休市日，显示最近交易日数据 |

## 📊 监控的股票

### 🇰🇷 韩股（6 只游戏股）
| 公司 | 代表游戏 | 预警 |
|------|----------|------|
| **Shift Up** | 胜利女神 NIKKE | ✅ 涨跌超 10% 预警 |
| Krafton | PUBG | - |
| NCsoft | 天堂系列 | - |
| Netmarble | 石器时代 | - |
| Nexon Games | 冒险岛、DNF | - |
| Pearl Abyss | 黑色沙漠 | - |

### 🇺🇸 美股（11 只）
- **科技股**：苹果、谷歌、亚马逊、英伟达、Meta、特斯拉、微软
- **游戏股**：EA、Take-Two、Roblox、Unity

### 🇭🇰 港股（12 只）
- **科技股**：腾讯、阿里巴巴、网易、小米、百度、MiniMax、智谱AI
- **游戏股**：中手游、心动公司、哔哩哔哩、创梦天地、IGG

## 📋 报告格式

### 日报结构

```
📊 韩股游戏股票日报
> 📅 数据日期：2026-03-11 10:30
> ⚠️ 预警规则：Shift Up 涨跌超过10%时预警

### 📈 大盘指数
**KOSPI**
> 昨日收盘：2,650.00
> 今日收盘：2,680.00
> 🟢 变化：+1.13%

---

### 📊 个股变化
**Shift Up** 🟢
> 昨日：₩32,000
> 今日：₩33,500
> 涨跌：+4.69%

---

## 📰 新闻内容
| 公司 | 新闻内容 |
|:----:|:-----|
| 🌐 大盘 | 板块整体表现良好，3涨2跌 |
| 🎮 Shift Up | Stellar Blade 新章节发布... |
| 🎮 Krafton | PUBG新赛季活跃用户增长... |
```

### 月报结构

```
## 📈 韩股2026年2月游戏股月报

### 📊 大盘指数（月度）
> 📈 **KOSPI**: +2.35%
> 📊 近期变化：2/26: +0.5% | 2/27: -0.3% | 2/28: +0.8%
> 股票平均涨跌幅：**+3.12%**
> 股票数量：**6** 只

### 📊 个股表现
> 🟢 Shift Up: +8.23%
> 🟢 Pearl Abyss: +5.15%
> 🔴 Krafton: -2.15%

### 📰 月度新闻汇总
**行业大事**：...
**公司动态**：...

### 📝 月度分析
**月度总结**：...
**要点回顾**：...

📈 以下为月度股价走势图：
[股价趋势图]
```

## 📅 发送时间

所有市场统一在 **北京时间 10:30** 发送日报：

| 市场 | 交易时间 | 10:30 发送的数据 |
|------|----------|------------------|
| 🇰🇷 韩股 | 09:00-15:30 (首尔) | 前一交易日 |
| 🇭🇰 港股 | 09:30-16:00 (香港) | 前一交易日 |
| 🇺🇸 美股 | 09:30-16:00 (美东) | 当天凌晨刚收盘 |

## 🚀 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# 企业微信 Webhook（必填）
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

# 预警阈值（默认 10%）
CHANGE_THRESHOLD=10.0
```

> 💡 **摘要服务说明**: 系统使用基于模板的摘要服务生成日报和月报内容，无需配置任何 AI API，完全免费使用。

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 测试运行

```bash
# 测试所有市场日报
python main.py all

# 测试单个市场
python main.py kr    # 韩股
python main.py us    # 美股
python main.py hk    # 港股
```

### 4. 安装定时任务（macOS）

```bash
cd scripts
./install_macos.sh
```

## 🧪 测试命令

### 日报测试

```bash
python test_daily.py           # 测试日报发送
python test_daily.py kr        # 仅测试韩股
```

### 月报测试

```bash
python test_monthly.py                    # 所有市场月报
python test_monthly.py kr --preview       # 预览韩股月报，不发送
python test_monthly.py us --force         # 强制生成美股上月月报
python test_monthly.py hk --year 2026 --month 2  # 指定月份
python test_monthly.py --save             # 保存图片到本地
```

## 📁 项目结构

```
stock-monitor/
├── main.py                      # 主程序入口
├── config.py                    # 配置管理（股票列表、市场信息）
├── requirements.txt             # Python 依赖
├── .env                         # 环境变量配置
│
├── services/                    # 核心服务
│   ├── stock_service.py         # 股票数据获取
│   ├── ai_service.py            # AI 分析服务
│   ├── notify_service.py        # 企业微信通知
│   └── monthly_chart_service.py # 月度趋势图服务
│
├── models/                      # 数据模型
│   └── stock.py                 # 股票信息、变化、指数模型
│
├── utils/                       # 工具类
│   └── logger.py                # 日志工具
│
├── scripts/                     # 部署脚本
│   ├── install_macos.sh         # macOS 安装脚本
│   └── run_stock_check.sh       # 执行脚本
│
├── data/                        # 数据存储
│   └── sent_monthly_charts.json # 已发送月报记录
│
├── logs/                        # 运行日志
└── output/                      # 图片输出（测试用）
```

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                      main.py                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ run_kr_check │  │run_us_hk_check│ │run_all_markets│  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│           │                │                │           │
│           └────────────────┼────────────────┘           │
│                            │                            │
│              generate_and_send_monthly_report()         │
│                            │                            │
└────────────────────────────┼────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  StockService   │ │   AIService     │ │ NotifyService   │
│                 │ │                 │ │                 │
│ • get_stock_    │ │ • analyze_      │ │ • send_daily_   │
│   changes()     │ │   stock_changes │ │   report()      │
│ • get_market_   │ │ • analyze_      │ │ • send_monthly_ │
│   index()       │ │   monthly_news  │ │   report()      │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                             ▼
                ┌─────────────────────┐
                │MonthlyChartService  │
                │                     │
                │ • generate_market_  │
                │   monthly_report()  │
                │ • create_chart()    │
                └─────────────────────┘
```

## ⚙️ 配置说明

### 修改预警阈值

编辑 `.env` 文件中的 `CHANGE_THRESHOLD`（默认 10%）

> 注意：预警仅针对 Shift Up，其他股票不触发预警

### 添加/删除股票

编辑 `config.py` 中对应市场的股票列表：

```python
# 韩股
KR_STOCK_LIST = [
    ("462870", "Shift Up", "KOSPI"),
    # ...
]

# 美股科技股
US_TECH_LIST = [
    ("AAPL", "苹果", "tech"),
    # ...
]
```

### 修改定时任务时间

编辑 `scripts/com.colinzhou.stockmonitor.plist` 中的时间配置，然后重新加载：

```bash
launchctl unload ~/Library/LaunchAgents/com.colinzhou.stockmonitor.plist
launchctl load ~/Library/LaunchAgents/com.colinzhou.stockmonitor.plist
```

## 📊 数据来源

### 数据源优先级（日报/月报一致）

| 市场 | 股票数据 | 指数数据 |
|------|----------|----------|
| 🇰🇷 韩股 | pykrx（KRX 韩国交易所） | pykrx → akshare |
| 🇺🇸 美股 | yfinance → akshare → 腾讯股票 | yfinance → akshare |
| 🇭🇰 港股 | yfinance → akshare → 腾讯股票 | yfinance → akshare |

> 💡 **备用机制**：当主数据源失败时，自动切换到备用数据源，确保数据获取的稳定性

### 取数统计

| 市场 | 股票数量 | 指数数量 | 每日取数次数 |
|------|----------|----------|-------------|
| 🇰🇷 韩股 | 6 只 | 1 个 | 7 次 |
| 🇺🇸 美股 | 11 只 | 1 个 | 12 次 |
| 🇭🇰 港股 | 12 只 | 1 个 | 13 次 |
| **总计** | **29 只** | **3 个** | **32 次** |

## 📝 新闻与摘要服务

系统使用 **Google News RSS** 获取真实新闻，完全免费，无需配置任何 API：

| 功能 | 数据来源 | 说明 |
|------|----------|------|
| 📰 日报 - 昨日新闻 | Google News RSS | 自动获取各股票相关新闻 |
| 📰 月报 - 新闻汇总 | Google News RSS | 行业大事、公司动态、市场热点 |
| 📊 月报 - 月度分析 | 股票数据 | 月度总结、要点回顾、后市展望 |

**新闻服务特点**：
- ✅ **完全免费** - 使用 Google News RSS，无需 API 密钥
- ✅ **真实新闻** - 从 Google News 获取最新相关报道
- ✅ **自动关联** - 按股票名称搜索相关新闻
- ✅ **多语言支持** - 支持英文、韩文、中文新闻源
- ✅ **智能缓存** - 缓存新闻数据减少重复请求

## 🔧 常用命令

```bash
# 查看定时任务状态
launchctl list | grep stockmonitor

# 手动触发执行
launchctl start com.colinzhou.stockmonitor

# 查看日志
tail -f logs/stock_check.log

# 停止定时任务
launchctl unload ~/Library/LaunchAgents/com.colinzhou.stockmonitor.plist
```

## ⚠️ 注意事项

- 电脑需保持开机状态（休眠后唤醒会自动补执行）
- 预警规则仅对 Shift Up 生效
- 月报已发送记录保存在 `data/sent_monthly_charts.json`
- 日志位于 `logs/` 目录

## 📝 更新日志

### v2.1.0 (2026-03-16)
- 📊 完善数据源优先级说明（日报/月报一致）
- 📈 添加取数统计（29只股票 + 3个指数 = 32次/日）
- 🔧 美股/港股月报添加腾讯股票兜底数据源

### v2.0.1 (2026-03-13)
- 🔥 新增强化搜索机制（Shift Up 和涨跌超10%股票自动重试）
- 🔍 添加无新闻公司过滤功能
- 💪 加强 Shift Up 新闻搜索关键词

### v2.0.0 (2026-03-11)
- ✨ 统一三市场月报格式（韩股/美股/港股）
- ✨ 月报新增 AI 新闻汇总和月度分析
- ✨ 韩股月报新增 KOSPI 指数数据
- 🔧 重构代码，提取公共月报生成逻辑
- 📝 更新 README 文档

### v1.0.0
- 🎉 支持韩股、美股、港股三市场
- 📊 日报 + 月报功能
- 🤖 AI 智能分析

---

**祝使用愉快！🎮📈**
