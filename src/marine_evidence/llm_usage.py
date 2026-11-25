"""Request-local Responses API usage and estimated standard text charges in USD.
No prompt, answer, API key or provider ID is stored. SDK retries are opaque.
"""
from __future__ import annotations
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from pathlib import Path
from typing import Any

TOKEN_FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_tokens')
PRICE_FIELDS = ('input', 'cached_input', 'output')
ROLES = ('planner', 'generator')
RESPONSE_STATUSES = ('completed', 'incomplete', 'failed', 'cancelled', 'queued', 'in_progress', 'request_error', 'unknown')


def load_prices() -> dict:
    configured = os.getenv('MARINE_LLM_PRICES_PATH')
    path = Path(configured or 'config/llm_prices.json')
    if not configured and not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding='utf-8'), parse_float=Decimal, parse_int=Decimal)
    if not isinstance(raw, dict):
        raise ValueError('LLM price catalog must be a JSON object')
    for model, rates in raw.items():
        if (not model or not isinstance(rates, dict) or set(rates) != set(PRICE_FIELDS)
                or any(not isinstance(v, Decimal) or not v.is_finite() or v < 0 for v in rates.values())):
            raise ValueError('Invalid LLM price catalog entry')
    return raw


def _field(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _count(obj: Any, name: str) -> int | None:
    value = _field(obj, name)
    return value if type(value) is int and value >= 0 else None


class UsageLedger:
    def __init__(self, prices: dict):
        self.prices = prices
        self.calls: list[dict] = []

    def record(self, role: str, requested_model: str, response: Any = None) -> None:
        usage = _field(response, 'usage')
        inp = _count(usage, 'input_tokens')
        out = _count(usage, 'output_tokens')
        cached = _count(_field(usage, 'input_tokens_details'), 'cached_tokens')
        reasoning = _count(_field(usage, 'output_tokens_details'), 'reasoning_tokens')
        if inp is None or (cached is not None and cached > inp):
            cached = None
        if out is None or (reasoning is not None and reasoning > out):
            reasoning = None
        model = _field(response, 'model')
        tier = _field(response, 'service_tier')
        status = _field(response, 'status')
        # Price the returned model, not an unverified alias. Only standard pricing.
        # No tier is requested by this app; absent tier is assumed standard.
        rates = self.prices.get(model) if isinstance(model, str) else None
        cost = None
        if rates is not None and tier in (None, 'default') and None not in (inp, cached, out):
            cost = ((inp - cached) * rates['input'] + cached * rates['cached_input']
                    + out * rates['output']) / Decimal(1_000_000)
        self.calls.append(dict(role=role, requested_model=requested_model,
                               model=model if isinstance(model, str) else None,
                               response_status=status if status in RESPONSE_STATUSES[:-2] else ('request_error' if response is None else 'unknown'),
                               service_tier=tier if isinstance(tier, str) else None,
                               input_tokens=inp, cached_input_tokens=cached,
                               output_tokens=out, reasoning_tokens=reasoning,
                               estimated_cost_usd=cost,
                               pricing_usd_per_million={k: float(v) for k, v in rates.items()} if cost is not None else None))

    def summary(self) -> dict:
        known = sum((c['estimated_cost_usd'] for c in self.calls if c['estimated_cost_usd'] is not None), Decimal(0))
        unpriced = sum(c['estimated_cost_usd'] is None for c in self.calls)
        result = {'llm_calls': len(self.calls), 'unpriced_calls': unpriced,
                  'known_cost_usd': float(known), 'estimated_cost_usd': None if unpriced else float(known),
                  'calls': [{**c, 'estimated_cost_usd': None if c['estimated_cost_usd'] is None else float(c['estimated_cost_usd'])} for c in self.calls]}
        for field in TOKEN_FIELDS:
            result[field] = (None if any(c[field] is None for c in self.calls)
                             else sum(c[field] for c in self.calls))
        result['total_tokens'] = (None if result['input_tokens'] is None or result['output_tokens'] is None
                                  else result['input_tokens'] + result['output_tokens'])
        return result


_current: ContextVar[UsageLedger | None] = ContextVar('marine_llm_usage', default=None)


@contextmanager
def usage_scope(prices: dict):
    ledger = UsageLedger(prices)
    token = _current.set(ledger)
    try:
        yield ledger
    finally:
        _current.reset(token)


def tracked_create(client: Any, role: str, **kwargs: Any) -> Any:
    """Count one logical SDK call, even if it fails or returns incomplete output."""
    ledger = _current.get()
    try:
        response = client.responses.create(**kwargs)
    except Exception:
        if ledger is not None:
            ledger.record(role, kwargs['model'])
        raise
    if ledger is not None:
        ledger.record(role, kwargs['model'], response)
    return response
