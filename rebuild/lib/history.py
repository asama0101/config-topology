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
