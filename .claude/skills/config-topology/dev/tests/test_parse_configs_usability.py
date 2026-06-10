"""
parse_configs.py のユーザビリティ改善テスト (A1 / A2 / A3)

A1: 未知ベンダー時の警告メッセージが "Cisco IOS" と "Juniper JunOS" を含む
A2: workspace/ 不在・空時の案内が stderr に出る
A3: build_topology.py --help に workspace と拡張子の文言が含まれる
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

# ------------------------------------------------------------------
# スキルルートを sys.path に追加（conftest.py と同じ方法）
# ------------------------------------------------------------------
_SKILL_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

from scripts.parse_configs import collect_inputs, parse_paths  # noqa: E402


# ==================================================================
# A1: 未知ベンダー警告メッセージの親切化
# ==================================================================


@pytest.mark.unit
def test_unknown_vendor_warn_contains_cisco_ios(tmp_path, capsys):
    """未知ベンダーファイルをパースした際の警告に 'Cisco IOS' が含まれる。"""
    unknown_cfg = tmp_path / "unknown.cfg"
    unknown_cfg.write_text("this is not a valid cisco or junos config\n")

    parse_paths([str(unknown_cfg)])

    captured = capsys.readouterr()
    assert "Cisco IOS" in captured.err, (
        f"Expected 'Cisco IOS' in stderr, got: {captured.err!r}"
    )


@pytest.mark.unit
def test_unknown_vendor_warn_contains_juniper_junos(tmp_path, capsys):
    """未知ベンダーファイルをパースした際の警告に 'Juniper JunOS' が含まれる。"""
    unknown_cfg = tmp_path / "unknown.cfg"
    unknown_cfg.write_text("this is not a valid cisco or junos config\n")

    parse_paths([str(unknown_cfg)])

    captured = capsys.readouterr()
    assert "Juniper JunOS" in captured.err, (
        f"Expected 'Juniper JunOS' in stderr, got: {captured.err!r}"
    )


@pytest.mark.unit
def test_unknown_vendor_warn_contains_filepath(tmp_path, capsys):
    """未知ベンダー警告にファイルパスが含まれる。"""
    unknown_cfg = tmp_path / "mystery_device.cfg"
    unknown_cfg.write_text("totally unknown vendor config content\n")

    parse_paths([str(unknown_cfg)])

    captured = capsys.readouterr()
    assert "mystery_device.cfg" in captured.err, (
        f"Expected file path in stderr, got: {captured.err!r}"
    )


@pytest.mark.unit
def test_unknown_vendor_warn_returns_empty_devices(tmp_path):
    """未知ベンダーファイルのみの場合、空リストが返る。"""
    unknown_cfg = tmp_path / "unknown.cfg"
    unknown_cfg.write_text("this is not a valid cisco or junos config\n")

    devices = parse_paths([str(unknown_cfg)])
    assert devices == [], f"Expected empty list, got: {devices}"


# ==================================================================
# A2: workspace/ 不在・空時の案内
# ==================================================================


@pytest.mark.unit
def test_collect_inputs_no_workspace_warns_stderr(tmp_path, monkeypatch, capsys):
    """workspace/ が存在しない場合、stderr に 'workspace' と拡張子が含まれる案内が出る。"""
    # tmp_path には workspace/ ディレクトリが存在しない
    monkeypatch.chdir(tmp_path)

    result = collect_inputs()

    assert result == [], f"Expected empty list, got: {result}"
    captured = capsys.readouterr()
    assert "workspace" in captured.err, (
        f"Expected 'workspace' in stderr, got: {captured.err!r}"
    )
    assert any(ext in captured.err for ext in [".cfg", ".conf", ".txt"]), (
        f"Expected file extension in stderr, got: {captured.err!r}"
    )


@pytest.mark.unit
def test_collect_inputs_empty_workspace_warns_stderr(tmp_path, monkeypatch, capsys):
    """workspace/ が存在するが対象ファイルが0件の場合、stderr に案内が出る。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # .cfg/.conf/.txt 以外のファイルだけ置く
    (workspace / "README.md").write_text("readme\n")

    monkeypatch.chdir(tmp_path)

    result = collect_inputs()

    assert result == [], f"Expected empty list, got: {result}"
    captured = capsys.readouterr()
    assert "workspace" in captured.err, (
        f"Expected 'workspace' in stderr, got: {captured.err!r}"
    )
    assert any(ext in captured.err for ext in [".cfg", ".conf", ".txt"]), (
        f"Expected file extension in stderr, got: {captured.err!r}"
    )


@pytest.mark.unit
def test_collect_inputs_no_workspace_different_message(tmp_path, monkeypatch, capsys):
    """workspace/ 不在と空で異なるメッセージを出す（不在では存在しない旨）。"""
    monkeypatch.chdir(tmp_path)

    collect_inputs()

    captured_no_ws = capsys.readouterr()

    # workspace/ を作って空にする
    (tmp_path / "workspace").mkdir()
    collect_inputs()
    captured_empty_ws = capsys.readouterr()

    # 両方とも何か出力されているが、内容が異なること
    assert captured_no_ws.err != captured_empty_ws.err, (
        "Expected different messages for missing vs empty workspace"
    )


@pytest.mark.unit
def test_collect_inputs_explicit_file_no_warn(tmp_path, monkeypatch, capsys):
    """明示的なファイルパス指定時は workspace 案内が出ない。"""
    cfg_file = tmp_path / "router.cfg"
    cfg_file.write_text("version 15.1\n")

    monkeypatch.chdir(tmp_path)

    result = collect_inputs(str(cfg_file))

    assert result == [str(cfg_file)]
    captured = capsys.readouterr()
    assert "workspace" not in captured.err, (
        f"Unexpected 'workspace' warning in stderr: {captured.err!r}"
    )


@pytest.mark.unit
def test_collect_inputs_existing_workspace_with_files_no_warn(
    tmp_path, monkeypatch, capsys
):
    """対象ファイルがある workspace/ の場合、案内は出ない。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "router.cfg").write_text("version 15.1\n")

    monkeypatch.chdir(tmp_path)

    result = collect_inputs()

    assert len(result) == 1
    captured = capsys.readouterr()
    assert captured.err == "", (
        f"Expected no stderr output, got: {captured.err!r}"
    )


# ==================================================================
# A3: build_topology.py --help の文言確認
# ==================================================================

_BUILD_TOPOLOGY_PATH = os.path.join(_SKILL_ROOT, "scripts", "build_topology.py")


@pytest.mark.integration
def test_build_topology_help_contains_workspace(tmp_path):
    """--help の出力に 'workspace' が含まれる。"""
    result = subprocess.run(
        [sys.executable, _BUILD_TOPOLOGY_PATH, "--help"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, f"--help exited with {result.returncode}"
    assert "workspace" in result.stdout, (
        f"Expected 'workspace' in --help output, got:\n{result.stdout}"
    )


@pytest.mark.integration
def test_build_topology_help_contains_cfg_extension(tmp_path):
    """--help の出力に '.cfg' が含まれる。"""
    result = subprocess.run(
        [sys.executable, _BUILD_TOPOLOGY_PATH, "--help"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, f"--help exited with {result.returncode}"
    assert ".cfg" in result.stdout, (
        f"Expected '.cfg' in --help output, got:\n{result.stdout}"
    )


@pytest.mark.integration
def test_build_topology_help_contains_conf_or_txt_extension(tmp_path):
    """--help の出力に '.conf' または '.txt' が含まれる。"""
    result = subprocess.run(
        [sys.executable, _BUILD_TOPOLOGY_PATH, "--help"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, f"--help exited with {result.returncode}"
    assert ".conf" in result.stdout or ".txt" in result.stdout, (
        f"Expected '.conf' or '.txt' in --help output, got:\n{result.stdout}"
    )
