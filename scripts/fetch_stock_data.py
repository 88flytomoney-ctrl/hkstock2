#!/usr/bin/env python3
"""
HK Stock Data Fetcher + AI Analysis
Generates public/data/stocks.json for the GitHub Pages frontend.

Usage:
    python scripts/fetch_stock_data.py
"""
import sys
import os
import re
import json
import time
import io
import requests
import pandas as pd
import tushare as ts
from datetime import datetime, timedelta
from pathlib import Path
from stock_analysis import analyze_stock

# ── Config ──────────────────────────────────────────────────────────────────
ETNET_URL = 'https://www.etnet.com.hk/mobile/tc/stocks/top50.php?subtype=turnover'
HKEX_XLSX_URL = 'https://www.hkex.com.hk/chi/services/trading/securities/securitieslists/ListOfSecurities_c.xlsx'
DAYS_BACK = 10
LIMIT = 15
TOP_N = 10
OUTPUT_FILE = Path('public/data/stocks.json')
HISTORY_DIR = Path('public/data/history')
TUSHARE_TOKEN = os.environ.get('TUSHARE_TOKEN', '9bfdcb66a5e11f5161a867270b4499a77966ea65c4bd0033a5da9f3b')


# ── Step 0: Build name mapping from HKEX xlsx ────────────────────────────────
def build_name_mapping():
    """Download HKEX securities list and extract Chinese stock names."""
    print('📥 Downloading HKEX securities list...')
    try:
        resp = requests.get(HKEX_XLSX_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=60)
        resp.raise_for_status()
        # Read xlsx from bytes
        df = pd.read_excel(io.BytesIO(resp.content), engine='openpyxl', header=2)
        df.columns = df.columns.str.strip()
        # Column names: 股份代號, 股份名稱
        df = df[['股份代號', '股份名稱']].dropna()
        # HKEX codes are integers — zero-pad to 5 digits for consistent lookup
        df['股份代號'] = df['股份代號'].astype(int).astype(str).str.zfill(5)
        df['股份名稱'] = df['股份名稱'].astype(str).str.strip()
        mapping = dict(zip(df['股份代號'], df['股份名稱']))
        print(f'  → Loaded {len(mapping)} Chinese stock names from HKEX')
        return mapping
    except Exception as e:
        print(f'  ⚠️  Failed to download HKEX list: {e}')
        return {}


# ── Step 1: Fetch ETNet Top codes ────────────────────────────────────────────
def fetch_etnet_codes():
    print('📡 Fetching ETNet Top50...')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
    }
    try:
        resp = requests.get(ETNET_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f'❌ ETNet fetch failed: {e}')
        return []

    # Pattern: quote.php?code=XXXXX
    pattern = r'quote\.php\?code=["\']?([0-9]{4,6})["\']?'
    raw_codes = re.findall(pattern, html, re.IGNORECASE)

    seen = set()
    codes = []
    for code in raw_codes:
        if not code.startswith('8') and code not in seen:
            seen.add(code)
            codes.append(code.zfill(5))
    print(f'  → Found {len(codes)} stock codes')
    return codes


# ── Step 2: Fetch Tushare prices ─────────────────────────────────────────────
def fetch_tushare_prices(codes, name_mapping):
    if not TUSHARE_TOKEN:
        print('⚠️  TUSHARE_TOKEN not set, using mock data')
        return get_mock_data(codes)

    print('📊 Fetching Tushare prices...')
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=DAYS_BACK)
    start_str = start_date.strftime('%Y%m%d')
    end_str = end_date.strftime('%Y%m%d')

    results = []
    for code in codes[:LIMIT]:
        symbol = f'{code}.HK'
        name = name_mapping.get(code, symbol)
        try:
            df = pro.hk_daily(ts_code=symbol, start_date=start_str, end_date=end_str)
            if df is None or df.empty:
                print(f'  ⚠️  {symbol} no data')
                continue

            df = df.sort_values('trade_date')
            df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
            last5 = df.tail(5).copy()

            if len(last5) < 2:
                print(f'  ⚠️  {symbol} insufficient data')
                continue

            rows = []
            for _, row in last5.iterrows():
                rows.append({
                    'date': row['trade_date'].strftime('%Y-%m-%d'),
                    'dateShort': row['trade_date'].strftime('%m/%d'),
                    'close': float(row['close']),
                    'open': float(row.get('open', row['close'])),
                    'high': float(row.get('high', row['close'])),
                    'low': float(row.get('low', row['close'])),
                    'volume': int(row['vol']),
                    'volumeM': round(int(row['vol']) / 1e6, 2),
                })

            # Calculate metrics (rows[0]=oldest, rows[-1]=newest)
            oldest_close = rows[0]['close']
            newest_close = rows[-1]['close']
            five_day_pct = round((newest_close / oldest_close - 1) * 100, 2)
            high_5 = max(r['high'] for r in rows)
            low_5 = min(r['low'] for r in rows)
            avg_vol = sum(r['volume'] for r in rows) / len(rows)
            vol_trend = '↑' if rows[-1]['volume'] > avg_vol else '↓'

            results.append({
                'code': code,
                'symbol': symbol,
                'name': name,
                'prices': rows,
                'fiveDayPct': five_day_pct,
                'high5': high_5,
                'low5': low_5,
                'avgVolume': avg_vol,
                'volTrend': vol_trend,
            })
            print(f'  ✅ {symbol} {name}: {five_day_pct:+.2f}%')
            time.sleep(0.5)

        except Exception as e:
            print(f'  ❌ {symbol} error: {e}')

    return results


# ── Mock data (when no Tushare token) ────────────────────────────────────────
def get_mock_data(codes, name_mapping):
    print('📊 Using mock data...')
    results = []
    import random
    random.seed(42)
    base_prices = {
        '00700': 380, '09988': 82, '00941': 68, '00939': 5.8, '01398': 4.2,
        '01698': 28, '06098': 48, '02688': 85, '06888': 22, '01810': 18,
    }
    for code in codes[:LIMIT]:
        symbol = f'{code}.HK'
        name = name_mapping.get(code, symbol)
        base = base_prices.get(code, 50)
        today = datetime.now().date()
        rows = []
        for i in range(5):
            d = today - timedelta(days=4-i)
            close = round(base * (1 + random.uniform(-0.03, 0.03)), 2)
            open_p = round(close * (1 + random.uniform(-0.01, 0.01)), 2)
            high = round(max(close, open_p) * (1 + random.uniform(0, 0.01)), 2)
            low = round(min(close, open_p) * (1 - random.uniform(0, 0.01)), 2)
            vol = int(random.uniform(5e6, 50e6))
            rows.append({
                'date': d.strftime('%Y-%m-%d'),
                'dateShort': d.strftime('%m/%d'),
                'close': close, 'open': open_p, 'high': high, 'low': low,
                'volume': vol, 'volumeM': round(vol / 1e6, 1),
            })
            base = close

        # Mock prices: newest first (rows[0]=newest, rows[-1]=oldest)
        first_close = rows[-1]['close']
        last_close = rows[0]['close']
        five_day_pct = round((last_close / first_close - 1) * 100, 2)
        results.append({
            'code': code, 'symbol': symbol, 'name': name,
            'prices': rows, 'fiveDayPct': five_day_pct,
            'high5': max(r['high'] for r in rows),
            'low5': min(r['low'] for r in rows),
            'avgVolume': sum(r['volume'] for r in rows) / 5,
            'volTrend': '↑' if rows[-1]['volume'] > sum(r['volume'] for r in rows) / 5 else '↓',
        })
    return results


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f'🚀 HK Stock fetcher started at {datetime.now().strftime("%Y-%m-%d %H:%M")}')

    # 1. Fetch codes
    codes = fetch_etnet_codes()
    if not codes:
        print('❌ No codes fetched, exiting')
        sys.exit(1)

    # 2. Build name mapping from HKEX
    name_mapping = build_name_mapping()

    # 3. Fetch prices
    stocks = fetch_tushare_prices(codes, name_mapping)
    if not stocks:
        print('❌ No stock data fetched, exiting')
        sys.exit(1)

    # 3. AI Analysis
    print('🤖 Running AI analysis...')
    for stock in stocks:
        stock['analysis'] = analyze_stock(stock)
    ai_summary = generate_summary(stocks)

    # 4. Build output
    output = {
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'generatedDate': datetime.now().strftime('%Y-%m-%d'),
        'stockCount': len(stocks),
        'stocks': stocks,
        'aiSummary': ai_summary,
    }

    # 5. Write JSON
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 5b. Save to history (timestamped snapshot)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime('%Y-%m-%d')
    history_file = HISTORY_DIR / f'{date_str}.json'
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 5c. Update history manifest
    manifest_file = HISTORY_DIR / 'manifest.json'
    existing_dates = []
    if manifest_file.exists():
        with open(manifest_file, 'r', encoding='utf-8') as f:
            existing_dates = json.load(f)
    if date_str not in existing_dates:
        existing_dates.append(date_str)
        existing_dates.sort(reverse=True)
    with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(existing_dates, f, ensure_ascii=False)

    print(f'✅ Done! Written to {OUTPUT_FILE}')
    print(f'   History: {history_file}')
    print(f'   Stocks: {len(stocks)}')
    print(f'   Summary: {ai_summary[:80]}...')


def generate_summary(stocks):
    """Generate an overall market summary."""
    gainers = [s for s in stocks if s['fiveDayPct'] > 0]
    losers = [s for s in stocks if s['fiveDayPct'] < 0]
    avg_pct = sum(s['fiveDayPct'] for s in stocks) / len(stocks)
    top_gainer = max(stocks, key=lambda s: s['fiveDayPct'])
    top_loser = min(stocks, key=lambda s: s['fiveDayPct'])

    summary = (
        f"今日追蹤 {len(stocks)} 檔熱門港股，五日整體平均{('上漲' if avg_pct > 0 else '下跌')}"
        f"{abs(avg_pct):.2f}%。"
        f"表現最佳：{top_gainer['name']}（{top_gainer['code']}）{top_gainer['fiveDayPct']:+.2f}%，"
        f"表現最弱：{top_loser['name']}（{top_loser['code']}）{top_loser['fiveDayPct']:+.2f}%。"
        f"上漲 {len(gainers)} 檔，下跌 {len(losers)} 檔。"
    )
    return summary


if __name__ == '__main__':
    main()
