"""IP / CIDR / IPv6 / OSPF area の正規化（要件書 §6.3）。標準 ipaddress のみ使用。"""
import ipaddress

_LINK_LOCAL = ipaddress.ip_network("fe80::/10")


def norm_ipv4(ip):
    """IPv4 を先行ゼロ除去の標準ドット 10 進へ。

    Python 3.12+ の ipaddress は先行ゼロを拒否するため、
    各オクテットを int() で正規化してから渡す。
    """
    octets = ip.strip().split(".")
    return str(ipaddress.IPv4Address(".".join(str(int(o)) for o in octets)))


def norm_ipv6(ip):
    """IPv6 を RFC 5952 短縮形へ。"""
    return str(ipaddress.IPv6Address(ip.strip()))


def mask_to_prefix(mask):
    """サブネットマスク（255.255.255.252）を prefix 長（30）へ。"""
    return ipaddress.IPv4Network("0.0.0.0/" + mask.strip()).prefixlen


def wildcard_to_prefix(wildcard):
    """ワイルドカードマスク（0.0.0.255）を prefix 長（24）へ。

    連続マスク（標準 OSPF `network <addr> <wildcard>` 形式）を前提とする。
    非連続ワイルドカードは popcount 近似であり厳密ではない。
    """
    mask_int = int(ipaddress.IPv4Address(wildcard.strip())) ^ 0xFFFFFFFF
    return bin(mask_int).count("1")


def norm_cidr(ip, prefix):
    """ホストアドレス + prefix からホストビットを除去した CIDR 文字列へ。

    IPv4 部は先行ゼロ除去済みであることを前提とする（呼び出し側で norm_ipv4 を適用すること）。
    Python 3.12 の ipaddress は先行ゼロを拒否するため、未正規化のまま渡すと ValueError になる。
    """
    net = ipaddress.ip_network("%s/%s" % (ip, prefix), strict=False)
    return "%s/%s" % (net.network_address, net.prefixlen)


def norm_cidr_str(cidr):
    """`a.b.c.d/len` 形式の CIDR を正規化（ホストビット除去・v6 短縮形）。

    IPv4 部は先行ゼロ除去済みであることを前提とする（呼び出し側で norm_ipv4 を適用すること）。
    Python 3.12 の ipaddress は先行ゼロを拒否するため、未正規化のまま渡すと ValueError になる。
    """
    net = ipaddress.ip_network(cidr.strip(), strict=False)
    return "%s/%s" % (net.network_address, net.prefixlen)


def v6_scope(ip):
    """fe80::/10 に属すなら 'link-local'、それ以外は None。

    IPv6 アドレス専用（v4 を渡すと AddressValueError）。
    """
    return "link-local" if ipaddress.IPv6Address(ip) in _LINK_LOCAL else None


def asdot_to_asplain(s):
    """asdot 表記の ASN 文字列を int（asplain）へ変換する。

    - "1.0"   -> 1*65536+0 = 65536
    - "65001" -> 65001（ドット無しはそのまま int）

    結果が 0〜4294967295（2^32-1）の範囲外の場合は ValueError を投げる
    （IOS 実機も範囲外は reject するため）。
    """
    s = s.strip()
    if "." in s:
        high, low = s.split(".", 1)
        result = int(high) * 65536 + int(low)
    else:
        result = int(s)
    if not (0 <= result <= 4294967295):
        raise ValueError("ASN out of range [0, 4294967295]: %s -> %d" % (s, result))
    return result


def norm_ospf_area(area):
    """OSPF area を整数文字列へ正規化（§6.3）。不正値は原文のまま返す。"""
    area = area.strip()
    if area.isdigit():
        return str(int(area))
    parts = area.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        a, b, c, d = (int(p) for p in parts)
        return str((a << 24) | (b << 16) | (c << 8) | d)
    return area
