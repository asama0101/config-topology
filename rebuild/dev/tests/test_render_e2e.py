"""§11.3 決定性・通しパイプライン E2E（config → 層別 YAML → HTML）。"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REBUILD_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REBUILD_ROOT / "dev" / "examples" / "configs"
BUILD = REBUILD_ROOT / "scripts" / "build_topology.py"
RENDER = REBUILD_ROOT / "scripts" / "render_topology.py"


def _build(out):
    r = subprocess.run([sys.executable, str(BUILD),
                        str(CONFIG_DIR / "sample-ios-r1.cfg"),
                        str(CONFIG_DIR / "sample-junos-r2.conf"), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _render(topo_dir, out):
    r = subprocess.run([sys.executable, str(RENDER), str(topo_dir), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_full_pipeline_and_html_determinism(tmp_path):
    topo = tmp_path / "topology"
    _build(topo)
    h1 = tmp_path / "a.html"; h2 = tmp_path / "b.html"
    _render(topo, h1)
    _render(topo, h2)
    assert h1.read_bytes() == h2.read_bytes()        # §11.3 同一 YAML → バイト一致
    assert b"<!doctype html" in h1.read_bytes()[:64].lower()


def test_render_deterministic_independent_of_build(tmp_path):
    t1 = tmp_path / "t1"; t2 = tmp_path / "t2"
    _build(t1); _build(t2)
    h1 = tmp_path / "h1.html"; h2 = tmp_path / "h2.html"
    _render(t1, h1); _render(t2, h2)
    assert h1.read_bytes() == h2.read_bytes()        # パイプライン全体の決定性
