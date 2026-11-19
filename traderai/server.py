"""Local HTTP API and bundled browser workspace. Start: python -m traderai.server."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from urllib.parse import parse_qs, urlsplit
import uuid

from .cli import DEFAULT_MODELS, KEY_NAMES, load_env
from .forex import PAIRS, INTERVALS, market, position_size, quantitative
from .providers import LLMClient
from .workflow import run_workflow
from .backtest import DEFAULTS, STRATEGIES, parse_csv, simulate, validate_params

WEB = Path(__file__).parent / 'web'


class Workspace:
    def __init__(self, db_path, env):
        self.env = env
        self.db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.slots = threading.BoundedSemaphore(2)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS research (id TEXT PRIMARY KEY, kind TEXT, created TEXT, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created TEXT, pair TEXT, status TEXT, payload TEXT)')
            for run_id, payload in db.execute("SELECT id,payload FROM runs WHERE status='running'").fetchall():
                payload = {**json.loads(payload), 'error': 'Server đã khởi động lại. Vui lòng chạy lại phân tích.'}
                db.execute("UPDATE runs SET status='failed',payload=? WHERE id=?", (json.dumps(payload), run_id))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def research_list(self, kind):
        with self.connect() as db:
            rows = db.execute('SELECT id,created,payload FROM research WHERE kind=? ORDER BY created DESC LIMIT 100', (kind,)).fetchall()
        heavy = {'candles', 'input_candles', 'equity', 'trades'}
        return [dict(id=r[0], created=r[1], **{k:v for k,v in json.loads(r[2]).items() if k not in heavy}) for r in rows]

    def research_get(self, kind, item_id):
        with self.connect() as db:
            row = db.execute('SELECT created,payload FROM research WHERE kind=? AND id=?', (kind, item_id)).fetchone()
        if not row:
            raise LookupError('Không tìm thấy dữ liệu nghiên cứu.')
        return dict(id=item_id, created=row[0], **json.loads(row[1]))

    def research_create(self, kind, body):
        pair = body.get('pair', 'EUR/USD')
        from .forex import validate_pair
        validate_pair(pair)
        if kind == 'datasets':
            candles = parse_csv(body.get('csv'))
            payload = {'name': str(body.get('name', 'Imported OHLC'))[:100], 'pair': pair, 'source': 'csv',
                       'candles': candles, 'bars': len(candles), 'start': candles[0]['time'], 'end': candles[-1]['time']}
        elif kind == 'strategies':
            payload = {'name': str(body.get('name', 'Chiến lược mới'))[:100], 'pair': pair,
                       'params': validate_params(body.get('params', {}))}
        else:
            interval, source = body.get('interval', '1h'), body.get('source', 'demo')
            if body.get('dataset_id'):
                data = self.research_get('datasets', body['dataset_id'])
                if data['pair'] != pair:
                    raise ValueError('Cặp tiền phải khớp bộ dữ liệu CSV.')
                candles, source = data['candles'], 'csv'
            else:
                candles = market(pair, interval, source, self.env)['candles']
            payload = {**simulate(pair, candles, body.get('params', {})), 'source': source,
                       'interval': interval if source != 'csv' else 'CSV', 'name': str(body.get('name', 'Backtest'))[:100]}
        item_id, created = uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('INSERT INTO research VALUES (?,?,?,?)', (item_id, kind, created, json.dumps(payload, allow_nan=False)))
        return dict(id=item_id, created=created, **payload)

    def research_delete(self, kind, item_id):
        self.research_get(kind, item_id)
        with self.connect() as db:
            db.execute('DELETE FROM research WHERE kind=? AND id=?', (kind, item_id))

    def config(self):
        return {'providers': [{'id': p, 'model': self.env.get('TRADERAI_MODEL') if self.env.get('TRADERAI_PROVIDER') == p else DEFAULT_MODELS[p],
                               'configured': bool(self.env.get(KEY_NAMES[p])) and (p != 'openai-compatible' or bool(self.env.get('TRADERAI_BASE_URL')))} for p in DEFAULT_MODELS],
                'strategies': STRATEGIES, 'backtest_defaults': DEFAULTS,
                'live_configured': bool(self.env.get('TWELVE_DATA_API_KEY')), 'pairs': list(PAIRS), 'intervals': list(INTERVALS)}

    def history(self):
        with self.connect() as db:
            return [dict(id=r[0], created=r[1], pair=r[2], status=r[3], **json.loads(r[4]))
                    for r in db.execute('SELECT * FROM runs ORDER BY created DESC LIMIT 100')]

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise LookupError('Không tìm thấy báo cáo.')
        return dict(id=row[0], created=row[1], pair=row[2], status=row[3], **json.loads(row[4]))

    def save(self, run_id, status, payload):
        with self.connect() as db:
            db.execute('UPDATE runs SET status=?, payload=? WHERE id=?', (status, json.dumps(payload, ensure_ascii=False), run_id))

    def analyze(self, body):
        pair, interval = body.get('pair', 'EUR/USD'), body.get('interval', '1h')
        mode = body.get('mode', 'quant')
        if mode not in ('quant', 'llm'):
            raise ValueError('Chế độ phân tích không hợp lệ.')
        provider = body.get('provider', 'openai')
        rounds = body.get('rounds', 1)
        if type(rounds) is not int or not 1 <= rounds <= 3:
            raise ValueError('Số vòng tranh luận phải từ 1 đến 3.')
        client = None
        if mode == 'llm':
            if provider not in DEFAULT_MODELS or not self.env.get(KEY_NAMES[provider]):
                raise ValueError('Chưa cấu hình API key cho nhà cung cấp đã chọn trong .env.')
            model = body.get('model') or (self.env.get('TRADERAI_MODEL') if self.env.get('TRADERAI_PROVIDER') == provider else None) or DEFAULT_MODELS[provider]
            base = self.env.get('TRADERAI_BASE_URL') or (self.env.get('OPENAI_BASE_URL') if provider == 'openai' else None)
            if not isinstance(model, str) or not model or len(model) > 200 or (provider == 'openai-compatible' and not base):
                raise ValueError('Cần cấu hình model và endpoint phù hợp.')
            client = LLMClient(provider, model, self.env[KEY_NAMES[provider]], base)
        evidence = body.get('evidence', {})
        if not isinstance(evidence, dict):
            raise ValueError('Dữ liệu bổ sung phải là JSON object.')
        if not self.slots.acquire(blocking=False):
            raise ValueError('Đang xử lý hai báo cáo. Vui lòng chờ hoàn tất.')
        try:
            snapshot = market(pair, interval, body.get('source', 'demo'), self.env)
            run_id = uuid.uuid4().hex
            payload = {'mode': mode, 'source': snapshot['source'], 'interval': interval, 'stage': 'Chuẩn bị dữ liệu',
                       'as_of': snapshot['as_of']}
            with self.connect() as db:
                db.execute('INSERT INTO runs VALUES (?,?,?,?,?)', (run_id, datetime.now(timezone.utc).isoformat(), pair, 'running', json.dumps(payload)))
            self.executor.submit(self._work, run_id, snapshot, payload, client, evidence, rounds)
            return {'id': run_id, 'status': 'running'}
        except Exception:
            self.slots.release()
            raise

    def _work(self, run_id, snapshot, payload, client, evidence, rounds):
        try:
            result = quantitative(snapshot)
            if client:
                data = {'asset_class': 'forex', 'language': 'Vietnamese', 'as_of': snapshot['as_of'],
                        'fundamentals': evidence.get('fundamentals'), 'sentiment': evidence.get('sentiment'),
                        'news': evidence.get('news'), 'portfolio': evidence.get('portfolio'),
                        'risk_constraints': evidence.get('risk_constraints'),
                        'technical': {'source': snapshot['source'], 'candles': snapshot['candles'], 'indicators': snapshot['indicators']}}
                def progress(stage):
                    self.save(run_id, 'running', {**payload, 'stage': stage})
                reports = run_workflow(client, snapshot['pair'], data, rounds, progress)
                result['reports'] = [{'role': r, 'content': c} for r, c in reports]
                result['decision'] = 'REVIEW'  # final decision remains in the manager's report, not inferred from free text
            self.save(run_id, 'completed', {**payload, **result, 'stage': 'Hoàn tất'})
        except Exception:
            logging.exception('Analysis failed for run %s', run_id)
            self.save(run_id, 'failed', {**payload, 'error': 'Không hoàn thành được phân tích. Kiểm tra kết nối, model và API key trên server rồi thử lại.'})
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'TraderAI'

    def respond(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(path.query).items()}
        try:
            parts = path.path.strip('/').split('/')
            if len(parts) in (2, 3) and parts[0] == 'api' and parts[1] in ('datasets', 'strategies', 'backtests'):
                return self.respond(self.server.workspace.research_get(parts[1], parts[2]) if len(parts) == 3 else self.server.workspace.research_list(parts[1]))
            if path.path == '/api/health':
                return self.respond({'status': 'ok'})
            if path.path == '/api/config':
                return self.respond(self.server.workspace.config())
            if path.path == '/api/market':
                return self.respond(market(query.get('pair', 'EUR/USD'), query.get('interval', '1h'), query.get('source', 'demo'), self.server.workspace.env))
            if path.path == '/api/watchlist':
                return self.respond([{'pair': p, **{k: s[k] for k in ('price', 'change', 'source', 'candles')}} for p in PAIRS for s in [market(p)]])
            if path.path == '/api/history':
                return self.respond(self.server.workspace.history())
            if path.path.startswith('/api/analysis/'):
                return self.respond(self.server.workspace.get(path.path.rsplit('/', 1)[-1]))
            assets = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/lab.js': ('lab.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if path.path not in assets:
                return self.respond({'error': 'Không tìm thấy tài nguyên.'}, 404)
            file, mime = assets[path.path]
            raw = (WEB / file).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)
        except ValueError as exc:
            self.respond({'error': str(exc)}, 400)
        except LookupError as exc:
            self.respond({'error': str(exc)}, 404)

    def mutation(self):
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            raise ValueError('Nguồn yêu cầu không được chấp nhận.')

    def do_POST(self):
        try:
            self.mutation()
            if self.path not in ('/api/analysis', '/api/risk', '/api/datasets', '/api/strategies', '/api/backtests'):
                return self.respond({'error': 'Không tìm thấy endpoint.'}, 404)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 524288:
                raise ValueError('Kích thước yêu cầu phải từ 1 byte đến 512 KB.')
            body = json.loads(self.rfile.read(length), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Số không hợp lệ.')))
            if not isinstance(body, dict):
                raise ValueError('Yêu cầu phải là JSON object.')
            if self.path in ('/api/datasets', '/api/strategies', '/api/backtests'):
                return self.respond(self.server.workspace.research_create(self.path.rsplit('/', 1)[-1], body), 201)
            if self.path == '/api/risk':
                result = position_size(body.get('pair'), *(body.get(k) for k in ('balance', 'risk_percent', 'entry', 'stop', 'target')))
                return self.respond(result)
            self.respond(self.server.workspace.analyze(body), 202)
        except LookupError as exc:
            self.respond({'error': str(exc)}, 404)
        except (ValueError, TypeError) as exc:
            self.respond({'error': str(exc) if isinstance(exc, ValueError) else 'Định dạng dữ liệu không hợp lệ.'}, 400)

    def do_DELETE(self):
        try:
            self.mutation()
            parts = self.path.strip('/').split('/')
            if len(parts) == 3 and parts[0] == 'api' and parts[1] in ('datasets', 'strategies', 'backtests'):
                self.server.workspace.research_delete(parts[1], parts[2])
                return self.respond({'deleted': True})
            if not self.path.startswith('/api/analysis/'):
                return self.respond({'error': 'Không tìm thấy endpoint.'}, 404)
            run_id = self.path.rsplit('/', 1)[-1]
            row = self.server.workspace.get(run_id)
            if row['status'] == 'running':
                raise ValueError('Không thể xóa báo cáo đang chạy.')
            with self.server.workspace.connect() as db:
                db.execute('DELETE FROM runs WHERE id=?', (run_id,))
            self.respond({'deleted': True})
        except ValueError as exc:
            self.respond({'error': str(exc)}, 400)
        except LookupError as exc:
            self.respond({'error': str(exc)}, 404)

    def log_message(self, fmt, *args):
        pass


def create_server(host, port, db_path, env):
    server = ThreadingHTTPServer((host, port), Handler)
    server.workspace = Workspace(db_path, env)
    return server


def main():
    parser = argparse.ArgumentParser(description='TraderAI Forex web workspace')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    env = dict(os.environ)
    load_env(Path('.env'), env)
    server = create_server(args.host, args.port, env.get('TRADERAI_DB_PATH', '.traderai/workspace.db'), env)
    print(f'TraderAI Forex listening on http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        server.workspace.executor.shutdown(wait=True)


if __name__ == '__main__':
    main()
