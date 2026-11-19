"""Chronological strategy selection and reproducible holdout diagnostics.

No holdout value participates in selecting parameters. The existing simulation
engine is reused unchanged, including its fill, cost and sizing assumptions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import random
import statistics

from .backtest import ENGINE_VERSION, STRATEGIES, simulate, validate_candles, validate_params
from .forex import PAIRS, validate_pair

VALIDATION_VERSION = '1.0'
OPTIONS = {'train_percent': 70, 'min_trades': 3, 'max_drawdown': 20,
           'samples': 500, 'seed': 42}
GRID = {'strategy': [s['id'] for s in STRATEGIES], 'stop_pips': [15, 25, 40],
        'reward_risk': [1, 1.5, 2]}
WARMUP = 50


def validate_options(body):
    if not isinstance(body, dict):
        raise ValueError('Tùy chọn kiểm định phải là JSON object.')
    result = {k: body.get(k, v) for k, v in OPTIONS.items()}
    bounds = {'train_percent': (50, 80), 'min_trades': (1, 50),
              'max_drawdown': (1, 100), 'samples': (100, 1000), 'seed': (0, 2**32-1)}
    for key, (lo, hi) in bounds.items():
        val = result[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not lo <= val <= hi:
            raise ValueError(f'{key} phải nằm trong khoảng {lo}–{hi}.')
        if key != 'max_drawdown' and type(val) is not int:
            raise ValueError(f'{key} phải là số nguyên.')
    return result


def demo_history(pair='EUR/USD'):
    """Fixed synthetic hourly fixture, including weekends, never market history."""
    validate_pair(pair)
    rng = random.Random('traderai-validation-v1:' + pair)
    current = PAIRS[pair][1]
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = []
    for i in range(720):
        opened = current
        drift = (.00013, -.00009, 0, .00005)[(i // 90) % 4]
        current = opened * (1 + rng.gauss(drift, .0007))
        candles.append({'time': (start + timedelta(hours=i)).isoformat(),
                        'open': opened, 'close': current,
                        'high': max(opened, current) * (1 + rng.uniform(.0001, .0006)),
                        'low': min(opened, current) * (1 - rng.uniform(.0001, .0006))})
    return candles


def data_quality(candles):
    """Describe spacing; gaps do not prove missing data without a session calendar."""
    candles = validate_candles(candles)
    times = [datetime.fromisoformat(c['time']) for c in candles]
    steps = [(b-a).total_seconds() for a, b in zip(times, times[1:])]
    typical = statistics.median(steps)
    gaps = []
    for i, step in enumerate(steps):
        if step <= typical * 1.5:
            continue
        begin, end = times[i], times[i+1]
        weekend = step >= 7*86400 or any(
            (begin + timedelta(days=d)).weekday() >= 5
            for d in range(min(7, (end.date()-begin.date()).days) + 1))
        gaps.append({'after': begin.isoformat(), 'before': end.isoformat(),
                     'hours': round(step/3600, 2), 'includes_weekend': weekend})
    jumps = sum(abs(b['close']/a['close']-1) > .03 for a, b in zip(candles, candles[1:]))
    flat = sum(c['high'] == c['low'] for c in candles)
    weekend_bars = sum(t.weekday() >= 5 for t in times)
    return {'bars': len(candles), 'start': candles[0]['time'], 'end': candles[-1]['time'],
            'typical_interval_seconds': typical, 'gap_count': len(gaps),
            'largest_gaps': sorted(gaps, key=lambda g: g['hours'], reverse=True)[:5],
            'flat_bars': flat, 'jumps_over_3_percent': jumps, 'weekend_bars': weekend_bars,
            'note': 'Khoảng cách > 1.5 lần trung vị được đánh dấu. Chưa đối chiếu lịch phiên; không tự điền nến thiếu. Nến cuối tuần hoặc biến động > 3% cần kiểm tra nguồn.'}


def _percentile(values, fraction):
    ordered = sorted(values)
    at = (len(ordered)-1) * fraction
    lo = math.floor(at)
    hi = math.ceil(at)
    return ordered[lo] + (ordered[hi]-ordered[lo]) * (at-lo)


def bootstrap(trades, balance, samples=500, seed=42):
    """Circular block resampling of fixed USD trade P/L, not a return forecast."""
    if len(trades) < 10:
        return {'status': 'insufficient_trades', 'trades': len(trades),
                'minimum_trades': 10, 'samples': samples, 'seed': seed}
    rng = random.Random(seed)
    pnls = [t['pnl'] for t in trades]
    block = min(5, math.ceil(math.sqrt(len(pnls))))
    returns, drawdowns = [], []
    for _ in range(samples):
        equity = peak = balance
        max_dd = 0
        used = 0
        while used < len(pnls):
            start = rng.randrange(len(pnls))
            for offset in range(min(block, len(pnls)-used)):
                equity += pnls[(start+offset) % len(pnls)]
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak-equity)/peak*100)
                used += 1
        returns.append((equity/balance-1)*100)
        drawdowns.append(max_dd)
    lower, upper = min(returns), max(returns)
    width = (upper-lower)/20 if upper > lower else 1
    bins = [0]*20
    for value in returns:
        bins[min(19, int((value-lower)/width))] += 1
    return {'status': 'available', 'trades': len(trades), 'samples': samples, 'seed': seed,
            'block_length': block,
            'return_percent': {str(p): round(_percentile(returns, p/100), 2) for p in (5, 50, 95)},
            'drawdown_percent': {str(p): round(_percentile(drawdowns, p/100), 2) for p in (50, 95)},
            'sample_loss_fraction_percent': round(sum(r < 0 for r in returns)/samples*100, 2),
            'histogram': [{'from': round(lower+i*width, 4), 'to': round(lower+(i+1)*width, 4),
                           'count': count} for i, count in enumerate(bins)],
            'note': 'Lấy mẫu lại các khối P/L USD cố định từ lệnh holdout đã đóng; không tái tính lot, không mô phỏng equity nội lệnh hay margin call. Tỷ lệ mẫu lỗ không phải xác suất lỗ tương lai.'}


def _holdout(pair, candles, split, params):
    # Reinitialize indicators using exactly the 50 observations before holdout.
    # The engine cannot open a position during that prefix.
    offset = split-WARMUP
    result = simulate(pair, candles[offset:], params)
    trades = [{**t, 'entry_index': t['entry_index']+offset} for t in result['trades']]
    index = {c['time']: i for i, c in enumerate(candles)}
    exposed = sum(index[t['closed']]-t['entry_index']+1 for t in trades)
    metrics = {**result['metrics'], 'exposure_percent': round(exposed/(len(candles)-split)*100, 2)}
    return {'params': result['params'], 'metrics': metrics, 'equity': result['equity'][WARMUP:],
            'trades': trades, 'start': candles[split]['time'], 'end': candles[-1]['time'],
            'bars': len(candles)-split, 'warmup_start': candles[offset]['time'], 'warmup_bars': WARMUP}


def validate_strategy(pair, candles, params=None, options=None):
    validate_pair(pair)
    candles = validate_candles(candles)
    if len(candles) < 300:
        raise ValueError('Kiểm định cần ít nhất 300 nến. Nhập CSV dài hơn hoặc dùng mẫu mô phỏng 720 nến.')
    params = validate_params({} if params is None else params)
    opts = validate_options({} if options is None else options)
    split = len(candles)*opts['train_percent']//100
    training = candles[:split]
    candidates = []
    for strategy in GRID['strategy']:
        for stop in GRID['stop_pips']:
            for rr in GRID['reward_risk']:
                candidate = {**params, 'strategy': strategy, 'stop_pips': stop, 'reward_risk': rr}
                result = simulate(pair, training, candidate)
                m = result['metrics']
                eligible = m['trades'] >= opts['min_trades'] and m['max_drawdown'] <= opts['max_drawdown']
                candidates.append({'params': candidate, 'metrics': m, 'eligible': eligible})
    # Stable deterministic tie order; training metrics are the only ranking input.
    ranked = sorted(candidates, key=lambda c: (-c['metrics']['net_profit'], c['metrics']['max_drawdown'],
                                             c['params']['strategy'], c['params']['stop_pips'], c['params']['reward_risk']))
    eligible = [c for c in ranked if c['eligible']]
    selected = eligible[0] if eligible else None
    holdout, stress = None, []
    boot = {'status': 'not_run'}
    assessment = 'insufficient_training'
    if selected:
        holdout = _holdout(pair, candles, split, selected['params'])
        m = holdout['metrics']
        if m['trades'] < opts['min_trades']:
            assessment = 'insufficient_holdout'
        elif m['max_drawdown'] > opts['max_drawdown']:
            assessment = 'holdout_drawdown_exceeded'
        else:
            assessment = 'holdout_positive' if m['net_profit'] > 0 else 'holdout_non_positive'
        for multiplier in (1, 1.5, 2):
            p = {**selected['params'], **{k: selected['params'][k]*multiplier
                                        for k in ('spread_pips', 'slippage_pips')}}
            scenario = {'multiplier': multiplier}
            if p['spread_pips'] > 100 or p['slippage_pips'] > 100:
                scenario.update(status='unavailable', reason='Chi phí vượt giới hạn engine 100 pip mỗi loại.')
            else:
                scenario.update(status='available', metrics=(holdout if multiplier == 1 else _holdout(pair, candles, split, p))['metrics'])
            stress.append(scenario)
        boot = bootstrap(holdout['trades'], params['balance'], opts['samples'], opts['seed'])
    digest = lambda data: hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return {'validation_version': VALIDATION_VERSION, 'engine_version': ENGINE_VERSION,
            'pair': pair, 'options': opts, 'grid': GRID, 'input_candles': candles,
            'data_hash': digest(candles), 'train_data_hash': digest(training),
            'split': {'train_bars': split, 'holdout_bars': len(candles)-split,
                      'train_start': candles[0]['time'], 'train_end': candles[split-1]['time'],
                      'holdout_start': candles[split]['time'], 'holdout_end': candles[-1]['time']},
            'selection_rule': 'Lợi nhuận USD huấn luyện cao nhất sau chi phí, chỉ trong cấu hình đủ số lệnh và không vượt drawdown đã đặt. Hòa điểm: drawdown thấp hơn, rồi strategy/stop/RR tăng dần.',
            'candidates': ranked, 'selected': selected, 'holdout': holdout, 'cost_stress': stress,
            'bootstrap': boot, 'quality': data_quality(candles), 'assessment': assessment,
            'limitations': [
                '18 cấu hình cố định; thử nhiều lần trên cùng holdout sẽ làm mất tính độc lập. Chưa có kiểm định tiến cuốn chiếu.',
                'Holdout bắt đầu bằng tài khoản mới, không chuyển vị thế từ train; chỉ báo khởi tạo lại bằng 50 nến trước holdout.',
                'Chi phí stress tái tính khối lượng theo cùng ngân sách rủi ro; không chọn lại cấu hình.',
                'Dùng giả định khớp lệnh engine v1.0: không swap, commission riêng, tick hay margin call; drawdown theo close.',
                'Kết quả nghiên cứu không phải phê duyệt giao dịch của Portfolio Manager.'
            ]}


def main():
    import argparse
    from pathlib import Path
    from .backtest import DEFAULTS, parse_csv
    parser = argparse.ArgumentParser(description='TraderAI chronological forex validation / USD account')
    parser.add_argument('pair')
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--csv', type=Path)
    sources.add_argument('--demo', action='store_true', help='720 synthetic hourly bars, not market history')
    parser.add_argument('--output', type=Path)
    for key, default in OPTIONS.items():
        parser.add_argument('--'+key.replace('_', '-'), type=float if key == 'max_drawdown' else int, default=default)
    for key in ('balance', 'risk_percent', 'spread_pips', 'slippage_pips', 'leverage'):
        parser.add_argument('--'+key.replace('_', '-'), type=float, default=DEFAULTS[key])
    args = parser.parse_args()
    try:
        candles = parse_csv(args.csv.read_text(encoding='utf-8')) if args.csv else demo_history(args.pair)
        result = validate_strategy(args.pair, candles, {k: getattr(args, k) for k in
                                   ('balance', 'risk_percent', 'spread_pips', 'slippage_pips', 'leverage')},
                                   {k: getattr(args, k) for k in OPTIONS})
        result.update(source='csv' if args.csv else 'demo', name=args.csv.name if args.csv else 'Synthetic validation demo')
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
