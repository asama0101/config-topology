# CONFIG 編集の見直し（編集＋統一差分・横並び）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CONFIG タブのノード駆動編集を「編集（左: textarea＋行番号）＋ 統一差分プレビュー（右: 読取専用 git 風 diff）」の横並びに刷新し、DL/コピー/dirty/元に戻す導線を加える。

**Architecture:** 変更は render 層（`lib/rendering/assets.py` の `_CSS`/`_JS`）のみ。編集面と差分面を分離し、差分は `lineAlign` の ops（same/del/add）を unified 順に全行レンダリング（新 `cfgUnifiedRows`）。旧整列方式 `cfgEditLeftRows`（ギャップ行・境界マーカー）を撤去。層別 YAML（golden）は byte 不変、生成 HTML は決定的（編集状態は localStorage / DOM のランタイムのみ）。

**Tech Stack:** Python 3（pure・PyYAML のみ）、バニラ JS（`assets._JS` 内）、pytest（node 抽出 eval ＋ 文字列存在検証）、`node --check`。

**作業前提:** ブランチ `feat/config-edit-redesign` で作業（spec は同ブランチにコミット済み）。テストは `cd .claude/skills/config-topology/dev && python3 -m pytest` で実行。`SKILL=".claude/skills/config-topology"`。

---

## 影響ファイル（File Structure）

- **Modify** `.claude/skills/config-topology/lib/rendering/assets.py`
  - `_JS`: 追加 `cfgUnifiedRows(before,after,q)` / `cfgFileName(host)` / `downloadText(name,text)` / `cfgIsDirty(cur)` / `updateCfgEditDiff(ta)`。刷新 `renderCfgEdit(q,cur)`。撤去 `cfgEditLeftRows`。`updateCfgSplitDiff` の edit 分岐・編集トグル dispatch・DL/revert dispatch・機器リスト dirty バッジ。
  - `_CSS`: 追加 `.urow`/`.urow .ug`/`.urow .us`/`.urow .utx`/`.urow.ctx`/`.urow.del`/`.urow.add`/`.urow.cur`、編集側行番号ガター `.cfgedit-gut`/`.cfgedit-gut .n`、dirty バッジ `.cfgdirty`。撤去 `.del-above`/`.cfgdelmark`（編集専用）。`.gap`/`.diff-add`/`.diff-del` は COMPARE が使うため**維持**。
- **Modify** `.claude/skills/config-topology/dev/tests/test_render_assets.py`
  - 追加: `cfgUnifiedRows`/`cfgFileName`/`cfgIsDirty` の純関数テスト、DL/revert/badge のマークアップ・dispatch 存在テスト。
  - 撤去/置換: `cfgEditLeftRows` 系テスト（`test_cfg_edit_left_rows_aligns_to_after` 4493 / `test_cfg_edit_left_rows_trailing_deletion_marker` 4504 / `test_render_cfg_edit_markup_aligned` 4455）を unified 版へ。
- **Modify** ドキュメント: `$SKILL/SKILL.md`、`.claude/CLAUDE.md`（render 索引）、`$SKILL/dev/IMPROVEMENT_LOG.md`。

---

## Task 1: `cfgUnifiedRows` 純関数（統一差分行の生成）

**Files:**
- Modify: `.claude/skills/config-topology/lib/rendering/assets.py`（`_JS`・`cfgEditLeftRows` の直後あたりに追加）
- Test: `.claude/skills/config-topology/dev/tests/test_render_assets.py`

- [ ] **Step 1: 失敗するテストを書く**

`test_render_assets.py` に追記（既存ヘルパ `_extract_fn` / `_CFG_ALIGN_STUBS` / `node_bin` フィクスチャを流用）:

```python
def _run_cfg_unified(node_bin, before_js, after_js):
    driver = (
        _extract_fn(assets._JS, "lineAlign") + "\n"
        + _extract_fn(assets._JS, "cfgDiffCounts") + "\n"
        + _extract_fn(assets._JS, "cfgUnifiedRows") + "\n"
        + _CFG_ALIGN_STUBS
        + f'const r = cfgUnifiedRows({before_js}, {after_js}, "");\n'
        + 'process.stdout.write(JSON.stringify(r));\n'
    )
    r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def test_cfg_unified_identical_all_context(node_bin):
    r = _run_cfg_unified(node_bin, '["a","b","c"]', '["a","b","c"]')
    assert r["adds"] == 0 and r["dels"] == 0
    assert r["html"].count('class="urow ctx') == 3
    assert "urow del" not in r["html"] and "urow add" not in r["html"]


def test_cfg_unified_inplace_edit_is_del_then_add(node_bin):
    # 1 行を書き換え → 削除(−)＋追加(+)・unified 順で del が add より先
    r = _run_cfg_unified(node_bin, '["a","desc CORE","c"]', '["a","desc CORE-UP","c"]')
    assert r["adds"] == 1 and r["dels"] == 1
    assert "urow del" in r["html"] and "urow add" in r["html"]
    assert r["html"].index("urow del") < r["html"].index("urow add")


def test_cfg_unified_escapes_html(node_bin):
    r = _run_cfg_unified(node_bin, '["x"]', '["x","<b>&"]')
    assert "&lt;b&gt;&amp;" in r["html"]
    assert "<b>" not in r["html"]
```

- [ ] **Step 2: 失敗を確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k cfg_unified -q`
Expected: FAIL（`_extract_fn` が `cfgUnifiedRows` を見つけられず例外、または node が undefined 関数で失敗）

- [ ] **Step 3: 最小実装を書く**

`assets.py` の `_JS` 内、`cfgEditLeftRows` の定義の**直後**に追加（後続タスクで `cfgEditLeftRows` は撤去するが、本タスクでは既存のまま隣に置く）:

```javascript
function cfgUnifiedRows(before, after, q) {
  const { ops, skipped } = lineAlign(before, after);
  const { adds, dels } = skipped ? { adds: 0, dels: 0 } : cfgDiffCounts(ops);
  const hit = ln => !!q && ln.toLowerCase().includes(q);
  if (skipped) {
    const rows = after.map((ln, i) =>
      `<div class="urow ctx${hit(ln) ? " hit" : ""}"><span class="ug">${i + 1}</span><span class="us"> </span><span class="utx">${esc(ln) || "&nbsp;"}</span></div>`);
    return { html: rows.join(""), adds: 0, dels: 0, skipped: true };
  }
  const rows = [];
  for (const o of ops) {
    if (o.t === "same") {
      const ln = before[o.ai];
      rows.push(`<div class="urow ctx${hit(ln) ? " hit" : ""}" data-b="${o.bi}"><span class="ug">${o.ai + 1}</span><span class="us"> </span><span class="utx">${esc(ln) || "&nbsp;"}</span></div>`);
    } else if (o.t === "del") {
      const ln = before[o.ai];
      rows.push(`<div class="urow del${hit(ln) ? " hit" : ""}"><span class="ug">${o.ai + 1}</span><span class="us">−</span><span class="utx">${esc(ln) || "&nbsp;"}</span></div>`);
    } else {
      const ln = after[o.bi];
      rows.push(`<div class="urow add${hit(ln) ? " hit" : ""}" data-b="${o.bi}"><span class="ug"></span><span class="us">+</span><span class="utx">${esc(ln) || "&nbsp;"}</span></div>`);
    }
  }
  return { html: rows.join(""), adds, dels, skipped: false };
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k cfg_unified -q`
Expected: PASS（3 件）

- [ ] **Step 5: コミット**

```bash
git add "$SKILL/lib/rendering/assets.py" "$SKILL/dev/tests/test_render_assets.py"
git commit -m "feat(render): add cfgUnifiedRows for unified diff preview"
```

---

## Task 2: `cfgFileName` / `downloadText`（ファイル DL 導線）

**Files:**
- Modify: `.claude/skills/config-topology/lib/rendering/assets.py`（`_JS`）
- Test: `.claude/skills/config-topology/dev/tests/test_render_assets.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
def _run_cfg_filename(node_bin, host_js):
    driver = _extract_fn(assets._JS, "cfgFileName") + f'\nprocess.stdout.write(cfgFileName({host_js}));\n'
    r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return r.stdout


def test_cfg_filename_basic(node_bin):
    assert _run_cfg_filename(node_bin, '"r1"') == "r1.cfg"


def test_cfg_filename_sanitizes_unsafe_chars(node_bin):
    # スラッシュ・空白等は _ に置換（パストラバーサル/不正ファイル名回避）
    assert _run_cfg_filename(node_bin, r'"core/sw 1"') == "core_sw_1.cfg"


def test_js_has_download_helper():
    # downloadText は DOM/Blob 依存で単体実行できないため存在のみ検証
    assert "function downloadText(" in assets._JS
    assert "URL.createObjectURL" in assets._JS
```

- [ ] **Step 2: 失敗を確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k "filename or download_helper" -q`
Expected: FAIL（`cfgFileName` 未定義）

- [ ] **Step 3: 最小実装を書く**

`assets.py` の `_JS` 内（`copyText` 近傍のユーティリティ群に）追加:

```javascript
function cfgFileName(host) {
  return String(host).replace(/[^A-Za-z0-9._-]/g, "_") + ".cfg";
}
function downloadText(name, text) {
  const blob = new Blob([text], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(a.href), 500);
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k "filename or download_helper" -q`
Expected: PASS（3 件）

- [ ] **Step 5: コミット**

```bash
git add "$SKILL/lib/rendering/assets.py" "$SKILL/dev/tests/test_render_assets.py"
git commit -m "feat(render): add cfgFileName + downloadText for config download"
```

---

## Task 3: `cfgIsDirty`（編集有り判定）

**Files:**
- Modify: `.claude/skills/config-topology/lib/rendering/assets.py`（`_JS`）
- Test: `.claude/skills/config-topology/dev/tests/test_render_assets.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
def _run_cfg_is_dirty(node_bin, scratch_js, cur_js):
    driver = (
        f'var S = {{ configScratch: {scratch_js} }};\n'
        + 'function cfgRawOf(k){ return "a\\nb\\n"; }\n'   # 原本は常に "a\nb"
        + _extract_fn(assets._JS, "cfgIsDirty") + "\n"
        + f'process.stdout.write(JSON.stringify(cfgIsDirty({cur_js})));\n'
    )
    r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def test_cfg_is_dirty_absent_scratch_false(node_bin):
    assert _run_cfg_is_dirty(node_bin, "{}", '"r1"') is False


def test_cfg_is_dirty_equal_to_original_false(node_bin):
    assert _run_cfg_is_dirty(node_bin, '{"scratch:r1":"a\\nb\\n"}', '"r1"') is False


def test_cfg_is_dirty_changed_true(node_bin):
    assert _run_cfg_is_dirty(node_bin, '{"scratch:r1":"a\\nXX\\n"}', '"r1"') is True
```

- [ ] **Step 2: 失敗を確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k is_dirty -q`
Expected: FAIL（`cfgIsDirty` 未定義）

- [ ] **Step 3: 最小実装を書く**

`assets.py` の `_JS` 内、`cfgTextOf` / `cfgRawOf` 近傍に追加:

```javascript
function cfgIsDirty(cur) {
  if (cur == null) return false;
  const sk = "scratch:" + cur;
  const s = S.configScratch[sk];
  if (s == null) return false;
  return s.replace(/\n$/, "") !== cfgRawOf("dev:" + cur).replace(/\n$/, "");
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k is_dirty -q`
Expected: PASS（3 件）

- [ ] **Step 5: コミット**

```bash
git add "$SKILL/lib/rendering/assets.py" "$SKILL/dev/tests/test_render_assets.py"
git commit -m "feat(render): add cfgIsDirty helper"
```

---

## Task 4: `renderCfgEdit` を「編集＋統一差分」横並びに刷新

**Files:**
- Modify: `.claude/skills/config-topology/lib/rendering/assets.py`（`_JS` 行 2309–2340 を置換）
- Test: `.claude/skills/config-topology/dev/tests/test_render_assets.py`

- [ ] **Step 1: 失敗するテストを書く（旧 `test_render_cfg_edit_markup_aligned` を置換）**

旧 `test_render_cfg_edit_markup_aligned`（行 4455 付近）を削除し、以下を追加:

```python
def test_render_cfg_edit_has_editor_and_unified(node_bin):
    """編集モード = 左 textarea(編集)＋右 unified 差分＋DL/元に戻すボタン。"""
    js = (
        _extract_fn(assets._JS, "lineAlign") + "\n"
        + _extract_fn(assets._JS, "cfgDiffCounts") + "\n"
        + _extract_fn(assets._JS, "cfgUnifiedRows") + "\n"
        + _extract_fn(assets._JS, "renderCfgEdit") + "\n"
        + _CFG_ALIGN_STUBS
        + 'var DATA = { devices: [{ hostname: "r1" }] };\n'
        + 'var S = { configScratch: { "scratch:0": "a\\nB2\\nc\\n" } };\n'
        + 'function cfgTextOf(k){ return k.indexOf("scratch:")===0 ? S.configScratch[k] : "a\\nb\\nc\\n"; }\n'
        + 'function cfgRawOf(k){ return "a\\nb\\nc\\n"; }\n'
        + 'const out = renderCfgEdit("", 0);\n'
        + 'process.stdout.write(out);\n'
    )
    r = subprocess.run([node_bin], input=js, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    html = r.stdout
    assert 'class="cfgedit"' in html            # 左: 編集 textarea
    assert 'data-cfgpane="E"' in html
    assert 'class="cfgunified"' in html         # 右: 統一差分コンテナ
    assert "urow" in html                       # 差分行が描画される
    assert 'data-cfgdl=' in html                # ダウンロードボタン
    assert 'data-cfgrevert=' in html            # 元に戻すボタン
    assert 'data-cfgreplace="E"' in html        # 全置換（編集ペイン対象）
    assert 'data-cfgtoggle="edit"' in html      # 編集トグル（on）
```

- [ ] **Step 2: 失敗を確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k cfg_edit_has_editor -q`
Expected: FAIL（旧 `renderCfgEdit` には `cfgunified`/`data-cfgdl` 等が無い）

- [ ] **Step 3: `renderCfgEdit` を置換**

`assets.py` の `_JS` 内 `renderCfgEdit`（行 2309–2340）を以下で全置換:

```javascript
function renderCfgEdit(q, cur) {
  const host = (DATA.devices[cur] && DATA.devices[cur].hostname) || cur;
  const rKey = "scratch:" + cur;
  const before = cfgRawOf("dev:" + cur).replace(/\n$/, "").split("\n");
  const after = cfgTextOf(rKey).replace(/\n$/, "").split("\n");
  const uni = cfgUnifiedRows(before, after, q);

  const toolbar = `<div class="cfgtools">`
    + `<button class="tbtn on" data-cfgtoggle="edit" title="編集を終了して一覧に戻る">編集</button>`
    + `<span class="cfgdiffsum" data-cfgsum="${esc(rKey)}">+${uni.adds} −${uni.dels}${uni.skipped ? " (差分省略:大規模)" : ""}</span>`
    + `<div class="cfgreplace"><input class="cfgfind" data-cfgpane="E" placeholder="検索文字列" spellcheck="false">`
    + `<input class="cfgrepl" data-cfgpane="E" placeholder="置換文字列" spellcheck="false">`
    + `<button class="tbtn" data-cfgreplace="E" title="検索文字列をすべて置換">全置換</button>`
    + `<span class="cfgreplmsg" data-cfgpane="E"></span></div>`
    + `<span class="sp"></span>`
    + `<button class="tbtn" data-cfgrevert="${esc(cur + "")}" title="編集を破棄して原本に戻す">↩ 元に戻す</button>`
    + `<button class="tbtn" data-cfgdl="${esc(cur + "")}" title="編集後を ${esc(cfgFileName(host))} として保存">⬇ ダウンロード</button>`
    + `<button class="tbtn" data-cfgcopytext="E" title="編集後を全文コピー">📋 コピー</button>`
    + `</div>`;

  /* 左: 行番号ガター＋編集 textarea（編集に専念） */
  const lPane = `<div class="cfgpane" data-cfgkey="${esc(rKey)}">`
    + `<div class="cfgpane-h"><span class="cfgsrc-fixed">${esc(host)} <span class="cfgedited">編集中</span></span></div>`
    + `<div class="cfgedit-wrap"><div class="cfgedit-gut" data-cfggut="E"></div>`
    + `<textarea class="cfgedit" data-cfgpane="E" data-cfgkey="${esc(rKey)}" spellcheck="false">${esc(cfgTextOf(rKey))}</textarea></div></div>`;

  /* 右: 統一差分（読取専用・vs 原本） */
  const rPane = `<div class="cfgpane" data-cfgkey="dev:${esc(cur + "")}">`
    + `<div class="cfgpane-h"><span class="cfgsrc-fixed">${esc(host)} <span class="dim-t">vs 原本（差分プレビュー）</span></span></div>`
    + `<div class="cfgpre cfgunified" data-cfgunified="${esc(rKey)}">${uni.html}</div></div>`;

  return toolbar + `<div class="cfgsplit">` + lPane + rPane + `</div>`;
}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k cfg_edit_has_editor -q`
Expected: PASS

- [ ] **Step 5: `node --check` で _JS 構文検証**

Run:
```bash
python3 - <<'PY'
from lib.rendering import assets
open("/tmp/_chk.js","w").write(assets._JS)
PY
node --check /tmp/_chk.js && echo "JS OK"
```
（`cd "$SKILL/dev"` のうえ実行。`lib` import が通る作業ディレクトリで。）
Expected: `JS OK`

- [ ] **Step 6: コミット**

```bash
git add "$SKILL/lib/rendering/assets.py" "$SKILL/dev/tests/test_render_assets.py"
git commit -m "feat(render): rewrite renderCfgEdit as editor + unified diff"
```

---

## Task 5: ライブ更新（`updateCfgEditDiff`）＋行番号ガター＋カーソル行ハイライト

**Files:**
- Modify: `.claude/skills/config-topology/lib/rendering/assets.py`（`_JS`：`updateCfgSplitDiff` の edit 分岐を置換／textarea の input/scroll/keyup ハンドラ）
- Test: `.claude/skills/config-topology/dev/tests/test_render_assets.py`

- [ ] **Step 1: 失敗するテストを書く（存在＋構造検証）**

```python
def test_js_has_update_cfg_edit_diff():
    js = assets._JS
    assert "function updateCfgEditDiff(" in js
    # ライブ更新は右 unified コンテナと行番号ガター・カウントを書き換える
    assert 'data-cfgunified=' in js
    assert 'data-cfggut=' in js
    # textarea 入力で編集差分を更新し scratch を保存する導線
    assert "updateCfgEditDiff" in js and "saveCfgScratch" in js


def test_js_edit_cursor_line_highlight():
    js = assets._JS
    # カーソル行（after-line index）に対応する差分行/ガター行を強調する
    assert "urow cur" in js or "\"cur\"" in js
    assert "data-b" in js
```

- [ ] **Step 2: 失敗を確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k "update_cfg_edit or cursor_line" -q`
Expected: FAIL（`updateCfgEditDiff` 未定義）

- [ ] **Step 3: 実装する**

(a) `assets.py` の `_JS` に `updateCfgEditDiff` を追加（`updateCfgSplitDiff` 近傍）。行番号ガター・unified・カウント・dirty・scratch 保存・カーソル行ハイライトを更新:

```javascript
function cfgGutHtml(n, curIdx) {
  let s = "";
  for (let i = 0; i < n; i++) s += `<div class="n${i === curIdx ? " cur" : ""}" data-i="${i}">${i + 1}</div>`;
  return s;
}
function cfgCurLine(ta) {
  return ta.value.slice(0, ta.selectionStart).split("\n").length - 1;
}
function updateCfgEditDiff(ta) {
  const cur = ta.dataset.cfgkey.replace(/^scratch:/, "");
  const rKey = "scratch:" + cur;
  S.configScratch[rKey] = ta.value;
  saveCfgScratch();
  const before = cfgRawOf("dev:" + cur).replace(/\n$/, "").split("\n");
  const after = ta.value.replace(/\n$/, "").split("\n");
  const uni = cfgUnifiedRows(before, after, S.configGrep ? "" : "");
  const curIdx = cfgCurLine(ta);
  /* unified 差分・行番号ガター・カウント */
  const uniEl = document.querySelector('[data-cfgunified="' + cssEsc(rKey) + '"]');
  if (uniEl) uniEl.innerHTML = uni.html;
  const gut = document.querySelector('[data-cfggut="E"]');
  if (gut) gut.innerHTML = cfgGutHtml(after.length, curIdx);
  const sum = document.querySelector('[data-cfgsum="' + cssEsc(rKey) + '"]');
  if (sum) sum.textContent = `+${uni.adds} −${uni.dels}${uni.skipped ? " (差分省略:大規模)" : ""}`;
  cfgEditHighlightCur(ta);
}
function cfgEditHighlightCur(ta) {
  const idx = cfgCurLine(ta);
  const gut = document.querySelector('[data-cfggut="E"]');
  if (gut) gut.querySelectorAll(".n").forEach(el => el.classList.toggle("cur", el.dataset.i === String(idx)));
  const uniEl = document.querySelector('.cfgunified');
  if (uniEl) uniEl.querySelectorAll(".urow").forEach(el => el.classList.toggle("cur", el.dataset.b === String(idx)));
  /* ガターを textarea とスクロール同期 */
  if (gut) gut.scrollTop = ta.scrollTop;
}
```

> 注: `cssEsc` は属性セレクタ用のエスケープ。既存に無ければ最小実装 `function cssEsc(s){ return String(s).replace(/["\\\]]/g, "\\$&"); }` を併せて追加。device id（配列 index の数値）なので実害は薄いが安全側で。

(b) 旧 `updateCfgSplitDiff` 内で `cfgEditLeftRows` を使って編集ライブ差分を更新していた分岐（行 2270 付近）を、編集モードでは `updateCfgEditDiff(ta)` 呼び出しへ置換（COMPARE モードの分岐はそのまま）。

(c) textarea の input/scroll/keyup/click ハンドラ（`.cfgedit` 対象）で、編集モード時に `updateCfgEditDiff` / `cfgEditHighlightCur` を呼ぶよう配線。初回描画直後（`renderCfgEdit` 出力を挿入した後）にもガターを初期化するため、`renderTableView` 後の初期化箇所で `data-cfggut="E"` を `cfgGutHtml(after.length, 0)` で埋める。

- [ ] **Step 4: テストが通ることを確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k "update_cfg_edit or cursor_line" -q`
Expected: PASS

- [ ] **Step 5: `node --check`**

Run（Task 4 Step 5 と同じ手順）: Expected `JS OK`

- [ ] **Step 6: コミット**

```bash
git add "$SKILL/lib/rendering/assets.py" "$SKILL/dev/tests/test_render_assets.py"
git commit -m "feat(render): live unified diff update + line-number gutter + cursor highlight"
```

---

## Task 6: dispatch（DL・元に戻す・dirty バッジ・置換対象 E）

**Files:**
- Modify: `.claude/skills/config-topology/lib/rendering/assets.py`（`_JS`：click dispatch 行 2693–2765 周辺・機器リスト 2380–2383）
- Test: `.claude/skills/config-topology/dev/tests/test_render_assets.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_js_has_dl_and_revert_dispatch():
    js = assets._JS
    assert "data-cfgdl" in js and "downloadText(" in js          # DL ハンドラ
    assert "data-cfgrevert" in js                                # 元に戻す
    assert "delete S.configScratch[" in js                       # revert は scratch を破棄
    # 置換は編集ペイン "E" を対象に解決できる
    assert 'data-cfgreplace' in js


def test_js_device_list_dirty_badge():
    js = assets._JS
    assert "cfgIsDirty(" in js          # 機器リストで dirty 判定
    assert "cfgdirty" in js             # dirty バッジのクラス
```

- [ ] **Step 2: 失敗を確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k "dl_and_revert or dirty_badge" -q`
Expected: FAIL

- [ ] **Step 3: 実装する**

(a) click dispatch（`renderTableView` の click リスナ・行 2716 付近、`data-cfgcopytext` 分岐の近く）に追加:

```javascript
const dlb = ev.target.closest("[data-cfgdl]");
if (dlb) {
  const cur = dlb.dataset.cfgdl;
  const host = (DATA.devices[cur] && DATA.devices[cur].hostname) || cur;
  downloadText(cfgFileName(host), cfgTextOf("scratch:" + cur));
  return;
}
const rvb = ev.target.closest("[data-cfgrevert]");
if (rvb) {
  const cur = rvb.dataset.cfgrevert;
  delete S.configScratch["scratch:" + cur];
  saveCfgScratch();
  renderTableView();
  return;
}
```

(b) `data-cfgreplace` 分岐（行 2725–2742）が `data-cfgpane="E"` の find/repl を拾えること（`cfgPaneKey` ／ `data-cfgpane` の解決が "E" を含む textarea を対象にする）。置換後は `updateCfgEditDiff(ta)` を呼び unified/ガター/カウントを更新。置換件数は既存 `.cfgreplmsg` に `${n}件 置換` 表示。

(c) 機器リスト（`cfgdev` 描画・行 2380–2383）に dirty バッジを付ける:

```javascript
// 各機器行の描画で:
const dirty = cfgIsDirty(String(i)) ? `<span class="cfgdirty" title="未保存の編集あり">●</span>` : "";
// → 機器名の後ろに ${dirty} を差し込む
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k "dl_and_revert or dirty_badge" -q`
Expected: PASS

- [ ] **Step 5: `node --check`**: Expected `JS OK`

- [ ] **Step 6: コミット**

```bash
git add "$SKILL/lib/rendering/assets.py" "$SKILL/dev/tests/test_render_assets.py"
git commit -m "feat(render): config edit DL/revert dispatch + device-list dirty badge"
```

---

## Task 7: CSS（unified 差分行・編集ガター・dirty バッジ）

**Files:**
- Modify: `.claude/skills/config-topology/lib/rendering/assets.py`（`_CSS`）
- Test: `.claude/skills/config-topology/dev/tests/test_render_assets.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_css_has_unified_and_gutter_classes():
    css = assets._CSS
    for cls in [".urow", ".urow.del", ".urow.add", ".urow.ctx", ".cfgedit-gut", ".cfgdirty", ".urow.cur"]:
        assert cls in css, f"missing CSS: {cls}"
```

- [ ] **Step 2: 失敗を確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k css_has_unified -q`
Expected: FAIL

- [ ] **Step 3: 実装する**

`assets.py` の `_CSS` に追記（既存 `.cfgline`/`.diff-*` の近傍・配色は既存 diff 配色に合わせる）:

```css
.cfgedit-wrap{position:relative;display:flex;flex:1;min-height:0}
.cfgedit-gut{flex:0 0 44px;overflow:hidden;text-align:right;padding-right:6px;
  color:#8a93a3;background:rgba(0,0,0,.12);font:inherit;user-select:none}
.cfgedit-gut .n{height:1.5em;line-height:1.5em}
.cfgedit-gut .n.cur{color:#5b8def}
.cfgunified{flex:1}
.urow{display:flex;white-space:pre}
.urow .ug{flex:0 0 40px;text-align:right;padding-right:6px;color:#8a93a3;user-select:none}
.urow .us{flex:0 0 14px;text-align:center;user-select:none}
.urow .utx{flex:1;padding-right:6px}
.urow.ctx .utx{color:#c8cdd6}
.urow.del{background:rgba(248,113,127,.14)} .urow.del .us{color:#f8717f}
.urow.add{background:rgba(86,211,100,.14)} .urow.add .us{color:#56d364}
.urow.cur{box-shadow:inset 3px 0 0 #5b8def}
.urow.hit{outline:1px solid rgba(91,141,239,.5)}
.cfgdirty{color:#e3c84e;margin-left:4px}
```

> 既存テーマの色変数があればそれに合わせる（ハードコード色は既存 `_CSS` の diff 配色を踏襲）。

- [ ] **Step 4: テストが通ることを確認**

Run: `cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -k css_has_unified -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add "$SKILL/lib/rendering/assets.py" "$SKILL/dev/tests/test_render_assets.py"
git commit -m "style(render): unified diff rows + edit gutter + dirty badge CSS"
```

---

## Task 8: 旧 `cfgEditLeftRows` と関連 CSS・テストの撤去

> **承認ゲート**: テスト削除は CLAUDE.md「テスト保護」に該当。ユーザーが本見直し（旧整列方式の置換）を承認済みである前提で、置換後に不要化した自前コード/テストのみ撤去する。撤去前に削除対象を提示して確認すること。

**Files:**
- Modify: `.claude/skills/config-topology/lib/rendering/assets.py`（`_JS` から `cfgEditLeftRows` 削除・`_CSS` から `.del-above`/`.cfgdelmark` 削除）
- Modify: `.claude/skills/config-topology/dev/tests/test_render_assets.py`（旧テスト削除）

- [ ] **Step 1: 撤去対象を確認（呼び出し 0 を確認）**

Run:
```bash
grep -rn "cfgEditLeftRows" "$SKILL/lib" "$SKILL/dev"
grep -rn "del-above\|cfgdelmark" "$SKILL/lib"
```
Expected: `cfgEditLeftRows` の呼び出しが定義以外に残っていない（Task 4/5 で除去済み）。残っていれば先に解消。

- [ ] **Step 2: 旧テストを削除**

`test_render_assets.py` から削除:
- `test_cfg_edit_left_rows_aligns_to_after`（4493 付近）
- `test_cfg_edit_left_rows_trailing_deletion_marker`（4504 付近）
- それらが使う `_run_cfg_edit_left_rows` ヘルパ（他テストが使わない場合）

- [ ] **Step 3: 実装（コード撤去）**

- `assets.py` `_JS` から `function cfgEditLeftRows(...) { ... }` ブロックを削除。
- `assets.py` `_CSS` から `.del-above` と `.cfgdelmark` のルールを削除（`.gap`/`.diff-add`/`.diff-del` は COMPARE が使うため残す）。

- [ ] **Step 4: 全テスト＋構文確認**

Run:
```bash
cd "$SKILL/dev" && python3 -m pytest tests/test_render_assets.py -q
python3 -c "from lib.rendering import assets; open('/tmp/_chk.js','w').write(assets._JS)" && node --check /tmp/_chk.js && echo JS OK
grep -c "cfgEditLeftRows" "$SKILL/lib/rendering/assets.py"   # → 0
```
Expected: 全 PASS・`JS OK`・`0`

- [ ] **Step 5: コミット**

```bash
git add "$SKILL/lib/rendering/assets.py" "$SKILL/dev/tests/test_render_assets.py"
git commit -m "refactor(render): remove superseded cfgEditLeftRows + markers"
```

---

## Task 9: ドキュメント更新

**Files:**
- Modify: `.claude/skills/config-topology/SKILL.md`
- Modify: `.claude/CLAUDE.md`
- Modify: `.claude/skills/config-topology/dev/IMPROVEMENT_LOG.md`

- [ ] **Step 1: SKILL.md の CONFIG 編集記述を更新**

`CONFIG` ビュー④「ノード駆動編集」の説明を、新仕様へ書き換える:
> ④ノード駆動編集（ツールバー「編集」で選択中の機器を *編集（左: 行番号付き textarea）vs 統一差分プレビュー（右: 読取専用・vs 原本・git 風）* の2ペインで開く。差分は追加(+)/削除(−)の行単位（変更カテゴリなし）。編集後は **ダウンロード**（`<host>.cfg`）/コピー/**元に戻す**が可能、未保存編集は機器リストに dirty バッジ。リテラル全置換可。編集内容はブラウザ内（localStorage）のみで生成 HTML には焼き込まない）。

- [ ] **Step 2: .claude/CLAUDE.md の render 索引を更新**

`renderConfigView`/`renderCfgSplit` の記述群のうち「ノード駆動編集 `renderCfgEdit`」部分を、`cfgUnifiedRows`（統一差分）・`cfgEditLeftRows` 撤去・DL（`downloadText`/`cfgFileName`）・dirty（`cfgIsDirty`）・`updateCfgEditDiff`・`data-cfgdl`/`data-cfgrevert` に更新。

- [ ] **Step 3: IMPROVEMENT_LOG.md にエントリ追加**

```
- 2026-06-16 CONFIG 編集を「編集(textarea+行番号) + 統一差分プレビュー(読取専用)」横並びに刷新。
  変更カテゴリ廃止・cfgEditLeftRows/ピルマーカー撤去・DL/コピー/dirty/元に戻す導線追加。render 層のみ・golden 不変。
```

- [ ] **Step 4: コミット**

```bash
git add "$SKILL/SKILL.md" .claude/CLAUDE.md "$SKILL/dev/IMPROVEMENT_LOG.md"
git commit -m "docs: update CONFIG edit (editor + unified diff) description"
```

---

## Task 10: 統合検証（全テスト・決定性・golden・レビュー）

**Files:** なし（検証のみ）

- [ ] **Step 1: 全ユニット/統合/E2E テスト**

Run: `cd "$SKILL/dev" && python3 -m pytest -q`
Expected: 全 PASS（旧編集テストの置換ぶんを含め緑）

- [ ] **Step 2: `node --check`（生成 HTML の JS 構文）**

Run:
```bash
cd /home/asama/config-topology
python3 "$SKILL/scripts/render_topology.py" "$SKILL/dev/examples/topology" -o /tmp/topo1.html
python3 - <<'PY'
import re
h=open('/tmp/topo1.html').read()
m=re.search(r'<script>(.*)</script>', h, re.S)
open('/tmp/_e2e.js','w').write(m.group(1))
PY
node --check /tmp/_e2e.js && echo "JS OK"
```
Expected: `JS OK`

- [ ] **Step 2.5: 不正タグ／NBSP 混入チェック**

Run:
```bash
grep -c '<\\/' /tmp/topo1.html; grep -c $'\xc2\xa0' /tmp/topo1.html || true
```
Expected: 不正タグ `<\/` は 0（NBSP は既存テンプレ次第・新規追加分で増えていないこと）

- [ ] **Step 3: 決定性（HTML 2回生成 byte 一致）**

Run:
```bash
python3 "$SKILL/scripts/render_topology.py" "$SKILL/dev/examples/topology" -o /tmp/topo2.html
cmp /tmp/topo1.html /tmp/topo2.html && echo "DETERMINISTIC OK"
```
Expected: `DETERMINISTIC OK`

- [ ] **Step 4: golden 層別 YAML byte 不変（build 再生成）**

Run:
```bash
python3 "$SKILL/scripts/build_topology.py" \
  "$SKILL/dev/examples/configs/sample-ios-r1.cfg" \
  "$SKILL/dev/examples/configs/sample-junos-r2.conf" -o /tmp/topo_yaml
for f in /tmp/topo_yaml/*.yaml; do cmp "$f" "$SKILL/dev/examples/topology/$(basename "$f")" || echo "DIFF: $f"; done
echo "golden check done"
```
Expected: `DIFF:` 行が出ない（render 変更は YAML に影響しない）

- [ ] **Step 5: run-reviewers（5本並列）＋ HTML 敵対的クロスレビュー**

`run-reviewers` スキルで 5 レビュアー並列起動。各プロンプトに**実コード裏取り指示**を含める。重点:
- correctness: unified 差分の same/del/add 順序・行番号・カウント、revert の scratch 破棄、dirty 判定。
- security: 行/ファイル名/差分テキストの `esc()`、DL ファイル名サニタイズ（パストラバーサル）、`URL.createObjectURL` の revoke。
- performance: `lineAlign` スキップガード流用・ライブ更新の DOM 書換が input ごとに重くないか。
- maintainability: `cfgEditLeftRows` 撤去の完全性・docstring/SKILL.md/CLAUDE.md 整合。
- test: unified/filename/dirty のカバレッジ・COMPARE モード回帰。
加えて、生成 `/tmp/topo1.html` と層別 YAML を突合する **HTML 敵対的クロスレビュー**（ノード/差分/ラベルの欠落・崩れ）。

- [ ] **Step 6: 指摘修正→再レビュー→最終コミット**

CRITICAL/HIGH を解消し、必要なら再レビュー。完了後、ブランチをユーザーに提示（push/PR はユーザー指示時のみ）。

---

## Self-Review（この計画の自己点検）

- **spec カバレッジ**: §3.1 差分モデル→Task1/8、§3.2 レイアウト→Task4、§3.3 エクスポート/保存→Task2/3/6、§3.4 操作性→Task5、§3.5 置換→Task4/6、§4 不変条件→Task10、§5 影響ファイル→全タスク網羅、§6 テスト→各タスク＋Task10、§7 レビュー→Task10。COMPARE 維持（§3.6）→触らない（Task1〜8 で `renderCfgSplit`/`cfgSymRows` 不変）。
- **プレースホルダ**: なし（各 step に実コード・実コマンド・期待値）。
- **型/名称整合**: `lineAlign` ops キー `{t, ai, bi}`、`cfgUnifiedRows`→`{html,adds,dels,skipped}`、`cfgFileName`/`downloadText`/`cfgIsDirty`/`updateCfgEditDiff`/`cfgGutHtml`/`cfgCurLine`/`cfgEditHighlightCur`/`cssEsc` を全タスクで一貫使用。data 属性 `data-cfgpane="E"`/`data-cfgunified`/`data-cfggut="E"`/`data-cfgdl`/`data-cfgrevert`/`data-cfgsum` で一貫。
