from copy import deepcopy
from datetime import datetime, timedelta
import unittest

from traderai.backtest import simulate
from traderai.validation import (bootstrap, data_quality, demo_history,
                                validate_options, validate_strategy)


class ValidationTests(unittest.TestCase):
    def test_selection_cannot_observe_future_holdout_prices(self):
        candles = demo_history()
        original = validate_strategy('EUR/USD', candles, options={'samples': 100})
        changed = deepcopy(candles)
        split = original['split']['train_bars']
        for i in range(split, len(changed)):
            for key in ('open', 'high', 'low', 'close'):
                changed[i][key] *= 1.1 + (i-split)/10000
        future = validate_strategy('EUR/USD', changed, options={'samples': 100})
        self.assertEqual(original['selected'], future['selected'])
        self.assertEqual(original['candidates'], future['candidates'])
        self.assertEqual(original['train_data_hash'], future['train_data_hash'])
        self.assertNotEqual(original['data_hash'], future['data_hash'])
        self.assertNotEqual(original['holdout']['metrics'], future['holdout']['metrics'])

    def test_holdout_has_no_carried_position_or_warmup_trades(self):
        candles = demo_history('USD/JPY')
        result = validate_strategy('USD/JPY', candles, options={'train_percent': 80, 'samples': 100})
        split = result['split']['train_bars']
        held = result['holdout']
        reference = simulate('USD/JPY', candles[split-50:], result['selected']['params'])
        self.assertEqual(len(held['equity']), len(candles)-split)
        self.assertEqual(held['start'], candles[split]['time'])
        self.assertEqual(held['warmup_start'], candles[split-50]['time'])
        self.assertEqual(held['equity'], reference['equity'][50:])
        self.assertEqual(held['metrics']['net_profit'], reference['metrics']['net_profit'])
        self.assertTrue(held['trades'])
        for trade in held['trades']:
            self.assertGreaterEqual(trade['entry_index'], split)
            self.assertGreaterEqual(trade['opened'], held['start'])
            self.assertLessEqual(trade['closed'], held['end'])
        self.assertEqual(result['cost_stress'][0]['metrics'], held['metrics'])
        self.assertTrue(0 <= held['metrics']['exposure_percent'] <= 100)

    def test_grid_selection_uses_profit_only_after_prespecified_gates(self):
        result = validate_strategy('EUR/USD', demo_history(), {'risk_percent': .7, 'balance': 20000},
                                   {'samples': 100, 'max_drawdown': 3})
        self.assertEqual(len(result['candidates']), 18)
        eligible = [c for c in result['candidates'] if c['eligible']]
        self.assertTrue(eligible)
        self.assertEqual(result['selected']['metrics']['net_profit'], max(c['metrics']['net_profit'] for c in eligible))
        for candidate in result['candidates']:
            self.assertEqual(candidate['params']['risk_percent'], .7)
            self.assertEqual(candidate['params']['balance'], 20000)
            self.assertEqual(candidate['eligible'], candidate['metrics']['trades'] >= 3 and candidate['metrics']['max_drawdown'] <= 3)

    def test_flat_input_produces_no_winner_or_fabricated_statistics(self):
        candles = demo_history()[:300]
        for c in candles:
            c.update(open=1, high=1, low=1, close=1)
        result = validate_strategy('EUR/USD', candles, options={'train_percent': 80, 'samples': 100})
        self.assertIsNone(result['selected'])
        self.assertIsNone(result['holdout'])
        self.assertEqual(result['assessment'], 'insufficient_training')
        self.assertEqual(result['cost_stress'], [])
        self.assertEqual(result['bootstrap']['status'], 'not_run')
        self.assertEqual(result['split']['holdout_bars'], 60)

    def test_block_bootstrap_known_distribution_and_small_sample(self):
        r = bootstrap([{'pnl': 10}]*10, 10000, 100, 0)
        self.assertEqual(r['return_percent'], {'5': 1, '50': 1, '95': 1})
        self.assertEqual(r['drawdown_percent'], {'50': 0, '95': 0})
        self.assertEqual(r['sample_loss_fraction_percent'], 0)
        self.assertEqual(sum(h['count'] for h in r['histogram']), 100)
        losses = bootstrap([{'pnl': -10}]*10, 10000, 100, 0)
        self.assertEqual(losses['drawdown_percent']['95'], 1)
        self.assertEqual(losses['sample_loss_fraction_percent'], 100)
        small = bootstrap([{'pnl': 1}]*9, 10000)
        self.assertEqual(small['status'], 'insufficient_trades')
        self.assertNotIn('return_percent', small)
        trades = [{'pnl': n} for n in (100, -120, 30, -10, 5, 200, -60, 45, -20, 150, 12)]
        self.assertEqual(bootstrap(trades, 10000, 100, 42), bootstrap(trades, 10000, 100, 42))
        self.assertNotEqual(bootstrap(trades, 10000, 100, 42), bootstrap(trades, 10000, 100, 43))

    def test_quality_flags_gaps_and_flat_bars_without_filling(self):
        candles = demo_history()[:300]
        for c in candles[200:]:
            c['time'] = (datetime.fromisoformat(c['time'])+timedelta(hours=48)).isoformat()
        candles[0].update(open=1.08, high=1.08, low=1.08, close=1.08)
        quality = data_quality(candles)
        self.assertEqual(quality['bars'], 300)
        self.assertEqual(quality['flat_bars'], 1)
        self.assertEqual(quality['typical_interval_seconds'], 3600)
        self.assertEqual(quality['gap_count'], 1)
        self.assertEqual(quality['largest_gaps'][0]['hours'], 49)
        self.assertTrue(quality['largest_gaps'][0]['includes_weekend'])
        self.assertEqual(len(candles), 300)

    def test_options_and_short_inputs_rejected(self):
        for opts in ({'samples': 99}, {'samples': 1001}, {'seed': True}, {'min_trades': 3.5},
                     {'train_percent': 49}, {'train_percent': 81}, {'max_drawdown': float('nan')}, []):
            with self.subTest(options=opts), self.assertRaises(ValueError):
                validate_options(opts)
        with self.assertRaises(ValueError):
            validate_strategy('EUR/USD', demo_history()[:299])
        with self.assertRaises(ValueError):
            validate_strategy('EUR/USD', demo_history(), options=[])

    def test_synthetic_history_is_explicitly_reproducible(self):
        self.assertEqual(demo_history(), demo_history())
        self.assertEqual(len(demo_history()), 720)
        self.assertNotEqual(demo_history()[0]['close'], demo_history('GBP/USD')[0]['close'])
        self.assertEqual(demo_history()[0]['time'], '2025-01-01T00:00:00+00:00')


if __name__ == '__main__':
    unittest.main()
