# rebuild/dev/tests/test_history.py
"""§10.3 history 退避（旧成果物の自動退避）のテスト。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # rebuild/
from lib.history import (  # noqa: E402
    current_timestamp,
    retain_for_build,
    retain_for_render,
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


def _seed_topo_dir(d):
    d.mkdir(parents=True)
    (d / "devices.yaml").write_text("devices: []\n", encoding="utf-8")


def test_retain_build_moves_existing_yaml(tmp_path):
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    history = tmp_path / "history"
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert dest == history / "2026-06-14_1530"
    assert (dest / "topology" / "devices.yaml").exists()
    assert not out.exists()                       # 元ディレクトリは移動済み


def test_retain_build_none_when_empty(tmp_path):
    out = tmp_path / "topology"                    # 存在しない
    history = tmp_path / "history"
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert dest is None
    assert not history.exists()                    # 退避不要なら history も作らない


def test_retain_build_pairs_html_into_same_dir(tmp_path):
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_build(out, html, "2026-06-14_1530", history_root=history)
    assert (dest / "topology" / "devices.yaml").exists()
    assert (dest / "topology.html").exists()       # 同一退避ディレクトリへペア退避
    assert not html.exists()


def test_retain_build_html_only_when_pair_given(tmp_path):
    # html_pair=None（非既定パス相当）のとき既存 HTML を巻き込まない
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert (dest / "topology").exists()
    assert html.exists()                           # HTML は退避されず残る


def test_retain_build_html_not_moved_when_no_yaml(tmp_path):
    # output_dir に YAML が無い + html_pair 実在 → ペア前提が崩れるので退避しない
    out = tmp_path / "topology"           # 作成しない（YAML なし）
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_build(out, html, "2026-06-14_1530", history_root=history)
    assert dest is None
    assert html.exists()                  # HTML は退避されず残る
    assert not history.exists()           # history も作られない


def test_retain_build_collision_suffix(tmp_path):
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    history = tmp_path / "history"
    (history / "2026-06-14_1530").mkdir(parents=True)   # 既存退避ディレクトリ
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert dest == history / "2026-06-14_1530_2"


def test_retain_render_moves_existing_html(tmp_path):
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>old", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_render(html, "2026-06-14_1530", history_root=history)
    assert dest == history / "2026-06-14_1530"
    assert (dest / "topology.html").read_text(encoding="utf-8") == "<!doctype html>old"
    assert not html.exists()


def test_retain_render_none_when_absent(tmp_path):
    html = tmp_path / "topology.html"              # 存在しない
    history = tmp_path / "history"
    dest = retain_for_render(html, "2026-06-14_1530", history_root=history)
    assert dest is None
    assert not history.exists()
