"""
Stock AI Analysis Module
Uses rule-based + heuristic analysis to generate stock insights.
Can be extended to use LLM API calls.
"""
from datetime import datetime


def analyze_stock(stock: dict) -> dict:
    """
    Generate AI-style analysis for a single stock.

    Args:
        stock: dict with keys: code, symbol, name, prices, fiveDayPct,
               high5, low5, avgVolume, volTrend

    Returns:
        dict with keys: signal, summary, trend, volumeSignal, support, resistance
    """
    prices = stock.get('prices', [])
    if not prices:
        return _empty_analysis()

    last = prices[-1]['close']
    first = prices[0]['close']
    pct = stock.get('fiveDayPct', 0)
    high = stock.get('high5', last)
    low = stock.get('low5', last)

    # Trend detection
    trend = _detect_trend(prices)

    # Support / Resistance
    support = round(low * 1.02, 2)
    resistance = round(high * 0.98, 2)

    # Volume signal
    vol_signal = _volume_signal(prices)

    # Overall signal (simplified heuristic)
    signal = _generate_signal(pct, trend, vol_signal)

    # Summary text
    summary = _generate_summary(stock, trend, pct, vol_signal)

    return {
        'signal': signal,
        'summary': summary,
        'trend': trend,
        'volumeSignal': vol_signal,
        'support': support,
        'resistance': resistance,
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }


def _empty_analysis():
    return {
        'signal': 'neutral', 'summary': '暂无数据',
        'trend': 'neutral', 'volumeSignal': 'neutral',
        'support': 0, 'resistance': 0,
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }


def _detect_trend(prices):
    """Detect short-term trend from 5-day prices."""
    if len(prices) < 3:
        return 'neutral'
    closes = [p['close'] for p in prices]
    # Simple linear slope
    n = len(closes)
    mid = n // 2
    first_half_avg = sum(closes[:mid]) / mid
    second_half_avg = sum(closes[mid:]) / (n - mid)
    if second_half_avg > first_half_avg * 1.02:
        return 'uptrend'
    elif second_half_avg < first_half_avg * 0.98:
        return 'downtrend'
    return 'sideways'


def _volume_signal(prices):
    """Detect if volume is increasing or decreasing."""
    if len(prices) < 3:
        return 'neutral'
    vols = [p['volume'] for p in prices]
    recent_avg = sum(vols[-2:]) / 2
    older_avg = sum(vols[:-2]) / max(len(vols) - 2, 1)
    if recent_avg > older_avg * 1.3:
        return 'volume surge'
    elif recent_avg < older_avg * 0.7:
        return 'volume decline'
    return 'stable'


def _generate_signal(pct, trend, vol_signal):
    """Generate overall buy/hold/sell signal."""
    if pct > 5 and trend == 'uptrend' and vol_signal == 'volume surge':
        return 'strong buy'
    elif pct > 2 and trend == 'uptrend':
        return 'buy'
    elif pct > 0 and vol_signal == 'volume surge':
        return 'buy'
    elif pct < -5 and trend == 'downtrend' and vol_signal == 'volume surge':
        return 'strong sell'
    elif pct < -3:
        return 'sell'
    elif pct < -1:
        return 'watch'
    return 'hold'


def _generate_summary(stock, trend, pct, vol_signal):
    """Generate Chinese summary text."""
    name = stock.get('name', stock.get('code', ''))
    code = stock.get('code', '')
    trend_map = {'uptrend': '上升', 'downtrend': '下跌', 'sideways': '震盪', 'neutral': '中性'}
    trend_cn = trend_map.get(trend, '震盪')
    signal_map = {
        'strong buy': '強烈買入', 'buy': '買入', 'hold': '持有',
        'watch': '觀望', 'sell': '賣出', 'strong sell': '強烈賣出',
    }
    signal_cn = signal_map.get(_generate_signal(pct, trend, vol_signal), '持有')

    vol_cn = {'volume surge': '成交量放大', 'volume decline': '成交量萎縮', 'stable': '成交量穩定'}.get(vol_signal, '')

    parts = [
        f"{name}（{code}）五日走勢{trend_cn}，累積變動{pct:+.2f}%。"
    ]
    if vol_cn:
        parts.append(vol_cn + '。')
    parts.append(f"技術信號：{signal_cn}。")

    return ''.join(parts)