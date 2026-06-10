---
name: config-topology
description: >-
  NW機器のConfig（Cisco IOS/IOS-XE running-config、Juniper JunOS set形式）から
  ネットワーク構成図（トポロジー図）を生成する。複数機器のConfigを束ね、IP/サブネット一致で
  機器間リンクを自動推論し、中間表現（レイヤー別YAML）を経てインタラクティブHTML構成図を出力する。
  「構成図を作って」「トポロジー図を描いて」「このconfigから構成を可視化」「ネットワーク図にして」
  「configから結線を起こして」「機器の接続関係を図にして」等の発言、または ./workspace/ にconfig
  ファイル(.cfg/.conf/.txt)が置かれているときは必ずこのスキルを使う。Excel手順書のレビューや
  パラメータ入力ではなく、Config(テキスト)からのネットワーク図化が対象。
---

# config-topology — Config からネットワーク構成図を生成

ネットワーク機器の running-config（テキスト）を入力に、機器・インターフェース・IP・機器間リンク・
ルーティングを読み取り、中間表現（**レイヤー別 YAML**）を経て**インタラクティブなHTML構成図**を生成する。

- **入力**: Cisco IOS / IOS-XE running-config、Juniper JunOS（set 形式）。複数機器を一括。
- **出力**: `./topology/`（**ベンダー中立のレイヤー別 YAML 正本**＝`_meta.yaml`/`devices.yaml`/`physical.yaml`/`routing.*.yaml`）＋ `./topology.html`（自己完結・`file://` で開ける）。中間表現は YAML で、人手編集して再描画できる（round-trip）。
- **依存**: 唯一の依存は **PyYAML**（pure Python）。system `python3` で `import yaml` できればそのまま使う。できなければ `pip install pyyaml` するか、任意で venv を作る（**venv は必須ではない**。作る場合は gitignore すること）。`python3` を使う（`python` エイリアスは無い前提）。

このスキルは**ホストプロジェクトのディレクトリ（cwd）から呼び出される**。スキルバンドルはそのホスト配下の
`.claude/skills/config-topology/` にある。以降このバンドルのディレクトリを `$SKILL` と書く。**絶対パスをハードコードせず、
バンドルの場所から相対で導出する**（コピーしたバンドルがどこでも動くように）。実行前にシェル変数を設定しておく:
```bash
SKILL=".claude/skills/config-topology"   # ホスト cwd からの相対パス
```
入力・出力はすべて**ホスト cwd 相対**（`./workspace/` に入力、`./topology/`・`./topology.html` に出力）。

> **注意（機密情報）**: config の `interface description` 等に管理者が誤って community 文字列やパスワードを書いている場合、その値はそのまま 層別 YAML・`topology.html` に出力される（パーサは `password`/`secret`/`snmp community` 行自体はパースしないが description 等の自由記述は通す）。生成物を共有・保存する際は取り扱いに注意すること。

## アーキテクチャ（3層パイプライン）

```
./workspace/*.{cfg,conf,txt}
   │  scripts/parse_configs.py     ベンダー自動判定 → 正規化モデル(Device)
   ▼
   │  scripts/build_topology.py    IP/サブネット一致でリンク・セグメント推論、BGP対向解決
   ▼
./topology/  (層別YAML正本)          ← 中間表現（正確性が最優先・人手編集可）
   │  lib/topology_io.py             dump/load（層別YAML ⇄ topology dict・参照整合検証）
   │  scripts/render_topology.py
   ▼
./topology.html                     SVG+バニラJS（ズーム/パン/ホバー強調/レイヤー別ビュー）
```

各層は単一責務で、境界は層別 YAML（`lib/topology_io.py` が dict と相互変換）。詳細仕様は必要に応じて参照:
- `references/schema.md` — レイヤー別 YAML レイアウト・topology スキーマと ID 採番規則
- `references/link-inference.md` — サブネット結線推論と BGP 対向解決のルール
- `references/vendor-parsing.md` — ベンダー別パース要点と**新ベンダー追加手順**

## 実行手順

### Phase 1: 入力の収集とベンダー確認
1. ユーザーが config ファイルを `./workspace/` に置いているか、パスを指定しているか確認する。
   - `./workspace/` 方式: ホスト cwd の `./workspace/` に置かれた `*.cfg *.conf *.txt` を対象にする（inbox サブディレクトリは無い）。
   - パス指定方式: ユーザーが渡したファイル/ディレクトリ/glob を対象にする。
2. ベンダー判定の妥当性を素早く確認する（任意・デバッグ用）:
   ```bash
   python3 "$SKILL/scripts/parse_configs.py" <paths...>   # 正規化 devices を JSON で確認
   ```
   未知ベンダーのファイルはスキップされ stderr に警告が出る。意図せずスキップされていないか見る。

### Phase 2: 層別 YAML（中間表現）の生成（最優先で正確に）
```bash
python3 "$SKILL/scripts/build_topology.py" [paths...] -o ./topology
# paths 省略時は ./workspace/ を自動走査。-o は出力ディレクトリ（既定 topology/）
# → ./topology/ に _meta.yaml / devices.yaml / physical.yaml / routing.*.yaml を生成
```
- 生成された層別 YAML を**必ず目視確認**する（YAML なので読みやすく、必要なら手で補正可）。特に:
  - `devices.yaml`: 機器・IF・IP が漏れなく拾えているか（特に description / shutdown / loopback）。
  - `physical.yaml`: `links` と `segments` が意図通りか（2機器=link、3機器以上=segment、単独=スタブ）。
  - `routing.bgp.yaml`: `type`（ebgp/ibgp）と `local_ip` 解決が妥当か。
- 手で編集した場合、読込時に **ID 参照整合が検証**される（dangling 参照はファイル・フィールド・値を示すエラー）。
- 取りこぼしや誤りがあれば、まずパース/推論の問題か config の特殊記法かを切り分ける。

### Phase 3: HTML 構成図の描画
```bash
python3 "$SKILL/scripts/render_topology.py" ./topology -o ./topology.html
# 入力は層別YAMLディレクトリ（topology_io.load_topology が参照整合を検証して dict 復元）
# 構成図は常に ./topology.html に出力する
```
- **レイヤー別ビュー切替**（上部タブ）: `Physical`（L1物理＝機器+リンク+セグメント）/ `L3`（サブネットでグルーピング+routing隣接）/
  プロトコル別（`BGP`・`OSPF` … `routing` キーから動的生成）。ビューごとに配置が変わり、機器数が多くても見やすい。
- **検索ボックス**: hostname / IP で現在ビュー内のノードを絞り込み（淡色化）。
- レイアウトは**決定的 force-directed**（同一 topology → 同一HTML）＋**動的キャンバス**（台数に応じて拡大、〜150台目安）。
- ズーム（ホイール）/パン（ドラッグ）/ホバー強調/レイヤートグル（routingオーバーレイ表示制御）/
  F=全体表示・Esc=リセット が動く自己完結 HTML。

### Phase（履歴）: 再生成前の旧成果物の退避（非破壊出力の尊重）
出力は固定パス（`./topology/`・`./topology.html`）に上書きされる。再生成する前に、**既に `./topology/` か
`./topology.html` が存在する場合は、履歴を残すかユーザーに確認する**。残す場合は、既存の成果物を先に
`./history/<YYYY-MM-DD_HHMM>/` へ退避してから再生成する（`runs/` は廃止）。
```bash
TS=$(date +%Y-%m-%d_%H%M); mkdir -p "./history/$TS"
[ -e ./topology ] && mv ./topology "./history/$TS/"
[ -e ./topology.html ] && mv ./topology.html "./history/$TS/"
# この後で Phase 2,3 を実行して新しい成果物を生成する
```

### Phase（クロスレビュー）: HTML 成果物のクロスレビュー（提示前に必須）
HTML 構成図は提示前に**サブエージェントで敵対的にクロスレビュー**する（層別 YAML(topology) と HTML を突合し、
ノード/リンク/ルーティングの欠落・誤接続・ラベル不整合・描画崩れを洗い出す）。指摘があれば修正してから提示する。

## トラブルシューティング

### `[WARN] Unknown vendor, skipping: <path>` が出る
対応ベンダーは **Cisco IOS / IOS-XE running-config** と **Juniper JunOS（set 形式）** のみ。
`detect` が判定に失敗したファイルはスキップされる。主な原因と対処:
- `show` コマンド出力や設定の抜粋のみ → **running-config 全文**（IOS）/ **set 形式**（JunOS）で保存し直す。
- 別ベンダー（NX-OS / Arista 等）→ v1 はスコープ外（「拡張の指針」のベンダー追加を参照）。
- 設定行が無い・文字化け → ファイルの中身とエンコーディング（UTF-8）を確認する。

### `./workspace/` に置いたのに「config が見つからない」
`paths` 省略時は `./workspace/` 配下の `*.cfg *.conf *.txt` だけを走査する。該当が無いと
stderr に `[INFO]` 案内が出る（workspace が無い場合は `workspace/ not found. Place config
files (*.cfg, *.conf, *.txt) in ...`、存在するが対象ファイル 0 件の場合は `workspace/ exists
but no *.cfg, *.conf, or *.txt files found in ...`）。
- ディレクトリ名・拡張子・置き場所（**ホスト cwd 直下の workspace/**）を確認する。
- workspace を使わず、パスを直接渡してもよい:
  `python3 "$SKILL/scripts/build_topology.py" path/to/a.cfg path/to/b.conf -o ./topology`

### 層別 YAML を手編集したら「参照整合エラー」が出る
`render_topology.py`（`topology_io.load_topology`）は device / interface ID の dangling 参照を、
**ファイル名・フィールド・値付きの `ValueError`** で弾く。多くは device id を変えたのに参照側を
直し忘れたケース。
- 正しい device id 一覧は `devices.yaml` の `devices[].id`:
  `grep "id:" ./topology/devices.yaml`
- エラーに出た参照元（`interfaces[].device` / `physical.yaml` の `links[].a_device`・`b_device` /
  `segments[].members[]` / `routing.*.yaml` の `device`）を、正しい id に揃える。

## スコープ（v1）
- **対象**: 機器・IF・IP・サブネット結線（コア）＋ ルーティング（BGP / OSPF / static）。
- **スコープ外（将来拡張）**: VLAN/L2・SVI、HSRP/VRRP・LAG/Port-channel、CDP/LLDP 由来リンク、
  NX-OS/Arista 等の追加ベンダー、Mermaid/Graphviz 併出力、フロー選択等のリッチUX。

## 拡張の指針
- **ベンダー追加**: `lib/parsers/<vendor>.py` に `detect`/`parse` を実装し registry に登録するだけ
  （`references/vendor-parsing.md` の手順）。スキーマ・build・render は変更不要。
- **プロトコル/レイヤー追加**: topology の `routing` にキーを足す（新 `routing.<proto>.yaml` 層が増える）、または
  `devices[].sections` に汎用テーブルを足す。レンダラーは `routing` のキーを走査してレイヤー別ビュー/トグルを自動生成するので加算的に対応。
- **結線手段追加**: `links[].kind` に新しい由来（例 `neighbor-cdp`）を足す。

## 検証
開発資産（`$SKILL/dev/tests/`・`$SKILL/dev/examples/`・`$SKILL/dev/evals/`・`$SKILL/dev/pytest.ini`）はスキルの実行時には不要で、
保守者向け（ユニットテスト・E2E・ゴールデン出力）。
```bash
cd "$SKILL/dev" && python3 -m pytest -q          # ユニットテスト
# E2E:
python3 "$SKILL/scripts/build_topology.py" "$SKILL/dev/examples/configs/sample-ios-r1.cfg" "$SKILL/dev/examples/configs/sample-junos-r2.conf" -o ./topology
python3 "$SKILL/scripts/render_topology.py" ./topology -o ./topology.html
```
`$SKILL/dev/examples/topology/`（層別 YAML）は 2 つのサンプル config から生成される期待出力（ゴールデン）。
