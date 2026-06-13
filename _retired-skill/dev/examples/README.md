# examples/ — テスト用ゴールデンフィクスチャ

pytest が参照する**決定的なゴールデン**。E2E 検証・回帰防止に使う。

| パス | 役割 |
|-----|------|
| `configs/` | 入力サンプル config（`sample-ios-r1.cfg` / `sample-junos-r2.conf`） |
| `topology/` | 上記から `scripts/build_topology.py` が生成する**期待出力（層別 YAML）**。`tests/test_build_topology.py` が厳密一致で比較する |

- `topology/` は生成物のスナップショット。**手編集しない**（パーサ/推論を変えたら再生成してコミット）。
- 再生成: `python3 scripts/build_topology.py examples/configs/*.cfg examples/configs/*.conf -o examples/topology`
- 挙動（スコア）評価のシナリオは `examples/` ではなく `evals/` を参照。
