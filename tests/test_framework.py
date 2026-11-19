import contextlib
import io
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from traderai.cli import load_env, main
from traderai.providers import LLMClient, ProviderError
from traderai.workflow import run_workflow


class FakeClient:
    def __init__(self):
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return f"response {len(self.calls)}"


class WorkflowTests(unittest.TestCase):
    def test_debate_and_reviews_receive_prior_work(self):
        client = FakeClient()
        data = {"fundamentals": {"revenue": 10}, "sentiment": {"posts": 5},
                "technical": {"closes": [1, 2]}, "news": ["event"],
                "portfolio": {"cash": 100}, "risk_constraints": {"max": 5}}
        results = run_workflow(client, "XYZ", data, rounds=2)
        self.assertEqual(len(results), 11)
        self.assertEqual([label for label, _ in results][-3:], ["Trader", "Risk manager", "Portfolio manager"])
        self.assertIn('"revenue": 10', client.calls[0][1])
        self.assertNotIn('"posts": 5', client.calls[0][1])
        self.assertIn('response 5', client.calls[5][1])  # bear sees bull
        self.assertIn('response 6', client.calls[6][1])  # next bull sees bear
        self.assertIn('response 9', client.calls[9][1])  # risk sees trader
        self.assertIn('response 10', client.calls[10][1])  # manager sees risk
        self.assertIn('"max": 5', client.calls[10][1])

    def test_invalid_rounds(self):
        with self.assertRaises(ValueError):
            run_workflow(FakeClient(), "XYZ", {}, 0)


class ProviderTests(unittest.TestCase):
    def test_provider_request_and_response_shapes(self):
        responses = {
            "openai": {"choices": [{"message": {"content": "openai response"}}]},
            "openai-compatible": {"choices": [{"message": {"content": "compatible response"}}]},
            "anthropic": {"content": [{"type": "text", "text": "anthropic response"}]},
            "gemini": {"candidates": [{"content": {"parts": [{"text": "gemini response"}]}}]},
        }
        for provider, response in responses.items():
            with self.subTest(provider=provider):
                captured = []
                def open_url(request, timeout):
                    captured.append(request)
                    return io.BytesIO(json.dumps(response).encode())
                with patch("urllib.request.urlopen", side_effect=open_url):
                    result = LLMClient(provider, "test-model", "secret", "https://example.test/v1").complete("system", "user")
                self.assertIn("response", result)
                request = captured[0]
                body = json.loads(request.data)
                self.assertEqual(request.get_method(), "POST")
                if provider in ("openai", "openai-compatible"):
                    self.assertTrue(request.full_url.endswith("/chat/completions"))
                    self.assertEqual(body["messages"][0]["content"], "system")
                    self.assertEqual(request.get_header("Authorization"), "Bearer secret")
                elif provider == "anthropic":
                    self.assertTrue(request.full_url.endswith("/messages"))
                    self.assertEqual(body["system"], "system")
                    self.assertEqual(request.get_header("X-api-key"), "secret")
                else:
                    self.assertTrue(request.full_url.endswith("/models/test-model:generateContent"))
                    self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "system")
                    self.assertEqual(request.get_header("X-goog-api-key"), "secret")

    def test_unexpected_response_does_not_expose_provider_body(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"error":"secret"}')):
            with self.assertRaises(ProviderError) as error:
                LLMClient("openai", "model", "secret").complete("s", "u")
        self.assertNotIn("secret", str(error.exception))


class CLITests(unittest.TestCase):
    def test_env_file_and_process_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text('export KEY="value with spaces"\nKEEP=file\nEMPTY=\n', encoding="utf-8")
            env = {"KEEP": "process"}
            load_env(path, env)
            self.assertEqual(env, {"KEY": "value with spaces", "KEEP": "process", "EMPTY": ""})

    def test_cli_with_local_compatible_server(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                body = json.dumps({"choices": [{"message": {"content": f"report {len(requests)}"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                data = Path(tmp) / "data.json"
                output = Path(tmp) / "report.md"
                data.write_text('{"ticker":"XYZ","fundamentals":{"revenue":10}}', encoding="utf-8")
                env = {"TRADERAI_API_KEY": "test", "TRADERAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1"}
                with patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(io.StringIO()):
                    result = main(["XYZ", "--data", str(data), "--provider", "openai-compatible", "--model", "test", "--output", str(output)])
                self.assertEqual(result, 0)
                self.assertEqual(len(requests), 9)
                self.assertEqual(requests[0][0], "/v1/chat/completions")
                self.assertIn("## Portfolio manager\n\nreport 9", output.read_text(encoding="utf-8"))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_ticker_mismatch_does_not_call_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data.json"
            data.write_text('{"ticker":"ABC"}', encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=True), patch.object(LLMClient, "complete") as complete, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["XYZ", "--data", str(data)]), 1)
            complete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
