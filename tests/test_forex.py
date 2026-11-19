import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from traderai.forex import market, indicators, position_size
from traderai.server import create_server, Workspace


class ForexTests(unittest.TestCase):
    def test_demo_is_deterministic_and_labelled(self):
        a, b = market(), market()
        self.assertEqual(a['price'], b['price'])
        self.assertEqual(a['source'], 'demo')
        self.assertEqual(len(a['candles']), 120)
        self.assertTrue(0 <= a['indicators']['rsi'] <= 100)
        self.assertGreater(a['indicators']['atr'], 0)
        self.assertNotEqual(a['price'], market(interval='4h')['price'])

    def test_flat_series_indicators(self):
        candles = [{'open': 1, 'high': 1, 'low': 1, 'close': 1} for _ in range(60)]
        result = indicators(candles)
        self.assertEqual(result['rsi'], 50)
        self.assertEqual(result['atr'], 0)
        self.assertEqual(result['macd'], 0)
        self.assertEqual(result['ema20'][-1], 1)

    def test_usd_quote_sizing_and_rounding(self):
        r = position_size('EUR/USD', 10000, 1, 1.1, 1.095, 1.11)
        self.assertAlmostEqual(r['lots'], .2)
        self.assertAlmostEqual(r['risk_usd'], 100)
        self.assertAlmostEqual(r['reward_risk'], 2)
        self.assertEqual(r['direction'], 'BUY')
        r = position_size('GBP/USD', 10000, 1, 1.1, 1.106, 1.088)
        self.assertLessEqual(r['risk_usd'], 100)
        self.assertEqual(r['direction'], 'SELL')

    def test_usd_base_converts_at_exit(self):
        r = position_size('USD/JPY', 10000, 1, 150, 149, 152)
        self.assertEqual(r['lots'], .14)
        self.assertAlmostEqual(r['risk_usd'], round(14000/149, 2))
        self.assertEqual(r['stop_pips'], 100)

    def test_invalid_risk_is_rejected(self):
        for value in (float('nan'), float('inf'), -1, 0, True, 10**400):
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError):
                position_size('EUR/USD', value, 1, 1.1, 1.09, 1.12)
        with self.assertRaises(ValueError):
            position_size('EUR/USD', 10000, 1, 1.1, 1.12, 1.13)

    def test_live_requires_key_and_never_falls_back(self):
        with self.assertRaises(ValueError):
            market(source='live')
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{"status":"error"}')):
            with self.assertRaises(ValueError):
                market(source='live', env={'TWELVE_DATA_API_KEY': 'secret'})

    def test_live_candle_parsing(self):
        demo = market()
        values = [{'datetime': c['time'], **{k: str(c[k]) for k in ('open','high','low','close')}} for c in reversed(demo['candles'])]
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps({'values': values}).encode())):
            data = market(source='live', env={'TWELVE_DATA_API_KEY':'secret'})
        self.assertEqual(data['source'], 'live')
        self.assertEqual(data['price'], demo['price'])


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = create_server('127.0.0.1', 0, Path(self.temp.name)/'db.sqlite', {'OPENAI_API_KEY': 'private-key'})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.workspace.executor.shutdown(wait=True)
        self.server.server_close()
        self.temp.cleanup()

    def request(self, path, body=None, method=None, origin=None):
        headers = {'Content-Type':'application/json'}
        if origin:
            headers['Origin'] = origin
        req = Request(self.base+path, data=json.dumps(body).encode() if body is not None else None,
                      headers=headers, method=method)
        with urlopen(req, timeout=5) as response:
            return response.status, json.load(response)

    def complete(self, run_id):
        for _ in range(100):
            _, run = self.request('/api/analysis/'+run_id)
            if run['status'] != 'running':
                return run
            time.sleep(.01)
        self.fail('Analysis did not complete')

    def test_quant_analysis_persistence_and_delete(self):
        status, created = self.request('/api/analysis', {'pair':'EUR/USD'})
        self.assertEqual(status, 202)
        run = self.complete(created['id'])
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(len(run['reports']), 9)
        self.assertEqual(run['decision'], 'HOLD')
        self.assertEqual(self.request('/api/history')[1][0]['id'], created['id'])
        self.request('/api/analysis/'+created['id'], method='DELETE')
        self.assertEqual(self.request('/api/history')[1], [])

    def test_llm_pipeline_receives_forex_context(self):
        calls = []
        def complete(client, system, user):
            calls.append(user)
            return 'Báo cáo thử nghiệm'
        with patch('traderai.providers.LLMClient.complete', complete):
            _, created = self.request('/api/analysis', {'pair':'USD/JPY','mode':'llm','provider':'openai'})
            run = self.complete(created['id'])
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['decision'], 'REVIEW')
        self.assertEqual(len(calls), 9)
        self.assertIn('monetary policy', calls[0])
        self.assertIn('Vietnamese', calls[0])
        self.assertIn('demo', calls[2])

    def test_research_artifacts_and_data_provenance(self):
        status, strategy = self.request('/api/strategies', {'name':'Test EMA', 'pair':'EUR/USD', 'params':{}})
        self.assertEqual(status, 201)
        self.assertEqual(self.request('/api/strategies')[1][0]['id'], strategy['id'])
        status, result = self.request('/api/backtests', {'pair':'EUR/USD','source':'demo','params':{}})
        self.assertEqual(status, 201)
        self.assertEqual(result['source'], 'demo')
        self.assertEqual(len(result['data_hash']), 64)
        self.assertEqual(len(result['input_candles']), 120)
        self.assertNotIn('input_candles', self.request('/api/backtests')[1][0])
        self.assertEqual(self.request('/api/backtests/'+result['id'])[1]['metrics'], result['metrics'])
        with self.assertRaises(HTTPError) as error:
            self.request('/api/backtests', {'dataset_id':'missing'})
        self.assertEqual(error.exception.code, 404)
        error.exception.close()
        self.request('/api/backtests/'+result['id'], method='DELETE')
        self.assertEqual(self.request('/api/backtests')[1], [])

    def test_csv_import_and_snapshot_survives_dataset_delete(self):
        bars = market()['candles']
        csv = 'time,open,high,low,close\n'+'\n'.join(','.join(str(c[k]) for k in ('time','open','high','low','close')) for c in bars)
        _, dataset = self.request('/api/datasets', {'pair':'EUR/USD','name':'Imported','csv':csv})
        _, result = self.request('/api/backtests', {'pair':'EUR/USD','dataset_id':dataset['id']})
        self.assertEqual(result['source'], 'csv')
        with self.assertRaises(HTTPError) as error:
            self.request('/api/backtests', {'pair':'USD/JPY','dataset_id':dataset['id']})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        self.request('/api/datasets/'+dataset['id'], method='DELETE')
        self.assertEqual(len(self.request('/api/backtests/'+result['id'])[1]['input_candles']),120)

    def test_configuration_hides_secrets(self):
        _, config = self.request('/api/config')
        self.assertNotIn('private-key', json.dumps(config))
        self.assertTrue(config['providers'][0]['configured'])

    def test_cross_origin_and_invalid_data_rejected(self):
        for path, data, origin in [('/api/analysis', {}, 'https://untrusted.test'),
                                    ('/api/analysis', {'pair':'NOT/FX'}, None),
                                    ('/api/analysis', {'mode':'llm','provider':'gemini'}, None),
                                    ('/api/risk', {'pair':'EUR/USD'}, None)]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                self.request(path, data, origin=origin)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.request('/.env')
        self.assertEqual(error.exception.code, 404)
        error.exception.close()

    def test_static_assets_and_risk_api(self):
        with urlopen(self.base+'/') as response:
            self.assertIn('Forex Intelligence', response.read().decode())
            self.assertIn("script-src 'self'", response.headers['Content-Security-Policy'])
        _, result = self.request('/api/risk', {'pair':'EUR/USD','balance':10000,'risk_percent':1,'entry':1.1,'stop':1.095,'target':1.11})
        self.assertEqual(result['lots'], .2)
