"""
render_topology.py — 層別 YAML topology を自己完結 HTML (SVG + vanilla JS) にレンダリングする。

公開 API:
    render(topology: dict) -> str   # 自己完結 HTML 文字列を返す
    main()                          # CLI エントリーポイント

CLI:
    python scripts/render_topology.py <topology_dir> [-o out.html]
    topology_dir: 層別 YAML ディレクトリ（topology_io.load_topology() で読み込む）
    -o: 出力 HTML ファイルパス（省略時は topology_dir/topology.html）

設計原則:
- レンダリングロジック（render）は決定論的: Math.random() や時刻に依存しない
  （CLI/IO は topology_io 経由で PyYAML に依存。render 単体は lib.rendering で完結）
- self-contained HTML: file:// で直接開ける（外部 CDN 不使用）
- HTML エスケープ: hostname / description 等のユーザーデータは必ずエスケープ
- 堅牢性: 空 topology でもクラッシュしない
"""

from __future__ import annotations

import argparse
import os
import sys

import yaml

# ---------------------------------------------------------------------------
# sys.path セットアップ（scripts/ を直接実行したときも import できるよう）
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # バンドルルート（scripts/ の1階層上）
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# render はライブラリ（lib.rendering）が正本。main() から使う。
from lib.rendering import render  # noqa: E402


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI エントリーポイント"""
    from lib.topology_io import load_topology

    parser = argparse.ArgumentParser(
        description="Render layer-split YAML topology to a self-contained HTML file."
    )
    parser.add_argument("topology_dir", help="入力: 層別 YAML ディレクトリパス")
    parser.add_argument(
        "-o",
        "--output",
        help="出力 HTML ファイルパス（必須）",
        default=None,
    )
    args = parser.parse_args()

    topology_dir = args.topology_dir
    if not os.path.isdir(topology_dir):
        print(f"Error: ディレクトリが見つかりません: {topology_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        topology = load_topology(topology_dir)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as e:
        print(f"Error: topology 読み込みに失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    html_content = render(topology)

    if args.output:
        out_path = args.output
    else:
        out_path = os.path.join(os.path.abspath(topology_dir), "topology.html")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Generated: {out_path}")


if __name__ == "__main__":
    main()
