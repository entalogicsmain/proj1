"""Model router. Roles map to (provider, model) in config; agents never name models."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .config import Config
from .costs import SpendTracker
from .db import DB
from .killswitch import KillSwitch
from .secrets_store import get_secret


@dataclass
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int


class ProviderError(RuntimeError):
    pass


def _post_json(url: str, headers: dict, body: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP {e.code}: {e.read()[:300]!r}") from e
    except urllib.error.URLError as e:
        raise ProviderError(f"network: {e.reason}") from e


class AnthropicProvider:
    URL = "https://api.anthropic.com/v1/messages"

    def complete(self, model: str, system: str, user: str, max_tokens: int, cache_system: bool) -> LLMResult:
        sys_block = [{"type": "text", "text": system}]
        if cache_system:
            sys_block[0]["cache_control"] = {"type": "ephemeral"}  # prompt caching for long fixed text
        data = _post_json(self.URL, {
            "x-api-key": get_secret("ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, {"model": model, "max_tokens": max_tokens, "system": sys_block,
            "messages": [{"role": "user", "content": user}]})
        text = "".join(b.get("text", "") for b in data.get("content", []))
        u = data.get("usage", {})
        return LLMResult(text, u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0),
                         u.get("output_tokens", 0))


class DeepSeekProvider:
    URL = "https://api.deepseek.com/chat/completions"  # OpenAI-compatible

    def complete(self, model: str, system: str, user: str, max_tokens: int, cache_system: bool) -> LLMResult:
        data = _post_json(self.URL, {
            "Authorization": f"Bearer {get_secret('DEEPSEEK_API_KEY')}",
            "content-type": "application/json",
        }, {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        u = data.get("usage", {})
        return LLMResult(data["choices"][0]["message"]["content"], u.get("prompt_tokens", 0),
                         u.get("completion_tokens", 0))


class MockProvider:
    """Offline provider. `handler(task, system, user)` returns text. Used by tests and dry runs."""

    def __init__(self, handler: Callable[[str, str, str], str] | None = None):
        self.handler = handler or default_mock_handler
        self.current_task = ""

    def complete(self, model, system, user, max_tokens, cache_system) -> LLMResult:
        text = self.handler(self.current_task, system, user)
        return LLMResult(text, max(1, len(system + user) // 4), max(1, len(text) // 4))


def default_mock_handler(task: str, system: str, user: str) -> str:
    canned = {
        "score_lead": {"score": 8, "need": "small automation script", "budget_hint": "unknown",
                       "urgency": "medium", "reason": "clear ask, in niche"},
        "draft_pitch": {"type": "pitch", "draft": "Hi, I saw your post about needing a script to clean your CSV exports. "
                        "I build small Python automations and can send a short plan today. Reply STOP to opt out.",
                        "reason": "personal line from post", "risk_flags": []},
        "judge": {"scores": {"tone": 4, "accuracy": 5, "spam_risk": 4, "over_promising": 5, "fit": 4},
                  "verdict": "pass", "fixes": [], "reason": "ok"},
        "manager": {"decision": "reject", "rule": "mock default", "terms": {}},
        "questioner": {"questions": ["Why this lead?"]},
    }
    return json.dumps(canned.get(task, {}))


class ModelRouter:
    def __init__(self, cfg: Config, db: DB, spend: SpendTracker, kill: KillSwitch,
                 providers: dict | None = None):
        self.cfg, self.db, self.spend, self.kill = cfg, db, spend, kill
        self.providers = providers or {"anthropic": AnthropicProvider(), "deepseek": DeepSeekProvider(),
                                       "mock": MockProvider()}

    def call(self, role: str, agent: str, task: str, system: str, user: str,
             max_tokens: int = 1024, cache_system: bool = True, retries: int = 2) -> str:
        self.kill.check()
        self.spend.check_before_call()
        spec = self.cfg.model(role)
        prov = self.providers[spec.provider]
        if isinstance(prov, MockProvider):
            prov.current_task = task
        last: Exception | None = None
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                res = prov.complete(spec.model, system, user, max_tokens, cache_system)
                self.spend.record(agent, task, spec.model, res.tokens_in, res.tokens_out, time.time() - t0)
                return res.text
            except ProviderError as e:
                last = e
                self.spend.record(agent, task, spec.model, 0, 0, time.time() - t0, error=str(e))
                time.sleep(min(2 ** attempt, 8) if spec.provider != "mock" else 0)
        raise ProviderError(f"{role}/{task} failed after retries: {last}")

    def call_json(self, *args, **kwargs) -> dict:
        text = self.call(*args, **kwargs)
        return parse_json(text)


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates code fences)."""
    s = text.strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < start:
        raise ProviderError(f"no JSON in model reply: {text[:120]!r}")
    try:
        return json.loads(s[start:end + 1])
    except json.JSONDecodeError as e:
        raise ProviderError(f"bad JSON from model: {e}") from e
