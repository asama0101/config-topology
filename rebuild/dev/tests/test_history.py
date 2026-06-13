# rebuild/dev/tests/test_history.py
"""§10.3 history 退避（旧成果物の自動退避）のテスト。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # rebuild/
from lib.history import (  # noqa: E402
    current_timestamp,
    unique_history_dir,
)

pytestmark = pytest.mark.integration


def test_current_timestamp_format():
    ts = current_timestamp()
    # YYYY-MM-DD_HHMM の固定幅（例: 2026-06-14_1530）
    assert len(ts) == len("2026-06-14_1530")
    assert ts[4] == "-" and ts[7] == "-" and ts[10] == "_"
    assert ts.replace("-", "").replace("_", "").isdigit()


def test_unique_history_dir_no_collision(tmp_path):
    got = unique_history_dir(tmp_path, "2026-06-14_1530")
    assert got == tmp_path / "2026-06-14_1530"


def test_unique_history_dir_collision_suffix(tmp_path):
    (tmp_path / "2026-06-14_1530").mkdir()
    (tmp_path / "2026-06-14_1530_2").mkdir()
    got = unique_history_dir(tmp_path, "2026-06-14_1530")
    assert got == tmp_path / "2026-06-14_1530_3"
