# 股票监控网页

这是股票监控系统的静态网页展示模块，通过 GitHub Pages 免费托管。

## 功能特点

- 📊 展示韩股、美股、港股三个市场的日报和月报数据
- 🔄 定时任务自动更新数据
- 📱 响应式设计，支持移动端访问
- 🌙 现代深色主题，专业金融风格

## 部署方式

### 1. 启用 GitHub Pages

1. 进入仓库 Settings → Pages
2. Source 选择 "Deploy from a branch"
3. Branch 选择 `main`，目录选择 `/docs`
4. 点击 Save

### 2. 配置环境变量

在 GitHub Actions secrets 或本地 `.env` 文件中配置：

```bash
# 网页地址（可选，不配置则自动推断）
WEBPAGE_URL=https://your-username.github.io/stock-monitor/

# 是否自动推送 Git（默认 true）
GIT_AUTO_PUSH=true
```

### 3. 自动更新

定时任务执行后，会自动：
1. 生成 JSON 数据文件到 `docs/data/` 目录
2. 提交更改到 Git
3. 推送到 GitHub，触发 Pages 自动部署

## 目录结构

```
docs/
├── index.html          # 首页（三市场概览）
├── kr.html             # 韩股详情页
├── us.html             # 美股详情页
├── hk.html             # 港股详情页
├── css/
│   └── style.css       # 统一样式
├── js/
│   └── main.js         # 数据加载和渲染逻辑
└── data/
    ├── meta.json       # 元数据（最后更新时间）
    ├── kr_daily.json   # 韩股日报数据
    ├── kr_monthly.json # 韩股月报数据
    ├── us_daily.json   # 美股日报数据
    ├── us_monthly.json # 美股月报数据
    ├── hk_daily.json   # 港股日报数据
    └── hk_monthly.json # 港股月报数据
```

## 数据格式

### 日报数据 (xxx_daily.json)

```json
{
  "latest": {
    "date": "2026-04-02",
    "update_time": "2026-04-02 10:30:00",
    "stocks": [
      {
        "symbol": "462870",
        "name": "Shift Up",
        "prev_close": 85000,
        "prev_prev_close": 82000,
        "change_percent": 3.66,
        "prev_date": "2026-04-01",
        "prev_prev_date": "2026-03-31"
      }
    ],
    "market_index": { ... },
    "ai_analysis": "...",
    "holidays": []
  },
  "history": [ ... ]  // 最近 7 天历史
}
```

### 月报数据 (xxx_monthly.json)

```json
{
  "latest": {
    "year": 2026,
    "month": 3,
    "update_time": "2026-04-01 10:00:00",
    "avg_change": 5.23,
    "stock_data": { ... },
    "index_data": { ... },
    "ai_analysis": "...",
    "ai_news_summary": "..."
  },
  "history": [ ... ]  // 最近 6 个月历史
}
```

## 群消息策略

改进后的群消息推送策略：

- **韩股**：仅当 Shift Up 涨跌幅超过阈值（默认 10%）时推送预警消息
- **美股/港股**：保持原有推送逻辑

所有详细数据都可以在网页上查看，减少群消息干扰。

## 本地预览

```bash
# 进入 docs 目录
cd docs

# 使用 Python 启动本地服务器
python -m http.server 8080

# 访问 http://localhost:8080
```

## 技术栈

- 纯静态网页：HTML + CSS + JavaScript
- 无需构建工具，无需框架依赖
- 数据通过 JSON 文件加载，支持离线缓存
