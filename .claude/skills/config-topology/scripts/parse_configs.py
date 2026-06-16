#!/usr/bin/env python3
"""CLI①: 正規化 Device リストを JSON で stdout に出力（要件書 §10.1・§10.2）。

警告・進捗は stderr（[INFO]/[WARN]）。stdout は JSON のみ（パイプ可能）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # rebuild/ を import パスへ

from lib.inputs import collect_inputs            # noqa: E402
from lib.parsers import detect_vendor, parse_config, diagnose_input  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Parse network configs into normalized Device JSON.")
    parser.add_argument("paths", nargs="*", help="config files / dirs / glob（省略時 ./workspace/）")
    args = parser.parse_args(argv)

    files = collect_inputs(args.paths)
    if not files:
        print("[WARN] 対象 config が見つかりません（拡張子: .cfg/.conf/.txt）", file=sys.stderr)

    devices, warnings = [], []
    for f in files:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print("[ERROR] 読込失敗: %s (%s)" % (f, e), file=sys.stderr)
            return 1
        name = os.path.basename(f)
        vendor = detect_vendor(text)
        if vendor is None:
            diag = diagnose_input(text, name)
            if diag is not None:
                print("[WARN] %s: %s" % (name, diag["message"]), file=sys.stderr)
            print("[WARN] %s: skipped (unknown vendor)" % name, file=sys.stderr)
            continue
        try:
            dev = parse_config(text, warnings)
        except Exception as e:                       # noqa: BLE001
            print("[WARN] %s: パース中の予期しない例外につきスキップ (%s)" % (name, e), file=sys.stderr)
            continue
        if dev is None:
            print("[WARN] %s: skipped (unknown vendor)" % name, file=sys.stderr)
            continue
        devices.append(dev.to_dict())
        print("[INFO] %s: %s" % (name, vendor), file=sys.stderr)

    if warnings:
        print("[WARN] パース警告 %d 件" % len(warnings), file=sys.stderr)

    json.dump(devices, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
