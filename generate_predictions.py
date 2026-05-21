#!/usr/bin/env python3
"""
generate_predictions.py
HK Stock AI Prediction Script using NVIDIA MiniMax M2.7 API.

Workflow:
  1. Scrape ETNet Top 10 stock codes
  2. Fetch 5-day historical OHLCV data via Tushare
  3. For each stock → call NVIDIA MiniMax M2.7 API → get 5-day future predictions
  4. Merge historical + predicted → save to public/data/predictions.json

Usage:
    python generate_predictions.py

Environment:
    NVIDIA_API_KEY   — NVIDIA NGC API key (required)
    TUSHARE_TOKEN    — Tushare API token (optional, falls back to mock data)
"""

import os
import sys
import re
import json
import time
import io
import random
import requests
import pandas as pd
import tushare as ts
from datetime import datetime, timedelta, date
from pathlib import Path

# ── NVIDIA OpenAI-compatible client ───────────────────────────────────────────
from openai import OpenAI

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
os.environ["OPENAI_API_KEY"] = NVIDIA_API_KEY  # openai library checks this env var

def get_nvidia_client():
    """Lazy creation so env vars are set before instantiation."""
    return OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=NVIDIA_API_KEY,
    )

# ── Config ────────────────────────────────────────────────────────────────────
ETNET_URL    = "https://www.etnet.com.hk/mobile/tc/stocks/top50.php?subtype=turnover"
HKEX_XLSX    = "https://www.hkex.com.hk/chi/services/trading/securities/securitieslists/ListOfSecurities_c.xlsx"
LIMIT        = 10
TOP_N        = 10
OUTPUT_FILE  = Path("public/data/predictions.json")
HIST_DATA    = Path("public/data/stocks.json")          # written by fetch_stock_data.py
DAYS_BACK    = 10
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
NVIDIA_MODEL = "minimaxai/minimax-m2.7"


# ── Step 1: Build name mapping from HKEX xlsx ────────────────────────────────
def build_name_mapping():
    print("📥 Downloading HKEX securities list...")
    try:
        resp = requests.get(HKEX_XLSX, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        resp.raise_for_status()
        df = pd.read_excel(io.BytesIO(resp.content), engine="openpyxl", header=2)
        df.columns = df.columns.str.strip()
        df = df[["股份代號", "股份名稱"]].dropna()
        df["股份代號"] = df["股份代號"].astype(int).astype(str).str.zfill(5)
        df["股份名稱"] = df["股份名稱"].astype(str).str.strip()
        mapping = dict(zip(df["股份代號"], df["股份名稱"]))
        print(f"  → Loaded {len(mapping)} Chinese stock names")
        return mapping
    except Exception as e:
        print(f"  ⚠️  HKEX download failed: {e}")
        return {}


# ── Step 2: Scrape ETNet Top 10 codes ───────────────────────────────────────
def fetch_etnet_codes():
    print("📡 Fetching ETNet Top50...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }
    try:
        resp = requests.get(ETNET_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"❌ ETNet fetch failed: {e}")
        return []

    pattern = r'quote\.php\?code=["\']?([0-9]{4,6})["\']?'
    raw_codes = re.findall(pattern, html, re.IGNORECASE)

    seen, codes = set(), []
    for code in raw_codes:
        if not code.startswith("8") and code not in seen:
            seen.add(code)
            codes.append(code.zfill(5))
    print(f"  → Found {len(codes)} stock codes")
    return codes[:LIMIT]


# ── Step 3: Fetch Tushare historical prices ──────────────────────────────────
def fetch_tushare_prices(codes, name_mapping):
    if not TUSHARE_TOKEN:
        print("⚠️  TUSHARE_TOKEN not set — using mock data")
        return get_mock_data(codes, name_mapping)

    print("📊 Fetching Tushare prices...")
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    end_date   = date.today()
    start_date = end_date - timedelta(days=DAYS_BACK)
    start_str  = start_date.strftime("%Y%m%d")
    end_str    = end_date.strftime("%Y%m%d")

    results = []
    for code in codes[:LIMIT]:
        symbol = f"{code}.HK"
        name   = name_mapping.get(code, symbol)
        try:
            df = pro.hk_daily(ts_code=symbol, start_date=start_str, end_date=end_str)
            if df is None or df.empty:
                print(f"  ⚠️  {symbol} no data")
                continue

            df = df.sort_values("trade_date")
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
            last5 = df.tail(5).copy()

            if len(last5) < 2:
                print(f"  ⚠️  {symbol} insufficient data")
                continue

            rows = []
            for _, row in last5.iterrows():
                rows.append({
                    "date":      row["trade_date"].strftime("%Y-%m-%d"),
                    "dateShort": row["trade_date"].strftime("%m/%d"),
                    "close":     float(row["close"]),
                    "open":      float(row.get("open", row["close"])),
                    "high":      float(row.get("high", row["close"])),
                    "low":       float(row.get("low",  row["close"])),
                    "volume":    int(row["vol"]),
                    "volumeM":   round(int(row["vol"]) / 1e6, 2),
                })

            results.append({"code": code, "name": name, "symbol": symbol, "prices": rows})
            print(f"  ✅ {symbol} {name}: {len(rows)} rows")
            time.sleep(0.5)

        except Exception as e:
            print(f"  ❌ {symbol} error: {e}")

    return results


def get_mock_data(codes, name_mapping):
    """Fallback mock data when Tushare is unavailable."""
    print("📊 Using mock price data...")
    random.seed(42)
    base_prices = {
        "00700": 380, "09988": 82, "00941": 68, "00939": 5.8, "01398": 4.2,
        "01698": 28,  "06098": 48, "02688": 85, "06888": 22, "01810": 18,
    }
    results = []
    today = date.today()
    for code in codes[:LIMIT]:
        symbol = f"{code}.HK"
        name   = name_mapping.get(code, symbol)
        base   = base_prices.get(code, 50)
        rows   = []
        for i in range(5):
            d     = today - timedelta(days=4 - i)
            close = round(base * (1 + random.uniform(-0.03, 0.03)), 2)
            open_ = round(close * (1 + random.uniform(-0.01, 0.01)), 2)
            high  = round(max(close, open_) * (1 + random.uniform(0, 0.01)), 2)
            low   = round(min(close, open_) * (1 - random.uniform(0, 0.01)), 2)
            vol   = int(random.uniform(5e6, 50e6))
            rows.append({
                "date":      d.strftime("%Y-%m-%d"),
                "dateShort": d.strftime("%m/%d"),
                "close":  close, "open": open_, "high": high, "low": low,
                "volume": vol, "volumeM": round(vol / 1e6, 1),
            })
            base = close
        results.append({"code": code, "name": name, "symbol": symbol, "prices": rows})
    return results


# ── Step 4: Call NVIDIA MiniMax M2.7 for each stock ─────────────────────────
def call_nvidia_ai(history_rows, stock_code, stock_name):
    """Send 5-day historical data to NVIDIA MiniMax M2.7 and return 5-day predicted rows."""
    if not NVIDIA_API_KEY:
        print(f"  ⚠️  No NVIDIA_API_KEY — skipping AI prediction for {stock_code}")
        return None

    # Build context string
    segments = []
    for row in history_rows:
        seg = (
            f"{row['date']}: "
            f"O:{row['open']:.2f} H:{row['high']:.2f} "
            f"L:{row['low']:.2f} C:{row['close']:.2f} V:{row['volumeM']:.1f}M"
        )
        segments.append(seg)
    historical_context = " | ".join(segments)

    prompt = (
        f"Based on these 5 days of actual Hong Kong stock data for {stock_name} ({stock_code}), "
        f"predict the next 5 upcoming trading days sequentially. "
        f"Return ONLY a valid JSON array containing exactly 5 items formatted precisely like this sample: "
        f'[{{"date": "MM/DD_PRED", "open": 74.50, "high": 76.00, "low": 72.10, "close": 75.30, "volume": "180.5M"}}]. '
        f"Use realistic price continuation based on the trend in the historical data. "
        f"Data: {historical_context}"
    )

    client = get_nvidia_client()
    try:
        response = client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1.0,
            max_tokens=2048,
            timeout=30,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        predicted_rows = json.loads(raw)

        # Normalise predicted rows
        normalised = []
        for row in predicted_rows:
            normalised.append({
                "date":      row.get("date", ""),
                "dateShort": row.get("date", "")[:5] if row.get("date") else "",
                "open":      float(row.get("open", 0)),
                "high":      float(row.get("high", 0)),
                "low":       float(row.get("low",  0)),
                "close":     float(row.get("close", 0)),
                "volume":    int(float(str(row.get("volume", "0M")).rstrip("Mm")) * 1e6),
                "volumeM":   str(row.get("volume", "0M")),
            })
        print(f"  🤖 {stock_code} AI prediction: {len(normalised)} rows")
        return normalised

    except Exception as e:
        print(f"  ❌ {stock_code} NVIDIA API error: {e}")
        return None


# ── Step 5: Orchestrator ──────────────────────────────────────────────────────
def main():
    print(f"\n🚀 generate_predictions.py started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 5a. Scrape codes
    codes = fetch_etnet_codes()
    if not codes:
        print("❌ No codes fetched")
        sys.exit(1)

    # 5b. Name mapping
    name_mapping = build_name_mapping()

    # 5c. Fetch historical prices
    stocks_data = fetch_tushare_prices(codes, name_mapping)
    if not stocks_data:
        print("❌ No stock data fetched")
        sys.exit(1)

    # 5d. Generate AI predictions per stock
    final_predictions_db = {}
    for stock in stocks_data:
        code    = stock["code"]
        name    = stock["name"]
        history = stock["prices"]          # 5 historical rows, oldest→newest

        print(f"\n🤖 Processing {name} ({code})...")
        ai_rows = call_nvidia_ai(history, code, name)

        if ai_rows:
            combined = history + ai_rows
        else:
            # Fallback: no prediction available
            combined = history

        final_predictions_db[code] = {
            "name":         name,
            "symbol":       stock["symbol"],
            "combined_data": combined,   # 5 historical + 5 predicted = 10 rows
            "has_ai":       ai_rows is not None,
        }

        # Respect API rate limits
        time.sleep(1)

    # 5e. Write predictions.json
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_predictions_db, f, ensure_ascii=False, indent=2)

    has_ai_count = sum(1 for v in final_predictions_db.values() if v["has_ai"])
    print(f"\n✅ predictions.json written → {OUTPUT_FILE}")
    print(f"   Stocks: {len(final_predictions_db)} | With AI predictions: {has_ai_count}")


if __name__ == "__main__":
    main()
