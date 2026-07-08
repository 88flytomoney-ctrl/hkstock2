#!/usr/bin/env python3
"""
generate_predictions.py
HK Stock AI Prediction Script with historical forecast persistence.
Saves up to two records per stock day: [Actual] and [AI Predicted].
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
import yfinance as yf
from datetime import datetime, timedelta, date
from pathlib import Path
from openai import OpenAI

# ── OpenRouter Configuration ──────────────────────────────────────────────────
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OUTPUT_FILE = Path("public/data/predictions.json")
AI_MODEL_ID = "poolside/laguna-xs-2.1:free"
LIMIT = 20

def get_openrouter_client():
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

def load_existing_database():
    """Reads current predictions.json to extract and preserve historical predictions."""
    if not OUTPUT_FILE.exists():
        return {}
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("stocks", {})
    except Exception as e:
        print(f"⚠️ Failed to load existing database: {e}")
        return {}

def build_name_mapping():
    # Downloads securities lists from HKEX or returns a fall-back dictionary
    HKEX_XLSX = "https://www.hkex.com.hk/chi/services/trading/securities/securitieslists/ListOfSecurities_c.xlsx"
    print("📥 Downloading HKEX securities list...")
    try:
        resp = requests.get(HKEX_XLSX, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        resp.raise_for_status()
        df = pd.read_excel(io.BytesIO(resp.content), engine="openpyxl", header=2)
        df.columns = df.columns.str.strip()
        df = df[["股份代號", "股份名稱"]].dropna()
        df["股份代號"] = df["股份代號"].astype(int).astype(str).str.zfill(5)
        df["股份名稱"] = df["股份名稱"].astype(str).str.strip()
        return dict(zip(df["股份代號"], df["股份名稱"]))
    except Exception as e:
        print(f"⚠️ HKEX download failed: {e}")
        return {}

def fetch_etnet_codes():
    ETNET_URL = "https://www.etnet.com.hk/mobile/tc/stocks/top50.php?subtype=turnover"
    print("📡 Fetching ETNet Top50...")
    headers = {"User-Agent": "Mozilla/5.0"}
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
    return codes[:LIMIT]

def fetch_yahoo_prices(codes, name_mapping):
    # Yahoo Finance historical data — 10 days of historical OHLCV
    results = []
    for code in codes:
        # Yahoo Finance HK symbol: keep last 4 digits (e.g. 00700 → 0700.HK, 02800 → 2800.HK)
        yahoo_code = code[-4:]  # Take last 4 chars
        symbol = f"{yahoo_code}.HK"
        name = name_mapping.get(code, symbol)
        try:
            print(f"📊 Fetching Yahoo Finance history for {symbol}...")
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="15d") # Fetch slightly more to ensure 10 clean days
            if hist.empty:
                # No Yahoo history, but still record the stock (Sina may have data)
                results.append({"code": code, "name": name, "symbol": symbol, "prices": []})
                continue

            # Format rows matching the frontend properties
            rows = []
            hist = hist.tail(10) # Grab the final 10 days of real history
            for timestamp, row in hist.iterrows():
                vol = int(row["Volume"])
                close_val = round(float(row["Close"]), 2)
                open_val  = round(float(row["Open"]), 2)
                high_val  = round(float(row["High"]), 2)
                low_val   = round(float(row["Low"]), 2)
                # ⚠️ Skip rows with NaN — market holiday / weekend returns invalid data
                if any(pd.isna(v) for v in [close_val, open_val, high_val, low_val]):
                    continue
                rows.append({
                    "date":      timestamp.strftime("%Y-%m-%d"),
                    "dateShort": timestamp.strftime("%m/%d"),
                    "close":     close_val,
                    "open":      open_val,
                    "high":      high_val,
                    "low":       low_val,
                    "volume":    vol,
                    "volumeM":   f"{round(vol / 1e6, 2)}M",
                    "is_predicted": False
                })
            results.append({"code": code, "name": name, "symbol": symbol, "prices": rows})
        except Exception as e:
            print(f"❌ Yahoo Finance fetch failed for {symbol}: {e}")
    return results


def fetch_sina_realtime(codes, name_mapping):
    """Real-time HK stock prices from Sina Finance API (free, no rate limit).
    Returns only today's quote row to overlay on the yahoo history."""
    if not codes:
        return {}
    # Build batch query: hk<5-digit-code>
    codes_5 = [c.zfill(5) for c in codes]
    sina_codes = ",".join(f"hk{c}" for c in codes_5)
    url = f"https://hq.sinajs.cn/list={sina_codes}"
    print("📡 Fetching Sina Finance real-time quotes...")
    try:
        resp = requests.get(url, headers={
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0"
        }, timeout=15)
        resp.encoding = "gbk"
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️ Sina request failed: {e}")
        return {}

    result_map = {}
    for code in codes:
        code_5 = code.zfill(5)
        match = re.search(rf'hq_str_hk{code_5}="([^"]+)"', resp.text)
        if not match:
            continue
        fields = match.group(1).split(",")
        if len(fields) < 19:
            continue
        try:
            today_open = float(fields[2])
            today_current = float(fields[4])   # latest / current price (may = high during trading)
            sina_low = float(fields[5])         # Sina HK: field 5 = low (field 6 = high, swapped!)
            sina_high = float(fields[6])
            # Fix swapped high/low for HK stocks
            today_low = min(sina_low, sina_high)
            today_high = max(sina_low, sina_high)
            # Sina's "current" is the latest traded price, capped at high
            # If current > high (shouldn't happen after swap), clamp it
            today_close = min(today_current, today_high)
            volume = int(fields[12]) if fields[12].isdigit() else 0
            date_str = fields[17].replace("/", "-")  # 2026/05/29 → 2026-05-29
            name = name_mapping.get(code, fields[1] or code)
            # Skip rows with zero prices (market closed / no trade today)
            if today_close == 0:
                continue
            result_map[code] = {
                "code": code,
                "name": name,
                "date": date_str,
                "dateShort": datetime.strptime(date_str, "%Y-%m-%d").strftime("%m/%d"),
                "open": today_open,
                "close": today_close,
                "high": today_high,
                "low": today_low,
                "volume": volume,
                "volumeM": f"{round(volume / 1e6, 2)}M",
                "is_predicted": False,
            }
        except (ValueError, IndexError) as e:
            print(f"  ⚠️ Sina parse failed for {code}: {e}")
            continue

    print(f"  → Got {len(result_map)} real-time quotes from Sina")
    return result_map

def fetch_global_indices():
    """Fetches real-time HK index data using yfinance.
    
    IMPORTANT: Call this BEFORE fetching stock history to avoid Yahoo rate-limiting.
    Only ^HSI and ^HSCE are available — ^HSTECH is delisted.
    """
    indices = {
        "^HSI": {"name": "恒生指數", "key": "hsi"},
        "^HSCE": {"name": "國企指數", "key": "hsce"},
        # ^HSTECH is delisted/not available on Yahoo Finance
    }
    results = {}
    for ticker, info in indices.items():
        try:
            import time
            time.sleep(0.5)  # Small delay to avoid rate limiting
            obj = yf.Ticker(ticker)
            hist = obj.history(period="2d")
            if not hist.empty and len(hist) >= 2:
                close_today = round(float(hist["Close"].iloc[-1]), 2)
                close_yesterday = round(float(hist["Close"].iloc[-2]), 2)
                change = round(close_today - close_yesterday, 2)
                pct = round((change / close_yesterday) * 100, 2)
                results[info["key"]] = {
                    "name": info["name"],
                    "value": close_today,
                    "change": change,
                    "pct": pct,
                    "isPositive": change >= 0
                }
                print(f"📈 {ticker}: {close_today} ({change:+.2f}, {pct:+.2f}%)")
            else:
                print(f"⚠️ {ticker}: insufficient data ({len(hist)} rows)")
        except Exception as e:
            print(f"⚠️ Failed to fetch index {ticker}: {e}")
    print(f"✅ Indices fetched: {list(results.keys())}")
    return results

def call_openrouter_vector_engine(history_rows, stock_code):
    if not OPENROUTER_API_KEY:
        print("⚠️ OPENROUTER_API_KEY is not defined.")
        return None, "持有"

    # Convert prices to raw multidimensional coordinate vectors
    segments = []
    for i, row in enumerate(history_rows[-10:]):
        idx = i + 1
        vol_clean = str(row['volumeM']).replace('M', '')
        segments.append(f"t{idx}: [{row['open']:.2f}, {row['high']:.2f}, {row['low']:.2f}, {row['close']:.2f}, {vol_clean}]")
    historical_context = " | ".join(segments)

    sample_input = "t1: [75.30, 76.10, 71.50, 71.50, 98.4] | t2: [73.90, 76.65, 70.75, 71.15, 156.8]"
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
        f"Generate exactly 5 continuous vector steps (t11_ext to t15_ext) following the mathematical progression pattern for the sequence node: {node_token}.\n"
        f"Also determine the overall extrapolated trend vector index 'trend_direction_index' as an integer: 1 for upward continuation, 0 for range-bound, or -1 for downward continuation.\n"
        f"Do not return conversational explanations or markdown blocks. Return ONLY a valid JSON object matching the sample structure shown above.\n\n"
        f"[SAMPLE]\nInput Matrix:\n{sample_input}\nOutput JSON:\n{sample_output}\n\n"
        f"[REAL-TIME TASK]\nInput Matrix:\n{historical_context}\n\n"
        f"Output JSON:"
    )

    try:
        client = get_openrouter_client()
        response = client.chat.completions.create(
            model=AI_MODEL_ID,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=4000,
            timeout=30,
            extra_body={"reasoning": {"enabled": False}},
        )
        msg = response.choices[0].message
        raw = msg.content
        if not raw:
            # Reasoning models may put output in reasoning_content / reasoning
            raw = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
        if not raw:
            print(f"⚠️ Model returned empty content for {stock_code}")
            return None, "持有"
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw.rsplit("\n", 1)[0]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        
        parsed_response = json.loads(raw)
        predicted_rows = parsed_response.get("extrapolated_steps", [])
        trend_idx = int(parsed_response.get("trend_direction_index", 0))
        indicator_map = {1: "買入", 0: "持有", -1: "賣出"}
        recommendation = indicator_map.get(trend_idx, "持有")

        last_history_date_str = history_rows[-1]["date"]
        last_date = datetime.strptime(last_history_date_str, "%Y-%m-%d")
        
        next_trading_days = []
        curr_date = last_date
        while len(next_trading_days) < 5:
            curr_date += timedelta(days=1)
            if curr_date.weekday() < 5:
                next_trading_days.append(curr_date)

        normalised = []
        for idx, item in enumerate(predicted_rows[:5]):
            vals = item.get("values", [])
            if len(vals) < 5: continue
            target_date = next_trading_days[idx]
            raw_vol_m = float(vals[4])
            
            # Validate and fix OHLC relationships (AI may generate invalid values)
            o = float(vals[0])
            h = float(vals[1])
            l = float(vals[2])
            c = float(vals[3])
            
            # Ensure high >= all other values, low <= all other values
            h = max(h, o, c, l)
            l = min(l, o, c, h)
            
            normalised.append({
                "date":      target_date.strftime("%Y-%m-%d"),
                "dateShort": f"🔮 {target_date.strftime('%m/%d')}",
                "open":      o,
                "high":      h,
                "low":       l,
                "close":     c,
                "volume":    int(raw_vol_m * 1e6),
                "volumeM":   f"{raw_vol_m:.1f}M",
                "is_predicted": True # 🛠️ CRITICAL FIX: Explicitly mark as predicted to avoid key collisions
            })
        return normalised, recommendation
    except Exception as e:
        print(f"❌ OpenRouter failed for {stock_code}: {e}")
        return None, "持有"

def main():
    existing_stocks = load_existing_database()
    
    codes = fetch_etnet_codes()
    if not codes:
        print("❌ Scraper failed to fetch active stock codes.")
        sys.exit(1)
        
    name_mapping = build_name_mapping()
    
    # Step 1: Get Sina real-time today's data
    sina_today = fetch_sina_realtime(codes, name_mapping)
    
    # Step 1: Fetch HK indices FIRST (before stock fetches to avoid Yahoo rate-limiting)
    indices = fetch_global_indices()

    # Step 2: Get Yahoo Finance historical data (10 days)
    stocks_data = fetch_yahoo_prices(codes, name_mapping)
    if not stocks_data:
        print("❌ Scraper failed to fetch pricing rows.")
        sys.exit(1)

    final_predictions_db = {}
    for stock in stocks_data:
        code    = stock["code"]
        name    = stock["name"]
        history = stock["prices"]  # 10 elements of actual daily data

        # Step 3: Overlay Sina real-time row on top of yahoo history
        # Only use Sina for the name (more readable Chinese name)
        # Sina's "current price" is the latest trade, NOT the official close
        # so we do NOT overwrite Yahoo's closing price with it
        if code in sina_today:
            # Use Sina's Chinese name if available (more readable)
            sina_name = sina_today[code].get("name", "")
            if sina_name and sina_name != stock["symbol"]:
                name = sina_name
            print(f"  ℹ️  {code}: using Yahoo close={history[-1]['close'] if history else 'N/A'} (Sina name={name})")

        # Explicitly tag the newly fetched history as ACTUAL data
        for row in history:
            row["is_predicted"] = False

        # Get fresh 5-day future predictions
        ai_rows, recommendation = call_openrouter_vector_engine(history, code)

        # ── PERSISTENCE ENGINE: Merge with old predictions ────────────────────
        past_predicted_saved = []
        if code in existing_stocks:
            old_combined = existing_stocks[code].get("combined_data", [])
            for old_row in old_combined:
                # Retain older historical predictions to enable side-by-side display
                if old_row.get("is_predicted", False):
                    past_predicted_saved.append(old_row)

        # Merge Actual History + Old Predictions + New Predictions
        combined = history + past_predicted_saved + (ai_rows if ai_rows else [])
        
        # Deduplicate predictions for the exact same predicted date (keep only latest run)
        unique_combined = []
        seen_keys = set()
        # Collect actual dates first to filter out stale predictions
        actual_dates = set(r['date'] for r in combined if not r.get('is_predicted', False))
        for row in combined:
            # Skip AI-predicted rows that overlap with actual data dates
            if row.get('is_predicted', False) and row['date'] in actual_dates:
                continue
            # Create a unique composite key: date + prediction status
            key = f"{row['date']}_{row.get('is_predicted', False)}"
            if key not in seen_keys:
                seen_keys.add(key)
                unique_combined.append(row)

        # Sort the array chronologically by date
        unique_combined.sort(key=lambda x: (x["date"], x.get("is_predicted", False)))

        final_predictions_db[code] = {
            "name":          name,
            "symbol":        stock["symbol"],
            "combined_data": unique_combined,
            "has_ai":        ai_rows is not None,
            "recommendation": recommendation,
        }
        time.sleep(0.2)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        # Wrap database cleanly for the frontend loader
        json.dump({"stocks": final_predictions_db, "indices": indices}, f, ensure_ascii=False, indent=2)
    print(f"✅ Telemetry database merged cleanly with past projections → {OUTPUT_FILE}")

    # ── Save to history ─────────────────────────────────────────────────────────
    HISTORY_DIR = Path("public/data/history")
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    
    # Include time in filename to distinguish between midday/evening runs
    # e.g., 2026-06-01-13.json (for 13:xx run)
    time_str = datetime.now().strftime('%H') 
    date_str = datetime.now().strftime('%Y-%m-%d')
    history_file = HISTORY_DIR / f'{date_str}-{time_str}.json'
    
    # Structure history file to match what the frontend expects (same as stocks.json)
    # But we need to preserve "generatedAt" for the frontend to display
    history_data = {
        "generatedAt": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "generatedDate": date_str,
        "generatedTime": f"{time_str}:00",
        "stockCount": len(final_predictions_db),
        "stocks": [
            {
                "code": code,
                "symbol": details["symbol"],
                "name": details["name"],
                "prices": [row for row in details.get("combined_data", []) if not row.get("is_predicted", False)] # Only actual prices for history
            }
            for code, details in final_predictions_db.items()
        ]
    }
    
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history_data, f, ensure_ascii=False, indent=2)
    print(f"   ✅ History snapshot: {history_file}")

    # Update manifest
    manifest_file = HISTORY_DIR / 'manifest.json'
    existing_manifest = []
    if manifest_file.exists():
        with open(manifest_file, 'r', encoding='utf-8') as f:
            try:
                raw_data = json.load(f)
                # Handle migration from old format (array of strings) to new format (array of objects)
                if raw_data and isinstance(raw_data[0], str):
                    # Old format: ["2026-05-26", ...]
                    # Check actual files exist: old files are "YYYY-MM-DD.json" (no time suffix)
                    existing_manifest = []
                    for d in raw_data:
                        # First try: date only (old format)
                        old_file = f"{d}.json"
                        if Path(history_dir, old_file).exists():
                            existing_manifest.append({
                                "date": d,
                                "time": "00:00",
                                "file": old_file,
                                "display": d
                            })
                        else:
                            # Try: date with time (new format like 2026-06-01-08)
                            for hour in ['00', '08', '13', '17']:
                                new_file = f"{d}-{hour}.json"
                                if Path(history_dir, new_file).exists():
                                    existing_manifest.append({
                                        "date": d,
                                        "time": f"{hour}:00",
                                        "file": new_file,
                                        "display": f"{d} {hour}:00"
                                    })
                                    break
                else:
                    existing_manifest = raw_data
            except:
                existing_manifest = []
    
    # Add new entry
    new_entry = {
        "date": date_str,
        "time": f"{time_str}:00",
        "file": f"{date_str}-{time_str}.json",
        "display": f"{date_str} {time_str}:00"
    }
    
    # Remove old entry for same date+time if exists (overwrite), add new one
    # Filter out entries with same date and time
    existing_manifest = [e for e in existing_manifest if not (e['date'] == date_str and e['time'] == f"{time_str}:00")]
    existing_manifest.append(new_entry)
    
    # Sort by date (desc) then time (desc)
    existing_manifest.sort(key=lambda x: (x['date'], x['time']), reverse=True)
    
    with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(existing_manifest, f, ensure_ascii=False)
    print(f"   ✅ Manifest updated")

if __name__ == "__main__":
    main()
