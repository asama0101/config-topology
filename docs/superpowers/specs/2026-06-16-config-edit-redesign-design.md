# CONFIG タブ 編集機能の見直し — 設計 (spec)

- **日付**: 2026-06-16
- **対象**: config-topology スキル / render 層（`lib/rendering/`）の CONFIG ビュー「ノード駆動編集」モード
- **状態**: ユーザー承認済み（動くモックアップ `config-edit-mockup.html` で UI 確定）

## 1. 背景と課題
CONFIG タブの「ノード駆動編集」モード（`renderCfgEdit` / `cfgEditLeftRows`）は、左=編集前(原本/読取専用)・右=編集中(textarea) を**行ごとに整列**して差分表示する。これが見づらい。根本原因:

- **textarea は行を空けられない** → 削除行を「細いピルマーカー（`−N行`）」で表現するしかなく、行内編集（旧行削除＋新行追加）が「ピル＋緑行」にバラけて差分を追いにくい。
- 編集面と差分面が同一ペインに混在し、整列ロジック（`cfgEditLeftRows` のギャップ行・境界マーカー）が複雑。

加えて、保存/エクスポート導線が弱い（localStorage 自動保存が無表示・DL 不可・「元に戻す」なし）。

## 2. 解決方針（確定）
**編集する面と差分を見る面を分離する。** 編集は普通の textarea に専念させ、差分は別ペインに **git 風の統一差分（unified diff・全行色付き・読取専用）** でライブ表示する。削除も追加も「行まるごと」で出せるため、ピルマーカーと整列ハックが不要になる。

レイアウト = **編集（左）＋ 統一差分プレビュー（右）の横並び**（ユーザー選択）。

## 3. 確定スコープ（決定事項）

### 3.1 差分モデル
- **行単位のみ**：`same` / `add` / `del` の 3 種（既存 `lineAlign` の LCS ops と同形）。
- **「変更(~)」カテゴリは廃止**。行内で文字を直した場合も「旧行を削除(−)＋新行を追加(+)」として表示。
- **文字単位ハイライト（intra-line）は不要**（変更行が存在しないため）。

### 3.2 編集モードのレイアウト（`renderCfgEdit` を全面刷新）
- **左ペイン＝編集**：行番号ガター＋ textarea（`scratch:<dev>`）。差分都合を一切気にせず自由編集。ガターは textarea とスクロール同期。
- **右ペイン＝統一差分プレビュー（読取専用）**：`vs dev:<dev>`（原本）。git 風の全行表示:
  - `same` → コンテキスト行（グレー・原本行番号付き・無印）
  - `del`  → 赤の全行（`−`・原本行番号）
  - `add`  → 緑の全行（`+`・行番号なし）
  - ops 出現順（unified 順）に並べる。
- カーソル行ハイライト：textarea のカーソル行（after-line index）に対応する差分行（`data-b` 一致）と左ガター行を強調。

### 3.3 保存/エクスポート導線
- **ダウンロード**：現在の機器のみ。編集後全文を `<host>.cfg` として Blob ダウンロード（`URL.createObjectURL`＋`<a download>`・依存ゼロ・`file://` 動作）。ファイル名は当該 device の表示名/ID から導出。
- **コピー改善**：既存 `copyText` を流用しつつ、ボタンを明示し「✓ コピーしました」のトーストフィードバックを出す。
- **dirty バッジ**：scratch が原本と異なる機器に「●」を機器リスト／ツールバーに表示。
- **元に戻す**：scratch（localStorage の該当キー）を破棄し原本に戻す。

### 3.4 編集ペイン操作性
- 編集側（textarea）にも**行番号ガター**（スクロール同期）。
- **編集中行ハイライト**（カーソル行を差分側＋ガターで強調）。
- 編集前/編集中の行位置整列の課題は、統一差分プレビューへの分離により解消（`cfgEditLeftRows` のギャップ/境界マーカー方式は撤去）。

### 3.5 文字列置換
- 既存の**リテラル全置換**（`data-cfgreplace`）を新編集モードのツールバーにも維持。置換件数のトースト表示を追加。

### 3.6 スコープ外（今回触らない）
- **2ペイン比較（読取専用 COMPARE）モード**（`renderCfgSplit` / `cfgSymRows`・source ドロップダウン dev/prev/scratch）は現状維持。
- parse 状態 3 色分け・grep・未対応抽出・閲覧モードは現状維持。
- 複数機器同時編集は対象外（機器は従来どおり1つずつ）。

## 4. アーキテクチャ上の制約（厳守）
- 変更は **render 層のみ**（`lib/rendering/assets.py` の `_CSS`/`_BODY`/`_JS`、必要なら `template.py`）。
- **層別 YAML（golden）は byte 不変**・`schema_version` 据え置き（DATA への新キー追加なし。`DATA.raw_configs` 等の既存データのみ参照）。
- **決定性**：編集/差分/DL/トーストはすべてランタイム状態（localStorage / DOM）で、生成 HTML には焼き込まない。同一入力→同一 HTML を維持。
- **XSS**：行・ファイル名・差分テキストはすべて `esc()` を通す。
- 依存は **PyYAML のみ**（pure Python）。JS はバニラ・自己完結。

## 5. 影響ファイル（想定）
- `lib/rendering/assets.py`
  - `_JS`: 新 `cfgUnifiedRows(before, after)`（unified 行 HTML 生成・純関数）／`renderCfgEdit` 刷新（editor＋unified の2ペイン）／編集側行番号ガター＋スクロール同期／カーソル行ハイライト／`downloadText(name, text)`／dirty 判定ヘルパ／コピー・置換のトースト。**`cfgEditLeftRows` は撤去**。
  - `_CSS`: editor ガター・unified 差分行（ctx/del/add・記号ガター）・dirty バッジ・トースト。旧 `.cfgline.gap`/`.del-above`/`.cfgdelmark` 系は撤去。
  - `_BODY`/`template.py`: ツールバーに DL ボタン（＋既存 revert/replace/copy の配置確認）。
- `dev/tests/test_render_assets.py`: `cfgUnifiedRows` の純関数テスト（same/add/del・順序・esc）／dirty 判定／DL ファイル名導出／node 抽出 eval。**`cfgEditLeftRows` 関連テストは `cfgUnifiedRows` テストへ置換**（テスト削除は要承認）。
- ドキュメント: `SKILL.md`（CONFIG 編集の記述更新）・`.claude/CLAUDE.md`（render 索引の `renderCfgEdit` 記述更新）・`dev/IMPROVEMENT_LOG.md`（エントリ追加）。`references/schema.md` は DATA 不変のため原則更新なし。

## 6. テスト方針
- **純関数（node 抽出 eval）**：`cfgUnifiedRows` が same/add/del を unified 順で正しく生成・行番号・記号・`esc()` 適用。dirty 判定（scratch==原本→false）。DL ファイル名導出。
- **マークアップ存在**：DL ボタン・編集側ガター・unified 差分のクラス（`urow ctx/del/add`）が HTML に出る。`node --check` で JS 構文。
- **不変条件**：層別 YAML byte 不変・HTML 2回生成 byte 一致（決定性）・`<\/` 不正タグ 0・NBSP 混入 0。
- **回帰**：COMPARE モード（`renderCfgSplit`）・閲覧・parse 状態が壊れていないこと。

## 7. レビュー
実装後 `run-reviewers`（5本）＋ HTML 敵対的クロスレビュー。重点: 統一差分の正当性（同一・追加・削除の順序と行番号）・XSS（行/ファイル名 esc）・決定性・golden YAML byte 不変・既存 COMPARE/閲覧モードを壊さないこと・各レビュアーに実コード裏取りを指示。

## 8. リスク
- **撤去するコード/テスト**（`cfgEditLeftRows` とその tests）は本見直しで置換された自前の新規コード。削除はユーザー承認のうえ実施（テスト保護規約）。
- **DL ファイル名**：device 表示名に `/` 等が含まれる場合のサニタイズ（`esc` とは別に拡張子前のファイル名安全化）。
- **大規模 config**：unified は ops 線形で軽量。`lineAlign` の既存スキップガード（`n*m>=4e6`）は流用検討。
