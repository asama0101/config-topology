"""§10.1/§10.2 render_topology.py CLI のテスト。"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REBUILD_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REBUILD_ROOT / "dev" / "examples" / "topology"
CLI = REBUILD_ROOT / "scripts" / "render_topology.py"


def _run(args, cwd=None):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True,
                          text=True, cwd=cwd)


def test_generates_html_default_output(tmp_path):
    proc = _run([str(GOLDEN)], cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "topology.html"
    assert out.exists()
    assert out.read_text(encoding="utf-8").lstrip().lower().startswith("<!doctype html")
    assert "Generated" in proc.stdout
    assert "description" in proc.stderr or "確認" in proc.stderr   # §10.2 機密注意行


def test_explicit_output(tmp_path):
    out = tmp_path / "x.html"
    proc = _run([str(GOLDEN), "-o", str(out)])
    assert proc.returncode == 0 and out.exists()


def test_dangling_ref_exits_1(tmp_path):
    bad = tmp_path / "topo"
    bad.mkdir()
    (bad / "_meta.yaml").write_text("generated_from: []\nschema_version: '1.0'\ntitle: T\n",
                                    encoding="utf-8")
    (bad / "devices.yaml").write_text(
        "devices: []\ninterfaces:\n- {id: 'rX::Gi0', device: rX, name: Gi0, ip: null, vlan: null,"
        " description: null, shutdown: false, admin_status: up, oper_status: null, mtu: null,"
        " speed: null, duplex: null, l2_l3: null, switchport: null, encapsulation: null,"
        " source: parsed, addresses: []}\n", encoding="utf-8")
    (bad / "physical.yaml").write_text("links: []\nsegments: []\n", encoding="utf-8")
    proc = _run([str(bad)])
    assert proc.returncode == 1
    assert "rX" in proc.stderr
