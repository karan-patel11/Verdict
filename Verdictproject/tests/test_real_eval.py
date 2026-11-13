"""Replay engine end to end on synthetic stand-in observations (NOT real-data evidence).

These tests check the machinery: every cell is emitted (rule 10), metrics are exact, signals are
chosen on dev, an unfrozen primary signal is refused, and low-error runs are inconclusive.
"""
import pytest
from _real_helpers import synth_obs

from abstention.data.sec_schema import SecField
from abstention.experiment.real_eval import (METHODS, ORDERINGS, Obs, RealEvalConfig, aurc, choose_primary_signal,
                                             evaluate, metrics, order_stream, run_method, swap_stream,
                                             window_violations, with_primary)

CFG = RealEvalConfig(n_boot=8, primary_signal={"ext-a": "stated", "ext-b": "agreement"})


@pytest.fixture(scope="module")
def data():
    dev = {"ext-a": synth_obs(120, 1), "ext-b": synth_obs(120, 2)}
    test = {"ext-a": synth_obs(260, 11), "ext-b": synth_obs(260, 12)}
    # both extractors read the same filings in the test set
    test["ext-b"] = [Obs(o.filing_id.replace("f12-", "f11-"), o.filed, o.division, o.field, o.extractor_status,
                         o.true_error, o.signals, o.page_pos) for o in test["ext-b"]]
    return dev, test


def test_every_cell_is_emitted_and_none_dropped(data):
    dev, test = data
    res = evaluate(dev, test, CFG)
    assert len(res["cells"]) == res["expected_cell_count"] == 2 * len(ORDERINGS) * 2 * 2 * len(METHODS)
    keys = {(c["extractor"], c["ordering"], c["alpha"], c["audit_rate"], c["method"]) for c in res["cells"]}
    assert len(keys) == len(res["cells"])
    assert set(res["hypotheses"]) == {"H1", "H2", "H3", "H4", "H5", "H6"}
    for h in res["hypotheses"].values():
        assert h["verdict"] in {"pass", "fail", "inconclusive", "not_evaluable"}


def test_unfrozen_primary_signal_is_refused(data):
    dev, test = data
    with pytest.raises(ValueError, match="not frozen"):
        evaluate(dev, test, RealEvalConfig(n_boot=2, primary_signal={"ext-a": "stated"}))


def test_too_few_errors_marks_everything_inconclusive(data):
    dev, test = data
    cfg = RealEvalConfig(n_boot=4, min_errors=10**6, primary_signal=CFG.primary_signal)
    res = evaluate(dev, test, cfg)
    assert all(h["verdict"] == "inconclusive" for h in res["hypotheses"].values())


def test_b0_metrics_are_exact(data):
    _, test = data
    obs = order_stream(test["ext-a"], "chronological")
    decs = run_method(obs, "B0", signal="stated", alpha=0.1, cfg=CFG)
    expect = sum(o.true_error for o in obs if o.extractor_status == "found") / len(obs)
    assert metrics(decs)["marginal_miscoverage"] == pytest.approx(expect)
    assert metrics(decs)["automation_rate"] == pytest.approx(sum(o.extractor_status == "found" for o in obs) / len(obs))


def test_absent_and_unscored_fields_are_never_automated(data):
    _, test = data
    obs = order_stream(test["ext-a"], "chronological")
    for m in ("B1", "B4", "B5", "B6"):
        decs = run_method(obs, m, signal="stated", alpha=0.1, cfg=CFG)
        assert not any(d.automated for d, o in zip(decs, obs) if o.extractor_status != "found")
    none_sig = [Obs(o.filing_id, o.filed, o.division, o.field, "found", o.true_error, {"stated": None}) for o in obs[:400]]
    assert not any(d.automated for d in run_method(none_sig, "B6", signal="stated", alpha=0.1, cfg=CFG))


def test_full_gate_beats_automate_everything_on_errors(data):
    _, test = data
    obs = order_stream(test["ext-a"], "chronological")
    b0 = metrics(run_method(obs, "B0", signal="stated", alpha=0.05, cfg=CFG))
    b6 = metrics(run_method(obs, "B6", signal="stated", alpha=0.05, cfg=CFG))
    assert b6["marginal_miscoverage"] < b0["marginal_miscoverage"]
    assert 0 < b6["automation_rate"] < b0["automation_rate"]


def test_stream_orderings_are_deterministic_and_keep_filings_contiguous(data):
    _, test = data
    for ordering in ORDERINGS:
        a, b = order_stream(test["ext-a"], ordering), order_stream(test["ext-a"], ordering)
        assert a == b and len(a) == len(test["ext-a"])
        ids = [o.filing_id for o in a]
        seen, last = set(), None
        for i in ids:
            if i != last:
                assert i not in seen            # a filing never reappears after another begins
                seen.add(i)
            last = i
    chrono = [o.filed for o in order_stream(test["ext-a"], "chronological")]
    assert chrono == sorted(chrono)


def test_swap_stream_switches_extractor_at_midpoint(data):
    _, test = data
    stream, mid = swap_stream({"ext-a": test["ext-a"], "ext-b": test["ext-b"]}, "ext-a", "ext-b")
    assert 0 < mid < len(stream) and len(stream) == len(test["ext-a"])


def test_choose_primary_signal_prefers_the_informative_one():
    dev = synth_obs(200, 5, informative=True)
    sig, table = choose_primary_signal(dev)
    assert sig in ("stated", "agreement") and table["token_prob"] is None
    assert table["structural"] > table[sig]       # the random structural signal is worse


def test_aurc_and_windows():
    assert aurc([0.9, 0.8, 0.1], [0, 0, 1]) == pytest.approx(1 / 9)         # best possible: the one error ranks last
    assert aurc([0.1, 0.8, 0.9], [0, 0, 1]) > aurc([0.9, 0.8, 0.1], [0, 0, 1])
    from abstention.experiment.real_eval import Dec
    ds = [Dec("f", True, 1 if i < 30 else 0, 0.9) for i in range(400)]
    assert window_violations(ds, 200, 0.05) == [1, 0]
