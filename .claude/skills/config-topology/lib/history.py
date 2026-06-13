# rebuild/lib/history.py
"""§10.3 history 退避（再生成時に旧成果物を自動退避する）。

退避ディレクトリ名のタイムスタンプのみ実行時刻に依存する（§9.1 決定性の唯一の例外）。
退避処理本体は now_str を引数で受け取るため決定的でテスト可能。
"""
import re
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


def _ts_sort_key(name):
    """history ディレクトリ名 <ts>[_N] のソートキーを返す。

    末尾の `_<数値>` 連番を数値として比較し、同一 base（タイムスタンプ）内で
    _10 > _9 となるよう保証する（lexical だと '_9' > '_10' になりバグになる）。

    ソートキー = (base 名（連番を除いた部分）, 連番の int 値（無ければ 0）)

    reverse=True と組み合わせることで:
    - base 名（タイムスタンプ）は降順（新しい日時が先）
    - 同一 base 内は連番が大きい方（最新衝突）が先
    """
    m = re.match(r'^(.+?)_(\d+)$', name)
    if m:
        return (m.group(1), int(m.group(2)))
    return (name, 0)


def latest_history_topology(history_root="history"):
    """直近 history の層別 YAML inner ディレクトリを返す（D3c §10.x）。

    history_root 直下の <ts> サブディレクトリを**名前の降順**で走査し、
    各 <ts>/ の直下サブディレクトリに _meta.yaml を持つものを探す。
    見つかった場合、その inner ディレクトリ（例: history/<ts>/topology/）の Path を返す。

    ソートは末尾連番 `_N` を数値として比較する（_ts_sort_key を参照）。
    同一 base（タイムスタンプ）内で _10 > _9 となり、lexical より衝突が正しく解決される。

    返り値:
        Path: 最新の inner dir（_meta.yaml を含む）
        None: history_root 不在・空・層別 YAML を含む history が無い場合

    決定性: 同一 FS 状態 → 同一選択（数値降順 max が決定的）。
    """
    history_root = Path(history_root)
    if not history_root.is_dir():
        return None
    # <ts> サブディレクトリを降順ソート（末尾 _N 連番を数値として比較）
    ts_dirs = sorted(
        (d for d in history_root.iterdir() if d.is_dir()),
        key=lambda d: _ts_sort_key(d.name),
        reverse=True,
    )
    for ts_dir in ts_dirs:
        # <ts>/ 直下のサブディレクトリを検索し _meta.yaml を持つものを探す
        for inner in sorted(ts_dir.iterdir(), key=lambda d: d.name):
            if inner.is_dir() and (inner / "_meta.yaml").exists():
                return inner
    return None


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
