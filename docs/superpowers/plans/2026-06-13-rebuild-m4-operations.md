# M4 運用機能（history 退避・実行サマリー）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 再生成時に旧成果物を自動退避（§10.3）し、build 完了時に判定結果・警告・生成数の実行サマリー（§10.4）を stderr 出力する運用機能を rebuild に追加する。

**Architecture:** 退避ロジックは新規 `lib/history.py`（純関数・`now_str` 注入でテスト可能）に集約し、build/render CLI が薄く呼ぶ。実行サマリーは新規 `lib/run_summary.py`（純関数・行リスト生成）に集約し build CLI が呼ぶ。時刻依存は退避ディレクトリ名のみ（§9.1 決定性の唯一の例外）で、生成成果物の決定性は不変。

**Tech Stack:** Python 3.12 / 標準ライブラリのみ（`shutil`・`datetime`・`pathlib`）。PyYAML 以外の依存追加なし。

---

## 前提・不変条件（M4 で壊さないこと）

- **既存 194 passed を維持**。既存 e2e/決定性テストは毎回 fresh な絶対パス（`a`/`b`/`t1`/`t2`/`h1`/`h2`）かつ非デフォルトパスへ出力するため、退避は発火しない（裏取り済み）。
- **退避先は cwd 相対 `./history/<YYYY-MM-DD_HHMM>/`**（§10.3 の文言どおり）。同名衝突時は `_2`,`_3`… の連番サフィックス。
- **build のペア退避**: 既定パス運用時（`-o` が既定 `topology` のとき）に限り、`./topology.html` が存在すれば `./topology/` と**同一**退避ディレクトリへ一緒に移動。非既定パス時は HTML を巻き込まない。
- **決定性**: 生成される層別 YAML / HTML の内容は時刻非依存のまま。退避ディレクトリ名のみ実行時刻に依存（§9.1 の許容例外）。
- `topo` dict のキー: `meta` / `devices` / `interfaces` / `links` / `segments` / `routing{bgp,ospf,static}`（`lib/build.py:194` で裏取り済み）。
- テスト実行は `cd rebuild/dev && python3 -m pytest`。

## File Structure

- **Create** `rebuild/lib/history.py` — 退避純関数（`current_timestamp`・`unique_history_dir`・`retain_for_build`・`retain_for_render`）。
- **Create** `rebuild/lib/run_summary.py` — 実行サマリー行生成（`build_summary_lines`）。
- **Modify** `rebuild/scripts/build_topology.py` — 退避呼び出し＋判定記録＋サマリー出力。
- **Modify** `rebuild/scripts/render_topology.py` — 退避呼び出し。
- **Create** `rebuild/dev/tests/test_history.py` — 退避関数の integration テスト。
- **Create** `rebuild/dev/tests/test_run_summary.py` — サマリー純関数の unit テスト。
- **Modify** `rebuild/dev/tests/test_build_cli.py` — build 退避＋サマリーの CLI 結線テストを追記。
- **Modify** `rebuild/dev/tests/test_render_cli.py` — render 退避の CLI 結線テストを追記。

---

### Task 1: history.py — タイムスタンプと衝突回避ディレクトリ名

**Files:**
- Create: `rebuild/lib/history.py`
- Test: `rebuild/dev/tests/test_history.py`

- [ ] **Step 1: Write the failing test**

```python
# rebuild/dev/tests/test_history.py
"""§10.3 history 退避（旧成果物の自動退避）のテスト。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # rebuild/
from lib.history import (  # noqa: E402
    current_timestamp,
    unique_history_dir,
)

pytestmark = pytest.mark.integration


def test_current_timestamp_format():
    ts = current_timestamp()
    # YYYY-MM-DD_HHMM の固定幅（例: 2026-06-14_1530）
    assert len(ts) == len("2026-06-14_1530")
    assert ts[4] == "-" and ts[7] == "-" and ts[10] == "_"
    assert ts.replace("-", "").replace("_", "").isdigit()


def test_unique_history_dir_no_collision(tmp_path):
    got = unique_history_dir(tmp_path, "2026-06-14_1530")
    assert got == tmp_path / "2026-06-14_1530"


def test_unique_history_dir_collision_suffix(tmp_path):
    (tmp_path / "2026-06-14_1530").mkdir()
    (tmp_path / "2026-06-14_1530_2").mkdir()
    got = unique_history_dir(tmp_path, "2026-06-14_1530")
    assert got == tmp_path / "2026-06-14_1530_3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rebuild/dev && python3 -m pytest tests/test_history.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'lib.history'` または ImportError）

- [ ] **Step 3: Write minimal implementation**

```python
# rebuild/lib/history.py
"""§10.3 history 退避（再生成時に旧成果物を自動退避する）。

退避ディレクトリ名のタイムスタンプのみ実行時刻に依存する（§9.1 決定性の唯一の例外）。
退避処理本体は now_str を引数で受け取るため決定的でテスト可能。
"""
import shutil
from datetime import datetime
from pathlib import Path

TS_FORMAT = "%Y-%m-%d_%H%M"


def current_timestamp():
    """実行時のローカル時刻を <YYYY-MM-DD_HHMM> 文字列で返す（§10.3）。"""
    return datetime.now().strftime(TS_FORMAT)


def unique_history_dir(history_root, now_str):
    """history_root/now_str を返す。既存なら _2, _3... の連番で衝突回避する（§10.3）。"""
    history_root = Path(history_root)
    base = history_root / now_str
    if not base.exists():
        return base
    n = 2
    while True:
        cand = history_root / ("%s_%d" % (now_str, n))
        if not cand.exists():
            return cand
        n += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd rebuild/dev && python3 -m pytest tests/test_history.py -q`
Expected: PASS（3 件）

- [ ] **Step 5: Commit**

```bash
git add rebuild/lib/history.py rebuild/dev/tests/test_history.py
git commit -m "feat(m4): add history timestamp and collision-safe dir naming (§10.3)"
```

---

### Task 2: history.py — build 退避（YAML ディレクトリ＋ペア HTML）

**Files:**
- Modify: `rebuild/lib/history.py`
- Test: `rebuild/dev/tests/test_history.py`

- [ ] **Step 1: Write the failing test**（既存 test_history.py の import 行に `retain_for_build` を追加し、末尾に以下を追記）

import 追加（既存の `from lib.history import (...)` ブロックに行を足す）:
```python
from lib.history import (  # noqa: E402
    current_timestamp,
    retain_for_build,
    unique_history_dir,
)
```

追記する関数:
```python
def _seed_topo_dir(d):
    d.mkdir(parents=True)
    (d / "devices.yaml").write_text("devices: []\n", encoding="utf-8")


def test_retain_build_moves_existing_yaml(tmp_path):
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    history = tmp_path / "history"
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert dest == history / "2026-06-14_1530"
    assert (dest / "topology" / "devices.yaml").exists()
    assert not out.exists()                       # 元ディレクトリは移動済み


def test_retain_build_none_when_empty(tmp_path):
    out = tmp_path / "topology"                    # 存在しない
    history = tmp_path / "history"
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert dest is None
    assert not history.exists()                    # 退避不要なら history も作らない


def test_retain_build_pairs_html_into_same_dir(tmp_path):
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_build(out, html, "2026-06-14_1530", history_root=history)
    assert (dest / "topology" / "devices.yaml").exists()
    assert (dest / "topology.html").exists()       # 同一退避ディレクトリへペア退避
    assert not html.exists()


def test_retain_build_html_only_when_pair_given(tmp_path):
    # html_pair=None（非既定パス相当）のとき既存 HTML を巻き込まない
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert (dest / "topology").exists()
    assert html.exists()                           # HTML は退避されず残る


def test_retain_build_collision_suffix(tmp_path):
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    history = tmp_path / "history"
    (history / "2026-06-14_1530").mkdir(parents=True)   # 既存退避ディレクトリ
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert dest == history / "2026-06-14_1530_2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rebuild/dev && python3 -m pytest tests/test_history.py -q`
Expected: FAIL（`ImportError: cannot import name 'retain_for_build'`）

- [ ] **Step 3: Write minimal implementation**（history.py に追記）

```python
def retain_for_build(output_dir, html_pair, now_str, history_root="history"):
    """build 再生成前の退避（§10.3）。

    - output_dir に層別 YAML(*.yaml) があれば history/<now_str>/<output_dir名>/ へ移動。
    - html_pair（既定パス運用時のみ Path('topology.html')。非既定時は None）が存在すれば
      同一退避ディレクトリへ一緒に移動（成果物ペアの整合維持）。
    退避対象が無ければ何もせず None を返す。退避したら退避先 Path を返す。
    """
    output_dir = Path(output_dir)
    targets = []
    if output_dir.is_dir() and any(output_dir.glob("*.yaml")):
        targets.append(output_dir)
    if html_pair is not None and Path(html_pair).exists():
        targets.append(Path(html_pair))
    if not targets:
        return None
    dest = unique_history_dir(history_root, now_str)
    dest.mkdir(parents=True)
    for t in targets:
        shutil.move(str(t), str(dest / t.name))
    return dest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd rebuild/dev && python3 -m pytest tests/test_history.py -q`
Expected: PASS（8 件）

- [ ] **Step 5: Commit**

```bash
git add rebuild/lib/history.py rebuild/dev/tests/test_history.py
git commit -m "feat(m4): retain existing build artifacts with paired HTML (§10.3)"
```

---

### Task 3: history.py — render 退避（既存 HTML）

**Files:**
- Modify: `rebuild/lib/history.py`
- Test: `rebuild/dev/tests/test_history.py`

- [ ] **Step 1: Write the failing test**（import に `retain_for_render` を追加し末尾に追記）

import 追加:
```python
from lib.history import (  # noqa: E402
    current_timestamp,
    retain_for_build,
    retain_for_render,
    unique_history_dir,
)
```

追記:
```python
def test_retain_render_moves_existing_html(tmp_path):
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>old", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_render(html, "2026-06-14_1530", history_root=history)
    assert dest == history / "2026-06-14_1530"
    assert (dest / "topology.html").read_text(encoding="utf-8") == "<!doctype html>old"
    assert not html.exists()


def test_retain_render_none_when_absent(tmp_path):
    html = tmp_path / "topology.html"              # 存在しない
    history = tmp_path / "history"
    dest = retain_for_render(html, "2026-06-14_1530", history_root=history)
    assert dest is None
    assert not history.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rebuild/dev && python3 -m pytest tests/test_history.py -q`
Expected: FAIL（`ImportError: cannot import name 'retain_for_render'`）

- [ ] **Step 3: Write minimal implementation**（history.py に追記）

```python
def retain_for_render(output_html, now_str, history_root="history"):
    """render 再生成前の退避（§10.3）。既存 HTML を history/<now_str>/ へ移動する。

    既存 HTML が無ければ何もせず None を返す。退避したら退避先 Path を返す。
    """
    output_html = Path(output_html)
    if not output_html.exists():
        return None
    dest = unique_history_dir(history_root, now_str)
    dest.mkdir(parents=True)
    shutil.move(str(output_html), str(dest / output_html.name))
    return dest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd rebuild/dev && python3 -m pytest tests/test_history.py -q`
Expected: PASS（10 件）

- [ ] **Step 5: Commit**

```bash
git add rebuild/lib/history.py rebuild/dev/tests/test_history.py
git commit -m "feat(m4): retain existing rendered HTML before re-render (§10.3)"
```

---

### Task 4: run_summary.py — 実行サマリー行生成

**Files:**
- Create: `rebuild/lib/run_summary.py`
- Test: `rebuild/dev/tests/test_run_summary.py`

- [ ] **Step 1: Write the failing test**

```python
# rebuild/dev/tests/test_run_summary.py
"""§10.4 実行サマリー（build_summary_lines）のテスト。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # rebuild/
from lib.run_summary import build_summary_lines  # noqa: E402

pytestmark = pytest.mark.unit


def _topo(n_dev=1, n_if=2, n_link=1, n_seg=0, bgp=0, ospf=0, static=0):
    return {
        "meta": {}, "devices": [{}] * n_dev, "interfaces": [{}] * n_if,
        "links": [{}] * n_link, "segments": [{}] * n_seg,
        "routing": {"bgp": [{}] * bgp, "ospf": [{}] * ospf, "static": [{}] * static},
    }


def test_summary_lists_each_file_verdict():
    verdicts = [("r1.cfg", "cisco_ios"), ("r2.conf", "juniper_junos")]
    lines = build_summary_lines(verdicts, [], _topo())
    text = "\n".join(lines)
    assert "r1.cfg: cisco_ios" in text
    assert "r2.conf: juniper_junos" in text


def test_summary_skipped_label_and_incompleteness_notice():
    verdicts = [("r1.cfg", "cisco_ios"), ("weird.txt", None)]
    lines = build_summary_lines(verdicts, [], _topo())
    text = "\n".join(lines)
    assert "weird.txt: skipped (unknown vendor)" in text
    assert "不完全" in text                     # §10.4 注意喚起


def test_summary_warning_count_and_example():
    lines = build_summary_lines([("r1.cfg", "cisco_ios")],
                                ["bad line 'foo'", "bad line 'bar'"], _topo())
    text = "\n".join(lines)
    assert "警告: 2 件" in text
    assert "bad line 'foo'" in text             # 代表例を併記
    assert "不完全" in text                     # 警告>=1 でも注意喚起


def test_summary_counts_and_no_notice_when_clean():
    lines = build_summary_lines([("r1.cfg", "cisco_ios")], [],
                                _topo(n_dev=2, n_if=5, n_link=3, n_seg=1,
                                      bgp=4, ospf=2, static=1))
    text = "\n".join(lines)
    assert "devices=2" in text and "interfaces=5" in text
    assert "links=3" in text and "segments=1" in text
    assert "routing.bgp=4" in text and "routing.ospf=2" in text and "routing.static=1" in text
    assert "不完全" not in text                 # スキップ0・警告0 なら注意喚起なし
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rebuild/dev && python3 -m pytest tests/test_run_summary.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'lib.run_summary'`）

- [ ] **Step 3: Write minimal implementation**

```python
# rebuild/lib/run_summary.py
"""§10.4 実行サマリー（build_topology.py 用）。stderr へ出す行リストを生成する。"""


def build_summary_lines(verdicts, warnings, topo):
    """サマリー行リストを返す（§10.4）。

    verdicts: [(basename, vendor_or_None)] を入力順に。vendor=None はスキップ扱い。
    warnings: パース警告メッセージのリスト。
    topo: build_topology が返す topology dict。
    """
    lines = ["[SUMMARY] 入力ファイル判定:"]
    skipped = 0
    for name, vendor in verdicts:
        if vendor is None:
            skipped += 1
            label = "skipped (unknown vendor)"
        else:
            label = vendor
        lines.append("  - %s: %s" % (name, label))

    lines.append("[SUMMARY] 警告: %d 件" % len(warnings))
    if warnings:
        lines.append("  例: %s" % warnings[0])

    devices = topo.get("devices") or []
    interfaces = topo.get("interfaces") or []
    links = topo.get("links") or []
    segments = topo.get("segments") or []
    lines.append("[SUMMARY] 生成数: devices=%d interfaces=%d links=%d segments=%d"
                 % (len(devices), len(interfaces), len(links), len(segments)))
    routing = topo.get("routing") or {}
    for proto in sorted(routing.keys()):
        lines.append("  routing.%s=%d" % (proto, len(routing.get(proto) or [])))

    if skipped or warnings:
        lines.append("[SUMMARY] 注意: スキップまたは警告があり、結果が不完全な可能性があります。")
    return lines
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd rebuild/dev && python3 -m pytest tests/test_run_summary.py -q`
Expected: PASS（4 件）

- [ ] **Step 5: Commit**

```bash
git add rebuild/lib/run_summary.py rebuild/dev/tests/test_run_summary.py
git commit -m "feat(m4): add run summary line builder (§10.4)"
```

---

### Task 5: build_topology.py 結線（退避＋判定記録＋サマリー）

**Files:**
- Modify: `rebuild/scripts/build_topology.py`
- Test: `rebuild/dev/tests/test_build_cli.py`（追記）

- [ ] **Step 1: Write the failing test**（test_build_cli.py 末尾に追記。既存の `_run`/`CONFIG_DIR`/`CLI` を再利用）

```python
def test_cli_emits_run_summary(tmp_path):
    weird = tmp_path / "weird.cfg"
    weird.write_text("foo bar\nbaz qux\n", encoding="utf-8")   # 未知ベンダー
    out = tmp_path / "topology"
    proc = _run([str(CONFIG_DIR / "sample-ios-r1.cfg"), str(weird), "-o", str(out)])
    assert proc.returncode == 0
    assert "[SUMMARY]" in proc.stderr
    assert "skipped (unknown vendor)" in proc.stderr
    assert "不完全" in proc.stderr                         # §10.4 注意喚起


def test_cli_retains_existing_default_output(tmp_path):
    # 既定パス運用（-o 省略）で cwd の既存 ./topology/ と ./topology.html をペア退避
    (tmp_path / "topology").mkdir()
    (tmp_path / "topology" / "devices.yaml").write_text("devices: []\n", encoding="utf-8")
    (tmp_path / "topology.html").write_text("<!doctype html>old", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), str(CONFIG_DIR / "sample-ios-r1.cfg")],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    history = tmp_path / "history"
    assert history.exists()
    snaps = list(history.iterdir())
    assert len(snaps) == 1
    assert (snaps[0] / "topology" / "devices.yaml").exists()   # 旧 YAML 退避
    assert (snaps[0] / "topology.html").exists()               # ペア HTML 退避
    assert (tmp_path / "topology" / "devices.yaml").exists()   # 新規生成
    assert "退避" in proc.stderr


def test_cli_no_retention_when_no_existing(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(CLI), str(CONFIG_DIR / "sample-ios-r1.cfg")],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "history").exists()                 # 退避対象なし
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rebuild/dev && python3 -m pytest tests/test_build_cli.py -q`
Expected: FAIL（`test_cli_emits_run_summary` で `[SUMMARY]` 不在、`test_cli_retains_existing_default_output` で history 不在）

- [ ] **Step 3: Write minimal implementation**（build_topology.py を以下で全置換）

```python
#!/usr/bin/env python3
"""CLI②: parse + 推論を実行し層別 YAML を生成（要件書 §10.1・§10.2・§10.3・§10.4）。"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # rebuild/ を import パスへ

from lib.inputs import collect_inputs                # noqa: E402
from lib.parsers import detect_vendor, parse_config  # noqa: E402
from lib.build import build_topology                 # noqa: E402
from lib.topology_io import dump_topology            # noqa: E402
from lib.history import retain_for_build, current_timestamp  # noqa: E402
from lib.run_summary import build_summary_lines      # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Build layered topology YAML from configs.")
    p.add_argument("paths", nargs="*", help="config files / dirs / glob（省略時 ./workspace/）")
    p.add_argument("-o", "--output", default="topology", help="出力ディレクトリ（既定 ./topology）")
    args = p.parse_args(argv)

    files = collect_inputs(args.paths)
    if not files:
        print("[WARN] 対象 config が見つかりません（拡張子: .cfg/.conf/.txt）", file=sys.stderr)

    parsed, basenames, warnings, verdicts = [], [], [], []
    for f in files:
        try:
            text = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print("[ERROR] 読込失敗: %s (%s)" % (f, e), file=sys.stderr)
            return 1
        name = os.path.basename(f)
        vendor = detect_vendor(text)
        if vendor is None:
            print("[WARN] %s: skipped (unknown vendor)" % name, file=sys.stderr)
            verdicts.append((name, None))
            continue
        try:
            dev = parse_config(text, warnings)
        except Exception as e:                        # noqa: BLE001
            print("[WARN] %s: パース中の例外につきスキップ (%s)" % (name, e), file=sys.stderr)
            verdicts.append((name, None))
            continue
        if dev is None:
            verdicts.append((name, None))
            continue
        parsed.append(dev)
        basenames.append(name)
        verdicts.append((name, vendor))
        print("[INFO] %s: %s" % (name, vendor), file=sys.stderr)

    topo = build_topology(parsed, basenames)

    # §10.3 history 退避（既定パス運用時のみ ./topology.html もペア退避）
    out_dir = Path(args.output)
    html_pair = Path("topology.html") if out_dir == Path("topology") else None
    retained = retain_for_build(out_dir, html_pair, current_timestamp())
    if retained is not None:
        print("[INFO] 旧成果物を退避: %s" % retained, file=sys.stderr)

    try:
        dump_topology(topo, args.output)
    except OSError as e:
        print("[ERROR] 出力失敗: %s (%s)" % (args.output, e), file=sys.stderr)
        return 1

    # §10.4 実行サマリー
    for line in build_summary_lines(verdicts, warnings, topo):
        print(line, file=sys.stderr)

    print("Generated: %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd rebuild/dev && python3 -m pytest tests/test_build_cli.py -q`
Expected: PASS（既存 2 件 + 新規 3 件 = 5 件）

- [ ] **Step 5: Commit**

```bash
git add rebuild/scripts/build_topology.py rebuild/dev/tests/test_build_cli.py
git commit -m "feat(m4): wire history retention and run summary into build CLI (§10.3/§10.4)"
```

---

### Task 6: render_topology.py 結線（退避）＋ M4 全体回帰

**Files:**
- Modify: `rebuild/scripts/render_topology.py`
- Test: `rebuild/dev/tests/test_render_cli.py`（追記）

- [ ] **Step 1: Write the failing test**（test_render_cli.py 末尾に追記。既存 `_run`/`GOLDEN`/`CLI` を再利用）

```python
def test_render_retains_existing_html(tmp_path):
    # 既定出力 ./topology.html が既存 → 生成前に history へ退避
    (tmp_path / "topology.html").write_text("<!doctype html>old", encoding="utf-8")
    proc = _run([str(GOLDEN)], cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    history = tmp_path / "history"
    assert history.exists()
    snaps = list(history.iterdir())
    assert len(snaps) == 1
    assert (snaps[0] / "topology.html").read_text(encoding="utf-8") == "<!doctype html>old"
    new = tmp_path / "topology.html"
    assert new.exists()
    assert new.read_text(encoding="utf-8").lstrip().lower().startswith("<!doctype html")
    assert "退避" in proc.stderr


def test_render_no_retention_when_absent(tmp_path):
    proc = _run([str(GOLDEN)], cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "history").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd rebuild/dev && python3 -m pytest tests/test_render_cli.py -q`
Expected: FAIL（`test_render_retains_existing_html` で history 不在）

- [ ] **Step 3: Write minimal implementation**（render_topology.py を以下で全置換）

```python
#!/usr/bin/env python3
"""CLI③: 層別 YAML から自己完結 HTML を生成（要件書 §10.1・§10.2・§10.3）。"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.topology_io import load_topology       # noqa: E402
from lib.rendering.template import render_html   # noqa: E402
from lib.history import retain_for_render, current_timestamp  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Render layered topology YAML to a self-contained HTML.")
    p.add_argument("topology_dir", help="層別 YAML のディレクトリ")
    p.add_argument("-o", "--output", default="./topology.html",
                   help="出力 HTML（既定 ./topology.html）")
    args = p.parse_args(argv)

    try:
        topo = load_topology(args.topology_dir)
    except ValueError as e:
        print("[ERROR] 参照整合エラー: %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("[ERROR] 読込失敗: %s (%s)" % (args.topology_dir, e), file=sys.stderr)
        return 1

    html = render_html(topo)

    # §10.3 既存 HTML を退避（生成前）
    retained = retain_for_render(Path(args.output), current_timestamp())
    if retained is not None:
        print("[INFO] 旧 HTML を退避: %s" % retained, file=sys.stderr)

    try:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
    except OSError as e:
        print("[ERROR] 出力失敗: %s (%s)" % (args.output, e), file=sys.stderr)
        return 1

    print("Generated: %s" % args.output)
    print("[WARN] 生成物には config 由来の自由記述（description 等）がそのまま含まれます。"
          "共有前に内容を確認してください。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd rebuild/dev && python3 -m pytest tests/test_render_cli.py -q`
Expected: PASS（既存 3 件 + 新規 2 件 = 5 件）

- [ ] **Step 5: M4 全体回帰（決定性・ゴールデン非破壊の確認）**

Run: `cd rebuild/dev && python3 -m pytest -q`
Expected: PASS（M3 終了時 194 + M4 新規 = 全 PASS）。特に `test_golden_e2e.py`・`test_render_e2e.py`（決定性）が緑であること。

- [ ] **Step 6: Commit**

```bash
git add rebuild/scripts/render_topology.py rebuild/dev/tests/test_render_cli.py
git commit -m "feat(m4): wire history retention into render CLI (§10.3)"
```

---

## Self-Review

**1. Spec coverage（§10.3 / §10.4 / §11.2 の Done 条件）:**
- §10.3 build 既存 YAML 退避 → Task2/Task5 ✓
- §10.3 既定パス時 ./topology.html ペア退避・非既定は巻き込まない → Task2（`test_retain_build_pairs_html_into_same_dir` / `test_retain_build_html_only_when_pair_given`）＋ Task5（`test_cli_retains_existing_default_output`）✓
- §10.3 連番衝突回避 → Task1（`test_unique_history_dir_collision_suffix`）＋ Task2（`test_retain_build_collision_suffix`）✓
- §10.3 退避なし（既存なし）→ Task2/Task3/Task5/Task6 ✓
- §10.3 render 既存 HTML 退避 → Task3/Task6 ✓
- §10.3 退避先パスを stderr 出力 → Task5/Task6（`"退避" in proc.stderr`）✓
- §10.4 判定結果/警告/生成数/注意喚起 → Task4（全 4 観点）＋ Task5（CLI で `[SUMMARY]`・skipped・不完全）✓
- §11.2 integration（history 退避・実行サマリー）/ §11.3 決定性非破壊 → Task6 Step5 ✓
- 終了コード（正常 0 / unknown 0）→ 既存 + Task5 ✓。入出力エラー 1・参照整合 1 は既存テスト（`test_render_cli.test_dangling_ref_exits_1` 等）で担保済み（M4 で非破壊）。

**2. Placeholder scan:** TODO/TBD なし。全ステップに実コードあり。

**3. Type consistency:** `retain_for_build(output_dir, html_pair, now_str, history_root)` / `retain_for_render(output_html, now_str, history_root)` / `unique_history_dir(history_root, now_str)` / `current_timestamp()` / `build_summary_lines(verdicts, warnings, topo)` をタスク間で一貫使用。`topo` キー（devices/interfaces/links/segments/routing{bgp,ospf,static}）は `lib/build.py:194` と一致。

**注意点（実装者向け）:**
- 退避は cwd 相対 `./history/`。CLI が `current_timestamp()` を呼んで `now_str` を注入する（純関数は時刻非依存＝テスト可能）。
- 退避は **生成前**（build: `dump_topology` 前 / render: ファイル書込前）。退避で元 `topology/` が消えるが `dump_topology` がディレクトリを再作成する（既存 e2e で裏取り済み）。
- パース例外・`dev is None` は判定 None（skipped）として記録し注意喚起をトリガーする（§10.4 の 3 ラベルに集約）。
- 既存 194 テストは fresh 絶対パス・非既定パスで退避非発火。本計画のテストはすべて tmp_path/cwd 隔離。
