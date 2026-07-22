"""Bridge: run the front-end engine tests (`node --test`) and syntax-check every classic
script from pytest, so one `pytest` run covers both sides of the graph contract. Skipped
cleanly when Node is not installed."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_graph_engine_node_suite():
    tests = sorted(str(p) for p in (FRONTEND / "tests").glob("*.test.mjs"))
    assert tests, "no front-end test files found"
    proc = subprocess.run(
        [NODE, "--test", *tests],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"node --test failed:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("script", sorted(p.name for p in (FRONTEND / "assets").glob("*.js")))
def test_assets_parse(script):
    proc = subprocess.run(
        [NODE, "--check", str(FRONTEND / "assets" / script)],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
