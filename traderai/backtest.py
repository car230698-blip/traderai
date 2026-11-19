"""Causal, single-position forex simulation. USD account, close-marked equity."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from .forex import ema, validate_pair

ENGINE_VERSION = '1.0'
DEFAULTS = {'strategy': 'ema_trend', 'balance': 10000, 'risk_percent': 1,
            'stop_pips': 25, 'reward_risk': 2, 'spread_pips': 1.2,
            'slippage_pips': .3, 'leverage': 10}
STRATEGIES = [
    {'id': 'ema_trend', 'name': 'EMA Trend', 'description': 'Mua khi close > EMA20 > EMA50; bán khi close < EMA20 < EMA50.'},
    {'id': 'rsi_reversion', 'name': 'RSI Reversion', 'description': 'Mua khi RSI14 < 30; bán khi RSI14 > 70. Chờ tín hiệu từ nến đã đóng.'},
]


def validate_params(body):
    if not isinstance(body, dict):
        raise ValueError('Cấu hình phải là JSON object.')
    result = {k: body.get(k, v) for k, v in DEFAULTS.items()}
    if result['strategy'] not in [s['id'] for s in STRATEGIES]:
        raise ValueError('Chiến lược không được hỗ trợ.')
    bounds = {'balance': (100, 1e8), 'risk_percent': (.01, 5), 'stop_pips': (1, 1000),
              'reward_risk': (.1, 10), 'spread_pips': (0, 100), 'slippage_pips': (0, 100), 'leverage': (1, 100)}
    for key, (lo, hi) in bounds.items():
        val = result[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not lo <= val <= hi:
            raise ValueError(f'{key} phải nằm trong khoảng {lo}–{hi}.')
    return result


def validate_candles(candles):
    if not isinstance(candles, list) or not 60 <= len(candles) <= 3000:
        raise ValueError('Dữ liệu cần từ 60 đến 3000 nến OHLC.')
    cleaned, previous = [], None
    for row in candles:
        try:
            dt = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
            nums = {k: float(row[k]) for k in ('open', 'high', 'low', 'close')}
            if any(isinstance(row[k], bool) for k in nums) or not all(0 < v <= 1e6 for v in nums.values()):
                raise ValueError
            if nums['high'] < max(nums['open'], nums['close']) or nums['low'] > min(nums['open'], nums['close']):
                raise ValueError
            if previous is not None and dt <= previous:
                raise ValueError
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            raise ValueError('OHLC không hợp lệ: cần giá dương, high/low đúng và thời gian tăng dần, không trùng lặp.') from None
        previous = dt
        cleaned.append({'time': dt.isoformat(), **nums})
    return cleaned


def parse_csv(text):
    if not isinstance(text, str) or len(text.encode()) > 450000:
        raise ValueError('CSV tối đa 450 KB.')
    try:
        rows = list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))
        return validate_candles(rows)
    except csv.Error:
        raise ValueError('Không đọc được CSV. Cần cột time,open,high,low,close.') from None


def rsi_series(closes):
    result = [50.] * len(closes)
    gain = loss = 0
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        if i <= 14:
            gain += max(change, 0) / 14
            loss += max(-change, 0) / 14
        else:
            gain = (gain * 13 + max(change, 0)) / 14
            loss = (loss * 13 + max(-change, 0)) / 14
        if i >= 14:
            result[i] = 100 - 100 / (1 + gain/loss) if loss else (100 if gain else 50)
    return result


def signals(candles, strategy):
    closes = [c['close'] for c in candles]
    fast, slow, rsi = ema(closes, 20), ema(closes, 50), rsi_series(closes)
    result = [0] * len(closes)
    for i in range(49, len(closes)):
        if strategy == 'ema_trend':
            result[i] = 1 if closes[i] > fast[i] > slow[i] else -1 if closes[i] < fast[i] < slow[i] else 0
        else:
            result[i] = 1 if rsi[i] < 30 else -1 if rsi[i] > 70 else 0
    return result


def simulate(pair, candles, params):
    validate_pair(pair)
    candles = validate_candles(candles)
    p = validate_params(params)
    sig = signals(candles, p['strategy'])
    pip = .01 if pair.endswith('JPY') else .0001
    distance = p['stop_pips'] * pip
    cost = (p['spread_pips'] + p['slippage_pips']) * pip
    balance = p['balance']
    trades, curve = [], []
    position = None
    peak, max_dd = balance, 0
    exposure = 0

    def pnl(pos, exit_price):
        conversion = 1 if pair.endswith('/USD') else 1/exit_price
        fee = pos['units'] * cost * conversion
        return pos['direction'] * (exit_price-pos['entry']) * pos['units'] * conversion - fee, fee

    for i, c in enumerate(candles):
        # Signal from completed candle i-1, fill at candle i open.
        if i >= 50 and position is None and balance > 0 and sig[i-1]:
            direction, entry = sig[i-1], c['open']
            stop, target = entry-direction*distance, entry+direction*distance*p['reward_risk']
            if stop > 0 and target > 0:
                conversion = 1 if pair.endswith('/USD') else 1/stop
                units_risk = balance*p['risk_percent']/100 / ((distance+cost)*conversion)
                notional = entry if pair.endswith('/USD') else 1
                units = math.floor(min(units_risk, balance*p['leverage']/notional)/1000)*1000
                if units >= 1000:
                    position = {'direction': direction, 'entry': entry, 'stop': stop, 'target': target,
                                'units': units, 'opened': c['time'], 'entry_index': i}
        if position:
            exposure += 1
            pos = position
            long = pos['direction'] == 1
            stop_hit = c['low'] <= pos['stop'] if long else c['high'] >= pos['stop']
            target_hit = c['high'] >= pos['target'] if long else c['low'] <= pos['target']
            exit_price, reason = None, None
            # A stop gap fills at the worse open. Both touched: stop first.
            if (c['open'] <= pos['stop'] if long else c['open'] >= pos['stop']):
                exit_price, reason = c['open'], 'gap_stop'
            elif (c['open'] >= pos['target'] if long else c['open'] <= pos['target']):
                exit_price, reason = pos['target'], 'target'
            elif stop_hit:
                exit_price, reason = pos['stop'], 'stop'
            elif target_hit:
                exit_price, reason = pos['target'], 'target'
            elif i == len(candles)-1:
                exit_price, reason = c['close'], 'end_of_data'
            if exit_price is not None:
                net, fee = pnl(pos, exit_price)
                balance += net
                trades.append({**pos, 'direction': 'BUY' if long else 'SELL', 'closed': c['time'],
                               'exit': exit_price, 'reason': reason, 'pnl': round(net, 4), 'cost_usd': round(fee, 4),
                               'balance': round(balance, 4), 'lots': pos['units']/100000})
                position = None
        equity = balance + (pnl(position, c['close'])[0] if position else 0)
        peak = max(peak, equity)
        dd = (peak-equity)/peak*100
        max_dd = max(max_dd, dd)
        curve.append({'time': c['time'], 'equity': round(equity, 4), 'drawdown': round(dd, 4)})
    wins = [t['pnl'] for t in trades if t['pnl'] > 0]
    losses = [t['pnl'] for t in trades if t['pnl'] < 0]
    return {'engine_version': ENGINE_VERSION, 'pair': pair, 'params': p, 'input_candles': candles,
            'data_hash': hashlib.sha256(json.dumps(candles, sort_keys=True).encode()).hexdigest(),
            'start': candles[0]['time'], 'end': candles[-1]['time'], 'bars': len(candles),
            'metrics': {'final_equity': round(balance, 2), 'net_profit': round(balance-p['balance'], 2),
                        'return_percent': round((balance/p['balance']-1)*100, 2), 'max_drawdown': round(max_dd, 2),
                        'trades': len(trades), 'win_rate': round(len(wins)/len(trades)*100, 2) if trades else 0,
                        'profit_factor': round(sum(wins)/abs(sum(losses)), 2) if losses else None,
                        'costs': round(sum(t['cost_usd'] for t in trades), 2),
                        'expectancy': round((balance-p['balance'])/len(trades), 2) if trades else 0,
                        'exposure_percent': round(exposure/len(candles)*100, 2)},
            'equity': curve, 'trades': trades}


def main():
    """Run a CSV experiment without starting the web server."""
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description='TraderAI Forex backtest / USD account')
    parser.add_argument('pair')
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--strategy', choices=[s['id'] for s in STRATEGIES], default='ema_trend')
    parser.add_argument('--output', type=Path)
    for key, default in DEFAULTS.items():
        if key != 'strategy':
            parser.add_argument('--'+key.replace('_', '-'), type=float, default=default)
    args = parser.parse_args()
    try:
        params = {k: getattr(args, k) for k in DEFAULTS}
        result = simulate(args.pair, parse_csv(args.csv.read_text(encoding='utf-8')), params)
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            args.output.write_text(text, encoding='utf-8')
        else:
            print(text)
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
