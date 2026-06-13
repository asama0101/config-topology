# config-topology

ネットワーク機器の running-config（テキスト）から、機器間の接続関係を自動推論し、レイヤー別 YAML（正本）を経て**インタラクティブな HTML 構成図**を生成する Claude Code スキル。

`Cisco IOS / IOS-XE` ・ `Juniper JunOS (set)` / `Python 3 + PyYAML` / 自己完結 HTML 出力 / 決定的・再現可能

## 特徴

- **マルチベンダー自動判定** — Cisco IOS/IOS-XE running-config と Juniper JunOS（set 形式）を自動判定し、複数機器を一括処理。
- **結線の自動推論** — 各インターフェースの IP / サブネット一致でリンクを推論（2 機器=リンク、3 機器以上=共有セグメント、単独=スタブ）。`shutdown` を含むリンクは admin_down として区別。BGP は対向を解決して ebgp/ibgp を判定し、config 内に対向が無い外部ピアも片側オーバーレイで描画。
- **IPv4 / IPv6 デュアルスタック** — インターフェースの全アドレス（v4/v6・secondary 含む）を正本として保持し、OSPF / static の v6 ルーティングにも対応。
- **編集可能なレイヤー別 YAML 正本** — 中間表現は人手で補正・注記できる層別 YAML。読込時に ID 参照整合を検証し、再描画する round-trip が可能。再生成時は旧成果物を `./history/<日時>/` へ自動退避。
- **自己完結・決定的な HTML 出力** — 外部依存ゼロ・`file://` で開ける単一 HTML。図ビュー（物理 / BGP / OSPF）と表ビュー（ADDRESSES / INTERFACES）の切替、演算子つき検索（`host:` / `ip:` / `as:` / `net:` 等）、ノード選択・ドラッグ、ズーム/パンに対応し、同一入力 → 同一出力。

## 入力 / 出力

| | パス | 内容 |
|---|------|------|
| 入力 | `./workspace/*.{cfg,conf,txt}` | 機器の running-config（複数機器を一括） |
| 出力① | `./topology/` | レイヤー別 YAML 正本（`_meta.yaml` / `devices.yaml` / `physical.yaml` / `routing.*.yaml`） |
| 出力② | `./topology.html` | 自己完結のインタラクティブ HTML 構成図 |

## 使い方

本ツールは **Claude Code のスキル**です。手動で CLI を叩く前提ではなく、Claude に自然言語で依頼して起動します。

- `./workspace/` に config（`.cfg / .conf / .txt`）を置く、または
- 「このconfigから構成図を作って」「トポロジー図を描いて」「ネットワーク図にして」等と Claude に依頼する。

Claude が `SKILL.md` に従い、収集・判定 → build（層別 YAML 生成）→ 確認 → render（HTML 生成）→ クロスレビューの順で実行します。

## 依存

Python 3 と **PyYAML** のみ（pure Python）。多くの環境では PyYAML は既に利用可能です。

## ドキュメント / コード実体

コードの実体はスキルバンドル `$SKILL`（= `.claude/skills/config-topology/`）配下にあります。詳細は以下を参照してください。

- [`$SKILL/SKILL.md`](.claude/skills/config-topology/SKILL.md) — スキル仕様・実行フロー
- [`$SKILL/references/schema.md`](.claude/skills/config-topology/references/schema.md) — 層別 YAML / topology スキーマ・ID 採番規則
- [`$SKILL/references/link-inference.md`](.claude/skills/config-topology/references/link-inference.md) — サブネット結線推論・BGP 対向解決のルール
- [`$SKILL/references/vendor-parsing.md`](.claude/skills/config-topology/references/vendor-parsing.md) — ベンダー別パース要点・新ベンダー追加手順

> **機密情報の注意**: config の `interface description` 等の自由記述は、そのまま層別 YAML・`topology.html` に出力されます（パーサは password / secret / snmp community 行自体はパースしません）。生成物の共有・保存時は取り扱いに注意してください。
