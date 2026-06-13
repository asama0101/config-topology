# evals/ — 挙動評価ハーネス

スキルの**挙動**（生成物の妥当性）を評価するためのシナリオ集。`examples/`（厳密一致ゴールデン）とは
役割が異なり、**期待出力ファイルは持たない**。

| パス | 役割 |
|-----|------|
| `evals.json` | 評価シナリオの定義。`expected_output` は**散文ルーブリック**（人/LLM が判定する観点）であり、固定の出力ファイルではない |
| `inputs/` | シナリオ別の入力 config 群（`cross-vendor-ospf/` `ebgp-p2p/` `segment-static/` など） |

- 単体テストのゴールデン照合は `tests/` + `examples/topology/` が担う。ここは「観点ベースの良し悪し」を見る。
- 入力を追加するときは `inputs/<scenario>/` にディレクトリを作り、`evals.json` に観点を追記する。
