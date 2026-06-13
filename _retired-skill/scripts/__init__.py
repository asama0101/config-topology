"""
scripts — config-topology スキルの CLI エントリーポイント群（SKILL.md の各 Phase が python3 で起動する）。

- parse_configs.py    コンフィグをパースして正規化 Device を出力
- build_topology.py   Device 群から topology を結線推論して層別 YAML 出力
- render_topology.py  層別 YAML topology を自己完結 HTML にレンダリング

共有ロジックは兄弟パッケージ lib/（parsers / rendering / topology_io）に置く。
"""
