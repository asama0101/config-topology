"""§10.1/§10.2 build_topology.py CLI（出力先・stdout/stderr・終了コード）のテスト。"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REBUILD_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REBUILD_ROOT / "dev" / "examples" / "configs"
CLI = REBUILD_ROOT / "scripts" / "build_topology.py"


def _run(args):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True, text=True)


def test_cli_generates_layered_yaml(tmp_path):
    out = tmp_path / "topology"
    proc = _run([str(CONFIG_DIR / "sample-ios-r1.cfg"),
                 str(CONFIG_DIR / "sample-junos-r2.conf"), "-o", str(out)])
    assert proc.returncode == 0
    for fn in ["_meta.yaml", "devices.yaml", "physical.yaml",
               "routing.bgp.yaml", "routing.ospf.yaml", "routing.static.yaml"]:
        assert (out / fn).exists()
    assert "Generated" in proc.stdout
    assert "[INFO]" in proc.stderr


def test_cli_unknown_vendor_skipped(tmp_path):
    weird = tmp_path / "weird.cfg"
    weird.write_text("foo bar\nbaz qux\n", encoding="utf-8")
    out = tmp_path / "topology"
    proc = _run([str(weird), "-o", str(out)])
    assert proc.returncode == 0
    assert "[WARN]" in proc.stderr
    assert (out / "devices.yaml").exists()
