#!/usr/bin/env python3
"""
generate_predictions.py
HK Stock AI Prediction Script using OpenRouter (openrouter/owl-alpha).
Anonymized vector-based prompts: [open, high, low, close, volumeM] per timestep.
Appends 5 future coordinate steps to 10-day Yahoo Finance historical data.
Includes upper indices fetching & trend direction index extrapolation.
"""

import os
import sys
import re
import json
import time
import io
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path
from openai import OpenAI

# ── OpenRouter Client ──────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

def get_openrouter_client():
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

ETNET_URL    = "https://www.etnet.com.hk/mobile/tc/stocks/top50.php?subtype=turnover"
HKEX_XLSX    = "https://www.hkex.com.hk/chi/services/trading/securities/securitieslists/ListOfSecurities_c.xlsx"
LIMIT        = 15
OUTPUT_FILE  = Path("public/data/predictions.json")
STOCKS_FILE  = Path("public/data/stocks.json")
AI_MODEL_ID  = "openrouter/owl-alpha"
HK_TZ        = timezone(timedelta(hours=8))  # Hong Kong Standard Time

# ── Yahoo: Fetch HK Market Indices for Upper Dashboard ────────────────────────
def fetch_market_indices():
    """Fetches real-time HK major indices directly from Yahoo Finance API."""
    indices = {"^HSI": "恒生指數", "^HSCE": "國企指數"}
    YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
    results = {}
    print("📥 Fetching live HK major indices from Yahoo Finance...")
    for ticker, name in indices.items():
        try:
            url = f"{YAHOO_BASE}/{ticker}?interval=1d&range=2d"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            result = data["chart"]["result"][0]
            timestamps = result["timestamp"]
            closes = result["indicators"]["quote"][0].get("close", [])

            # Extract last 2 points for change calculation
            valid_closes = [c for c in closes if c is not None]
            if len(valid_closes) >= 2:
                close_today    = round(valid_closes[-1], 2)
                close_yesterday = round(valid_closes[-2], 2)
                change = round(close_today - close_yesterday, 2)
                pct    = round((change / close_yesterday) * 100, 2)
                results[ticker] = {
                    "name":      name,
                    "value":     close_today,
                    "change":    change,
                    "pct":       pct,
                    "isPositive": change >= 0
                }
                print(f"  📊 {name} ({ticker}): {close_today} ({change:+.2f}%)")
        except Exception as e:
            print(f"  ⚠️  Failed to fetch index {ticker}: {e}")
    return results

# ── ETNet: fetch Top50 stock codes ────────────────────────────────────────────
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

# ── HKEX: build code→Chinese-name mapping ─────────────────────────────────────
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

# ── Yahoo Finance: 10-day historical OHLCV ────────────────────────────────────
def fetch_yahoo_prices(codes, name_mapping):
    """Fetch HK stock prices from Yahoo Finance (10-day historical OHLCV)."""
    print("📊 Fetching Yahoo Finance historical data...")
    YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
    results = []
    for code in codes[:LIMIT]:
        yahoo_sym = f"{int(code):04d}.HK"
        symbol    = f"{code}.HK"
        name      = name_mapping.get(code, symbol)
        try:
            url = f"{YAHOO_BASE}/{yahoo_sym}?interval=1d&range=10d"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            result = data["chart"]["result"][0]
            timestamps = result["timestamp"]
            quotes = result["indicators"]["quote"][0]
            closes = quotes.get("close", [])
            opens  = quotes.get("open",  [])
            highs  = quotes.get("high",  [])
            lows   = quotes.get("low",   [])
            vols   = quotes.get("volume",[])

            rows = []
            for i, ts_val in enumerate(timestamps):
                close = closes[i] if i < len(closes) and closes[i] is not None else None
                if close is None:
                    continue
                dt = datetime.fromtimestamp(ts_val, tz=HK_TZ).strftime("%Y-%m-%d")
                rows.append({
                    "date":      dt,
                    "dateShort": dt[5:].replace("-", "/"),  # "2026-05-22" → "05/22"
                    "close":     round(close, 2),
                    "open":      round(opens[i], 2) if i < len(opens) and opens[i] is not None else close,
                    "high":      round(highs[i], 2) if i < len(highs) and highs[i] is not None else close,
                    "low":       round(lows[i],  2) if i < len(lows)  and lows[i]  is not None else close,
                    "volume":    int(vols[i])   if i < len(vols) and vols[i] is not None else 0,
                    "volumeM":   f"{round(vols[i] / 1e6, 2)}M" if i < len(vols) and vols[i] is not None else "0.0M",
                })

            if not rows:
                print(f"  ⚠️  {symbol} no data")
                continue

            latest = rows[-1]
            prev   = rows[-2] if len(rows) >= 2 else None
            today_pct = round((latest["close"] / prev["close"] - 1) * 100, 2) if prev and prev["close"] else 0
            results.append({
                "code":     code,
                "name":     name,
                "symbol":   symbol,
                "prices":   rows,
                "todayPct": today_pct
            })
            print(f"  ✅ {symbol} {name}: {latest['date']} {today_pct:+.2f}% ({len(rows)} days)")
        except Exception as e:
            print(f"  ❌ {symbol} error: {e}")
    return results

# ── OpenRouter: 5-step vector extrapolation with trend indicator ──────────────
def call_openrouter_ai(history_rows, stock_code):
    """Sends 10-day anonymized coordinate vectors [O,H,L,C,V_M] to OpenRouter.
    Returns 5 future coordinate steps and trend direction classification.
    """
    if not OPENROUTER_API_KEY:
        print("  ⚠️  OPENROUTER_API_KEY not set — skipping AI")
        return None, "持有"

    # Anonymize: send raw [O, H, L, C, V_M] vectors, no stock name, no price value context
    segments = []
    for i, row in enumerate(history_rows[-10:]):
        vol_clean = str(row['volumeM']).replace('M', '')
        segments.append(
            f"t{i+1}: [{row['open']:.2f}, {row['high']:.2f}, {row['low']:.2f}, "
            f"{row['close']:.2f}, {vol_clean}]"
        )
    historical_context = " | ".join(segments)

    sample_input  = "t1: [75.30, 76.10, 71.50, 71.50, 98.4] | t2: [73.90, 76.65, 70.75, 71.15, 156.8]"
    sample_output = (
        '{\n'
        '  "extrapolated_steps": [\n'
        '    {"step": "t3_ext", "values": [74.50, 76.00, 72.10, 75.30, 180.5]},\n'
        '    {"step": "t4_ext", "values": [75.30, 77.20, 74.80, 76.80, 195.2]}\n'
        '  ],\n'
        '  "trend_direction_index": 1\n'
        '}'
    )

    node_token = f"node_hk_alpha_{stock_code.lstrip('0')}"

    prompt = (
        f"You are a mathematical sequence extrapolation compiler specializing in multi-dimensional coordinate vector progression.\n"
        f"Generate exactly 5 continuous vector steps (t11_ext to t15_ext) following the mathematical progression pattern "
        f"for the sequence node: {node_token}.\n"
        f"Also determine the overall extrapolated trend vector index 'trend_direction_index' as an integer: "
        f"1 for upward continuation, 0 for range-bound, or -1 for downward continuation.\n"
        f"Do not return conversational explanations, comments, or markdown blocks. "
        f"Return ONLY a valid JSON object matching the structure shown above.\n\n"
        f"[SAMPLE]\n"
        f"Input Matrix:\n{sample_input}\n\n"
        f"Output JSON:\n{sample_output}\n\n"
        f"[REAL-TIME TASK]\n"
        f"Input Matrix:\n{historical_context}\n\n"
        f"Output JSON:"
    )

    for attempt in range(2):
        try:
            client = get_openrouter_client()
            response = client.chat.completions.create(
                model=AI_MODEL_ID,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1500,
                timeout=25,
            )
            raw = response.choices[0].message.content.strip()

            # Strip markdown fences
            if raw.startswith("```"):
                parts = raw.split("\n", 1)
                if len(parts) > 1:
                    raw = parts[1]
                if raw.rstrip().endswith("```"):
                    raw = raw.rstrip()[:-3]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            parsed_response = json.loads(raw)
            predicted_rows  = parsed_response.get("extrapolated_steps", [])

            trend_idx     = int(parsed_response.get("trend_direction_index", 0))
            indicator_map = {1: "買入", 0: "持有", -1: "賣出"}
            recommendation = indicator_map.get(trend_idx, "持有")

            # Calculate consecutive future trading days programmatically (excluding weekends)
            last_history_date_str = history_rows[-1]["date"]
            last_date = datetime.strptime(last_history_date_str, "%Y-%m-%d").date()

            next_trading_days_list = []
            curr_date = last_date
            while len(next_trading_days_list) < 5:
                curr_date += timedelta(days=1)
                if curr_date.weekday() < 5:   # Mon–Fri
                    next_trading_days_list.append(curr_date)

            normalised = []
            for idx, item in enumerate(predicted_rows[:5]):
                vals = item.get("values", [])
                if len(vals) < 5:
                    continue
                target_date = next_trading_days_list[idx]
                raw_vol_m  = float(vals[4])
                normalised.append({
                    "date":      target_date.strftime("%Y-%m-%d"),
                    "dateShort": f"🔮 {target_date.strftime('%m/%d')}",
                    "open":      float(vals[0]),
                    "high":      float(vals[1]),
                    "low":       float(vals[2]),
                    "close":     float(vals[3]),
                    "volume":     int(raw_vol_m * 1e6),
                    "volumeM":   f"{raw_vol_m:.1f}M",
                })

            print(f"  🤖 {stock_code} OpenRouter: {len(normalised)} future steps [{recommendation}]")
            return normalised, recommendation

        except Exception as e:
            print(f"  ❌ {stock_code} OpenRouter attempt {attempt+1} failed: {e}")
            if attempt < 1:
                time.sleep(3)

    return None, "持有"

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    codes = fetch_etnet_codes()
    if not codes:
        sys.exit(1)

    name_mapping = build_name_mapping()
    stocks_data  = fetch_yahoo_prices(codes, name_mapping)
    if not stocks_data:
        sys.exit(1)

    indices_data = fetch_market_indices()

    SKIP_AI = os.environ.get("SKIP_AI", "false").lower() == "true"

    final_predictions_db = {}
    for stock in stocks_data:
        code    = stock["code"]
        name    = stock["name"]
        history = stock["prices"]

        if SKIP_AI:
            ai_rows        = None
            recommendation = "持有"
            print(f"  ⏭️  {code} AI skipped")
        else:
            ai_rows, recommendation = call_openrouter_ai(history, code)

        combined = history + ai_rows if ai_rows else history

        final_predictions_db[code] = {
            "name":           name,
            "symbol":         stock["symbol"],
            "combined_data":  combined,
            "has_ai":         ai_rows is not None,
            "recommendation": recommendation,
        }
        time.sleep(0.3)

    # ── Write predictions.json ─────────────────────────────────────────────────
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "stocks":  final_predictions_db,
            "indices": indices_data,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Predictions & Indices saved → {OUTPUT_FILE}")

    # ── Write stocks.json (frontend needs this for lastUpdated display) ────────
    now_hkt = datetime.now(HK_TZ).strftime("%Y-%m-%d %H:%M:%S")
    stocks_list = []
    for s in stocks_data:
        item = {
            "code":       s["code"],
            "symbol":     s["symbol"],
            "name":       s["name"],
            "prices":     s["prices"],
            "fiveDayPct": s.get("todayPct", 0),
            "high5":      None,
            "low5":       None,
            "avgVolume":  None,
            "volTrend":   None,
            "analysis":   None,
        }
        stocks_list.append(item)

    stocks_db = {
        "generatedAt":   now_hkt,
        "generatedDate": now_hkt[:10],
        "stockCount":    len(stocks_list),
        "stocks":        stocks_list,
        "aiSummary":     "",
    }
    with open(STOCKS_FILE, "w", encoding="utf-8") as f:
        json.dump(stocks_db, f, ensure_ascii=False, indent=2)
    print(f"✅ stocks.json saved → {STOCKS_FILE} ({stocks_db['stockCount']} stocks, {now_hkt})")

if __name__ == "__main__":
    main()
