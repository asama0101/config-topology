"""入力ファイル収集（要件書 §2.2）。"""
import glob
import os
from pathlib import Path

EXTS = (".cfg", ".conf", ".txt")
DEFAULT_DIR = "./workspace"


def _from_dir(d):
    out = []
    for f in sorted(Path(d).iterdir()):
        if f.is_file() and f.suffix.lower() in EXTS:
            out.append(str(f))
    return out


def collect_inputs(paths):
    """ファイル・ディレクトリ・glob から対象 config を名前順・重複排除で収集。

    paths 省略時は ./workspace/ を走査。ディレクトリは *.cfg/*.conf/*.txt のみ。
    明示ファイル・glob 結果は拡張子で絞らない（利用者指定を尊重）。
    """
    if not paths:
        paths = [DEFAULT_DIR]

    collected = []
    for p in paths:
        pth = Path(p)
        if pth.is_dir():
            collected.extend(_from_dir(pth))
        elif pth.is_file():
            collected.append(str(pth))
        else:
            for g in sorted(glob.glob(p)):
                if Path(g).is_file():
                    collected.append(g)

    # realpath で重複排除（出現順保持）
    seen, uniq = set(), []
    for c in collected:
        rp = os.path.realpath(c)
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(c)

    # basename 名前順でソート（同名は元パスで安定化）
    uniq.sort(key=lambda x: (os.path.basename(x), x))
    return uniq
