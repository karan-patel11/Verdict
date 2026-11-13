"""Governance rule 11: resample by filing, not by field."""
import random

import pytest

from abstention.experiment.real_eval import (Dec, bootstrap_metrics, group_by_filing, metrics,
                                             paired_bootstrap, resample_filings)


def _decs(n_filings=60, fields=8, seed=0):
    """Fields inside a filing are perfectly correlated: a filing is all-wrong or all-right."""
    rng = random.Random(seed)
    out = []
    for i in range(n_filings):
        bad = int(rng.random() < 0.2)
        out += [Dec(f"f{i}", True, bad, 0.9) for _ in range(fields)]
    return out


def test_resample_keeps_every_filing_whole():
    groups = group_by_filing(_decs())
    rng = random.Random(1)
    originals = [tuple(map(id, g)) for g in groups.values()]
    for sample in (resample_filings(groups, rng) for _ in range(20)):
        assert len(sample) == len(groups)
        assert all(tuple(map(id, g)) in originals for g in sample)     # each unit is a complete filing


def test_flat_field_list_is_rejected():
    with pytest.raises(ValueError, match="filing groups"):
        resample_filings(_decs(), random.Random(0))        # a list of fields, not groups


def test_filing_level_interval_is_wider_than_naive_field_level_for_correlated_fields():
    decs = _decs()
    lo, hi = bootstrap_metrics(group_by_filing(decs), 400, 3)["marginal_miscoverage"]
    rng = random.Random(3)
    naive = sorted(metrics([rng.choice(decs) for _ in decs])["marginal_miscoverage"] for _ in range(400))
    nlo, nhi = naive[10], naive[389]
    assert (hi - lo) > 1.8 * (nhi - nlo)      # ~sqrt(8)x wider: the naive interval is overconfident


def test_paired_bootstrap_needs_the_same_filings():
    a = group_by_filing(_decs(10))
    b = group_by_filing(_decs(11))
    with pytest.raises(ValueError, match="same filings"):
        paired_bootstrap(a, b, lambda d: metrics(d)["marginal_miscoverage"], 5, 0)
