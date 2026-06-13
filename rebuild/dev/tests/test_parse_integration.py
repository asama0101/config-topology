"""§附録 B / §10: 統合 — サンプル config が正しい正規化モデルになり CLI が JSON を出す。"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from lib.inputs import collect_inputs
from lib.parsers import parse_config

pytestmark = pytest.mark.integration

REBUILD_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REBUILD_ROOT / "dev" / "examples" / "configs"
CLI = REBUILD_ROOT / "scripts" / "parse_configs.py"


def test_full_pipeline_models():
    files = collect_inputs([str(CONFIG_DIR / "sample-ios-r1.cfg"),
                            str(CONFIG_DIR / "sample-junos-r2.conf")])
    assert [Path(f).name for f in files] == ["sample-ios-r1.cfg", "sample-junos-r2.conf"]

    devs = [parse_config(Path(f).read_text(encoding="utf-8")) for f in files]
    r1, r2 = devs
    assert r1.hostname == "R1" and r1.vendor == "cisco_ios" and r1.as_ == 65001
    assert r2.hostname == "R2" and r2.vendor == "juniper_junos" and r2.as_ == 65002
    gi0 = r1.interfaces[0]
    assert gi0.derived_ip() == "10.0.0.1/30"
    ge0 = r2.interfaces[0]
    assert ge0.derived_ip() == "10.0.0.2/30"


def test_cli_outputs_json_to_stdout():
    proc = subprocess.run(
        [sys.executable, str(CLI),
         str(CONFIG_DIR / "sample-ios-r1.cfg"),
         str(CONFIG_DIR / "sample-junos-r2.conf")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["hostname"] == "R1" and data[0]["vendor"] == "cisco_ios"
    assert data[0]["as"] == 65001
    assert data[1]["hostname"] == "R2"
    assert "[INFO]" in proc.stderr or "cisco_ios" in proc.stderr


def test_cli_skips_unknown_vendor_with_warning(tmp_path):
    unknown = tmp_path / "weird.cfg"
    unknown.write_text("foo bar\nbaz qux\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), str(unknown)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == []
    assert "[WARN]" in proc.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root はパーミッションを無視するため検証不能")
def test_cli_unreadable_file_exits_1(tmp_path):
    f = tmp_path / "secret.cfg"
    f.write_text("hostname X\n", encoding="utf-8")
    os.chmod(f, 0)  # 読み取り不可
    try:
        proc = subprocess.run(
            [sys.executable, str(CLI), str(f)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 1            # §10.2 入出力エラー → exit 1
        assert "[ERROR]" in proc.stderr
    finally:
        os.chmod(f, stat.S_IRUSR | stat.S_IWUSR)  # cleanup できるよう戻す
