"""ID 採番規則（要件書 §5.5）。device_id / interface_id / segment_id。"""
import re

_SUFFIX_RE = re.compile(r"^(.*)-(\d+)$")


def _slug(hostname):
    """hostname を小文字化し、英数字とハイフン以外を '-' に置換（§5.5 1-2）。"""
    return re.sub(r"[^a-z0-9-]", "-", hostname.lower())


def _stem(slug):
    """slug 末尾の `-<n>` suffix を剥がした stem と n を返す。

    suffix がなければ stem=slug, n=None。
    例: 'r1-2' -> ('r1', 2),  'r1' -> ('r1', None)
    """
    m = _SUFFIX_RE.match(slug)
    if m:
        return m.group(1), int(m.group(2))
    return slug, None


def assign_device_ids(parsed_devices):
    """appearance 順の Device 列に device_id を採番（§5.5）。

    空 hostname は 'device'。テキスト衝突時のみ -2,-3… へ繰り上げる（ファントム予約なし）。
    slug 末尾に `-<n>` を持つホスト名が衝突した場合、stem 系列の最大 n+1 を採用する。
    """
    used = set()
    ids = []
    for d in parsed_devices:
        slug = _slug(d.hostname) or "device"

        if slug not in used:
            used.add(slug)
            ids.append(slug)
            continue

        # slug が衝突 → stem 系列で bump
        stem, _ = _stem(slug)
        # stem 自体が used に存在しない場合も stem 系列として扱う
        # used から stem 系列の最大 suffix を求める
        max_n = 1  # stem 自体が存在すれば n=1 相当
        for existing in used:
            if existing == stem:
                # stem そのものは n=1 扱い (bump は -2 から)
                pass
            else:
                e_stem, e_n = _stem(existing)
                if e_stem == stem and e_n is not None:
                    if e_n > max_n:
                        max_n = e_n

        cand = "%s-%d" % (stem, max_n + 1)
        # 万一 cand も衝突している場合（連続して同一 slug が来るケース）はさらに繰り上げ
        while cand in used:
            max_n += 1
            cand = "%s-%d" % (stem, max_n + 1)

        used.add(cand)
        ids.append(cand)
    return ids


def interface_id(device_id, name):
    """`<device_id>::<name>`（§5.5）。"""
    return "%s::%s" % (device_id, name)


def segment_id(subnet_cidr):
    """`seg-<subnet>`。CIDR の `.` `/` `:` を `_` に置換（§5.5）。"""
    return "seg-" + re.sub(r"[./:]", "_", subnet_cidr)
