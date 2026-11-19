"""Forex market snapshots, technical indicators and USD-account risk sizing."""
from __future__ import annotations
import hashlib
import json
import math
import random
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

PAIRS = {
    'EUR/USD': ('Euro / US Dollar', 1.0842), 'GBP/USD': ('British Pound / US Dollar', 1.2716),
    'USD/JPY': ('US Dollar / Japanese Yen', 151.72), 'AUD/USD': ('Australian Dollar / US Dollar', .6584),
    'USD/CHF': ('US Dollar / Swiss Franc', .8835), 'USD/CAD': ('US Dollar / Canadian Dollar', 1.3652),
}
INTERVALS = {'15min': 15, '1h': 60, '4h': 240, '1day': 1440}


def validate_pair(pair, interval='1h'):
    if pair not in PAIRS or interval not in INTERVALS:
        raise ValueError('Cặp tiền hoặc khung thời gian không được hỗ trợ.')


def ema(values, period):
    result = [values[0]]
    for value in values[1:]:
        result.append(value * 2 / (period + 1) + result[-1] * (1 - 2 / (period + 1)))
    return result


def indicators(candles):
    closes = [c['close'] for c in candles]
    changes = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(c, 0) for c in changes[:14]) / 14
    loss = sum(max(-c, 0) for c in changes[:14]) / 14
    for change in changes[14:]:
        gain = (gain * 13 + max(change, 0)) / 14
        loss = (loss * 13 + max(-change, 0)) / 14
    rsi = 100 - 100 / (1 + gain / loss) if loss else (100 if gain else 50)
    tr = [max(c['high'] - c['low'], abs(c['high'] - candles[i-1]['close']),
              abs(c['low'] - candles[i-1]['close'])) for i, c in enumerate(candles) if i]
    atr = sum(tr[:14]) / 14
    for value in tr[14:]:
        atr = (atr * 13 + value) / 14
    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [a-b for a, b in zip(fast, slow)]
    return {'ema20': ema(closes, 20), 'ema50': ema(closes, 50), 'rsi': round(rsi, 2),
            'atr': atr, 'macd': macd[-1], 'macd_signal': ema(macd, 9)[-1],
            'support': min(c['low'] for c in candles[-20:]),
            'resistance': max(c['high'] for c in candles[-20:])}


def market(pair='EUR/USD', interval='1h', source='demo', env=None):
    validate_pair(pair, interval)
    if source not in ('demo', 'live'):
        raise ValueError('Nguồn dữ liệu không hợp lệ.')
    env = env or {}
    if source == 'live':
        key = env.get('TWELVE_DATA_API_KEY')
        if not key:
            raise ValueError('Thêm TWELVE_DATA_API_KEY vào .env để kết nối dữ liệu thị trường.')
        query = urllib.parse.urlencode({'symbol': pair, 'interval': interval, 'outputsize': 120, 'timezone': 'UTC', 'apikey': key})
        try:
            with urllib.request.urlopen('https://api.twelvedata.com/time_series?' + query, timeout=20) as response:
                body = json.load(response)
            candles = [{'time': row['datetime'], **{k: float(row[k]) for k in ('open', 'high', 'low', 'close')}}
                       for row in reversed(body['values'])]
            if len(candles) < 50 or any(not all(math.isfinite(c[k]) and c[k] > 0 for k in ('open', 'high', 'low', 'close'))
                                       or c['high'] < max(c['open'], c['close']) or c['low'] > min(c['open'], c['close']) for c in candles):
                raise ValueError('invalid candles')
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError('Không tải được dữ liệu Twelve Data. Kiểm tra API key, quyền truy cập forex và giới hạn lượt gọi.') from None
    else:
        rng = random.Random(int(hashlib.sha256((pair + interval).encode()).hexdigest()[:8], 16))
        price = PAIRS[pair][1]
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        candles = []
        for i in range(120):
            opened = price
            price = max(.01, price * (1 + rng.gauss(.00004, .00065)))
            candles.append({'time': (end - timedelta(minutes=INTERVALS[interval] * (119-i))).isoformat(),
                            'open': opened, 'close': price, 'high': max(opened, price) * (1 + rng.uniform(.0001, .0005)),
                            'low': min(opened, price) * (1 - rng.uniform(.0001, .0005))})
    latest = candles[-1]['close']
    return {'pair': pair, 'name': PAIRS[pair][0], 'interval': interval, 'source': source,
            'as_of': candles[-1]['time'], 'price': latest,
            'change': (latest / candles[-2]['close'] - 1) * 100,
            'period_change': (latest / candles[0]['open'] - 1) * 100,
            'candles': candles, 'indicators': indicators(candles)}


def position_size(pair, balance, risk_percent, entry, stop, target):
    validate_pair(pair)
    values = [balance, risk_percent, entry, stop, target]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1e12 for v in values):
        raise ValueError('Các giá trị phải là số dương hữu hạn.')
    if risk_percent > 5:
        raise ValueError('Mức rủi ro tối đa cho phép là 5%.')
    if stop == entry or (target - entry) * (stop - entry) >= 0:
        raise ValueError('Stop loss và take profit phải nằm ở hai phía của giá vào lệnh.')
    # USD quote: P/L in USD directly. USD base: convert quote P/L at stop.
    conversion = 1 if pair.endswith('/USD') else 1 / stop
    risk_usd = balance * risk_percent / 100
    units = risk_usd / (abs(entry - stop) * conversion)
    if not math.isfinite(units) or units > 1e12:
        raise ValueError('Khối lượng vượt giới hạn tính toán. Kiểm tra lại giá và số dư.')
    lots = math.floor(units / 1000 + 1e-9) / 100  # round down to broker micro-lot increments
    actual_risk = lots * 100000 * abs(entry - stop) * conversion
    reward_conversion = 1 if pair.endswith('/USD') else 1 / target
    reward = lots * 100000 * abs(target - entry) * reward_conversion
    return {'lots': lots, 'units': round(lots * 100000), 'risk_usd': round(actual_risk, 2),
            'risk_budget_usd': round(risk_usd, 2), 'reward_usd': round(reward, 2),
            'reward_risk': round(reward / actual_risk, 2) if actual_risk else 0,
            'stop_pips': round(abs(entry-stop) / (.01 if pair.endswith('JPY') else .0001), 1),
            'direction': 'BUY' if target > entry else 'SELL', 'account_currency': 'USD'}


def quantitative(snapshot):
    ind, price = snapshot['indicators'], snapshot['price']
    bullish = price > ind['ema20'][-1] > ind['ema50'][-1]
    bearish = price < ind['ema20'][-1] < ind['ema50'][-1]
    bias = 'bullish' if bullish else 'bearish' if bearish else 'neutral'
    trend = {'bullish': 'Tăng', 'bearish': 'Giảm', 'neutral': 'Đi ngang'}[bias]
    precision = 3 if snapshot['pair'].endswith('JPY') else 5
    f = lambda v: f'{v:.{precision}f}'
    reports = [
        ('Fundamentals analyst', 'Chưa có dữ liệu lãi suất, lạm phát hoặc chính sách ngân hàng trung ương của hai đồng tiền. Cần bổ sung nguồn vĩ mô trước khi hình thành luận điểm cơ bản.'),
        ('Sentiment analyst', 'Chưa kết nối dữ liệu COT hoặc nguồn tâm lý thị trường. Không suy diễn tâm lý từ biến động giá.'),
        ('Technical analyst', f"Xu hướng {trend.lower()}. Giá {f(price)}; EMA20 {f(ind['ema20'][-1])}; EMA50 {f(ind['ema50'][-1])}. RSI(14) {ind['rsi']:.1f}; ATR(14) {f(ind['atr'])}. Hỗ trợ {f(ind['support'])}, kháng cự {f(ind['resistance'])}."),
        ('News analyst', 'Chưa kết nối nguồn tin tức và lịch kinh tế trực tiếp. Lịch minh họa trên dashboard không được dùng làm bằng chứng phân tích.'),
        ('Bullish researcher (round 1)', f"Luận điểm tăng: giá cần duy trì trên {f(ind['ema20'][-1])} và phá vùng {f(ind['resistance'])}. EMA và RSI chỉ mô tả lịch sử, chưa xác nhận diễn biến tiếp theo."),
        ('Bearish researcher (round 1)', f"Phản biện: mất vùng {f(ind['support'])} làm suy yếu kịch bản tăng. Thiếu bằng chứng vĩ mô và tâm lý; tín hiệu kỹ thuật có thể đảo chiều."),
        ('Trader', 'HOLD — quan sát. Chưa đủ bằng chứng vĩ mô và tin tức để đưa ra kế hoạch giao dịch hoàn chỉnh. Các mức trên biểu đồ chỉ là vùng tham chiếu.'),
        ('Risk manager', 'Chưa đánh giá được spread, trượt giá, tương quan vị thế và rủi ro sự kiện. Dùng công cụ khối lượng với tài khoản USD để kiểm tra mức lỗ dự kiến; không bao gồm phí và gap.'),
        ('Portfolio manager', 'REVISE — yêu cầu bổ sung dữ liệu vĩ mô, tin tức và danh mục. Chưa phê duyệt kế hoạch giao dịch.'),
    ]
    return {'bias': bias, 'trend': trend, 'decision': 'HOLD', 'reports': [{'role': role, 'content': content} for role, content in reports]}
