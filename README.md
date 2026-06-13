# config-topology

ネットワーク機器の running-config（テキスト）から、機器間の接続関係を自動推論し、レイヤー別 YAML（正本）を経て**インタラクティブな HTML 構成図**を生成する Claude Code スキル。

`Cisco IOS / IOS-XE` ・ `Juniper JunOS (set)` / `Python 3 + PyYAML` / 自己完結 HTML 出力 / 決定的・再現可能

## 概要 / できること

- **マルチベンダー自動判定** — Cisco IOS/IOS-XE running-config と Juniper JunOS（set 形式）を自動判定し、複数機器を一括処理。
- **結線の自動推論** — 各インターフェースの IP / サブネット一致で機器間リンク・共有セグメントを推論（→「結線推論の考え方」）。
- **IPv4 / IPv6 デュアルスタック** — インターフェースの全アドレス（v4/v6・secondary 含む）を正本として保持し、OSPF / static の v6 ルーティングにも対応。
- **編集可能なレイヤー別 YAML 正本** — 中間表現は人手で補正・注記できる層別 YAML。読込時に ID 参照整合を検証し、再描画する round-trip が可能。
- **自己完結・決定的な HTML 出力** — 外部依存ゼロ・`file://` で開ける単一 HTML。同一入力 → 同一出力（→「HTML 構成図の機能」）。

## アーキテクチャ（3層パイプライン）

```
./workspace/*.{cfg,conf,txt}
   │  scripts/parse_configs.py     ベンダー自動判定 → 正規化モデル Device（ベンダー中立）
   ▼
   │  scripts/build_topology.py    IP/サブネット一致でリンク・セグメント推論、BGP 対向解決
   ▼
./topology/  (層別 YAML 正本)        ← 中間表現（正確性が最優先・人手編集可）
   │  lib/topology_io.py            層別 YAML ⇄ topology dict・参照整合検証
   │  scripts/render_topology.py
   ▼
./topology.html                     SVG + バニラ JS の自己完結 HTML
```

各層は単一責務で、**層間の唯一の契約は層別 YAML（= topology dict）**。`lib/topology_io.py` が dict ⇄ YAML を相互変換し参照整合を検証する。IP は機器ではなく**インターフェースに帰属**させ（実機と同じ構造）、物理層（機器/IF/リンク/セグメント）と論理層（routing）を分離して、render がレイヤートグルで重ねる。

## 結線推論の考え方

- **IP / サブネット一致のみ**で推論（v1 は CDP/LLDP 不使用）。同一サブネットのインターフェースが **2 機器 = リンク**、**3 機器以上 = 共有セグメント**、**単独 = スタブ**。
- `shutdown` を含むリンクは **admin_down** として区別。link-local（`fe80::/10`）は結線から除外（ただし INTERFACES 表・PHYSICAL のデバイス詳細／リンク端ラベルには淡色で表示。ADDRESSES 表からは除外）。
- **BGP** は対向を解決して ebgp / ibgp を判定。config 内に対向が無い外部ピアも片側オーバーレイで描画。
- **dual-stack** は `interfaces[].addresses` が IP の正本（`interfaces[].ip` は後方互換の派生フィールド）。

## 入力 / 出力

| | パス | 内容 |
|---|------|------|
| 入力 | `./workspace/*.{cfg,conf,txt}` | 機器の running-config（複数機器を一括） |
| 出力① | `./topology/` | レイヤー別 YAML 正本（`_meta.yaml` / `devices.yaml` / `physical.yaml` / `routing.*.yaml`） |
| 出力② | `./topology.html` | 自己完結のインタラクティブ HTML 構成図 |

## HTML 構成図の機能

- **図ビュー**（タブ）: `PHYSICAL`（機器 + リンク + セグメント）／`BGP`・`OSPF`（`routing` キーから動的生成）。
- **表ビュー**（タブ）: `ADDRESSES`（インターフェース集約・IP 一覧）／`INTERFACES`（状態・速度・description）。
- **演算子つき検索**: `host:` / `ip:` / `desc:` / `as:` / `vendor:` / `net:`（自由文字列も可）。`/` または `Ctrl+F` で検索欄へフォーカス。
- **操作**: クリックで機器・セグメント・ネイバーを選択（右欄に詳細）／ノードドラッグで再配置／ホイールでズーム・ドラッグでパン／ホバー強調／`F` = 全体表示・`Esc` = リセット。
- **決定的レイアウト**（force-directed・同一入力 → 同一 HTML）。再生成時は旧成果物を `./history/<YYYY-MM-DD_HHMM>/` へ自動退避（非破壊）。

## 使い方

本ツールは **Claude Code のスキル**です。手動で CLI を叩く前提ではなく、Claude に自然言語で依頼して起動します。

- `./workspace/` に config（`.cfg / .conf / .txt`）を置く、または
- 「このconfigから構成図を作って」「トポロジー図を描いて」「ネットワーク図にして」等と Claude に依頼する。

Claude が `SKILL.md` に従い、収集・判定 → build（層別 YAML 生成）→ 確認 → render（HTML 生成）→ クロスレビューの順で実行します。

## 依存

Python 3 と **PyYAML** のみ（pure Python）。多くの環境では PyYAML は既に利用可能です。

## ディレクトリ構成

```
config-topology/
├── README.md
├── .gitignore
├── workspace/                          # 入力 config 置き場（*.cfg/*.conf/*.txt・gitignore）
├── topology/ , topology.html           # 生成物（cwd 直下・gitignore）
├── history/<YYYY-MM-DD_HHMM>/           # 再生成時に旧成果物を自動退避（gitignore）
├── docs/
│   ├── requirements.md                 # 仕様正本（v2.1）
│   ├── design-sample.html              # UI 設計の正本
│   └── archive/                        # 完了した構築プロセス成果物（指示書・計画）
└── .claude/
    ├── CLAUDE.md                       # 開発・保守者向けの索引
    └── skills/config-topology/         # スキル本体（= $SKILL）
        ├── SKILL.md                    # スキル仕様・実行フロー（利用者向け正本）
        ├── requirements.txt            # 依存（PyYAML）
        ├── references/                 # schema / link-inference / vendor-parsing
        ├── scripts/                    # CLI 3 本（parse_configs / build_topology / render_topology）
        ├── lib/                        # 実装本体
        │   ├── parsers/                # ベンダー判定・正規化（registry __init__ / ios / junos / base）
        │   ├── rendering/              # HTML 生成（assets / data_transform / layout / tabs / template）
        │   ├── models.py               # 正規化モデル（Device / Address / 等）
        │   ├── inputs.py , normalize.py , idgen.py
        │   ├── build.py , topology_io.py   # 結線推論 / 層別 YAML I/O・参照整合
        │   └── history.py , run_summary.py # 履歴退避 / 実行サマリー
        └── dev/                        # 保守者向け（tests / examples ゴールデン / pytest.ini）
```

入出力（`workspace/`・`topology/`・`topology.html`・`history/`）はすべて**ホスト cwd 直下**で、`.gitignore` 済み（`workspace/.gitkeep` のみ追跡）。

## ドキュメント / コード実体

コードの実体はスキルバンドル `$SKILL`（= `.claude/skills/config-topology/`）配下にあります。詳細は以下を参照してください。

- [`$SKILL/SKILL.md`](.claude/skills/config-topology/SKILL.md) — スキル仕様・実行フロー
- [`$SKILL/references/schema.md`](.claude/skills/config-topology/references/schema.md) — 層別 YAML / topology スキーマ・ID 採番規則
- [`$SKILL/references/link-inference.md`](.claude/skills/config-topology/references/link-inference.md) — サブネット結線推論・BGP 対向解決のルール
- [`$SKILL/references/vendor-parsing.md`](.claude/skills/config-topology/references/vendor-parsing.md) — ベンダー別パース要点・新ベンダー追加手順

> **機密情報の注意**: config の `interface description` 等の自由記述は、そのまま層別 YAML・`topology.html` に出力されます（パーサは password / secret / snmp community 行自体はパースしません）。生成物の共有・保存時は取り扱いに注意してください。
