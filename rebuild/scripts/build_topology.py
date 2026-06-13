#!/usr/bin/env python3
"""CLI②: parse + 推論を実行し層別 YAML を生成（要件書 §10.1・§10.2）。

history 退避・実行サマリーは M4 で追加する（本 CLI には未実装）。
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # rebuild/ を import パスへ

from lib.inputs import collect_inputs                # noqa: E402
from lib.parsers import detect_vendor, parse_config  # noqa: E402
from lib.build import build_topology                 # noqa: E402
from lib.topology_io import dump_topology            # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Build layered topology YAML from configs.")
    p.add_argument("paths", nargs="*", help="config files / dirs / glob（省略時 ./workspace/）")
    p.add_argument("-o", "--output", default="topology", help="出力ディレクトリ（既定 ./topology）")
    args = p.parse_args(argv)

    files = collect_inputs(args.paths)
    if not files:
        print("[WARN] 対象 config が見つかりません（拡張子: .cfg/.conf/.txt）", file=sys.stderr)

    parsed, basenames, warnings = [], [], []
    for f in files:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print("[ERROR] 読込失敗: %s (%s)" % (f, e), file=sys.stderr)
            return 1
        name = os.path.basename(f)
        vendor = detect_vendor(text)
        if vendor is None:
            print("[WARN] %s: skipped (unknown vendor)" % name, file=sys.stderr)
            continue
        try:
            dev = parse_config(text, warnings)
        except Exception as e:                        # noqa: BLE001
            print("[WARN] %s: パース中の例外につきスキップ (%s)" % (name, e), file=sys.stderr)
            continue
        if dev is None:
            continue
        parsed.append(dev)
        basenames.append(name)
        print("[INFO] %s: %s" % (name, vendor), file=sys.stderr)

    topo = build_topology(parsed, basenames)
    try:
        dump_topology(topo, args.output)
    except OSError as e:
        print("[ERROR] 出力失敗: %s (%s)" % (args.output, e), file=sys.stderr)
        return 1

    print("Generated: %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
