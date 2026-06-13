"""ID 採番規則（要件書 §5.5）。device_id / interface_id / segment_id。"""
import re


def _slug(hostname):
    """hostname を小文字化し、英数字とハイフン以外を '-' に置換（§5.5 1-2）。"""
    return re.sub(r"[^a-z0-9-]", "-", hostname.lower())


def assign_device_ids(parsed_devices):
    """appearance 順の Device 列に device_id を採番（§5.5）。

    空 hostname は 'device'。採番済み ID とテキスト衝突する場合のみ -2,-3… を付与する
    （slug に対する単純な重複回避。サフィックス解釈やファントム予約はしない）。
    """
    used = set()
    ids = []
    for d in parsed_devices:
        base = _slug(d.hostname) or "device"
        cand = base
        n = 1
        while cand in used:
            n += 1
            cand = "%s-%d" % (base, n)
        used.add(cand)
        ids.append(cand)
    return ids


def interface_id(device_id, name):
    """`<device_id>::<name>`（§5.5）。"""
    return "%s::%s" % (device_id, name)


def segment_id(subnet_cidr):
    """`seg-<subnet>`。CIDR の `.` `/` `:` を `_` に置換（§5.5）。"""
    return "seg-" + re.sub(r"[./:]", "_", subnet_cidr)
