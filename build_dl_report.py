#!/usr/bin/env python3
"""
build_dl_report.py — Fetch HK Stock 2 data, generate a static report.html
with market indices, 20 tracked stocks, today's highlights, 10-day standouts,
and AI 5-day predictions. Supports historical archives with date selector.

Data source: local public/data/predictions.json (pipeline just wrote it)
             fallback: https://88flytomoney-ctrl.github.io/hkstock2/data/predictions.json
Output:      public/report.html        (latest report)
             public/archive/*.html      (historical snapshots)
             public/archive/index.json  (archive manifest)
"""
import json
import os
import sys
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_URL = "https://88flytomoney-ctrl.github.io/hkstock2/data/predictions.json"
LOCAL_DATA = "public/data/predictions.json"
PUBLIC_DIR = Path("public")
OUTPUT_FILE = PUBLIC_DIR / "report.html"
ARCHIVE_DIR = PUBLIC_DIR / "archive"
ARCHIVE_INDEX = ARCHIVE_DIR / "index.json"
HK_TZ = timezone(timedelta(hours=8))

REC_LABEL = {"買入": "buy", "賣出": "sell", "持有": "hold"}


def format_ts_label(slug):
    """Convert an archive slug to a readable label with time.

    "2026-08-13_1530"  -> "08/13 15:30"
    "2026-08-13"       -> "08/13"          (legacy daily snapshot)
    """
    if not slug:
        return ""
    if "_" in slug:
        date_part, time_part = slug.split("_", 1)
        mmdd = date_part[5:].replace("-", "/")
        hhmm = f"{time_part[:2]}:{time_part[2:]}" if len(time_part) >= 4 else time_part
        return f"{mmdd} {hhmm}"
    return slug[5:].replace("-", "/")


def fetch_data():
    """Read predictions JSON from local file (pipeline just wrote it),
    or fall back to the live URL if the local file doesn't exist."""
    if os.path.exists(LOCAL_DATA):
        with open(LOCAL_DATA, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def compute_stock_stats(stocks):
    """Return a list of dicts with today %, 10-day %, and 5-day AI predictions."""
    rows = []
    for code, stock in stocks.items():
        name = stock.get("name", "?")
        rec = stock.get("recommendation", "—")
        combined = stock.get("combined_data", [])
        actual = [d for d in combined if not d.get("is_predicted")]
        predicted = [d for d in combined if d.get("is_predicted")]
        if len(actual) < 2:
            continue
        last = actual[-1]
        prev = actual[-2]
        first = actual[0]
        today_chg = ((last["close"] - prev["close"]) / prev["close"]) * 100
        ten_chg = ((last["close"] - first["close"]) / first["close"]) * 100

        # 5-day predicted closes
        pred_closes = [p["close"] for p in predicted[:5]]
        pred_dates = [p.get("date", "") for p in predicted[:5]]
        pred_5d_chg = ((pred_closes[-1] - last["close"]) / last["close"] * 100) if pred_closes else None
        pred_min = min(pred_closes) if pred_closes else None
        pred_max = max(pred_closes) if pred_closes else None
        pred_min_chg = ((pred_min - last["close"]) / last["close"] * 100) if pred_closes else None
        pred_max_chg = ((pred_max - last["close"]) / last["close"] * 100) if pred_closes else None

        rows.append({
            "code": code,
            "name": name,
            "symbol": stock.get("symbol", ""),
            "close": last["close"],
            "today_chg": today_chg,
            "ten_chg": ten_chg,
            "rec": rec,
            "last_date": last.get("dateShort", ""),
            "pred_closes": pred_closes,
            "pred_dates": pred_dates,
            "pred_5d_chg": pred_5d_chg,
            "pred_min": pred_min,
            "pred_max": pred_max,
            "pred_min_chg": pred_min_chg,
            "pred_max_chg": pred_max_chg,
        })
    rows.sort(key=lambda r: ["buy", "sell", "hold"].index(r["rec"]) if r["rec"] in ["buy", "sell", "hold"] else 9)
    return rows


def build_html(data, rows, archive_entries=None, current_ts=None):
    """Build the full HTML report.

    archive_entries: list of archive slug strings (newest first), e.g.
                     ["2026-08-13_1530", "2026-08-13_0930", "2026-08-12_1600"]
                     Legacy date-only slugs ("2026-08-13") are supported.
    current_ts:      slug of the page being rendered (archive page), or None
                     for the latest report.html.
    """
    indices = data.get("indices", {})
    is_archive = current_ts is not None
    now_str = format_ts_label(current_ts) if current_ts else datetime.now(HK_TZ).strftime("%Y/%m/%d %H:%M HKT")

    # Build archive dropdown
    archive_options = '<option value="">最新數據</option>\n'
    if archive_entries:
        for slug in archive_entries:
            selected = ' selected' if slug == current_ts else ''
            label = format_ts_label(slug)
            archive_options += f'<option value="{slug}"{selected}>{label}</option>\n'

    dropdown_html = ""
    if archive_entries is not None:
        if is_archive:
            onchange = ("document.location.href="
                         "this.value? '../archive/'+this.value+'.html'"
                         ": '../report.html'")
        else:
            onchange = ("document.location.href="
                         "this.value? 'archive/'+this.value+'.html'"
                         ": 'report.html'")
        dropdown_html = f"""
  <div class="mb-4">
    <label class="text-sm text-gray-400 mr-2">📜 歷史記錄:</label>
    <select onchange="{onchange}" class="bg-gray-800 text-gray-100 border border-gray-600 rounded px-3 py-1.5 text-sm">
      {archive_options}
    </select>
  </div>"""

    # Indices rows
    idx_rows = ""
    for key in ["hsi", "hscei"]:
        idx = indices.get(key, {})
        if not idx:
            # Try alternate keys
            for alt in [key, key.upper(), "hsce"]:
                if alt in indices:
                    idx = indices[alt]
                    break
        if not idx:
            continue
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

    # ── AI 5-Day Prediction Section ────────────────────────────────────────────
    pred_day_headers = ""
    pred_dates_raw = rows[0]["pred_dates"] if rows and rows[0]["pred_dates"] else []
    for d in pred_dates_raw:
        if d:
            label = d[5:].replace("-", "/")
            pred_day_headers += f'<th class="px-2 py-2 text-right">{label}</th>\n'

    pred_table_rows = ""
    for r in rows:
        if not r["pred_closes"]:
            continue
        pred_cells = ""
        for pc in r["pred_closes"]:
            pred_cells += f'<td class="px-2 py-2 text-right text-gray-300">{pc:,.2f}</td>\n'

        chg = r["pred_5d_chg"]
        if chg is not None:
            arrow = "▲" if chg > 0 else "▼" if chg < 0 else "→"
            color = "#22c55e" if chg > 0 else "#ef4444" if chg < 0 else "#888"
            chg_str = f'<span style="color:{color}">{arrow} {chg:+.2f}%</span>'
        else:
            chg_str = "—"

        hi = r["pred_max_chg"]
        lo = r["pred_min_chg"]
        hi_color = "#22c55e" if hi and hi > 0 else "#ef4444"
        lo_color = "#ef4444" if lo and lo < 0 else "#22c55e"
        range_str = f'<span style="color:{hi_color}">+{hi:+.2f}%</span> / <span style="color:{lo_color}">{lo:+.2f}%</span>' if (hi is not None and lo is not None) else "—"

        rec_color = {"買入": "#22c55e", "賣出": "#ef4444", "持有": "#f59e0b"}.get(r["rec"], "#888")

        pred_table_rows += (
            f'<tr>'
            f'<td class="px-2 py-2 font-mono"><span style="color:{rec_color}">●</span> {r["code"]}</td>'
            f'<td class="px-2 py-2 text-right">{r["close"]:,.2f}</td>'
            f'{pred_cells}'
            f'<td class="px-2 py-2 text-right">{chg_str}</td>'
            f'<td class="px-2 py-2 text-right text-xs">{range_str}</td>'
            f'</tr>\n'
        )

    # AI prediction highlights
    pred_capable = [r for r in rows if r["pred_5d_chg"] is not None]
    if pred_capable:
        sorted_pred = sorted(pred_capable, key=lambda x: x["pred_5d_chg"], reverse=True)
        top_pred_gainer = f'{sorted_pred[0]["name"]} ({sorted_pred[0]["code"]}) ▲ {sorted_pred[0]["pred_5d_chg"]:+.2f}% → {sorted_pred[0]["pred_closes"][-1]:,.2f} HKD'
        top_pred_loser_chg = sorted_pred[-1]["pred_5d_chg"]
        top_pred_loser = f'{sorted_pred[-1]["name"]} ({sorted_pred[-1]["code"]}) {("▼" if top_pred_loser_chg < 0 else "▲")} {top_pred_loser_chg:+.2f}% → {sorted_pred[-1]["pred_closes"][-1]:,.2f} HKD'

        for r in pred_capable:
            r["_volatility"] = r["pred_max_chg"] - r["pred_min_chg"] if r["pred_max_chg"] is not None else 0
        sorted_vol = sorted(pred_capable, key=lambda x: x["_volatility"], reverse=True)
        most_volatile = f'{sorted_vol[0]["name"]} ({sorted_vol[0]["code"]}) — 區間 {sorted_vol[0]["pred_min_chg"]:+.2f}% ~ {sorted_vol[0]["pred_max_chg"]:+.2f}%'
        sorted_stable = sorted(pred_capable, key=lambda x: x["_volatility"])
        most_stable = f'{sorted_stable[0]["name"]} ({sorted_stable[0]["code"]}) — 區間 {sorted_stable[0]["pred_min_chg"]:+.2f}% ~ {sorted_stable[0]["pred_max_chg"]:+.2f}%'
    else:
        top_pred_gainer = top_pred_loser = most_volatile = most_stable = "無預測數據"

    hsi_chg = indices.get('hsi',{}).get('change',0)
    hsi_pct = indices.get('hsi',{}).get('pct',0)
    hsce_chg = indices.get('hscei',{}).get('change',0) or indices.get('hsce',{}).get('change',0)
    hsce_pct = indices.get('hscei',{}).get('pct',0) or indices.get('hsce',{}).get('pct',0)

    title = f"HK Stock 2 AI — {format_ts_label(current_ts)}" if is_archive else "HK Stock 2 AI — Summary Report"

    html = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>body{{font-family:system-ui,-apple-system,sans-serif;}}table{{border-collapse:collapse;}}</style>
</head>
<body class="bg-gray-950 text-gray-100 min-h-screen">
<div class="max-w-5xl mx-auto px-4 py-8">

  <!-- Header -->
  <h1 class="text-3xl font-bold mb-1">HK Stock 2 🤖 AI — Summary Report</h1>
  <p class="text-gray-400 mb-2">最後更新: {now_str}</p>
  {dropdown_html}

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
  <h2 class="text-xl font-semibold mb-3">📈 個股行情（{len(rows)} 檔）</h2>
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
      <li><b>大市:</b> 恒指 {hsi_chg:+,.0f} ({hsi_pct:+.2f}%), 國企 {hsce_chg:+,.0f} ({hsce_pct:+.2f}%)</li>
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

  <!-- AI 5-Day Predictions -->
  <h2 class="text-xl font-semibold mb-3">🔮 AI 預測（未來5日）</h2>
  <div class="bg-gray-900 rounded-lg p-5 mb-4 border border-gray-700 overflow-x-auto">
    <p class="text-sm text-gray-400 mb-3">基於 OpenRouter AI 模型對未來5個交易日的收盤價預測，與今日收盤價比較計算預期變動幅度。</p>
    <table class="w-full text-sm border border-gray-700 rounded-lg overflow-hidden" style="border-collapse:collapse">
      <thead class="bg-gray-800">
        <tr>
          <th class="px-2 py-2 text-left">Ticker</th>
          <th class="px-2 py-2 text-right">現價</th>
          {pred_day_headers}
          <th class="px-2 py-2 text-right">5日預期</th>
          <th class="px-2 py-2 text-right">區間高/低</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-800">
        {pred_table_rows}
      </tbody>
    </table>
  </div>

  <!-- AI Prediction Highlights -->
  <div class="bg-gray-900 rounded-lg p-5 mb-4 border border-gray-700">
    <h3 class="text-lg font-semibold mb-3">📊 AI 預測精選</h3>
    <ul class="space-y-1 text-sm">
      <li><b class="text-green-400">預期升幅最大:</b> {top_pred_gainer}</li>
      <li><b class="text-red-400">預期跌幅最大:</b> {top_pred_loser}</li>
      <li><b>預期波動最大:</b> {most_volatile}</li>
      <li><b>預期最穩定:</b> {most_stable}</li>
    </ul>
  </div>

  <!-- Footer -->
  <p class="text-xs text-gray-500 mt-8 text-center">
    數據來源：ETNet + Yahoo Finance · AI 預測：OpenRouter · 僅供參考，不構成投資建議
  </p>

</div>
</body>
</html>"""
    return html


def load_archive_index():
    if ARCHIVE_INDEX.exists():
        with open(ARCHIVE_INDEX) as f:
            return json.load(f)
    return []


def save_archive_index(dates):
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVE_INDEX, "w", encoding="utf-8") as f:
        json.dump(dates, f, ensure_ascii=False, indent=2)


def archive_today(data, rows, archive_entries):
    """Save a timestamped archive snapshot. Multiple runs per day are preserved.

    Slug format: YYYY-MM-DD_HHMM  (e.g. 2026-08-13_1530)
    Filename:    <slug>.html       (e.g. 2026-08-13_1530.html)
    """
    now = datetime.now(HK_TZ)
    today_slug = now.strftime("%Y-%m-%d_%H%M")
    archive_html = build_html(data, rows, archive_entries=archive_entries, current_ts=today_slug)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_file = ARCHIVE_DIR / f"{today_slug}.html"
    with open(archive_file, "w", encoding="utf-8") as f:
        f.write(archive_html)
    print(f"✅ Archive saved: {archive_file}")
    if today_slug not in archive_entries:
        archive_entries.insert(0, today_slug)
    else:
        # move to top in case the slug already existed (shouldn't normally)
        archive_entries.remove(today_slug)
        archive_entries.insert(0, today_slug)
    save_archive_index(archive_entries)
    print(f"✅ Archive index updated: {len(archive_entries)} entries")
    return archive_entries


def main():
    print(f"🚀 Building report at {datetime.now(HK_TZ).strftime('%Y-%m-%d %H:%M')} HKT")
    data = fetch_data()
    rows = compute_stock_stats(data["stocks"])

    # Load existing archive entries (list of slugs, newest first)
    archive_entries = load_archive_index()
    print(f"  → Existing archives: {len(archive_entries)}")

    # 1. Save today's archive snapshot (timestamped)
    archive_entries = archive_today(data, rows, archive_entries)

    # 2. Generate the latest report.html
    html = build_html(data, rows, archive_entries=archive_entries, current_ts=None)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Written {OUTPUT_FILE} ({len(html)} bytes, {len(rows)} stocks)")


if __name__ == "__main__":
    main()
