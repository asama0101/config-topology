"""
lib — 内部ライブラリ（CLI から呼ばれるロジック本体）。

- parsers/      ベンダー別パーサ registry（正規化モデル Device を返す）
- rendering/    層別 topology(dict) → 自己完結 HTML レンダリング
- topology_io   層別 YAML 正本 ⇄ topology dict の dump/load・参照整合検証
"""
