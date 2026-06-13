#!/usr/bin/env python3
"""CLI④: 2 つの層別 YAML ディレクトリを比較し、差分レポートを出力（要件書 §10.4）。

使用例:
    python3 diff_topology.py old_topology/ new_topology/
    python3 diff_topology.py old_topology/ new_topology/ -o diff_report.md

終了コード:
    0 … レポート生成成功（差分あり・なし問わず）
    1 … 入力エラー（ディレクトリ読込失敗・参照整合エラー・YAML 構文エラー）

注意:
    diff レポートには config 由来の自由記述（description 等）がそのまま含まれます。
    共有前に内容を確認してください。
"""
import argparse
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.topology_io import load_topology   # noqa: E402
from lib.diff import diff_topology, format_diff_report  # noqa: E402

_WARN_MSG = (
    "[WARN] diff レポートには config 由来の自由記述（description 等）が"
    "そのまま含まれます。共有前に内容を確認してください。"
)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Compare two layered topology YAML directories and output a diff report.")
    p.add_argument("old_dir", help="比較元の層別 YAML ディレクトリ（old）")
    p.add_argument("new_dir", help="比較先の層別 YAML ディレクトリ（new）")
    p.add_argument("-o", "--output", default=None,
                   help="出力ファイルパス（省略時 stdout）")
    args = p.parse_args(argv)

    try:
        old_topo = load_topology(args.old_dir)
    except (ValueError, yaml.YAMLError) as e:
        print("[ERROR] 参照整合エラー (old): %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("[ERROR] 読込失敗 (old): %s (%s)" % (args.old_dir, e), file=sys.stderr)
        return 1

    try:
        new_topo = load_topology(args.new_dir)
    except (ValueError, yaml.YAMLError) as e:
        print("[ERROR] 参照整合エラー (new): %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("[ERROR] 読込失敗 (new): %s (%s)" % (args.new_dir, e), file=sys.stderr)
        return 1

    diff = diff_topology(old_topo, new_topo)
    report = format_diff_report(diff, args.old_dir, args.new_dir)

    print(_WARN_MSG, file=sys.stderr)

    if args.output is None:
        print(report)
    else:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
        except OSError as e:
            print("[ERROR] 出力失敗: %s (%s)" % (args.output, e), file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
