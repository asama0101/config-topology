"""§7.1 結線推論・§7.2 admin_down のテスト。"""
import pytest

from lib.build import infer_links_segments

pytestmark = pytest.mark.unit


def _if(iid, device, name, addrs, shutdown=False):
    addresses = []
    for t in addrs:
        a = {"af": t[0], "ip": t[1], "prefix": t[2]}
        if len(t) > 3 and t[3]:
            a["scope"] = t[3]
        addresses.append(a)
    return {"id": iid, "device": device, "name": name, "shutdown": shutdown,
            "addresses": addresses}


def test_two_members_diff_device_make_link():
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 30)]),
           _if("r2::ge0", "r2", "ge0", [("v4", "10.0.0.2", 30)])]
    links, segments = infer_links_segments(ifs)
    assert segments == []
    assert links == [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
                      "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}]


def test_three_members_make_segment():
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "192.168.1.1", 24)]),
           _if("r2::Gi0", "r2", "Gi0", [("v4", "192.168.1.2", 24)]),
           _if("r3::Gi0", "r3", "Gi0", [("v4", "192.168.1.3", 24)])]
    links, segments = infer_links_segments(ifs)
    assert links == []
    assert segments == [{"id": "seg-192_168_1_0_24", "subnet": "192.168.1.0/24",
                         "members": ["r1::Gi0", "r2::Gi0", "r3::Gi0"]}]


def test_single_member_is_stub():
    ifs = [_if("r1::lo0", "r1", "lo0", [("v4", "1.1.1.1", 32)])]
    links, segments = infer_links_segments(ifs)
    assert links == [] and segments == []


def test_same_device_two_members_no_link():
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 30)]),
           _if("r1::Gi1", "r1", "Gi1", [("v4", "10.0.0.2", 30)])]
    links, segments = infer_links_segments(ifs)
    assert links == [] and segments == []


def test_link_local_excluded():
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v6", "fe80::1", 64, "link-local")]),
           _if("r2::ge0", "r2", "ge0", [("v6", "fe80::2", 64, "link-local")])]
    links, segments = infer_links_segments(ifs)
    assert links == [] and segments == []


def test_admin_down_when_endpoint_shutdown():
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 30)], shutdown=True),
           _if("r2::ge0", "r2", "ge0", [("v4", "10.0.0.2", 30)])]
    links, _ = infer_links_segments(ifs)
    assert links[0]["admin_down"] is True


def test_no_admin_down_key_when_both_up():
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 30)]),
           _if("r2::ge0", "r2", "ge0", [("v4", "10.0.0.2", 30)])]
    links, _ = infer_links_segments(ifs)
    assert "admin_down" not in links[0]


def test_same_iface_multiple_addr_same_net_dedup_member():
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 24), ("v4", "10.0.0.5", 24)]),
           _if("r2::ge0", "r2", "ge0", [("v4", "10.0.0.2", 24)])]
    links, segments = infer_links_segments(ifs)
    assert len(links) == 1 and segments == []


def test_link_endpoint_ordering():
    ifs = [_if("r2::ge0", "r2", "ge0", [("v4", "10.0.0.2", 30)]),
           _if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 30)])]
    links, _ = infer_links_segments(ifs)
    assert links[0]["a_device"] == "r1" and links[0]["b_device"] == "r2"


def test_three_members_segment_even_with_same_device():
    # メンバー≥3 は device 構成に関係なく segment（同一機器の複数 IF を含んでも）
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 24)]),
           _if("r1::Gi1", "r1", "Gi1", [("v4", "10.0.0.2", 24)]),
           _if("r2::ge0", "r2", "ge0", [("v4", "10.0.0.3", 24)])]
    links, segments = infer_links_segments(ifs)
    assert links == []
    assert len(segments) == 1
    assert segments[0]["members"] == ["r1::Gi0", "r1::Gi1", "r2::ge0"]
