# config-topology 全面刷新 実装指示書

**版** 1.0 | **作成日** 2026-06-13 | **対象仕様** `docs/requirements.md` v2.0

本書は、config-topology システムを 0 から作り直すコーディングエージェント向けの実装指示書である。**何を作るか**は要件定義書（`docs/requirements.md` v2.0、以下「要件書」）が規定し、本書は**どう進めるか**（正本の扱い・実装先・工程・Done 条件・検証手順）を規定する。

---

## 1. 前提と正本

### 1.1 仕様の正本

- **要件書（`docs/requirements.md` v2.0）が唯一の仕様正本**である。本書と要件書が食い違う場合は要件書を優先する。
- 仕様に疑義・曖昧さを見つけた場合は、**推測で実装せず作業を止めてユーザーに質問する**こと。

### 1.2 旧実装の参照ポリシー

- 旧実装は `.claude/skills/config-topology/` 配下にある。
- **旧実装コードのコピー・移植は禁止**。0 からの再実装であり、要件書のみから実装する。
- 例外として、要件書の解釈に疑義が生じた場合に限り、**振る舞いの確認目的で旧実装を読むこと（参照のみ）は許可**する。読んだ結果と要件書が食い違う場合は実装に反映せず、ユーザーに報告する。
- **旧ゴールデン（`.claude/skills/config-topology/dev/examples/topology/`）は古いスキーマ（`addresses` 欠落）のため、期待出力として絶対に使用しない**。期待出力は要件書 附録 B のみを用いる。

### 1.3 技術前提

| 項目 | 規定 |
|------|------|
| 言語 | Python（`python3` で実行。pure Python） |
| 外部依存 | **PyYAML のみ**（`yaml.safe_load` / `yaml.safe_dump` のみ使用）。それ以外のサードパーティ依存は追加しない |
| HTML | SVG + バニラ JavaScript を Python から文字列生成（フレームワーク・外部アセット禁止。要件書 §8.1） |
| テスト | pytest（マーカー `unit` / `integration` / `e2e`。要件書 §11.2） |

---

## 2. 実装先とディレクトリ構成

- 実装は**新規ディレクトリ `rebuild/`**（リポジトリルート直下）で行う。既存の `.claude/skills/config-topology/` 配下のファイルには**一切触れない**（読み取りのみ可）。
- 完成・受け入れ後の旧実装置換はユーザーが判断する（本指示書のスコープ外）。

推奨構成（内部構造は裁量。ただし CLI 3 本の名称と引数は要件書 §10.1 に従うこと）:

```
rebuild/
├── scripts/
│   ├── parse_configs.py      # CLI①: 正規化 Device の JSON 出力
│   ├── build_topology.py     # CLI②: 層別 YAML 生成
│   └── render_topology.py    # CLI③: HTML 生成
├── lib/                      # 内部モジュール（構成は裁量）
├── dev/
│   ├── pytest.ini            # testpaths=tests, マーカー定義
│   ├── tests/                # テストコード
│   └── examples/
│       ├── configs/          # 要件書 附録 B.1/B.2 のサンプル config
│       └── topology/         # 要件書 附録 B.3 の期待層別 YAML（ゴールデン）
└── README.md                 # 実行方法の簡潔な説明
```

- `dev/examples/` のサンプル config・ゴールデンは**要件書 附録 B から転記**して作成する（B.3 と完全一致させる。手で改変しない）。

---

## 3. 進め方（共通ルール）

1. **テストファースト**: 各マイルストーンで、要件書の該当節からテストを先に書き、実装で通す（TDD）。
2. **マイルストーンは順番に完了させる**: M1 → M2 → M3 → M4。各マイルストーンの Done 条件をすべて満たしてから次へ進む。
3. **Done の宣言には証拠を付ける**: テスト実行コマンドと出力（passed 数）を提示する。
4. **要件書の節番号をテストに紐付ける**: テストの docstring またはコメントに対応する要件書の節（例: `§6.1 L2/L3 判定`）を記載し、トレーサビリティを確保する。

---

## 4. マイルストーン

### M1: パーサ層（要件書 §2・§4・§6）

**実装範囲**:
- 入力ファイル収集（拡張子・名前順ソート・重複排除・`./workspace/` 既定走査。§2.2）
- ベンダー自動判定（JunOS 50% 超 / IOS 特徴行＋set 40% ガード / 未知スキップ。§2.3）
- ベンダー中立の正規化モデル（機器・IF・addresses・BGP/OSPF/static。§4.1）
- IOS / JunOS の構文マッピング全項目（§6.1・§6.2 の表のすべての行）
- 共通正規化（IPv4/IPv6/CIDR 正規化・OSPF area 正規化・複数値収集・エラーハンドリング。§6.3）
- `parse_configs.py` CLI（JSON を stdout、警告を stderr。§10.1・§10.2）

**Done 条件**:
- [ ] §6.1・§6.2 のマッピング表の**各行に対応する unit テスト**があり、すべて合格
- [ ] ベンダー判定の境界テスト（set 行 50% 前後・40% ガード・未知ベンダースキップ）合格
- [ ] OSPF area 正規化テスト（`"0"` 不変・`"0.0.0.0"`→`"0"`・`"1.2.3.4"`→`"16909060"`・`"backbone"` 不変）合格
- [ ] 附録 B.1/B.2 のサンプル config が正しい正規化モデルにパースされる統合テスト合格

### M2: 推論・層別 YAML（要件書 §3・§5・§7）

**実装範囲**:
- ID 採番（device_id 衝突回避・interface_id・segment_id。§5.5）
- サブネット一致の結線推論（メンバー 1/2/3+ の分岐・自己ループ回避・link-local 除外・重複除去。§7.1）
- admin_down 付与（§7.2）、BGP 対向解決・type 判定・片側オーバーレイ（§7.3）、OSPF area 注釈（正規化・スラッシュ連結。§7.4）
- 層別 YAML 書出（ファイル構成・空プロトコル省略・キー辞書順・ブロック表記・UTF-8。§3.2）と読込・参照整合検証（§5.6）
- 決定的出力順（§7.5）
- `build_topology.py` CLI（§10.1・§10.2。history 退避・サマリーは M4）

**Done 条件**:
- [ ] **ゴールデンテスト合格**: 附録 B.1/B.2 を入力した出力が `dev/examples/topology/`（= 附録 B.3）と**全ファイルバイト一致**
- [ ] **決定性テスト合格**: 同一入力 2 回実行で層別 YAML がバイト一致（§11.3）
- [ ] ID 採番の衝突ケース（`r1`,`r1`,`r2` / `R1-2`,`R1` / 空 hostname。§5.5 の例）のテスト合格
- [ ] 参照整合エラーテスト合格: dangling 参照を含む手編集 YAML の読込が、ファイル名・フィールド・値を含むエラーで停止（§5.6）
- [ ] 結線推論の境界テスト（メンバー 1=スタブ / 2=link / 3=segment、shutdown 込み、dual-stack、同一機器内サブネット）合格

### M3: レンダリング（要件書 §8）

**実装範囲**:
- 層別 YAML → 自己完結 HTML（単一ファイル・SVG・バニラ JS。§8.1）
- ビュー生成（Physical / BGP / OSPF / 汎用プロトコル。**static ビューは作らない**。§8.2）
- **ビュー間ノード配置共通化**（§8.2）・決定的レイアウト（§8.3）
- 要素可視化（**IF チップなし**・admin_down 破線・セグメント・AS 枠・外部ピア・凡例。§8.4）
- インタラクション一式（ズーム/パン/fit・キーボード・**選択モデル**・**ノードドラッグ**・検索/各種フィルタ・BGP 連動ハイライト・ホバー/Device Details パネル・テーマ・ミニマップ。§8.5）
- 決定的色規則（§8.6）
- `render_topology.py` CLI（§10.1・§10.2）

**Done 条件**:
- [ ] e2e テスト合格: サンプル config → 層別 YAML → HTML 生成まで通し実行でエラーなし
- [ ] 決定性テスト合格: 同一の層別 YAML から 2 回生成した HTML がバイト一致
- [ ] HTML 構造テスト合格（機械検査）: 生成 HTML に外部リソース参照（`http(s)://` の script/link/img 等）が無い／Physical タブが常に存在し、`routing.bgp[]` 存在時のみ BGP タブ・`routing.ospf[]` 存在時のみ OSPF タブが存在し、`routing.static[]` はタブを生成しない（サンプル config では結果的に Physical・BGP・OSPF の 3 タブ）／IF チップ要素が無い
- [ ] **ブラウザ目視チェック合格**: 要件書 §11.5 のチェックリストを 1 項目ずつ確認し、結果を報告（スクリーンショット添付推奨）

### M4: 運用機能（要件書 §10）

**実装範囲**:
- history 退避の自動化（build: 既存 topology/ ＋既定パスの topology.html をセット退避。render: 既存 HTML 退避。連番サフィックス衝突回避。§10.3）
- 実行サマリー（判定結果・警告件数・生成数・注意喚起。§10.4）
- 終了コード・stdout/stderr 規約の最終確認（§10.2）

**Done 条件**:
- [x] history 退避の integration テスト合格（既存成果物あり→退避して生成 / なし→退避しない / 退避先衝突→連番 / 既定パス運用時に `./topology.html` が存在すれば `./topology/` と**同一退避ディレクトリ**へペア退避、非既定パス時は HTML を巻き込まない）
- [x] 実行サマリーの integration テスト合格（未知ベンダー混在入力で skipped と注意行が出る）
- [x] 終了コードテスト合格（正常 0 / 入出力エラー 1 / 参照整合エラー 1 / 警告のみ 0）

---

## 5. 横断制約（全マイルストーン共通・違反禁止）

1. **決定性**: 成果物（層別 YAML・HTML）の生成に乱数・時刻・環境依存値（ホスト名・cwd 絶対パス等）を使わない。唯一の例外は history 退避ディレクトリ名のタイムスタンプ（§9.1・§10.3）。
2. **機密情報**: `password` / `secret` / `snmp community` 行を読み込まない（§9.2）。`generated_from` は basename のみ（§1.4）。
3. **クラッシュしない**: 個別行のパース失敗・未知ベンダーは警告＋継続。パイプラインを停止してよいのは入出力エラーと参照整合エラーのみ（§10.2）。
4. **依存追加禁止**: PyYAML 以外のサードパーティ依存を入れない。`yaml.safe_load` / `safe_dump` 以外の YAML API（unsafe load 等）を使わない。
5. **スキーマの加算的進化**: 要件書 §5 のフィールド名・型・順序規定を勝手に変えない（§5.7）。
6. **旧実装に触れない**: `.claude/skills/config-topology/` への書込・変更は禁止（§1.2 参照ポリシー）。

---

## 6. 検証手順

### 6.1 マイルストーンごとのテスト実行

```bash
cd rebuild/dev

# 全テスト
python3 -m pytest -q

# マーカー別
python3 -m pytest -m unit -q
python3 -m pytest -m integration -q
python3 -m pytest -m e2e -q

# カバレッジ（目標 80% 以上。§11.4）
python3 -m pytest --cov=../lib --cov=../scripts -q   # pytest-cov が無い環境では coverage 計測は省略可（依存追加はしない）
```

### 6.2 最終 E2E（受け入れ前に必ず実施）

```bash
# 1) ゴールデン一致（§11.1）
python3 rebuild/scripts/build_topology.py \
  rebuild/dev/examples/configs/sample-ios-r1.cfg \
  rebuild/dev/examples/configs/sample-junos-r2.conf -o /tmp/accept-topology
diff -r /tmp/accept-topology rebuild/dev/examples/topology   # 差分ゼロであること

# 2) 決定性（§11.3）
python3 rebuild/scripts/build_topology.py \
  rebuild/dev/examples/configs/sample-ios-r1.cfg \
  rebuild/dev/examples/configs/sample-junos-r2.conf -o /tmp/accept-topology-2
diff -r /tmp/accept-topology /tmp/accept-topology-2          # 差分ゼロであること

# 3) HTML 生成と目視チェック（§11.5）
python3 rebuild/scripts/render_topology.py /tmp/accept-topology -o /tmp/accept-topology.html
# → ブラウザ（file://）で開き、要件書 §11.5 のチェックリストを 1 項目ずつ確認して結果を報告
```

### 6.3 追加シナリオ確認（推奨）

附録 B のサンプルは最小構成（リンク 1 本・セグメントなし・v4 のみ）のため、以下を含むテスト用 config を `dev/tests/` のフィクスチャとして自作し、unit/integration テストでカバーすること。期待値はテストコード内のインライン記述（dict 比較等）で管理し、ファイルゴールデンとしては管理しない（ゴールデンは附録 B 由来の 1 セットのみ）:

- 3 台以上が同一サブネット（segment 生成）
- shutdown IF を含むリンク（admin_down・破線・OSPF area 非付与）
- dual-stack（IPv6 GUA・link-local・secondary）
- OSPF area 不一致リンク（`"0/1"` 連結）と dotted-decimal area
- iBGP・peer_as 不明（unknown）・外部ピア（対向 config なし）
- 未知ベンダーのファイル混在（スキップ＋サマリー注意行）
- hostname 衝突（ID 採番）

---

## 7. 報告様式

各マイルストーン完了時に以下を報告すること:

1. 実装した要件書の節番号一覧
2. テスト実行コマンドと結果（passed/failed 数）
3. Done 条件チェックリストの消し込み状況
4. 要件書に対して発見した疑義・曖昧点（あれば。**勝手に解釈して実装しないこと**）
