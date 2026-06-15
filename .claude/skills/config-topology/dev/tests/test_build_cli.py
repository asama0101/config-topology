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
    # CONFIG ビュー用に生 config を保持した raw_config.yaml も生成される
    assert (out / "raw_config.yaml").exists()
    raw = (out / "raw_config.yaml").read_text(encoding="utf-8")
    assert "raw_configs:" in raw and "hostname R1" in raw
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


def test_cli_emits_run_summary(tmp_path):
    weird = tmp_path / "weird.cfg"
    weird.write_text("foo bar\nbaz qux\n", encoding="utf-8")   # 未知ベンダー
    out = tmp_path / "topology"
    proc = _run([str(CONFIG_DIR / "sample-ios-r1.cfg"), str(weird), "-o", str(out)])
    assert proc.returncode == 0
    assert "[SUMMARY]" in proc.stderr
    assert "skipped (unknown vendor)" in proc.stderr
    assert "不完全" in proc.stderr                         # §10.4 注意喚起


def test_cli_retains_existing_default_output(tmp_path):
    # 既定パス運用（-o 省略）で cwd の既存 ./topology/ と ./topology.html をペア退避
    (tmp_path / "topology").mkdir()
    (tmp_path / "topology" / "devices.yaml").write_text("devices: []\n", encoding="utf-8")
    (tmp_path / "topology.html").write_text("<!doctype html>old", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), str(CONFIG_DIR / "sample-ios-r1.cfg")],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    history = tmp_path / "history"
    assert history.exists()
    snaps = list(history.iterdir())
    assert len(snaps) == 1
    assert (snaps[0] / "topology" / "devices.yaml").exists()   # 旧 YAML 退避
    assert (snaps[0] / "topology.html").exists()               # ペア HTML 退避
    assert (tmp_path / "topology" / "devices.yaml").exists()   # 新規生成
    assert "退避" in proc.stderr


def test_cli_no_retention_when_no_existing(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(CLI), str(CONFIG_DIR / "sample-ios-r1.cfg")],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "history").exists()                 # 退避対象なし


def test_cli_output_error_exits_1(tmp_path):
    # 出力先の親パスが既存ファイル → makedirs/書込が OSError → exit 1（§10.2）
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    out = blocker / "topology"          # blocker はファイルなので配下にディレクトリ作成不可
    proc = _run([str(CONFIG_DIR / "sample-ios-r1.cfg"), "-o", str(out)])
    assert proc.returncode == 1
    assert "[ERROR]" in proc.stderr
