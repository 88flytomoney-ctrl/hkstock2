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
AI_MODEL_ID = "openrouter/owl-alpha"
LIMIT = 10

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

def fetch_tushare_prices(codes, name_mapping):
    # Using Yahoo Finance fallback if no Tushare token is provided
    results = []
    for code in codes:
        symbol = f"{code}.HK"
        name = name_mapping.get(code, symbol)
        try:
            print(f"📊 Fetching Yahoo Finance data for {symbol}...")
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="15d") # Fetch slightly more to ensure 10 clean days
            if hist.empty: continue
            
            # Format rows matching the frontend properties
            rows = []
            hist = hist.tail(10) # Grab the final 10 days of real history
            for timestamp, row in hist.iterrows():
                vol = int(row["Volume"])
                rows.append({
                    "date":      timestamp.strftime("%Y-%m-%d"),
                    "dateShort": timestamp.strftime("%m/%d"),
                    "close":     round(float(row["Close"]), 2),
                    "open":      round(float(row["Open"]), 2),
                    "high":      round(float(row["High"]), 2),
                    "low":       round(float(row["Low"]), 2),
                    "volume":    vol,
                    "volumeM":   f"{round(vol / 1e6, 2)}M",
                    "is_predicted": False # Real transactions are tagged False
                })
            results.append({"code": code, "name": name, "symbol": symbol, "prices": rows})
        except Exception as e:
            print(f"❌ Yahoo Finance fetch failed for {symbol}: {e}")
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
            max_tokens=1500,
            timeout=25,
        )
        raw = response.choices[0].message.content.strip()
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
            normalised.append({
                "date":      target_date.strftime("%Y-%m-%d"),
                "dateShort": f"🔮 {target_date.strftime('%m/%d')}",
                "open":      float(vals[0]),
                "high":      float(vals[1]),
                "low":       float(vals[2]),
                "close":     float(vals[3]),
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
    stocks_data = fetch_tushare_prices(codes, name_mapping)
    if not stocks_data:
        print("❌ Scraper failed to fetch pricing rows.")
        sys.exit(1)

    final_predictions_db = {}
    for stock in stocks_data:
        code    = stock["code"]
        name    = stock["name"]
        history = stock["prices"]  # 10 elements of actual daily data

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
        for row in combined:
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
        json.dump({"stocks": final_predictions_db}, f, ensure_ascii=False, indent=2)
    print(f"✅ Telemetry database merged cleanly with past projections → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
