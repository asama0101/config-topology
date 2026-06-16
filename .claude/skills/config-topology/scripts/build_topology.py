#!/usr/bin/env python3
"""CLI②: parse + 推論を実行し層別 YAML を生成（要件書 §10.1・§10.2・§10.3・§10.4）。"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # rebuild/ を import パスへ

from lib.inputs import collect_inputs                # noqa: E402
from lib.parsers import detect_vendor, parse_config, diagnose_input  # noqa: E402
from lib.build import build_topology                 # noqa: E402
from lib.topology_io import dump_topology            # noqa: E402
from lib.history import retain_for_build, current_timestamp  # noqa: E402
from lib.run_summary import build_summary_lines      # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Build layered topology YAML from configs.")
    p.add_argument("paths", nargs="*", help="config files / dirs / glob（省略時 ./workspace/）")
    p.add_argument("-o", "--output", default="topology", help="出力ディレクトリ（既定 ./topology）")
    args = p.parse_args(argv)

    files = collect_inputs(args.paths)
    if not files:
        print("[WARN] 対象 config が見つかりません（拡張子: .cfg/.conf/.txt）", file=sys.stderr)

    parsed, basenames, raw_texts, parse_statuses, warnings, verdicts = [], [], [], [], [], []
    diag_list = []  # 入力形式診断（#1 波括弧・#2 apply-groups）
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
                diag_list.append(diag)
            print("[WARN] %s: skipped (unknown vendor)" % name, file=sys.stderr)
            verdicts.append((name, None))
            continue
        line_status = []                  # CONFIG parse 状態モード用に行ごとの認識可否を収集
        try:
            dev = parse_config(text, warnings, line_status=line_status, diagnostics=diag_list)
        except Exception as e:                        # noqa: BLE001
            print("[WARN] %s: パース中の例外につきスキップ (%s)" % (name, e), file=sys.stderr)
            verdicts.append((name, None))
            continue
        if dev is None:
            print("[WARN] %s: skipped (parse returned None)" % name, file=sys.stderr)
            verdicts.append((name, None))
            continue
        parsed.append(dev)
        basenames.append(name)
        raw_texts.append(text)            # CONFIG ビュー用に生 config を保持（parsed と並走）
        parse_statuses.append(line_status)
        verdicts.append((name, vendor))
        print("[INFO] %s: %s" % (name, vendor), file=sys.stderr)

    topo = build_topology(parsed, basenames, raw_texts=raw_texts, parse_statuses=parse_statuses,
                         diagnostics=diag_list or None)

    # §10.3 history 退避（既定パス運用時のみ ./topology.html もペア退避）
    out_dir = Path(args.output)
    html_pair = Path("topology.html") if out_dir == Path("topology") else None
    retained = retain_for_build(out_dir, html_pair, current_timestamp())
    if retained is not None:
        print("[INFO] 旧成果物を退避: %s" % retained, file=sys.stderr)

    try:
        dump_topology(topo, args.output)
    except OSError as e:
        print("[ERROR] 出力失敗: %s (%s)" % (args.output, e), file=sys.stderr)
        return 1

    # §10.4 実行サマリー
    for line in build_summary_lines(verdicts, warnings, topo):
        print(line, file=sys.stderr)

    print("Generated: %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
