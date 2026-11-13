"""Extractor plumbing, offline: parsing, transports (fake HTTP), confidence signals, budget, storage."""
import json
import math
from decimal import Decimal

import pytest

from abstention.data.sec_schema import SecField
from abstention.extraction import confidence as C
from abstention.extraction.llm_extractor import (AnthropicTransport, BudgetExceeded, CostMeter, LLMExtractor,
                                                 ModelResponse, ParsedField, RawStore, TransportError,
                                                 parse_response)

PAGE = "CONSOLIDATED BALANCE SHEETS\n(in thousands)\nTotal assets | 1,234,567\nCash | 45,210"


def _json(**over):
    f = {"field": "total_assets", "status": "found", "value": 1234567, "scale": "thousands", "page": 2,
         "quote": "Total assets | 1,234,567", "confidence": 0.97}
    f.update(over)
    rest = [{"field": x.value, "status": "absent", "value": None, "scale": "units", "page": None, "quote": "", "confidence": 0.9}
            for x in SecField if x != SecField.TOTAL_ASSETS]
    return json.dumps({"fields": [f, *rest]})


def test_parse_ok_fenced_and_garbage():
    p = parse_response("```json\n" + _json() + "\n```")
    assert p[SecField.TOTAL_ASSETS].value == Decimal(1234567) and p[SecField.TOTAL_ASSETS].scale == "thousands"
    assert p[SecField.CASH].status == "absent"
    assert all(v is None for v in parse_response("I cannot do that").values())
    assert parse_response(_json(value="abc"))[SecField.TOTAL_ASSETS] is None          # malformed field -> None
    assert parse_response(_json(confidence=1.7))[SecField.TOTAL_ASSETS].confidence is None
    assert parse_response(_json(scale="billions"))[SecField.TOTAL_ASSETS] is None


def _post_factory(responses):
    seen = []

    def post(url, headers, body, timeout):
        seen.append((url, headers, body))
        return responses.pop(0)
    return post, seen


def test_anthropic_request_never_sends_sampling_params_and_sets_effort():
    ok = (200, {"id": "msg_1", "model": "claude-fable-5-2", "content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": _json()}],
                "usage": {"input_tokens": 100, "output_tokens": 400}}, {})
    post, seen = _post_factory([ok])
    t = AnthropicTransport(api_key="k", post=post, effort="medium")
    r = t.complete("sys", "user")
    body = seen[0][2]
    assert body["model"] == "claude-fable-5-2" and body["output_config"] == {"effort": "medium"}
    for banned in ("temperature", "top_p", "top_k", "tool_choice", "thinking"):
        assert banned not in body
    assert r.usage == {"input_tokens": 100, "output_tokens": 400} and r.request_id == "msg_1"
    assert seen[0][1]["x-api-key"] == "k"


def test_retries_on_overload_then_succeeds_and_fails_on_client_error():
    ok = (200, {"content": [{"type": "text", "text": "{}"}], "usage": {}}, {})
    post, seen = _post_factory([(529, {}, {}), (429, {}, {}), ok])
    sleeps = []
    AnthropicTransport(api_key="k", post=post, sleep=sleeps.append).complete("s", "u")
    assert len(seen) == 3 and len(sleeps) == 2
    post, _ = _post_factory([(400, {"error": "bad"}, {})])
    with pytest.raises(TransportError, match="400"):
        AnthropicTransport(api_key="k", post=post).complete("s", "u")
    with pytest.raises(TransportError, match="ANTHROPIC_API_KEY"):
        AnthropicTransport(api_key="").complete("s", "u")


class FakeTransport:
    model_id = "fake-model"

    def __init__(self, texts):
        self.texts, self.n = texts, 0

    def params(self):
        return {"model": self.model_id}

    def complete(self, system, user):
        t = self.texts[self.n % len(self.texts)]
        self.n += 1
        return ModelResponse(t, {"input_tokens": 1000, "output_tokens": 500}, f"r{self.n}", self.model_id, 0.1)


def test_extractor_stores_every_call_and_enforces_budget(tmp_path):
    store = RawStore(tmp_path / "run")
    meter = CostMeter(max_usd=1.0, in_price=8.0, out_price=40.0)      # each call = $0.028
    ex = LLMExtractor(FakeTransport([_json()]), k_samples=3, store=store, meter=meter)
    out = ex.extract_filing("acc-1", [(2, PAGE)])
    assert len(out.samples) == 3
    lines = [json.loads(l) for l in store.path.read_text().splitlines()]
    assert len(lines) == 3 and {"prompt_sha256", "raw_response", "timestamp", "usage", "params"} <= set(lines[0])
    assert (tmp_path / "run" / "prompts" / f"{lines[0]['prompt_sha256']}.txt").exists()
    assert math.isclose(meter.spent_usd, 3 * (1000 / 1e6 * 8 + 500 / 1e6 * 40))
    tight = LLMExtractor(FakeTransport([_json()]), k_samples=5, meter=CostMeter(0.05, 8.0, 40.0))
    with pytest.raises(BudgetExceeded):
        tight.extract_filing("acc-2", [(2, PAGE)])


def _parsed(**kw):
    d = dict(status="found", value=Decimal(1234567), scale="thousands", page=2, quote="Total assets | 1,234,567", confidence=0.97)
    d.update(kw)
    return ParsedField(**d)


def test_signals():
    pages = {2: PAGE}
    assert C.structural(_parsed(), pages) == 1.0
    assert C.structural(_parsed(quote="Total assets | 9,999"), pages) == 0.5       # quote not on page and number not in quote; page exists and scale matches
    assert C.structural(_parsed(page=9), pages) == 0.25  # page missing: only "number appears in the quote" passes
    assert C.structural(_parsed(scale="units"), pages) == 0.75                    # scale contradicts "(in thousands)"
    assert C.structural(_parsed(status="absent", value=None), pages) is None
    s = lambda **kw: {SecField.TOTAL_ASSETS: _parsed(**kw)}
    assert C.agreement([s(), s(), s(value=Decimal(1))], SecField.TOTAL_ASSETS) == pytest.approx(2 / 3)
    assert C.agreement([s(), {SecField.TOTAL_ASSETS: None}], SecField.TOTAL_ASSETS) == 0.5
    assert C.agreement([{SecField.TOTAL_ASSETS: None}], SecField.TOTAL_ASSETS) is None
    lp = [("Total", -0.1), (" assets", -0.1), (" 1", -0.05), (",", -0.01), ("234", -0.2), (",", -0.0), ("567", -0.3), ("\n", -0.5)]
    assert C.token_prob(lp, _parsed()) == pytest.approx(math.exp(-0.05 - 0.01 - 0.2 - 0.0 - 0.3))
    assert C.token_prob(None, _parsed()) is None                                 # Fable 5.2: no logprobs
