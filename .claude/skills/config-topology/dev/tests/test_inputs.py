"""§2.2 入力ファイル収集: 拡張子・名前順・重複排除・dir/glob・workspace 既定。"""
import os

import pytest

from lib.inputs import collect_inputs

pytestmark = pytest.mark.unit


def _touch(p, text="x"):
    p.write_text(text, encoding="utf-8")


def test_collect_explicit_files_sorted_by_name(tmp_path):
    b = tmp_path / "b.cfg"; _touch(b)
    a = tmp_path / "a.cfg"; _touch(a)
    result = collect_inputs([str(b), str(a)])
    assert [os.path.basename(p) for p in result] == ["a.cfg", "b.cfg"]


def test_collect_directory_filters_by_extension(tmp_path):
    _touch(tmp_path / "r1.cfg")
    _touch(tmp_path / "r2.conf")
    _touch(tmp_path / "r3.txt")
    _touch(tmp_path / "ignore.log")
    _touch(tmp_path / "notes.md")
    result = collect_inputs([str(tmp_path)])
    assert [os.path.basename(p) for p in result] == ["r1.cfg", "r2.conf", "r3.txt"]


def test_collect_dedupes_same_path(tmp_path):
    f = tmp_path / "r1.cfg"; _touch(f)
    result = collect_inputs([str(f), str(f)])
    assert len(result) == 1


def test_collect_glob(tmp_path):
    _touch(tmp_path / "r1.cfg")
    _touch(tmp_path / "r2.cfg")
    _touch(tmp_path / "x.txt")
    result = collect_inputs([str(tmp_path / "*.cfg")])
    assert [os.path.basename(p) for p in result] == ["r1.cfg", "r2.cfg"]


def test_collect_default_workspace(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"; ws.mkdir()
    _touch(ws / "r1.cfg")
    monkeypatch.chdir(tmp_path)
    result = collect_inputs([])
    assert [os.path.basename(p) for p in result] == ["r1.cfg"]


def test_collect_missing_workspace_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert collect_inputs([]) == []
