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
