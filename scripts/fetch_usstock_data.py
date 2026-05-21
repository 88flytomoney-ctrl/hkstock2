#!/usr/bin/env python3
"""
US Stock Data Fetcher + AI Analysis
Fetches US top 20 by turnover from ETNet, gets 5-day prices via Alpha Vantage,
then outputs public/data/stocks.json, history snapshots and manifest.json.

Usage:
    python scripts/fetch_usstock_data.py

Environment:
    ALPHA_VANTAGE_API_KEY   Alpha Vantage API key (free tier: 5 req/min, 500 req/day)
    TOP_N                    Number of stocks to fetch (default: 10)
    LIMIT                    Max stocks to process (default: 10)
"""
import sys
import os
import re
import json
import time
import requests
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ── Add scripts dir to path so stock_analysis can be imported ─────────────────
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from stock_analysis import analyze_stock

# ── Config ────────────────────────────────────────────────────────────────────
ETNET_URL = "https://www.etnet.com.hk/www/tc/us-stocks/top20.php?tab=turnover"
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
DAYS_BACK = 10
TOP_N = int(os.environ.get("TOP_N", 10))
LIMIT = int(os.environ.get("LIMIT", 10))
OUTPUT_FILE = Path("public/data/stocks.json")
HISTORY_DIR = Path("public/data/history")

# ── US Company full-name map (fallback when ETNet name is empty) ──────────────
COMPANY_NAMES = {
    "TSLA": "Tesla Inc",
    "NVDA": "NVIDIA Corporation",
    "MU":   "Micron Technology Inc",
    "SNDK": "SanDisk Corporation",
    "MSFT": "Microsoft Corporation",
    "AMD":  "Advanced Micro Devices Inc",
    "AAPL": "Apple Inc",
    "META": "Meta Platforms Inc",
    "GOOGL":"Alphabet Inc (Class A)",
    "AMZN": "Amazon.com Inc",
    "LITE": "Lumentum Holdings Inc",
    "INTC": "Intel Corporation",
    "PLTR": "Palantir Technologies Inc",
    "AVGO": "Broadcom Inc",
    "GOOG": "Alphabet Inc (Class C)",
    "NFLX": "Netflix Inc",
    "XOM":  "Exxon Mobil Corporation",
    "MRVL": "Marvell Technology Inc",
    "ASML": "ASML Holding NV",
    "WDC":  "Western Digital Corporation",
}


# ── Step 1: Fetch ETNet US Top-20 codes ───────────────────────────────────────
def fetch_etnet_us_top20():
    """Fetch ETNet US stocks top-20 by turnover, parse embedded chartdata JSON."""
    print("📡 Fetching ETNet US Top-20 by turnover...")
    try:
        req = urllib.request.Request(ETNET_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8")

        # Pattern: "turnover": {... "chartdata": [...] }
        pattern = r'"turnover":\s*\{[^}]*"chartdata":\s*(\[[\s\S]*?\])'
        match = re.search(pattern, html)
        if not match:
            # Fallback: try to find any chartdata array
            pattern2 = r'"chartdata":\s*(\[[\s\S]*?\])'
            match = re.search(pattern2, html)
            if not match:
                print("  ⚠️  Could not find turnover chartdata in ETNet page")
                return None

        json_str = match.group(1)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # Try to fix truncated JSON
            last_valid = json_str.rfind("}]")
            if last_valid > 0:
                json_str = json_str[:last_valid + 2]
                data = json.loads(json_str)
            else:
                print("  ⚠️  JSON parse failed for ETNet data")
                return None

        stocks = []
        for item in data:
            code  = item.get("code",  "").strip()
            name  = item.get("name",  "").strip()
            value = item.get("value", 0)
            perchg = item.get("perchg", 0)
            if code:
                stocks.append({
                    "code":       code,
                    "name":       name,
                    "turnover":   value,
                    "change_pct": perchg,
                })

        stocks.sort(key=lambda x: x["turnover"], reverse=True)
        print(f"  → Found {len(stocks)} ETNet US stocks")
        return stocks

    except Exception as e:
        print(f"  ❌ ETNet fetch failed: {e}")
        return None


def get_us_symbols():
    """Return (symbols_list, name_map) — top N from ETNet or fallback list."""
    etnet_data = fetch_etnet_us_top20()

    if etnet_data:
        top = etnet_data[:TOP_N]
        symbols = [s["code"] for s in top]
        # Build name map: prefer ETNet name, fall back to COMPANY_NAMES
        name_map = {}
        for s in top:
            name_map[s["code"]] = s["name"] or COMPANY_NAMES.get(s["code"], s["code"])
        print(f"  📊 Using ETNet Top {TOP_N}: {', '.join(symbols)}")
        return symbols, name_map

    # Fallback: hard-coded default list
    fallback = ["TSLA", "NVDA", "MU", "SNDK", "MSFT", "AMD", "AAPL", "META", "GOOGL", "AMZN"]
    symbols = fallback[:TOP_N]
    name_map = {s: COMPANY_NAMES.get(s, s) for s in symbols}
    print(f"  📊 Using fallback Top {TOP_N}: {', '.join(symbols)}")
    return symbols, name_map


# ── Step 2: Fetch Alpha Vantage prices ────────────────────────────────────────
def fetch_alpha_vantage_prices(symbol):
    """Fetch 5-day daily time-series from Alpha Vantage."""
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        return None

    params = {
        "function":   "TIME_SERIES_DAILY",
        "symbol":     symbol,
        "apikey":     api_key,
        "outputsize": "compact",
    }
    try:
        resp = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=30)
        data = resp.json()

        if "Time Series (Daily)" not in data:
            error_msg = data.get("Note", "") or data.get("Information", "") or "no data"
            return {"error": error_msg}

        time_series = data["Time Series (Daily)"]
        # Alpha Vantage returns newest first
        sorted_dates = sorted(time_series.keys(), reverse=True)[:5]
        points = []
        for date in sorted_dates:
            daily = time_series[date]
            points.append({
                "date":   date,
                "open":   float(daily["1. open"]),
                "high":   float(daily["2. high"]),
                "low":    float(daily["3. low"]),
                "close":  float(daily["4. close"]),
                "volume": int(daily["5. volume"]),
            })
        return {"data": points, "success": True}
    except Exception as e:
        return {"error": str(e)}


def fetch_us_prices_for_symbols(symbols):
    """Iterate symbols, fetch Alpha Vantage data with rate-limit handling."""
    print("📊 Fetching Alpha Vantage prices...")
    results = []
    rate_limit_hit = False

    for i, symbol in enumerate(symbols[:LIMIT]):
        print(f"  [{i+1}/{min(len(symbols), LIMIT)}] {symbol}...", end=" ", flush=True)
        result = fetch_alpha_vantage_prices(symbol)

        if result and result.get("success"):
            print("✅")
            results.append({"symbol": symbol, "data": result["data"], "success": True})
        elif result and result.get("error"):
            err = result["error"]
            if "rate limit" in err.lower() or "premium" in err.lower():
                print("⚠️  rate limit — stopping early")
                rate_limit_hit = True
                break
            else:
                print(f"❌ {err[:40]}")
                results.append({"symbol": symbol, "error": err, "success": False})
        else:
            print("❌ no response")
            results.append({"symbol": symbol, "error": "no response", "success": False})

        # Alpha Vantage free tier: 5 calls/min — wait 15s between calls
        if i < len(symbols) - 1 and not rate_limit_hit:
            time.sleep(15)

    return results, rate_limit_hit


# ── Step 3: Build stock records ────────────────────────────────────────────────
def build_stock_records(price_results, name_map):
    """Transform raw Alpha Vantage results into frontend-ready stock records."""
    stocks = []

    for result in price_results:
        symbol = result["symbol"]
        name   = name_map.get(symbol, COMPANY_NAMES.get(symbol, symbol))

        if not result.get("success") or not result.get("data"):
            print(f"  ⚠️  {symbol} — skipping (no data)")
            continue

        data_points = result["data"]
        if len(data_points) < 2:
            print(f"  ⚠️  {symbol} — insufficient data ({len(data_points)} days)")
            continue

        # Sort oldest→newest for trend calculation
        rows = sorted(data_points, key=lambda x: x["date"])

        # Add volume in millions
        for p in rows:
            p["volumeM"] = round(p["volume"] / 1_000_000, 2)
            # Add dateShort (mm/dd)
            dt = datetime.strptime(p["date"], "%Y-%m-%d")
            p["dateShort"] = dt.strftime("%m/%d")

        first_close = rows[0]["close"]
        last_close  = rows[-1]["close"]
        five_day_pct = round((last_close / first_close - 1) * 100, 2)
        high_5       = max(p["high"] for p in rows)
        low_5        = min(p["low"]  for p in rows)
        avg_vol      = sum(p["volume"] for p in rows) / len(rows)
        vol_trend    = "↑" if rows[-1]["volume"] > avg_vol else "↓"

        stock = {
            "code":        symbol,
            "symbol":      symbol,
            "name":        name,
            "prices":      rows,
            "fiveDayPct": five_day_pct,
            "high5":       high_5,
            "low5":        low_5,
            "avgVolume":   avg_vol,
            "volTrend":    vol_trend,
        }
        stocks.append(stock)
        print(f"  ✅ {symbol} {name}: {five_day_pct:+.2f}%")

    return stocks


# ── Step 4: Generate summary ───────────────────────────────────────────────────
def generate_summary(stocks):
    """Generate overall market summary text."""
    if not stocks:
        return "暂无数据"

    gainers   = [s for s in stocks if s["fiveDayPct"] > 0]
    losers    = [s for s in stocks if s["fiveDayPct"] < 0]
    avg_pct   = sum(s["fiveDayPct"] for s in stocks) / len(stocks)
    top_gainer = max(stocks, key=lambda s: s["fiveDayPct"])
    top_loser  = min(stocks, key=lambda s: s["fiveDayPct"])

    direction = "上涨" if avg_pct > 0 else "下跌"
    summary = (
        f"今日追踪 {len(stocks)} 只热门美股，五日整体平均"
        f"{direction}{abs(avg_pct):.2f}%。"
        f"表现最佳：{top_gainer['name']}（{top_gainer['code']}）{top_gainer['fiveDayPct']:+.2f}%，"
        f"表现最弱：{top_loser['name']}（{top_loser['code']}）{top_loser['fiveDayPct']:+.2f}%。"
        f"上涨 {len(gainers)} 只，下跌 {len(losers)} 只。"
    )
    return summary


# ── Step 5: Write JSON outputs ─────────────────────────────────────────────────
def write_outputs(output, date_str):
    """Write stocks.json, history snapshot, and update manifest."""
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  ✅ Written: {OUTPUT_FILE}")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_file = HISTORY_DIR / f"{date_str}.json"
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  ✅ History: {history_file}")

    manifest_file = HISTORY_DIR / "manifest.json"
    existing_dates = []
    if manifest_file.exists():
        with open(manifest_file, "r", encoding="utf-8") as f:
            existing_dates = json.load(f)
    if date_str not in existing_dates:
        existing_dates.append(date_str)
        existing_dates.sort(reverse=True)
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(existing_dates, f, ensure_ascii=False)
    print(f"  ✅ Manifest updated: {manifest_file}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print(f"\n🚀 US Stock fetcher started at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   Alpha Vantage API key: {'✅ set' if os.environ.get('ALPHA_VANTAGE_API_KEY') else '❌ NOT SET'}")

    # 1. Get symbols from ETNet (or fallback)
    symbols, name_map = get_us_symbols()
    if not symbols:
        print("❌ No symbols available, exiting.")
        sys.exit(1)

    # 2. Fetch prices from Alpha Vantage
    price_results, rate_limit_hit = fetch_us_prices_for_symbols(symbols)

    successful = [r for r in price_results if r.get("success")]
    if not successful:
        print("❌ No successful price fetches, exiting.")
        sys.exit(1)

    # 3. Build stock records
    stocks = build_stock_records(price_results, name_map)
    if not stocks:
        print("❌ No stock records built, exiting.")
        sys.exit(1)

    # 4. AI analysis (reuse HK stock_analysis module)
    print("🤖 Running AI analysis...")
    for stock in stocks:
        stock["analysis"] = analyze_stock(stock)

    # 5. Generate summary
    ai_summary = generate_summary(stocks)

    # 6. Build output structure
    date_str = datetime.now().strftime("%Y-%m-%d")
    output = {
        "generatedAt":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generatedDate": date_str,
        "stockCount":   len(stocks),
        "rateLimitHit": rate_limit_hit,
        "stocks":       stocks,
        "aiSummary":    ai_summary,
    }

    # 7. Write all outputs
    write_outputs(output, date_str)

    print(f"\n✅ Done! {len(stocks)} stocks processed")
    print(f"   Summary: {ai_summary[:100]}...")


if __name__ == "__main__":
    main()
