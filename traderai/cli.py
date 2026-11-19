"""Command-line interface and environment configuration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sys

from .providers import LLMClient, ProviderError
from .workflow import run_workflow

DEFAULT_MODELS = {"openai": "gpt-4o-mini", "gemini": "gemini-2.5-flash",
                  "anthropic": "claude-sonnet-4-5", "openai-compatible": None}
KEY_NAMES = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
             "anthropic": "ANTHROPIC_API_KEY", "openai-compatible": "TRADERAI_API_KEY"}


def load_env(path: Path, environ: dict[str, str]) -> None:
    """Load simple KEY=value entries; existing process environment always wins."""
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"Invalid environment entry on line {number} of {path}.")
        try:
            parts = shlex.split(value.strip(), comments=True)
        except ValueError:
            raise ValueError(f"Invalid quoted value on line {number} of {path}.") from None
        if len(parts) > 1:
            raise ValueError(f"Quote values containing spaces on line {number} of {path}.")
        environ.setdefault(name, parts[0] if parts else "")


def positive_int(value: str) -> int:
    try:
        number = int(value)
        if number < 1:
            raise ValueError
        return number
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run a team of AI agents on supplied trading research data.")
    p.add_argument("ticker", help="Instrument to analyze, e.g. AAPL")
    p.add_argument("--data", required=True, type=Path, help="JSON file with research and portfolio data")
    p.add_argument("--provider", choices=DEFAULT_MODELS, help="LLM provider (or TRADERAI_PROVIDER)")
    p.add_argument("--model", help="Model name (or TRADERAI_MODEL)")
    p.add_argument("--env-file", type=Path, default=Path(".env"), help="Environment file (default: .env)")
    p.add_argument("--rounds", type=positive_int, default=1, help="Bull/bear debate rounds (default: 1)")
    p.add_argument("--output", type=Path, help="Write the complete report to this file")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        env = dict(os.environ)
        load_env(args.env_file, env)
        provider = args.provider or env.get("TRADERAI_PROVIDER") or "openai"
        if provider not in DEFAULT_MODELS:
            raise ValueError(f"Unknown provider {provider!r}; choose one of {', '.join(DEFAULT_MODELS)}.")
        model = args.model or env.get("TRADERAI_MODEL") or DEFAULT_MODELS[provider]
        if not model:
            raise ValueError("Specify a model with --model or TRADERAI_MODEL.")
        api_key = env.get(KEY_NAMES[provider], "")
        if not api_key:
            raise ValueError(f"Set {KEY_NAMES[provider]} in your environment or {args.env_file}.")
        base_url = env.get("TRADERAI_BASE_URL") or (env.get("OPENAI_BASE_URL") if provider == "openai" else None)
        if provider == "openai-compatible" and not base_url:
            raise ValueError("Set TRADERAI_BASE_URL for an OpenAI-compatible provider.")
        data = json.loads(args.data.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("The data file must contain a JSON object.")
        if data.get("ticker") and str(data["ticker"]).upper() != args.ticker.upper():
            raise ValueError("The data file ticker does not match the requested ticker.")
        client = LLMClient(provider, model, api_key, base_url)
        results = run_workflow(client, args.ticker.upper(), data, args.rounds,
                               lambda stage: print(f"Running {stage}...", file=sys.stderr))
        report = f"# Trading research: {args.ticker.upper()}\n\n" + "\n\n".join(
            f"## {name}\n\n{response}" for name, response in results) + "\n"
        if args.output:
            args.output.write_text(report, encoding="utf-8")
            print(f"Report written to {args.output}", file=sys.stderr)
        else:
            print(report, end="")
        return 0
    except (ValueError, OSError, ProviderError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
