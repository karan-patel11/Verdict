"""Governance rule 3 (frozen corpus) plus the SEC client rules and the company-level split."""
import json

import pytest
from _real_helpers import make_corpus

from abstention.data.edgar_corpus import (Candidate, RateLimiter, SecClient, facts_for_accession,
                                          parse_form_index, primary_document_url, sic_division,
                                          split_by_company, verify_manifest)


def test_clean_corpus_verifies_and_any_tamper_is_caught(tmp_path):
    corpus, _ = make_corpus(tmp_path)
    assert verify_manifest(corpus / "manifest.json", corpus) == []
    f = next((corpus / "labels").iterdir())
    f.write_text('{"x": 1}')
    assert any("hash mismatch" in p for p in verify_manifest(corpus / "manifest.json", corpus))
    f.unlink()
    assert any("missing labels" in p for p in verify_manifest(corpus / "manifest.json", corpus))


def test_editing_a_manifest_entry_breaks_the_corpus_hash(tmp_path):
    corpus, _ = make_corpus(tmp_path)
    m = json.loads((corpus / "manifest.json").read_text())
    m["entries"][0]["filed"] = "2030-01-01"
    (corpus / "manifest.json").write_text(json.dumps(m))
    assert "corpus_hash does not match entries" in verify_manifest(corpus / "manifest.json", corpus)


def test_client_requires_declared_user_agent_and_caches(tmp_path):
    with pytest.raises(ValueError, match="User-Agent"):
        SecClient("anonymous", tmp_path)
    calls = []
    c = SecClient("Karan Patel karan@example.com", tmp_path, fetch=lambda u, h: calls.append((u, h)) or b"{}",
                  limiter=RateLimiter(1000))
    c.get("https://data.sec.gov/x")
    c.get("https://data.sec.gov/x")
    assert len(calls) == 1 and calls[0][1]["User-Agent"].endswith("karan@example.com")


def test_rate_limiter_never_exceeds_configured_rate():
    t = [0.0]
    sleeps = []
    lim = RateLimiter(8, clock=lambda: t[0], sleep=lambda s: (sleeps.append(s), t.__setitem__(0, t[0] + s)))
    stamps = []
    for _ in range(50):
        lim.wait()
        stamps.append(t[0])
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert min(gaps) >= 1 / 8 - 1e-9          # <= 8 requests per second, under the SEC's 10


FORM_IDX = """Description:           Master Index of EDGAR Dissemination Feed by Form Type
Last Data Received:    September 30, 2026

Form Type   Company Name                                                  CIK         Date Filed  File Name
---------------------------------------------------------------------------------------------------------------
10-Q        ACME CORP                                                     1000001     2026-08-05  edgar/data/1000001/0001000001-26-000010.txt
10-K        BETA INC                                                      1000002     2026-06-20  edgar/data/1000002/0001000002-26-000003.txt
8-K         GAMMA LLC                                                     1000003     2026-08-06  edgar/data/1000003/0001000003-26-000001.txt
10-Q        DELTA CO                                                      1000004     2026-09-10  edgar/data/1000004/0001000004-26-000044.txt
"""


def test_form_index_parsing_filters_form_and_date():
    got = parse_form_index(FORM_IDX, min_filed="2026-07-01")
    assert [(c.cik, c.accession) for c in got] == [(1000001, "0001000001-26-000010"), (1000004, "0001000004-26-000044")]


def test_split_is_by_company_deterministic_and_capped():
    cands = [Candidate(cik, f"C{cik}", "10-Q", f"2026-0{8 + k % 3}-1{k}", f"{cik:010d}-26-00000{k}")
             for cik in range(1, 81) for k in range(3)]
    div = {cik: "DGHI"[cik % 4] for cik in range(1, 81)}
    a = split_by_company(cands, div, seed=7, n_dev=20, n_test=60)
    b = split_by_company(cands, div, seed=7, n_dev=20, n_test=60)
    assert a == b
    test_ciks, dev_ciks = {c.cik for c in a["test"]}, {c.cik for c in a["dev"]}
    assert not test_ciks & dev_ciks                      # no company on both sides
    assert len(a["test"]) == 60 and len(a["dev"]) == 20
    assert max(sum(1 for c in a["test"] if c.cik == k) for k in test_ciks) <= 2
    assert len({div[k] for k in test_ciks}) == 4          # stratified across divisions


def test_submissions_and_companyfacts_shapes():
    sub = {"cik": "1000001", "filings": {"recent": {"accessionNumber": ["0001000001-26-000010"],
           "primaryDocument": ["acme-20260630.htm"], "reportDate": ["2026-06-30"], "form": ["10-Q"]}}}
    url, rd, form = primary_document_url(sub, "0001000001-26-000010")
    assert url == "https://www.sec.gov/Archives/edgar/data/1000001/000100000126000010/acme-20260630.htm"
    assert (rd, form) == ("2026-06-30", "10-Q")
    cf = {"facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"end": "2026-06-30", "val": 5, "accn": "0001000001-26-000010"},
        {"end": "2025-12-31", "val": 4, "accn": "0001000001-26-000001"}]}}}}}
    facts = facts_for_accession(cf, "0001000001-26-000010")
    assert len(facts) == 1 and facts[0]["tag"] == "Assets" and facts[0]["instant"] == "2026-06-30"


def test_sic_division():
    assert [sic_division(x) for x in (1311, 2834, 3571, 4813, 5812, 6021, 7372, None)] == ["B", "D", "D", "E", "G", "H", "I", "?"]
