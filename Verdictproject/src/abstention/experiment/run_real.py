"""Command-line driver for the real-filings evaluation.

    # 0. build the corpus on your machine (see data/edgar_corpus.py), freeze, then:
    python -m abstention.experiment.run_real extract --split dev  --run-id dev-fable  --model claude-fable-5-2
    python -m abstention.experiment.run_real choose-signal --run runs/dev-fable
    #    ... write the chosen signal into configs/real_eval.yaml, fill PREREG.md, tag prereg-v1 ...
    python -m abstention.experiment.run_real extract --split test --run-id test-fable --model claude-fable-5-2
    python -m abstention.experiment.run_real evaluate --dev claude-fable-5-2=runs/dev-fable \\
                                                      --test claude-fable-5-2=runs/test-fable

`extract --split test` goes through experiment.lockbox.open_test_set and refuses unless the
governance rules hold. `evaluate` never calls a model: it replays stored raw outputs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Mapping

from ..data import gold_labels as gl
from ..data.sec_schema import SecField
from ..extraction.llm_extractor import (AnthropicTransport, CostMeter, LLMExtractor,
                                        OpenAICompatTransport, RawStore)
from .lockbox import open_test_set
from .real_eval import Obs, build_observations, choose_primary_signal, evaluate, load_config, load_extractions

DEFAULT_CUTOFFS = {"claude-fable-5-2": "2026-07-01"}  # reliable knowledge cutoff Jun 2026 (Anthropic model page)


def _gold(corpus: Path, accession: str) -> dict[SecField, gl.GoldValue]:
    raw = json.loads((corpus / "labels" / f"{accession}.json").read_text())
    return {SecField(f): gl.GoldValue(SecField(f), gl.GoldStatus(v["status"]),
                                      None if v["value"] is None else __import__("decimal").Decimal(v["value"]),
                                      v["tag"], "", v["detail"]) for f, v in raw.items()}


def observations(run_dir: str | Path, corpus: str | Path, manifest: Mapping, split: str) -> list[Obs]:
    corpus = Path(corpus)
    exs = load_extractions(run_dir, corpus)
    out: list[Obs] = []
    for e in manifest["entries"]:
        if e["split"] == split and e["accession"] in exs:
            out += build_observations(exs[e["accession"]], _gold(corpus, e["accession"]),
                                      filed=e["filed"], division=e["division"])
    return out


def _transport(a: argparse.Namespace):
    if a.openai_base_url:
        return OpenAICompatTransport(a.openai_base_url, a.model, temperature=a.temperature)
    return AnthropicTransport(a.model, effort=a.effort or None, max_tokens=a.max_tokens)


def cmd_extract(a: argparse.Namespace) -> None:  # pragma: no cover - needs API access
    repo, corpus = Path(a.repo), Path(a.corpus)
    manifest = json.loads(Path(a.manifest).read_text())
    cutoffs = dict(DEFAULT_CUTOFFS)
    for kv in a.cutoff or []:
        k, v = kv.split("=")
        cutoffs[k] = v
    if a.split == "test":
        entries = open_test_set(repo=repo, manifest_path=a.manifest, corpus_dir=corpus,
                                extractor_id=a.model, knowledge_cutoffs=cutoffs,
                                override_reason=a.override_reason)
    else:
        entries = [e for e in manifest["entries"] if e["split"] == "dev"]
    run = repo / "runs" / a.run_id
    store = RawStore(run)
    done = {json.loads(l)["filing_id"] for l in store.path.read_text().splitlines()} if store.path.exists() else set()
    meter = CostMeter(a.max_usd, a.in_price, a.out_price)
    ex = LLMExtractor(_transport(a), k_samples=a.k, store=store, meter=meter)
    for e in entries[: a.limit or None]:
        if e["accession"] in done:
            continue
        pages = [(int(n), t) for n, t in json.loads((corpus / "inputs" / f"{e['accession']}.json").read_text())["pages"]]
        ex.extract_filing(e["accession"], pages)
        print(f"{e['accession']} spent ${meter.spent_usd:.2f}")
    (run / "meter.json").write_text(json.dumps({"input_tokens": meter.input_tokens,
                                                "output_tokens": meter.output_tokens, "usd": meter.spent_usd}))


def cmd_choose(a: argparse.Namespace) -> None:
    manifest = json.loads(Path(a.manifest).read_text())
    sig, table = choose_primary_signal(observations(a.run, a.corpus, manifest, "dev"))
    print(json.dumps({"primary": sig, "dev_aurc": table}, indent=1))


def cmd_evaluate(a: argparse.Namespace) -> None:
    manifest = json.loads(Path(a.manifest).read_text())
    pair = lambda xs: dict(x.split("=", 1) for x in xs)
    dev = {k: observations(v, a.corpus, manifest, "dev") for k, v in pair(a.dev).items()}
    test = {k: observations(v, a.corpus, manifest, "test") for k, v in pair(a.test).items()}
    res = evaluate(dev, test, load_config(a.config))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1, sort_keys=True, default=str))
    print(json.dumps(res["hypotheses"], indent=1, default=str))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--manifest", default="corpus/manifest.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--split", choices=("dev", "test"), required=True)
    e.add_argument("--run-id", required=True)
    e.add_argument("--model", default="claude-fable-5-2")
    e.add_argument("--effort", default="medium", help="output_config.effort (low|medium|high|xhigh|max); '' to omit")
    e.add_argument("--max-tokens", type=int, default=16000)
    e.add_argument("--k", type=int, default=5)
    e.add_argument("--max-usd", type=float, required=True, help="hard budget cap, pre-registered")
    e.add_argument("--in-price", type=float, default=8.0, help="USD per million input tokens (Fable 5.2: 8)")
    e.add_argument("--out-price", type=float, default=40.0, help="USD per million output tokens (Fable 5.2: 40)")
    e.add_argument("--limit", type=int, default=0, help="first N filings only (use 10 for the cost pilot)")
    e.add_argument("--cutoff", action="append", help="MODEL=YYYY-MM-DD knowledge cutoff (repeat)")
    e.add_argument("--override-reason")
    e.add_argument("--openai-base-url")
    e.add_argument("--temperature", type=float, default=0.7)
    e.set_defaults(fn=cmd_extract)
    c = sub.add_parser("choose-signal")
    c.add_argument("--run", required=True)
    c.set_defaults(fn=cmd_choose)
    v = sub.add_parser("evaluate")
    v.add_argument("--dev", nargs="+", required=True, help="EXTRACTOR=run_dir")
    v.add_argument("--test", nargs="+", required=True, help="EXTRACTOR=run_dir")
    v.add_argument("--config", default="configs/real_eval.yaml")
    v.add_argument("--out", default="report/real_eval_results.json")
    v.set_defaults(fn=cmd_evaluate)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":  # pragma: no cover
    main()
