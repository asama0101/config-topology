"""
エントリポイント: コンフィグファイルをパースして正規化 Device リストを返す。

公開 API:
    parse_paths(paths: list[str]) -> list[Device]
        ファイルパスのリストをパースし、ファイル順を保持した Device リストを返す。
        未知ベンダー・空ファイル・パースエラーはスキップ（None を含まない）。

    collect_inputs(arg: str | None = None) -> list[str]
        引数パス（ファイル/ディレクトリ/glob）が無ければ workspace/ 配下の
        *.txt *.cfg *.conf を名前順で返す。

CLI:
    python scripts/parse_configs.py [paths...]
    → 正規化 devices を JSON として stdout に出力（デバッグ用）
"""

from __future__ import annotations

import dataclasses
import glob
import json
import os
import sys

# スクリプトから直接実行された場合もインポートできるようにパスを追加
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)  # バンドルルート（scripts/ の1階層上）
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from lib.parsers import parse_text
from lib.parsers.base import Device

# ドロップ先ディレクトリは実行時カレントディレクトリ基準（移植性を保つ）。
# ランタイムデータは workspace/ 配下に集約しているため workspace/ を直接見る。
_INBOX_EXTENSIONS = ("*.txt", "*.cfg", "*.conf")


def collect_inputs(arg: str | None = None) -> list[str]:
    """
    引数に応じてパースするファイルのパスリストを返す。

    - None        : カレントディレクトリ直下の workspace/ 配下を名前順で収集
    - ディレクトリ : そのディレクトリ配下の *.txt *.cfg *.conf を名前順で収集
    - glob パターン: glob 展開した結果を名前順で返す
    - ファイルパス  : そのまま [path] を返す
    """
    if arg is None:
        drop_dir = os.path.join(os.getcwd(), "workspace")
        results = _collect_from_dir(drop_dir)
        if not results:
            if not os.path.isdir(drop_dir):
                print(
                    f"[INFO] workspace/ not found. Place config files (*.cfg, *.conf, *.txt)"
                    f" in {drop_dir}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[INFO] workspace/ exists but no *.cfg, *.conf, or *.txt files found"
                    f" in {drop_dir}",
                    file=sys.stderr,
                )
        return results

    if os.path.isdir(arg):
        return _collect_from_dir(arg)

    if os.path.isfile(arg):
        return [arg]

    # glob パターン
    matched = sorted(glob.glob(arg))
    return matched


def _collect_from_dir(dir_path: str) -> list[str]:
    """ディレクトリ配下の対象拡張子ファイルを重複排除・名前順で返す。"""
    results = []
    for ext in _INBOX_EXTENSIONS:
        results.extend(glob.glob(os.path.join(dir_path, ext)))
    return sorted(set(results))


def parse_paths(paths: list[str]) -> list[Device]:
    """
    ファイルパスのリストをパースして Device リストを返す。

    - ファイル読み込みエラーはスキップ（stderr に警告出力）
    - 未知ベンダー（detect が None）はスキップ
    - 空ファイルはスキップ
    - ファイル順を保持する
    """
    devices: list[Device] = []

    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            print(f"[WARN] Cannot read {path}: {e}", file=sys.stderr)
            continue

        if not text.strip():
            continue

        device = parse_text(text)
        if device is None:
            print(
                f"[WARN] Unknown vendor, skipping: {path}"
                " (supported: Cisco IOS/IOS-XE running-config, Juniper JunOS set 形式)",
                file=sys.stderr,
            )
            continue

        devices.append(device)

    return devices


def _devices_to_json(devices: list[Device]) -> str:
    """Device リストを JSON 文字列に変換する（デバッグ用）。"""
    return json.dumps(
        [dataclasses.asdict(d) for d in devices],
        ensure_ascii=False,
        indent=2,
    )


def main() -> None:
    """CLI エントリポイント。"""
    args = sys.argv[1:]

    if args:
        paths: list[str] = []
        for arg in args:
            paths.extend(collect_inputs(arg))
    else:
        paths = collect_inputs()

    devices = parse_paths(paths)
    print(_devices_to_json(devices))


if __name__ == "__main__":
    main()
