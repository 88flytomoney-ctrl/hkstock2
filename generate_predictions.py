#!/usr/bin/env python3
"""
generate_predictions.py
HK Stock AI Prediction Script using Dreamfield MiniMax-M2.7-highspeed API.
Optimized Version: Stripped stock names from LLM payload to fix tokenization performance lag.
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
from datetime import datetime, timedelta, date
from pathlib import Path
from openai import OpenAI

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
os.environ["OPENAI_API_KEY"] = NVIDIA_API_KEY

def get_dreamfield_client():
    return OpenAI(
        base_url="https://www.dreamfield.top/v1/",
        api_key=NVIDIA_API_KEY,
    )

ETNET_URL     = "https://www.etnet.com.hk/mobile/tc/stocks/top50.php?subtype=turnover"
HKEX_XLSX     = "https://www.hkex.com.hk/chi/services/trading/securities/securitieslists/ListOfSecurities_c.xlsx"
LIMIT         = 10
OUTPUT_FILE   = Path("public/data/predictions.json")
DAYS_BACK     = 10
AI_MODEL_ID   = "MiniMax-M2.7-highspeed"

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

def fetch_yf_prices(codes, name_mapping):
    print("📊 Fetching Yahoo Finance prices...")
    import yfinance as yf
    end_date   = date.today()
    start_date = end_date - timedelta(days=DAYS_BACK)

    # Yahoo Finance uses no-leading-zero HK symbols: 00700→700.HK, 09988→9988.HK
    yf_symbols = [f'{int(c)}.HK' for c in codes[:LIMIT]]
    try:
        df_all = yf.download(
            yf_symbols,
            start=start_date,
            end=end_date,
            auto_adjust=True,
            group_by='ticker',
            progress=False,
        )
    except Exception as e:
        print(f"❌ yfinance batch download failed: {e}")
        return []

    results = []
    for code in codes[:LIMIT]:
        symbol = f"{code}.HK"
        yf_sym = f"{int(code)}.HK"
        name   = name_mapping.get(code, symbol)
        try:
            if yf_sym not in df_all.columns.get_level_values(0):
                print(f"  ⚠️  {symbol} not in yfinance response")
                continue
            df = df_all[yf_sym].dropna(how='all')
            if df is None or df.empty:
                continue
            df = df.sort_index()  # oldest → newest
            last5 = df.tail(5).copy()
            if len(last5) < 2:
                continue

            rows = []
            for idx, row in last5.iterrows():
                d = idx.date()
                vol = int(row['Volume']) if not pd.isna(row['Volume']) else 0
                rows.append({
                    "date":      d.strftime("%Y-%m-%d"),
                    "dateShort": d.strftime("%m/%d"),
                    "close":     round(float(row["Close"]), 2),
                    "open":      round(float(row["Open"]), 2),
                    "high":      round(float(row["High"]), 2),
                    "low":       round(float(row["Low"]), 2),
                    "volume":    vol,
                    "volumeM":   round(vol / 1e6, 2),
                })
            results.append({"code": code, "name": name, "symbol": symbol, "prices": rows})
            time.sleep(0.2)
        except Exception as e:
            print(f"❌ {symbol} error: {e}")
    return results

def call_nvidia_ai(history_rows, stock_code):
    """Sends numerical sequence context without Chinese character string headers."""
    if not NVIDIA_API_KEY:
        return None

    segments = []
    for row in history_rows:
        seg = f"{row['dateShort']}: O:{row['open']:.2f} H:{row['high']:.2f} L:{row['low']:.2f} C:{row['close']:.2f} V:{row['volumeM']:.1f}M"
        segments.append(seg)
    historical_context = " | ".join(segments)

    sample_input = "05/14: O:75.30 H:76.10 L:71.50 C:71.50 V:98.4M | 05/15: O:73.90 H:76.65 L:70.75 C:71.15 V:156.8M | 05/18: O:70.55 H:72.65 L:67.60 C:68.70 V:119.0M | 05/19: O:67.95 H:69.40 L:65.20 C:68.50 V:119.8M | 05/20: O:68.05 H:77.45 L:67.60 C:75.15 V:258.5M"
    sample_output = (
        '[\n'
        '  {"date": "05/21_PRED", "open": 74.50, "high": 76.00, "low": 72.10, "close": 75.30, "volume": "180.5M"},\n'
        '  {"date": "05/22_PRED", "open": 75.30, "high": 77.20, "low": 74.80, "close": 76.80, "volume": "195.2M"},\n'
        '  {"date": "05/25_PRED", "open": 76.80, "high": 76.90, "low": 73.50, "close": 74.10, "volume": "150.0M"},\n'
        '  {"date": "05/26_PRED", "open": 74.10, "high": 75.50, "low": 73.80, "close": 75.00, "volume": "115.6M"},\n'
        '  {"date": "05/27_PRED", "open": 75.00, "high": 78.40, "low": 74.90, "close": 77.90, "volume": "210.3M"}\n'
        ']'
    )

    prompt = (
        f"You are a professional financial quantitative analysis model specializing in trend continuation.\n\n"
        f"[TRAINING SAMPLE]\nInput:\n{sample_input}\nOutput:\n{sample_output}\n\n"
        f"[REAL-TIME TASK]\nPredict the next 5 upcoming trading days sequentially for stock identifier token: {stock_code}.\n"
        f"Do not return conversational text. Return ONLY a valid JSON array matching the structure shown above.\n"
        f"Input Data:\n{historical_context}\n\n"
        f"Output JSON:"
    )

    client = get_dreamfield_client()
    for attempt in range(1, 3):
        try:
            response = client.chat.completions.create(
                model=AI_MODEL_ID,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1500,
                timeout=20,
            )

            raw = response.choices[0].message.content.strip()

            # Strip AI thinking blocks
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL)

            # Strip markdown code fences
            if raw.startswith("```"):
                parts = raw.split("\n", 1)
                if len(parts) > 1:
                    raw = parts[1]
                if raw.rstrip().endswith("```"):
                    raw = raw.rstrip()[:-3]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            predicted_rows = json.loads(raw)
            normalised = []
            for row in predicted_rows:
                d_str = row.get("date", "")
                normalised.append({
                    "date":      d_str,
                    "dateShort": d_str.replace("_PRED", "").replace("🔮", "")[:5],
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
            print(f"  ❌ {stock_code} attempt {attempt} failed: {e}")
            if attempt < 2:
                print(f"     Retrying in 3s...")
                time.sleep(3)
            continue
    return None

def main():
    codes = fetch_etnet_codes()
    if not codes:
        sys.exit(1)
    name_mapping = build_name_mapping()
    stocks_data = fetch_tushare_prices(codes, name_mapping)
    if not stocks_data:
        sys.exit(1)

    final_predictions_db = {}
    for stock in stocks_data:
        code    = stock["code"]
        name    = stock["name"]
        history = stock["prices"]

        print(f"🤖 Inferencing numerical patterns for token code {code}...")
        ai_rows = call_nvidia_ai(history, code)

        combined = history + ai_rows if ai_rows else history

        final_predictions_db[code] = {
            "name":          name,
            "symbol":        stock["symbol"],
            "combined_data": combined,
            "has_ai":        ai_rows is not None,
        }
        time.sleep(0.2)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_predictions_db, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Optimized data asset compiled successfully → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
