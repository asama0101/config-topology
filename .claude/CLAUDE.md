# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このリポジトリの正体
ネットワーク機器の running-config（Cisco IOS/IOS-XE、Juniper JunOS set 形式）から
インタラクティブな HTML トポロジー図を生成する **`config-topology` スキル** のリポジトリ。
コードの実体はほぼ全て `.claude/skills/config-topology/`（以下 `$SKILL`）配下にある。
ルート直下はスキルの入出力ワークスペース:
- `workspace/` … 入力 config（`*.cfg *.conf *.txt`）
- `topology/` … 中間表現（レイヤー別 YAML 正本）= 出力①
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
  は `assets.py`（stats ビュー描画 `renderStatsView`・設計検証パネル描画 `renderChecksView`・隣接フォーカス `nHopNeighbors`/`S.focusMode` 含む）、
  データ変換・構成統計集計（`build_stats`→`DATA.stats`）・設計検証（`build_checks`→`DATA.checks`）は
  `data_transform.py`、決定的レイアウトは `layout.py`（AS クラスタリング初期配置 `cluster_order` 含む）、ビューロジックは `tabs.py`、
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

# 差分レポート（パイプライン外の独立ツール。2つの層別 YAML を比較し Markdown 出力。決定的・時刻非依存）
python3 "$SKILL/scripts/diff_topology.py" old_topology/ new_topology/ [-o diff.md]   # lib/diff.py が本体
```
`$SKILL/dev/examples/topology/` は 2 サンプル config から生成される期待出力（ゴールデン）。
`scripts/diff_topology.py`（→ `lib/diff.py`）は 3層パイプライン外の独立ツールで、`load_topology` で読んだ2つの topology dict を比較する（build/render に非依存・出力本文は時刻非依存）。
実装では rebuild により `lib/history.py`（history 退避）・`lib/run_summary.py`（実行サマリー集約）が追加。

## 機密情報の注意
config の `interface description` 等の自由記述はそのまま層別 YAML・`topology.html` に出力される
（password/secret/snmp community 行自体はパースしない）。生成物の共有・保存時は取り扱い注意。
