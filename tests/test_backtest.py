from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from traderai.backtest import parse_csv, signals, simulate, validate_params
from traderai.forex import market


def candles():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{'time': (start+timedelta(hours=i)).isoformat(), 'open': 1.1, 'high': 1.1001,
             'low': 1.0999, 'close': 1.1} for i in range(60)]


class BacktestTests(unittest.TestCase):
    def run_trade(self, bars, **params):
        sig = [0]*len(bars)
        sig[49] = params.pop('direction', 1)
        with patch('traderai.backtest.signals', return_value=sig):
            return simulate('EUR/USD', bars, {'stop_pips': 10, 'spread_pips': 0, 'slippage_pips': 0, 'leverage': 30, **params})

    def test_fills_next_open_and_stop_before_target(self):
        data = candles()
        data[50].update(open=1.101, high=1.104, low=1.099, close=1.101)
        r = self.run_trade(data)
        self.assertEqual(r['trades'][0]['entry_index'], 50)
        self.assertEqual(r['trades'][0]['entry'], 1.101)
        self.assertEqual(r['trades'][0]['reason'], 'stop')
        self.assertAlmostEqual(r['metrics']['net_profit'], -100)
        self.assertAlmostEqual(r['metrics']['max_drawdown'], 1)

    def test_costs_reduce_size_and_are_subtracted(self):
        data = candles()
        data[50]['high'] = 1.103
        clean = self.run_trade(data)
        costly = self.run_trade(data, spread_pips=2, slippage_pips=1)
        self.assertLess(costly['trades'][0]['units'], clean['trades'][0]['units'])
        self.assertGreater(costly['metrics']['costs'], 0)
        self.assertLess(costly['metrics']['net_profit'], clean['metrics']['net_profit'])
        self.assertEqual(costly['metrics']['trades'], 1)

    def test_gap_fills_worse_open(self):
        data = candles()
        data[51].update(open=1.098, high=1.0981, low=1.097, close=1.098)
        result = self.run_trade(data)
        self.assertEqual(result['trades'][0]['reason'], 'gap_stop')
        self.assertEqual(result['trades'][0]['exit'], 1.098)
        self.assertAlmostEqual(result['metrics']['net_profit'], -200)

    def test_target_gap_is_known_before_intrabar_stop(self):
        data = candles()
        data[51].update(open=1.103, high=1.104, low=1.098, close=1.1)
        result = self.run_trade(data)
        self.assertEqual(result['trades'][0]['reason'], 'target')
        self.assertAlmostEqual(result['trades'][0]['exit'], 1.102)

    def test_short_target_and_end_of_data_close(self):
        data = candles()
        data[50]['low'] = 1.097
        result = self.run_trade(data, direction=-1)
        self.assertEqual(result['trades'][0]['direction'], 'SELL')
        self.assertEqual(result['trades'][0]['reason'], 'target')
        result = self.run_trade(candles())
        self.assertEqual(result['trades'][0]['reason'], 'end_of_data')
        self.assertEqual(result['metrics']['final_equity'], 10000)

    def test_signals_do_not_depend_on_future(self):
        data = market()['candles']
        for strategy in ('ema_trend', 'rsi_reversion'):
            self.assertEqual(signals(data[:80], strategy), signals(data, strategy)[:80])

    def test_leverage_caps_notional_and_small_accounts_skip(self):
        result = self.run_trade(candles(), leverage=1)
        self.assertLessEqual(result['trades'][0]['units']*1.1, 10000)
        result = self.run_trade(candles(), balance=100, risk_percent=.01)
        self.assertEqual(result['metrics']['trades'], 0)
        self.assertEqual(result['metrics']['return_percent'], 0)
        self.assertIsNone(result['metrics']['profit_factor'])

    def test_csv_validation_and_normalization(self):
        data = candles()
        text = 'time,open,high,low,close\n'+'\n'.join(','.join(str(c[k]) for k in ('time','open','high','low','close')) for c in data)
        self.assertEqual(parse_csv(text), data)
        for bad in ['time,open,high,low,close\n', text.replace('1.1001','nan'), text.replace(data[1]['time'],data[0]['time'])]:
            with self.assertRaises(ValueError): parse_csv(bad)

    def test_invalid_params_and_candles(self):
        for params in ({'risk_percent':6},{'balance':float('inf')},{'leverage':True},{'strategy':'unknown'}):
            with self.assertRaises(ValueError): validate_params(params)
        data = candles()
        data[20]['high'] = 1
        with self.assertRaises(ValueError): simulate('EUR/USD',data,{})
        data = candles()
        data[20] = None
        with self.assertRaises(ValueError): simulate('EUR/USD',data,{})
