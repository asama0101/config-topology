#!/usr/bin/env python3
"""CLI③: 層別 YAML から自己完結 HTML を生成（要件書 §10.1・§10.2）。

history 退避（§10.3）は M4 で追加する（本 CLI には未実装）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.topology_io import load_topology       # noqa: E402
from lib.rendering.template import render_html   # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Render layered topology YAML to a self-contained HTML.")
    p.add_argument("topology_dir", help="層別 YAML のディレクトリ")
    p.add_argument("-o", "--output", default="./topology.html",
                   help="出力 HTML（既定 ./topology.html）")
    args = p.parse_args(argv)

    try:
        topo = load_topology(args.topology_dir)
    except ValueError as e:
        print("[ERROR] 参照整合エラー: %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("[ERROR] 読込失敗: %s (%s)" % (args.topology_dir, e), file=sys.stderr)
        return 1

    html = render_html(topo)
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
    except OSError as e:
        print("[ERROR] 出力失敗: %s (%s)" % (args.output, e), file=sys.stderr)
        return 1

    print("Generated: %s" % args.output)
    print("[WARN] 生成物には config 由来の自由記述（description 等）がそのまま含まれます。"
          "共有前に内容を確認してください。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
