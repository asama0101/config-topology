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
- 生成完了時 stderr に **実行サマリー** が出力される: 入力ファイルの判定結果（vendor or skip）・警告数・生成数（devices/interfaces/links/segments・各 routing）・注意喚起。

### Phase 3: HTML 構成図の描画
```bash
python3 "$SKILL/scripts/render_topology.py" ./topology -o ./topology.html
# 入力は層別YAMLディレクトリ（topology_io.load_topology が参照整合を検証して dict 復元）
# 構成図は常に ./topology.html に出力する

# 差分表示（DIFF ビュー）: 前回の topology/ を明示指定すると HTML に DIFF タブが追加される
python3 "$SKILL/scripts/render_topology.py" ./topology -o ./topology.html --diff-against ./history/<YYYY-MM-DD_HHMM>/topology/

# --diff-against-history: 直近 history スナップショットとの差分を自動表示（パス指定不要）
# history/ 直下の最新タイムスタンプディレクトリを自動選択して --diff-against 相当を実行する
# history が存在しない場合は差分なし（INFO を stderr に出力）で通常描画する
# --diff-against が明示されている場合は --diff-against が優先される
python3 "$SKILL/scripts/render_topology.py" ./topology -o ./topology.html --diff-against-history
```
- **図ビュー**（上部タブ）: `PHYSICAL`（L1物理＝機器+リンク+セグメント）＋プロトコル別（`BGP`・`OSPF` … `routing` キーから動的生成。例: BGP ネイバー隣接・OSPF エリア別）。**Physical / OSPF 両ビュー**で、対向のない IF（stub / loopback）を機器ノード脇に **segment 様式のノード**（点線楕円＋subnet＋area バッジ・色で区別: loopback=紫 / stub=緑）として表示する（segment と同規則: Physical=全件・OSPF=OSPF 参加〔area あり〕のみ・BGP=出さない）。ハイライトは segment と統一: **楕円/スポークに hover で IF 名 + IP ラベル**、**クリックでサブネット連動選択**（親デバイス自動選択＋表行連動）。凡例に **loopback / スタブ** 専用項目（クリックで該当群を強調）、表示ノードパネルで個別非表示可、**ツールバーの loopback / スタブ チェックボックスでカテゴリ全体を一括表示/非表示**（セグメント・外部ピアと同様）。
- **表ビュー**（上部タブ）: `ADDRESSES`（インターフェース集約・IP 一覧）・`INTERFACES`（インターフェース詳細・状態・速度・description）・`CHECKS`（設計検証パネル：重複 IP・OSPF/BGP router-id 重複・MTU 不一致・BGP local_ip 未解決・到達不可 next_hop・OSPF area0 非接続・RR 不在 iBGP の full-mesh 欠落・OSPF area 不一致 等の設計上の注意点を severity / kind / message / refs でリスト表示。0 件なら「問題は検出されませんでした」）・`SUBNETS`（v4 サブネット使用率集約：subnet / usable / used / free / util% / status を使用率降順で表示。util≥80% は exhausted 強調。/32・link-local 除外。ADDRESSES の IP 一覧に対しサブネット集約・枯渇監視で差別化）。`DIFF`（条件付き：`--diff-against` 指定時のみ表示 — 前回との差分を devices/interfaces/links/segments/routing_bgp/routing_ospf/routing_static の固定順で added(+)/removed(-)/changed(~) のセクションと件数サマリで表示。差分ゼロなら「差分なし」を明示）。
- **検索ボックス**: 自由文字列 / 演算子（`host:`/`ip:`/`desc:`/`as:`/`vendor:`/`net:`）で絞り込み。0 件警告（赤）。`/` または `Ctrl+F` で検索欄へフォーカス。
- **選択モデル**: クリックで機器・セグメント・ネイバーを選択。右欄で詳細・リンク一覧・ルーティング情報を表示（複数選択時は選択ノード間リンク）。
- **ノードドラッグ**: セッション内でノードを再配置可（リロードで初期配置に戻る）。
- **フォーカス（隣接フォーカスモード）**: 「フォーカス」ボタン（図ビュー専用）でトグル ON かつノード選択中のとき、選択ノードの N-hop（既定 1-hop）隣接サブグラフ以外を淡色化（dim）して文脈を残しつつ注目範囲を強調する。「接続先のみ」が非隣接を**非表示**にするのに対し、フォーカスは**淡色化**で差別化（既定 OFF）。
- **URL 共有**: 現在のビュー（タブ）と選択ノードを URL ハッシュ（`#v=bgp&n=r1,r2` 形式）に自動保存する。その URL をコピーして共有・ブックマークすると、開いた相手も同じビューと選択状態が復元される。ノード id は `encodeURIComponent` でエンコードされるため `:` や `/` を含む id も安全。生成 HTML 自体には焼き込まれない（同一入力 → 同一バイトの決定性を維持）。
- レイアウトは**決定的 force-directed**（同一 topology → 同一HTML）＋**動的キャンバス**（台数に応じて拡大、〜150台目安）。
- ズーム（ホイール）/パン（ドラッグ）/ホバー強調/F=全体表示・Esc=リセット が動く自己完結 HTML。ショートカット: G=接続先のみ・H=フォーカス・M=ミニマップ・L=凡例（図ビュー専用）・?=ショートカット一覧（`?` で開閉）。

### Phase（履歴）: 再生成時の旧成果物の自動退避
出力は固定パス（`./topology/`・`./topology.html`）に上書きされる。再生成時に既存成果物が存在する場合、
**CLI が自動で `./history/<YYYY-MM-DD_HHMM>/` へ退避する**（手動操作不要）。退避は build と render で独立して発生:
- **build**: `./topology/` に層別 YAML が存在すれば（既定パス運用時は `./topology.html` も同時に）退避。
- **render**: `./topology.html` が存在すれば退避。

退避先は `<now>` = `YYYY-MM-DD_HHMM`。同一タイムスタンプで衝突した場合は `_2, _3…` の連番で分離（§10.3）。
ユーザーは build → render の順で実行するだけで非破壊（旧成果物は履歴に残る）。

### Phase（クロスレビュー）: HTML 成果物のクロスレビュー（提示前に必須）
HTML 構成図は提示前に**サブエージェントで敵対的にクロスレビュー**する（層別 YAML(topology) と HTML を突合し、
ノード/リンク/ルーティングの欠落・誤接続・ラベル不整合・描画崩れを洗い出す）。指摘があれば修正してから提示する。

## 差分レポート（2 つの topology を比較）

2 時点の層別 YAML（`topology/` ディレクトリ）を比較し、Markdown レポートを出力する。
`diff_topology.py` は `load_topology` を使うため参照整合検証付き。

```bash
# stdout に出力
python3 "$SKILL/scripts/diff_topology.py" topology-old/ topology-new/

# ファイルに保存
python3 "$SKILL/scripts/diff_topology.py" topology-old/ topology-new/ -o diff_report.md
```

レポートには各セクション（devices / interfaces / links / segments / routing_bgp / routing_ospf / routing_static）の
件数サマリ `+N -M ~K` と added(+)/removed(-)/changed(~) 行が含まれる。差分ゼロなら「差分なし」を明示。
**決定性**: 時刻・乱数に依存せず、同一入力→同一レポート。

## トラブルシューティング

### `[WARN] <name>: skipped (unknown vendor)` が出る
対応ベンダーは **Cisco IOS / IOS-XE running-config** と **Juniper JunOS（set 形式）** のみ。
`detect_vendor()` が判定に失敗したファイルはスキップされる。主な原因と対処:
- `show` コマンド出力や設定の抜粋のみ → **running-config 全文**（IOS）/ **set 形式**（JunOS）で保存し直す。
- 別ベンダー（NX-OS / Arista 等）→ v1 はスコープ外（「拡張の指針」のベンダー追加を参照）。
- 設定行が無い・文字化け → ファイルの中身とエンコーディング（UTF-8）を確認する。

### `./workspace/` に置いたのに「config が見つからない」
`paths` 省略時は `./workspace/` 配下の `*.cfg *.conf *.txt` だけを走査する。対象が無い場合、
stderr に `[WARN] 対象 config が見つかりません（拡張子: .cfg/.conf/.txt）` が出る。
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
- **ベンダー追加**: `lib/parsers/<vendor>.py` に `parse_<vendor>()` を実装し、`lib/parsers/__init__.py` の `detect_vendor()` と `parse_config()` に分岐を追加
  （`references/vendor-parsing.md` の手順）。正規化モデルに合わせるだけでスキーマ・build・render は変更不要。
- **プロトコル/レイヤー追加**: topology の `routing` にキーを足す（新 `routing.<proto>.yaml` 層が増える）、または
  `devices[].sections` に汎用テーブルを足す。`routing.bgp`/`routing.ospf` があれば対応する図タブ（BGP/OSPF）が自動生成される（`lib/rendering/tabs.py`）。それ以外の汎用プロトコルは v1 ではタブ生成をスキップする（§9.3 の拡張余地。`tabs.py` に分岐を足して対応）。
- **結線手段追加**: `links[].kind` に新しい由来（例 `neighbor-cdp`）を足す。

## 検証
開発資産（`$SKILL/dev/tests/`・`$SKILL/dev/examples/`・`$SKILL/dev/pytest.ini`）はスキルの実行時には不要で、
保守者向け（ユニットテスト・E2E・ゴールデン出力）。
```bash
cd "$SKILL/dev" && python3 -m pytest -q          # ユニットテスト
# E2E:
python3 "$SKILL/scripts/build_topology.py" "$SKILL/dev/examples/configs/sample-ios-r1.cfg" "$SKILL/dev/examples/configs/sample-junos-r2.conf" -o ./topology
python3 "$SKILL/scripts/render_topology.py" ./topology -o ./topology.html
```
`$SKILL/dev/examples/topology/`（層別 YAML）は 2 つのサンプル config から生成される期待出力（ゴールデン）。
