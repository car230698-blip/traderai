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

WEB = Path(__file__).parent / 'web'


class Workspace:
    def __init__(self, db_path, env):
        self.env = env
        self.db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.slots = threading.BoundedSemaphore(2)
        with self.connect() as db:
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

    def config(self):
        return {'providers': [{'id': p, 'model': self.env.get('TRADERAI_MODEL') if self.env.get('TRADERAI_PROVIDER') == p else DEFAULT_MODELS[p],
                               'configured': bool(self.env.get(KEY_NAMES[p])) and (p != 'openai-compatible' or bool(self.env.get('TRADERAI_BASE_URL')))} for p in DEFAULT_MODELS],
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
            assets = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
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
            if self.path not in ('/api/analysis', '/api/risk'):
                return self.respond({'error': 'Không tìm thấy endpoint.'}, 404)
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 524288:
                raise ValueError('Kích thước yêu cầu phải từ 1 byte đến 512 KB.')
            body = json.loads(self.rfile.read(length), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Số không hợp lệ.')))
            if not isinstance(body, dict):
                raise ValueError('Yêu cầu phải là JSON object.')
            if self.path == '/api/risk':
                result = position_size(body.get('pair'), *(body.get(k) for k in ('balance', 'risk_percent', 'entry', 'stop', 'target')))
                return self.respond(result)
            self.respond(self.server.workspace.analyze(body), 202)
        except (ValueError, TypeError) as exc:
            self.respond({'error': str(exc) if isinstance(exc, ValueError) else 'Định dạng dữ liệu không hợp lệ.'}, 400)

    def do_DELETE(self):
        try:
            self.mutation()
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
