# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このリポジトリの正体
ネットワーク機器の running-config（Cisco IOS/IOS-XE、Juniper JunOS set 形式）から
インタラクティブな HTML トポロジー図を生成する **`config-topology` スキル** のリポジトリ。
コードの実体はほぼ全て `.claude/skills/config-topology/`（以下 `$SKILL`）配下にある。
ルート直下はスキルの入出力ワークスペース:
- `workspace/` … 入力 config（`*.cfg *.conf *.txt`）
- `topology/` … 中間表現（レイヤー別 YAML 正本）= 出力①（`raw_config.yaml` は生 config 保持時のみ・CONFIG ビュー用）
- `topology.html` … 自己完結 HTML 構成図 = 出力②
- `history/<YYYY-MM-DD_HHMM>/` … 再生成前に退避した旧成果物

エンドユーザー操作としてスキルを動かす手順は `$SKILL/SKILL.md` が正本。本ファイルは
**開発・保守者**向けの索引。

## アーキテクチャ（3層パイプライン）
```
workspace/*.{cfg,conf,txt}
  → scripts/parse_configs.py    ベンダー自動判定 → 正規化モデル Device（ベンダー中立 dataclass）
  → scripts/build_topology.py   IP/サブネット一致でリンク・セグメント推論、BGP 対向解決
  → topology/ (層別 YAML 正本)   ← 各層の境界。lib/topology_io.py が dict ⇄ YAML を相互変換し参照整合を検証
  → scripts/render_topology.py  SVG + バニラ JS の自己完結 HTML を出力
```
各層は単一責務で、層間の唯一の契約は **topology dict / 層別 YAML**。スキーマは
`references/schema.md`、結線推論は `references/link-inference.md`、ベンダー解析は
`references/vendor-parsing.md` が正本。コードを読む前にこの3つを読むのが最短。

把握に複数ファイルを要する勘所:
- **正規化モデル `lib/models.py` の `Device`・`Address`・`BgpNeighbor` 等** がパイプライン全体の中心
  （`Device.as_` フィールドは YAML 出力時に `as` に変換）。パーサはここに正規化し、build / render はこのモデル
  （→ topology dict）しか見ない。新ベンダーはこのモデルに合わせるだけ。
- **パーサ registry `lib/parsers/__init__.py`**: `detect_vendor()` / `parse_config()` の特異度が高い順に試行（JunOS→IOS）。
  どれも detect しなければ `None`（クラッシュしない＝未知ベンダーはスキップ）。
- **IP は interface に帰属**し機器に直接持たせない（実機と同じ構造）。物理層
  （devices/interfaces/links/segments）と論理層（routing）を分離し、render がレイヤートグルで重ねる。
  OSPF interface パラメータ（cost/network_type/passive）も IF 帰属で `interfaces[].ospf`（任意・設定時のみ出力）。
- **結線は IP/サブネット一致のみ**で推論（v1 は CDP/LLDP 非使用）。同一サブネットの IF が
  2 = `link`、3 以上 = `segment`、1 = スタブ。link-local（fe80::/10）は結線から除外。
- **dual-stack**: `interfaces[].addresses`（`[{af,ip,prefix,secondary?,scope?}]`）が IP の正本。
  `interfaces[].ip` は最初の非 secondary v4 から派生する後方互換フィールド（§4.1）。
- **render の実体は `lib/rendering/`**（`render_topology.py` は薄い CLI）。CSS/JS 定数 `_CSS`/`_BODY`/`_JS`
  は `assets.py`（設計検証パネル描画 `renderChecksView`・差分ビュー描画 `renderDiffView`・生 config 閲覧/比較/編集ワークベンチ描画 `renderConfigView`/`renderCfgSplit`〔CONFIG タブ・図連動なし・機密警告バナー。`DATA.raw_configs`/`parse_status`/`raw_configs_prev` 参照。ユーティリティ（`copyText`・折返し `S.configWrap`・grep `S.configGrep`・検索ナビ `cfgHitIdx`）・parse 状態 3 色分け `S.configParse`〔`.ps-parsed/ignored/unparsed`・未対応のみ `S.configUnparsedOnly`〕・2ペイン比較 `S.configSplit`〔**読取専用**・source `dev:/prev:/scratch:`・原本保持は `cfgTextOf`〔scratch のみ編集バッファ参照〕・行整列 `lineAlign`〔LCS 順序付き ops・同一テキスト早道・`n*m>=4e6` で省略〕→ 比較は対称整列 `cfgSymRows`（両ペイン同数＋空行ギャップ）・行 HTML は `cfgLineHtml`〕・ノード駆動編集 `renderCfgEdit`/`S.configEdit`〔`data-cfgtoggle="edit"`・選択機器を 編集前(左=`dev:`原本/読取専用) vs 編集中(右=`scratch:`/textarea) の固定2ペイン・source ドロップダウンなし・split と排他・左を右 textarea にライブ整列 `cfgEditLeftRows`〔追加=空行ギャップ `.cfgline.gap`・削除=行非消費の境界マーカー `.del-above[data-del]`/末尾 `.cfgdelmark`〕・編集スクラッチ `S.configScratch`〔localStorage〕・リテラル全置換 `data-cfgreplace`・ライブ差分 `updateCfgSplitDiff`（編集左のみ再描画・縦スクロール同期 `_cfgScrollLock`）〕・ペイン source 解決ヘルパ `cfgPaneKey`〔select 優先→`data-cfgkey` フォールバック・保存/置換/コピーで共通〕〕・隣接フォーカス `nHopNeighbors`/`S.focusMode`・URL ハッシュ状態 `encodeState`/`decodeState`・degree 連動ノードサイズ `nodeScale`・データ駆動凡例 `presentAreas`/`presentASes`・リンクラベル法線オフセット `edgeNormalOffset`・ラベル省略表示 `truncateLabel`/`nodeLabelMaxChars`・キーボードショートカット `keyToAction`/`toggleShortcutsOverlay`（g/h/m/l/?・図ビュー専用＋ヘルプ overlay）含む）、
  データ変換・設計検証（`build_checks`→`DATA.checks`・OSPF area 不一致 `ospf_area_mismatch` 含む）・**STATIC 図ビュー（スタティック経路フォワーディング・シミュレーション）**〔FIB 構築 `build_fib`→`DATA.fib`（protocol 非依存の最終 RIB＝connected＋static・将来 OSPF/BGP best-path を同形で流し込む拡張点）・next-hop 解決 `_resolve_next_hop`（host/サブネット/dangling/blackhole/IF名 P2P・`_build_host_ip_index`/`_build_subnet_index` 索引を iBGP/dangling チェックと共用）・オーバーレイ `build_static_edges`→`DATA.static_edges`/`build_static_stubs`→`DATA.static_stubs`・JS は純関数トレース `evalNode`/`traceForward`/`ipInCidr`/`ip6ToBig`〔LPM・verdict delivered/blackhole/unreachable-nexthop/no-route/loop・ECMP 先頭〕・トレース UI `runTrace`/`syncTraceControls`・`S.trace`・結果 `renderTraceResult`・方向矢じり marker `#se-arrow`・`tabs.py` で `routing.static` 非空時に STATIC タブ〕・stub / loopback ノード（`build_stub_nodes`→`DATA.stub_nodes`・Physical/OSPF 両ビューで segment 様式ノード描画〔`data-elem="seg"`・`lpId`/`segById`/`STUB_BY_ID`〕・色で区別〔`.lpnode`/`.stubnode`〕・クリックで `setHotNet` subnet 連動選択・IF/IP ラベルは **loopback/stub 自身**の選択/hover/hot 時のみ表示〔`showIf`・親機器選択には連動しない〕・DEVICE DETAILS の IF 行からも選択可〔`stubNetForDetail`→行 `data-net`〕・専用凡例・カテゴリ全体トグル `S.filters.lo`/`stub`〔`#f-lo`/`#f-stub`・`stubFiltered`〕）・生 config pass-through（`topo["raw_configs"]`→`DATA.raw_configs`・CONFIG タブは `has_config` 条件付き）・接続数（`_compute_degrees`→`DATA.devices[].degree`）は
  `data_transform.py`、決定的レイアウトは `layout.py`（AS クラスタリング初期配置 `cluster_order`・AS グループ化ヘルパ `_group_by_asn`・force/hierarchical 切替 `compute_positions(mode=)`＋階層グリッド `_hierarchical_positions`（`--layout hierarchical`）含む）、ビューロジックは `tabs.py`、
  テンプレート組立は `template.py` にそれぞれ分離。CSS/JS や色を直すときは `assets.py` を見る。

## 不変条件（変更時に壊さないこと）
- **決定性**: 乱数・時刻に依存せず、同一入力 → 同一の層別 YAML → 同一 HTML。
  テスト・diff・eval がこの前提に依存する（render の force-directed レイアウトも決定的）。
  **唯一の例外**: history 退避ディレクトリ名は YYYY-MM-DD_HHMM の時刻依存（再現性なし）。
  実行サマリー（`lib/run_summary.py`）も同様。ただし層別 YAML と HTML の出力は決定的（§9.1）。
- **加算的拡張**: 新プロトコルは `routing.<proto>` キー追加、新由来リンクは `links[].kind`、
  機器固有情報は `devices[].sections`。既存フィールドの意味・型は変えない（変えるときのみ
  `_meta.yaml` の `schema_version` をバンプ）。
- **参照整合**: `topology_io.load_topology` が device/interface ID の dangling 参照を
  ファイル名・フィールド・値付きの `ValueError` で弾く。層別 YAML を手編集したらこの検証を通すこと。
- **依存は PyYAML のみ**（pure Python）。`yaml.safe_load`/`safe_dump` のみ使用。`python3` を使う。

## 開発コマンド
スキルバンドル配下で作業する。テストは `$SKILL/dev/` から実行する。
```bash
SKILL=".claude/skills/config-topology"

# ユニット/統合/E2E テスト（pytest.ini は dev/ にある。testpaths=tests）
cd "$SKILL/dev" && python3 -m pytest -q
# 単一テストファイル / 単一テスト
python3 -m pytest tests/test_parsers.py -q
python3 -m pytest tests/test_build_topology.py::TestSubnetLinks::test_xxx -q
# マーカー絞り込み（unit / integration / e2e）
python3 -m pytest -m unit -q

# E2E（2つのサンプル config からゴールデン出力を再生成して描画）
python3 "$SKILL/scripts/build_topology.py" \
  "$SKILL/dev/examples/configs/sample-ios-r1.cfg" \
  "$SKILL/dev/examples/configs/sample-junos-r2.conf" -o ./topology
python3 "$SKILL/scripts/render_topology.py" ./topology -o ./topology.html

# パイプライン実行（保守時のスポットチェック）
python3 "$SKILL/scripts/parse_configs.py" <path1> [path2...]   # 正規化 Device を JSON 出力
python3 "$SKILL/scripts/build_topology.py" <path1> [path2...] -o ./topology   # paths 指定時、または省略で workspace/ を走査
python3 "$SKILL/scripts/render_topology.py" ./topology -o ./topology.html
# --diff-against <prev_dir> を付けると前回トポロジーとの差分を HTML の DIFF ビューに表示（diff_topology を埋め込み）
# --diff-against-history は直近 history/<ts>/ の層別YAMLを自動選択して差分表示（latest_history_topology。--diff-against 優先）

# 差分レポート（パイプライン外の独立ツール。2つの層別 YAML を比較し Markdown 出力。決定的・時刻非依存）
python3 "$SKILL/scripts/diff_topology.py" old_topology/ new_topology/ [-o diff.md]   # lib/diff.py が本体
```
`$SKILL/dev/examples/topology/` は 2 サンプル config から生成される期待出力（ゴールデン）。
`scripts/diff_topology.py`（→ `lib/diff.py`）は 3層パイプライン外の独立ツールで、`load_topology` で読んだ2つの topology dict を比較する（build/render に非依存・出力本文は時刻非依存）。
実装では rebuild により `lib/history.py`（history 退避・`latest_history_topology` で直近 history 解決）・`lib/run_summary.py`（実行サマリー集約）が追加。

## 機密情報の注意
config の `interface description` 等の自由記述はそのまま層別 YAML・`topology.html` に出力される
（password/secret/snmp community 行自体はパースしない）。**加えて CONFIG ビュー（`raw_config.yaml`）は
running-config 全文を原本のまま保持・表示するため、password/secret/snmp community/鍵 等の機密行そのものが
`raw_config.yaml` と `topology.html` に平文で載る**（UI に警告バナー・ユーザーが明示的に受容した設計）。
ファイル権限は他の層別 YAML 同様 umask 依存。生成物の共有・保存時は取り扱い注意。
