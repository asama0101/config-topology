"""§11.1 ゴールデン受け入れ・§11.3 決定性（附録 B.3 バイト一致）。"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REBUILD_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REBUILD_ROOT / "dev" / "examples" / "configs"
GOLDEN_DIR = REBUILD_ROOT / "dev" / "examples" / "topology"
CLI = REBUILD_ROOT / "scripts" / "build_topology.py"

GOLDEN_FILES = ["_meta.yaml", "devices.yaml", "physical.yaml",
                "routing.bgp.yaml", "routing.ospf.yaml", "routing.static.yaml"]


def _build(out_dir):
    proc = subprocess.run(
        [sys.executable, str(CLI),
         str(CONFIG_DIR / "sample-ios-r1.cfg"),
         str(CONFIG_DIR / "sample-junos-r2.conf"), "-o", str(out_dir)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return out_dir


def test_golden_byte_match(tmp_path):
    out = _build(tmp_path / "topology")
    produced = sorted(p.name for p in out.iterdir())
    assert produced == sorted(GOLDEN_FILES)
    for fn in GOLDEN_FILES:
        got = (out / fn).read_bytes()
        want = (GOLDEN_DIR / fn).read_bytes()
        assert got == want, "ゴールデン不一致: %s" % fn


def test_determinism_two_runs(tmp_path):
    a = _build(tmp_path / "a")
    b = _build(tmp_path / "b")
    for fn in GOLDEN_FILES:
        assert (a / fn).read_bytes() == (b / fn).read_bytes()
