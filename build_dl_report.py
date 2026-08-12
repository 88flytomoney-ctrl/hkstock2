#!/usr/bin/env python3
"""
build_dl_report.py — Fetch HK Stock 2 data, generate a static report.html
with market indices, 20 tracked stocks, today's highlights, and 10-day standouts.

Data source: https://88flytomoney-ctrl.github.io/hkstock2/data/predictions.json
Output:      public/report.html  (Vite copies public/ → dist/ on build)
"""
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from collections import defaultdict

DATA_URL = "https://88flytomoney-ctrl.github.io/hkstock2/data/predictions.json"
OUTPUT_FILE = "public/report.html"
HK_TZ = timezone(timedelta(hours=8))

REC_LABEL = {"買入": "buy", "賣出": "sell", "持有": "hold"}


def fetch_data():
    """Fetch predictions JSON from the live GitHub Pages deployment."""
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def compute_stock_stats(stocks):
    """Return a list of dicts with today % and 10-day % for each stock."""
    rows = []
    for code, stock in stocks.items():
        name = stock.get("name", "?")
        rec = stock.get("recommendation", "—")
        combined = stock.get("combined_data", [])
        actual = [d for d in combined if not d.get("is_predicted")]
        if len(actual) < 2:
            continue
        last = actual[-1]
        prev = actual[-2]
        first = actual[0]
        today_chg = ((last["close"] - prev["close"]) / prev["close"]) * 100
        ten_chg = ((last["close"] - first["close"]) / first["close"]) * 100
        rows.append({
            "code": code,
            "name": name,
            "symbol": stock.get("symbol", ""),
            "close": last["close"],
            "today_chg": today_chg,
            "ten_chg": ten_chg,
            "rec": rec,
            "last_date": last.get("dateShort", ""),
        })
    rows.sort(key=lambda r: ["buy", "sell", "hold"].index(r["rec"]) if r["rec"] in ["buy", "sell", "hold"] else 9)
    return rows


def fmt_pct(val):
    arrow = "▲" if val > 0 else "▼" if val < 0 else "→"
    return f"{arrow} {val:+.2f}%"


def build_html(data, rows):
    indices = data.get("indices", {})
    now_str = datetime.now(HK_TZ).strftime("%Y/%m/%d %H:%M HKT")

    # Indices rows
    idx_rows = ""
    for key in ["hsi", "hsce"]:
        idx = indices.get(key, {})
        arrow = "▲" if idx.get("isPositive") else "▼"
        color = "#22c55e" if idx.get("isPositive") else "#ef4444"
        name = idx.get("name", key.upper())
        val = f"{idx.get('value', 0):,.2f}"
        chg = f"{arrow} {idx.get('change', 0):+,.2f} ({idx.get('pct', 0):+.2f}%)"
        idx_rows += f'<tr><td class="px-4 py-2 font-semibold">{name}</td><td class="px-4 py-2 text-right">{val}</td><td class="px-4 py-2 text-right" style="color:{color}">{chg}</td></tr>\n'

    # Stock rows
    s_rows = ""
    gainers = []
    losers = []
    for r in rows:
        t_arrow = "▲" if r["today_chg"] > 0 else "▼" if r["today_chg"] < 0 else "→"
        t_color = "#22c55e" if r["today_chg"] > 0 else "#ef4444" if r["today_chg"] < 0 else "#888"
        d_arrow = "▲" if r["ten_chg"] > 0 else "▼" if r["ten_chg"] < 0 else "→"
        d_color = "#22c55e" if r["ten_chg"] > 0 else "#ef4444" if r["ten_chg"] < 0 else "#888"
        rec_color = {"買入": "#22c55e", "賣出": "#ef4444", "持有": "#f59e0b"}.get(r["rec"], "#888")
        s_rows += (
            f'<tr>'
            f'<td class="px-3 py-2 font-mono">{r["code"]}</td>'
            f'<td class="px-3 py-2">{r["name"]}</td>'
            f'<td class="px-3 py-2 text-right">{r["close"]:,.2f}</td>'
            f'<td class="px-3 py-2 text-right" style="color:{t_color}">{t_arrow} {r["today_chg"]:+.2f}%</td>'
            f'<td class="px-3 py-2 text-right" style="color:{d_color}">{d_arrow} {r["ten_chg"]:+.2f}%</td>'
            f'<td class="px-3 py-2 text-center font-semibold" style="color:{rec_color}">{r["rec"]}</td>'
            f'</tr>\n'
        )
        if r["today_chg"] > 0:
            gainers.append(r)
        else:
            losers.append(r)

    # Today highlights
    gainers.sort(key=lambda x: x["today_chg"], reverse=True)
    losers.sort(key=lambda x: x["today_chg"])
    top_gainers = ", ".join(f'{r["name"]} ({r["code"]}) {r["today_chg"]:+.2f}%' for r in gainers[:3])
    top_losers = ", ".join(f'{r["name"]} ({r["code"]}) {r["today_chg"]:+.2f}%' for r in losers[:3])
    adv_dec = f'{len(gainers)} 升 {len(losers)} 跌'

    buy_count = sum(1 for r in rows if r["rec"] == "買入")
    sell_count = sum(1 for r in rows if r["rec"] == "賣出")
    hold_count = sum(1 for r in rows if r["rec"] == "持有")

    # 10-day highlights
    sorted_10d = sorted(rows, key=lambda x: x["ten_chg"], reverse=True)
    biggest_gainer = sorted_10d[0]
    runner_up = sorted_10d[1]
    biggest_loser = sorted_10d[-1]
    buy_list = ", ".join(f'{r["name"]} ({r["code"]})' for r in rows if r["rec"] == "買入")
    sell_list = ", ".join(f'{r["name"]} ({r["code"]})' for r in rows if r["rec"] == "賣出")

    html = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HK Stock 2 AI — Summary Report</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>body{{font-family:system-ui,-apple-system,sans-serif;}}table{{border-collapse:collapse;}}</style>
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen">
<div class="max-w-5xl mx-auto px-4 py-8">

  <!-- Header -->
  <h1 class="text-3xl font-bold mb-1">HK Stock 2 🤖 AI — Summary Report</h1>
  <p class="text-gray-400 mb-6">最後更新: {now_str}</p>

  <!-- Market Indices -->
  <h2 class="text-xl font-semibold mb-3">🌐 香港主要指數</h2>
  <table class="w-full mb-6 text-sm border border-gray-700 rounded-lg overflow-hidden">
    <thead class="bg-gray-800">
      <tr><th class="px-4 py-2 text-left">指數</th><th class="px-4 py-2 text-right">點數</th><th class="px-4 py-2 text-right">變動</th></tr>
    </thead>
    <tbody>
      {idx_rows}
    </tbody>
  </table>

  <!-- 20 Tracked Stocks -->
  <h2 class="text-xl font-semibold mb-3">📈 個股行情（20 檔）</h2>
  <table class="w-full mb-6 text-sm border border-gray-700 rounded-lg overflow-hidden">
    <thead class="bg-gray-800">
      <tr>
        <th class="px-3 py-2 text-left">Code</th>
        <th class="px-3 py-2 text-left">名稱</th>
        <th class="px-3 py-2 text-right">Price (HKD)</th>
        <th class="px-3 py-2 text-right">Today Chg %</th>
        <th class="px-3 py-2 text-right">10-Day Chg %</th>
        <th class="px-3 py-2 text-center">AI 建議</th>
      </tr>
    </thead>
    <tbody class="divide-y divide-gray-800">
      {s_rows}
    </tbody>
  </table>

  <!-- Today Highlights -->
  <h2 class="text-xl font-semibold mb-3">🔑 Key Highlights</h2>
  <div class="bg-gray-900 rounded-lg p-5 mb-4 border border-gray-700">
    <h3 class="text-lg font-semibold mb-3">📅 Today</h3>
    <ul class="space-y-1 text-sm">
      <li><b>大市:</b> 恒指 {indices.get('hsi',{}).get('change',0):+,.0f} ({indices.get('hsi',{}).get('pct',0):+.2f}%), 國企 {indices.get('hsce',{}).get('change',0):+,.0f} ({indices.get('hsce',{}).get('pct',0):+.2f}%)</li>
      <li><b class="text-green-400">今日最強:</b> {top_gainers}</li>
      <li><b class="text-red-400">今日最弱:</b> {top_losers}</li>
      <li><b>升跌比:</b> {adv_dec}</li>
      <li><b>AI 分佈:</b> 買入 {buy_count} 檔 · 賣出 {sell_count} 檔 · 持有 {hold_count} 檔</li>
    </ul>
  </div>

  <!-- 10-Day Highlights -->
  <div class="bg-gray-900 rounded-lg p-5 mb-4 border border-gray-700">
    <h3 class="text-lg font-semibold mb-3">📊 10-Day Standouts</h3>
    <ul class="space-y-1 text-sm">
      <li><b class="text-green-400">Biggest gainer:</b> {biggest_gainer['name']} ({biggest_gainer['code']}) ▲ {biggest_gainer['ten_chg']:+.2f}% → {biggest_gainer['close']:,.2f} HKD</li>
      <li><b class="text-green-400">Runner-up:</b> {runner_up['name']} ({runner_up['code']}) ▲ {runner_up['ten_chg']:+.2f}% → {runner_up['close']:,.2f} HKD</li>
      <li><b class="text-red-400">Biggest loser:</b> {biggest_loser['name']} ({biggest_loser['code']}) ▼ {biggest_loser['ten_chg']:+.2f}% → {biggest_loser['close']:,.2f} HKD</li>
    </ul>
  </div>

  <!-- AI Signals -->
  <div class="bg-gray-900 rounded-lg p-5 mb-4 border border-gray-700">
    <h3 class="text-lg font-semibold mb-3">🤖 AI Signals</h3>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
      <div><b class="text-green-400">Buy ({buy_count}):</b> {buy_list}</div>
      <div><b class="text-red-400">Sell ({sell_count}):</b> {sell_list}</div>
    </div>
  </div>

  <!-- Footer -->
  <p class="text-xs text-gray-500 mt-8 text-center">
    數據來源：ETNet + Yahoo Finance · AI 預測：OpenRouter · 僅供參考，不構成投資建議
  </p>

</div>
</body>
</html>"""
    return html


def main():
    print(f"🚀 Building report at {datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M')} HKT")
    data = fetch_data()
    rows = compute_stock_stats(data["stocks"])
    html = build_html(data, rows)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Written {OUTPUT_FILE} ({len(html)} bytes, {len(rows)} stocks)")


if __name__ == "__main__":
    main()
