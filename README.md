# HK Stock Dashboard

📊 ETNet Top 10 熱門港股行情 · AI 分析 · 每日自動更新

[Live Demo →](https://88flytomoney-ctrl.github.io/hkstock/)

## Features

- 📈 **ETNet Top 10** — 每日自動抓取成交額最高港股
- 🤖 **AI 分析** — 技術信號（買入/賣出/持有）+ 支撐阻力位
- 📊 **互動圖表** — 5日迷你走势图 + 詳細行情表
- 🔄 **每日自動更新** — GitHub Actions 07:00 (Mon-Sat) 自動抓取

## Quick Start

```bash
# Frontend
npm install
npm run dev

# Data fetch (needs TUSHARE_TOKEN)
export TUSHARE_TOKEN=your_token
python scripts/fetch_stock_data.py
```

## GitHub Pages Deploy

1. Create repo `hkstock` on GitHub
2. Add secret: `TUSHARE_TOKEN` (from tushare.pro)
3. Push — GitHub Actions auto-builds and deploys

## Tech Stack

- **Frontend**: React 18 + Vite + Tailwind CSS + Recharts
- **Backend**: Python (ETNet scrape + Tushare API)
- **Deploy**: GitHub Actions → GitHub Pages
- **Data**: JSON file, regenerated daily by CI
