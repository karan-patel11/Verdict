"""LLM extractor for the real-filings evaluation (default model: Claude Fable 5.2).

Design notes
------------
* Pure stdlib (urllib). The transport is injectable so every code path is testable offline.
* Fable 5.2 specifics, from Anthropic's model page (platform.claude.com/docs/en/models/fable-5-2):
  model id `claude-fable-5-2`; omit temperature, top_p and top_k; forced tool use returns a 400;
  adaptive thinking is always on, so `max_tokens` must leave room for thinking. Consequences
  here: no temperature parameter is ever sent, structured output is requested as plain JSON
  text (no tool_choice), and k-sample agreement uses the model's default sampling. Token
  probabilities are not exposed by the Messages API, so that signal is None for this model.
* `output_config.effort` is the cost/quality control; it is pinned in the run manifest.
* Independence (governance rule 4): this module never imports gold_labels. It sees only
  rendered text pages plus plain-language field definitions. No XBRL tag names appear here.
* Every call is stored (RawStore): prompt hash, model, parameters, timestamp, raw response.

This does not implement `extraction.base.Extractor`: that ABC is typed to the synthetic
FieldType enum (SMB documents). The real harness feeds the decision loop through FieldInput,
which is duck-typed. Recorded as DEV-002 in DEVIATIONS.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from ..data.sec_schema import SCALES, SecField

PROMPT_VERSION = "v1"

FIELD_DEFS: dict[SecField, str] = {
    SecField.REVENUE: "Total revenue (net sales) for the current period, from the income statement.",
    SecField.OPERATING_INCOME: "Operating income or loss for the current period, from the income statement. Negative for a loss.",
    SecField.NET_INCOME: "Net income or loss for the current period attributable to the company, from the income statement. Negative for a loss.",
    SecField.DEPRECIATION_AMORTIZATION: "Depreciation and amortization from the cash-flow statement, current fiscal year-to-date column.",
    SecField.INTEREST_EXPENSE: "Interest expense for the current period, from the income statement or its notes if printed there. Report the amount as a positive number.",
    SecField.TOTAL_ASSETS: "Total assets at the end of the current period, from the balance sheet.",
    SecField.TOTAL_LIABILITIES: "Total liabilities at the end of the current period, from the balance sheet. If the balance sheet does not print a total liabilities line, report it absent.",
    SecField.CASH: "Cash and cash equivalents at the end of the current period, from the balance sheet (not restricted cash, not a cash-flow ending total that includes restricted cash).",
}

SYSTEM = (
    "You extract numbers from the primary financial statements of one SEC filing. "
    "Use only the text provided. Never use outside knowledge of the company. "
    "If a field is not printed in the text, report it as absent; do not estimate or compute it."
)

_INSTRUCTIONS = """Extract these eight fields. Period rules: for a quarterly report (10-Q), income-statement fields use the three-month column for the current quarter; depreciation and amortization uses the fiscal year-to-date column of the cash-flow statement; balance-sheet fields use the current period-end column. For an annual report (10-K), use the current fiscal year.

Fields:
{fields}

Return ONLY one JSON object, no prose, with this shape:
{{"fields": [{{"field": "<field id>", "status": "found" | "absent", "value": <number exactly as printed, negative if shown in parentheses or as a loss, null if absent>, "scale": "units" | "thousands" | "millions", "page": <page number where you read it>, "quote": "<the exact text of the table row you read it from>", "confidence": <your probability between 0 and 1 that the value is exactly right>}}]}}

The scale is what the statement header says ("in thousands", "in millions"); use "units" if none is stated. The value is the number as printed, before applying the scale. Include all eight field ids."""


@dataclass(frozen=True)
class Prompt:
    system: str
    instructions: str  # everything that is NOT the document
    document: str

    @property
    def user(self) -> str:
        return f"{self.instructions}\n\n<document>\n{self.document}\n</document>"

    @property
    def sha256(self) -> str:
        return hashlib.sha256((self.system + "\x00" + self.user).encode()).hexdigest()


def build_prompt(pages: Sequence[tuple[int, str]]) -> Prompt:
    fields = "\n".join(f"- {f.value}: {d}" for f, d in FIELD_DEFS.items())
    doc = "\n\n".join(f"=== PAGE {n} ===\n{t}" for n, t in pages)
    return Prompt(SYSTEM, _INSTRUCTIONS.format(fields=fields), doc)


@dataclass(frozen=True)
class ParsedField:
    status: str  # "found" | "absent"
    value: Decimal | None
    scale: str
    page: int | None
    quote: str
    confidence: float | None


def _to_dec(x: Any) -> Decimal | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        return Decimal(str(x).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def parse_response(text: str) -> dict[SecField, ParsedField | None]:
    """Parse the model's JSON. A field that is missing or malformed maps to None, which the
    decision loop treats as NO_CONFIDENCE_AVAILABLE (routed, never defaulted)."""
    out: dict[SecField, ParsedField | None] = {f: None for f in SecField}
    start = text.find("{")
    if start < 0:
        return out
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return out
    for item in obj.get("fields", []) if isinstance(obj, dict) else []:
        try:
            fld = SecField(item.get("field"))
        except (ValueError, AttributeError):
            continue
        status, scale = item.get("status"), item.get("scale", "units")
        if status not in ("found", "absent") or scale not in SCALES:
            continue
        val = _to_dec(item.get("value"))
        if status == "found" and val is None:
            continue
        conf = item.get("confidence")
        conf = float(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) and 0 <= conf <= 1 else None
        page = item.get("page")
        out[fld] = ParsedField(status, val if status == "found" else None, scale,
                               page if isinstance(page, int) else None,
                               str(item.get("quote") or ""), conf)
    return out


# --- transports ------------------------------------------------------------------------

@dataclass
class ModelResponse:
    text: str
    usage: dict[str, int]
    request_id: str | None
    model: str
    latency_s: float
    logprobs: list[tuple[str, float]] | None = None


class Transport(Protocol):
    model_id: str

    def params(self) -> dict[str, Any]: ...
    def complete(self, system: str, user: str) -> ModelResponse: ...


Post = Callable[[str, dict[str, str], dict[str, Any], float], tuple[int, dict[str, Any], dict[str, str]]]


def _urllib_post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read())
        except Exception:
            payload = {}
        return e.code, payload, dict(e.headers or {})


class TransportError(RuntimeError):
    pass


_RETRYABLE = {408, 429, 500, 502, 503, 504, 529}


class AnthropicTransport:
    """Messages API. Never sends temperature/top_p/top_k (Fable 5.2 rejects non-default values)."""

    def __init__(self, model: str = "claude-fable-5-2", *, effort: str | None = "medium",
                 max_tokens: int = 16000, api_key: str | None = None, timeout: float = 300.0,
                 max_retries: int = 5, post: Post = _urllib_post,
                 sleep: Callable[[float], None] = time.sleep,
                 base_url: str = "https://api.anthropic.com") -> None:
        self.model_id = model
        self.effort, self.max_tokens, self.timeout = effort, max_tokens, timeout
        self.max_retries, self._post, self._sleep, self._base = max_retries, post, sleep, base_url
        self._key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def params(self) -> dict[str, Any]:
        return {"model": self.model_id, "effort": self.effort, "max_tokens": self.max_tokens,
                "sampling": "provider default (no temperature sent)"}

    def complete(self, system: str, user: str) -> ModelResponse:
        if not self._key:
            raise TransportError("ANTHROPIC_API_KEY is not set")
        body: dict[str, Any] = {"model": self.model_id, "max_tokens": self.max_tokens,
                                "system": system, "messages": [{"role": "user", "content": user}]}
        if self.effort:
            body["output_config"] = {"effort": self.effort}
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        t0 = time.monotonic()
        for attempt in range(self.max_retries + 1):
            status, payload, hdrs = self._post(f"{self._base}/v1/messages", headers, body, self.timeout)
            if status == 200:
                text = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")
                u = payload.get("usage", {})
                return ModelResponse(text, {"input_tokens": int(u.get("input_tokens", 0)),
                                            "output_tokens": int(u.get("output_tokens", 0))},
                                     payload.get("id") or hdrs.get("request-id"), payload.get("model", self.model_id),
                                     time.monotonic() - t0)
            if status in _RETRYABLE and attempt < self.max_retries:
                self._sleep(min(60.0, 2.0 ** attempt))
                continue
            raise TransportError(f"HTTP {status}: {json.dumps(payload)[:300]}")
        raise TransportError("unreachable")


class OpenAICompatTransport:
    """For an open-weights Extractor 2 behind an OpenAI-compatible server (for example a local
    Ollama). Requests token log-probabilities. Untested against a live server in this repo:
    verify that your server returns `choices[0].logprobs.content` before relying on signal 3."""

    def __init__(self, base_url: str, model: str, *, api_key: str = "", temperature: float = 0.7,
                 max_tokens: int = 4096, timeout: float = 600.0, post: Post = _urllib_post) -> None:
        self.model_id, self._base, self._key = model, base_url.rstrip("/"), api_key
        self.temperature, self.max_tokens, self.timeout, self._post = temperature, max_tokens, timeout, post

    def params(self) -> dict[str, Any]:
        return {"model": self.model_id, "temperature": self.temperature, "max_tokens": self.max_tokens,
                "logprobs": True}

    def complete(self, system: str, user: str) -> ModelResponse:
        body = {"model": self.model_id, "temperature": self.temperature, "max_tokens": self.max_tokens,
                "logprobs": True, "top_logprobs": 1,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"content-type": "application/json"}
        if self._key:
            headers["authorization"] = f"Bearer {self._key}"
        t0 = time.monotonic()
        status, payload, _ = self._post(f"{self._base}/chat/completions", headers, body, self.timeout)
        if status != 200:
            raise TransportError(f"HTTP {status}: {json.dumps(payload)[:300]}")
        ch = payload["choices"][0]
        lp = None
        content = (ch.get("logprobs") or {}).get("content")
        if content:
            lp = [(t["token"], float(t["logprob"])) for t in content]
        u = payload.get("usage", {})
        return ModelResponse(ch["message"]["content"],
                             {"input_tokens": int(u.get("prompt_tokens", 0)),
                              "output_tokens": int(u.get("completion_tokens", 0))},
                             payload.get("id"), payload.get("model", self.model_id),
                             time.monotonic() - t0, lp)


# --- storage, budget, extractor --------------------------------------------------------

class BudgetExceeded(RuntimeError):
    pass


@dataclass
class CostMeter:
    """Hard budget cap (governance: cost gate). Prices are per million tokens and are
    pre-registered; thinking tokens are billed as output tokens and arrive in usage."""

    max_usd: float
    in_price: float
    out_price: float
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def spent_usd(self) -> float:
        return self.input_tokens / 1e6 * self.in_price + self.output_tokens / 1e6 * self.out_price

    def check(self) -> None:
        if self.spent_usd >= self.max_usd:
            raise BudgetExceeded(f"spent ${self.spent_usd:.2f} of ${self.max_usd:.2f}")

    def add(self, usage: dict[str, int]) -> None:
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)


class RawStore:
    """Append-only JSONL of every model call, plus each distinct prompt stored once by hash."""

    def __init__(self, run_dir: str | Path) -> None:
        self.dir = Path(run_dir)
        (self.dir / "prompts").mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "raw.jsonl"

    def append(self, record: dict[str, Any], prompt: Prompt) -> None:
        p = self.dir / "prompts" / f"{prompt.sha256}.txt"
        if not p.exists():
            p.write_text(f"[SYSTEM]\n{prompt.system}\n\n[USER]\n{prompt.user}")
        with self.path.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")


@dataclass
class FilingExtraction:
    filing_id: str
    extractor_id: str
    pages: dict[int, str]
    samples: list[dict[SecField, ParsedField | None]] = field(default_factory=list)
    logprobs: list[list[tuple[str, float]] | None] = field(default_factory=list)


class LLMExtractor:
    def __init__(self, transport: Transport, *, k_samples: int = 5, store: RawStore | None = None,
                 meter: CostMeter | None = None, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        if k_samples < 1:
            raise ValueError("k_samples must be >= 1")
        self.transport, self.k, self.store, self.meter, self._now = transport, k_samples, store, meter, now

    @property
    def extractor_id(self) -> str:
        return self.transport.model_id

    def extract_filing(self, filing_id: str, pages: Sequence[tuple[int, str]]) -> FilingExtraction:
        prompt = build_prompt(pages)
        out = FilingExtraction(filing_id, self.extractor_id, dict(pages))
        for i in range(self.k):
            if self.meter:
                self.meter.check()
            resp = self.transport.complete(prompt.system, prompt.user)
            if self.meter:
                self.meter.add(resp.usage)
            parsed = parse_response(resp.text)
            out.samples.append(parsed)
            out.logprobs.append(resp.logprobs)
            if self.store:
                rec_extra = {"logprobs": [[t, l] for t, l in resp.logprobs]} if resp.logprobs else {}
                self.store.append({**rec_extra,
                    "filing_id": filing_id, "sample_index": i, "prompt_sha256": prompt.sha256,
                    "prompt_version": PROMPT_VERSION, "params": self.transport.params(),
                    "model_reported": resp.model, "request_id": resp.request_id,
                    "timestamp": self._now().isoformat(), "usage": resp.usage,
                    "latency_s": round(resp.latency_s, 3), "raw_response": resp.text,
                    "parsed": {f.value: (None if p is None else {
                        "status": p.status, "value": None if p.value is None else str(p.value),
                        "scale": p.scale, "page": p.page, "confidence": p.confidence})
                        for f, p in parsed.items()},
                }, prompt)
        return out
