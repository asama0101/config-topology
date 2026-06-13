# M2: 推論・層別 YAML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M1 が生成する正規化 `Device` リストを入力に、ID 採番・サブネット一致の結線推論・BGP/OSPF/static 解析を行い、**層別 YAML（`topology/`）を決定的・バイト一致で生成**するビルド層と `build_topology.py` CLI を TDD で実装する。受け入れは附録 B.3 ゴールデンとの**全ファイルバイト一致**。

**Architecture:** `build.py`（正規化 Device → topology dict）＋ `idgen.py`（ID 採番）＋ `topology_io.py`（dict ⇄ 層別 YAML の書出/読込＋参照整合検証）＋ `scripts/build_topology.py`（CLI）。M1 のパーサ（`lib.parsers.parse_config`）・モデル（`lib.models`）・正規化（`lib.normalize`）・入力収集（`lib.inputs`）を再利用する。**history 退避・実行サマリーは M4**、**HTML レンダは M3** のため本 M2 では実装しない。

**Tech Stack:** Python 3（pure Python、`python3`）／ 依存は **PyYAML のみ**（`yaml.safe_load`/`yaml.safe_dump` のみ。M2 で初めて使用）＋標準 `ipaddress`/`re`/`os`/`argparse`／ テストは pytest（`unit`/`integration`/`e2e`）。

**仕様正本:** `docs/requirements.md` v2.1（§3.2 直列化・§5 スキーマ/ID/参照整合・§7 推論・§11 受け入れ・附録 B）。進め方は `docs/implementation-instructions.md`（M2 = §3・§5・§7）。本計画と要件書が食い違う場合は要件書を優先する。

**前提:** M1（パーサ層）は `rebuild/` 配下に実装済み・ブランチ `rebuild-m1-parser` に commit 済み。本 M2 は同ブランチ（または後続ブランチ）上で `rebuild/` 配下に追加実装する。

---

## 横断制約（全タスク共通・違反禁止）

1. **実装先は `rebuild/` 配下のみ**。`.claude/skills/config-topology/` には触れない（読み取り参照のみ可・コピー禁止）。
2. **旧ゴールデン（`.claude/skills/.../dev/examples/topology/`）を期待値に使わない**（addresses 欠落の旧スキーマ）。期待値は要件書 附録 B.3 のみ。
3. **決定性（最重要）**: 同一入力 → 同一の層別 YAML（バイト一致）。乱数・時刻・cwd 絶対パス・dict 反復順の非決定性を成果物に持ち込まない。全リストは §7.5 の規定順で出力する。
4. **YAML 直列化規約（§3.2）**: `yaml.safe_dump(data, sort_keys=True, default_flow_style=False, allow_unicode=True)` のみ。`---` を出さない（safe_dump 既定）。`null` 表記（`~` 不使用）。2 スペースインデント。UTF-8。`safe_load`/`safe_dump` 以外の YAML API 不使用。
5. **依存追加禁止**: PyYAML 以外のサードパーティを入れない。
6. **加算スキーマ**: §5 のフィールド名・型・順序を変えない。`admin_down`/`ospf_area`/`ospf_network` のみ条件付き省略（他は常時キー出力・null 可）。

## 確定インターフェース（後続タスクが従う契約）

Task で実装する公開 API（型は明示しないが下記シグネチャを守る）:

- `idgen.assign_device_ids(parsed_devices) -> list[str]`（appearance 順の Device に対応する device_id 列）
- `idgen.interface_id(device_id, name) -> str` = `"<device_id>::<name>"`
- `idgen.segment_id(subnet_cidr) -> str` = `"seg-" + (`.`/`/`/`:` を `_` 置換)`
- `build.build_topology(parsed_devices, generated_from, title=DEFAULT_TITLE) -> dict`（topology dict）
- `topology_io.dump_topology(topo, out_dir) -> None`
- `topology_io.load_topology(in_dir) -> dict`（§5.6 参照整合違反は `ValueError`）

**topology dict の形（内部表現）**:
```python
{
  "meta": {"schema_version": "1.0", "title": <str>, "generated_from": [<basename>, ...]},
  "devices": [ {id, hostname, vendor, as, ospf_router_id, bgp_router_id, sections}, ... ],     # id 昇順
  "interfaces": [ {id, device, name, ip, vlan, description, shutdown, admin_status,
                   oper_status, mtu, speed, duplex, l2_l3, switchport, encapsulation,
                   source, addresses}, ... ],                                                  # 出現順×config順
  "links": [ {a_device, a_if, b_device, b_if, subnet, kind, [admin_down], [ospf_area, ospf_network]}, ... ],
  "segments": [ {id, subnet, members, [ospf_area, ospf_network]}, ... ],
  "routing": {"bgp": [...], "ospf": [...], "static": [...]},
}
```
`dump_topology` のファイル割当: `meta`→`_meta.yaml`、`devices`+`interfaces`→`devices.yaml`、`links`+`segments`→`physical.yaml`、`routing.bgp`/`ospf`/`static` は**非空のときのみ** `routing.<proto>.yaml`。

**DEFAULT_TITLE** = `"Network Topology (config-derived)"`（§5.1）。

---

## File Structure

| ファイル | 責務 |
|---------|------|
| `rebuild/lib/idgen.py` | device_id / interface_id / segment_id 採番（§5.5） |
| `rebuild/lib/build.py` | 正規化 Device 群 → topology dict（ID付与・結線推論・BGP/OSPF/static・area注釈・順序）（§5/§7） |
| `rebuild/lib/topology_io.py` | topology dict ⇄ 層別 YAML（書出§3.2 / 読込＋参照整合§5.6） |
| `rebuild/scripts/build_topology.py` | CLI②（parse→build→dump。history/summary は M4） |
| `rebuild/dev/examples/topology/*.yaml` | 附録 B.3 ゴールデン（転記） |
| `rebuild/dev/tests/test_*.py` | 各層テスト＋ゴールデン受け入れ |

---

## Task 1: ID 採番 `idgen.py`（要件書 §5.5）

**Files:** Create `rebuild/lib/idgen.py`; Test `rebuild/dev/tests/test_idgen.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_idgen.py`:

```python
"""§5.5 ID 採番規則のテスト。"""
import pytest

from lib.idgen import assign_device_ids, interface_id, segment_id

pytestmark = pytest.mark.unit


class _D:
    def __init__(self, hostname):
        self.hostname = hostname


def _ids(hostnames):
    return assign_device_ids([_D(h) for h in hostnames])


def test_simple_dedup():
    assert _ids(["r1", "r1", "r2"]) == ["r1", "r1-2", "r2"]


def test_collision_bump():
    # 2台目 R1 が r1-2、3台目 R1-2(slug r1-2) はそれと衝突し -2 付与で r1-2-2（単純重複回避・§5.5）
    assert _ids(["R1", "R1", "R1-2"]) == ["r1", "r1-2", "r1-2-2"]


def test_empty_hostname():
    assert _ids(["", ""]) == ["device", "device-2"]


def test_slug_non_alnum_replaced():
    assert _ids(["Core.SW_1"]) == ["core-sw-1"]   # 英数字とハイフン以外 → '-'


def test_interface_id():
    assert interface_id("r1", "GigabitEthernet0/0") == "r1::GigabitEthernet0/0"
    assert interface_id("r2", "ge-0/0/0") == "r2::ge-0/0/0"


def test_segment_id_v4():
    assert segment_id("192.168.1.0/24") == "seg-192_168_1_0_24"


def test_segment_id_v6_deterministic():
    # §5.5 の v6 例は下線数の表記が曖昧なため、`.` `/` `:` を各々 `_` 置換する規則で固定。
    sid = segment_id("2001:db8:1::/64")
    assert sid.startswith("seg-2001_db8_1")
    assert ":" not in sid and "/" not in sid and "." not in sid
```

- [ ] **Step 2:** `cd rebuild/dev && python3 -m pytest tests/test_idgen.py -q` → FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 実装** `rebuild/lib/idgen.py`:

```python
"""ID 採番規則（要件書 §5.5）。device_id / interface_id / segment_id。"""
import re


def _slug(hostname):
    """hostname を小文字化し、英数字とハイフン以外を '-' に置換（§5.5 1-2）。"""
    return re.sub(r"[^a-z0-9-]", "-", hostname.lower())


def assign_device_ids(parsed_devices):
    """appearance 順の Device 列に device_id を採番（§5.5）。

    空 hostname は 'device'。テキスト衝突時のみ -2,-3… へ繰り上げる（ファントム予約なし）。
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
```

- [ ] **Step 4:** `cd rebuild/dev && python3 -m pytest tests/test_idgen.py -q` → PASS。
- [ ] **Step 5: Commit**
```bash
git add rebuild/lib/idgen.py rebuild/dev/tests/test_idgen.py
git commit -m "feat(rebuild): add ID assignment (device/interface/segment) (§5.5)"
```

> 注（実装者向け）: §5.5 の v6 segment_id 例の下線数（`seg-2001_db8_1__64`）は表記が曖昧。本実装は `.`/`/`/`:` を各々 `_` 置換で固定する（ゴールデン B.3 は segments=[] のため受け入れに影響しない）。

---

## Task 2: 層別 YAML 書出 `topology_io.dump_topology`（要件書 §3.2）

**Files:** Create `rebuild/lib/topology_io.py`; Test `rebuild/dev/tests/test_topology_io_dump.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_topology_io_dump.py`:

```python
"""§3.2 層別 YAML 書出（直列化規約・ファイル割当・空 routing 省略）のテスト。"""
import pytest

from lib.topology_io import dump_topology

pytestmark = pytest.mark.unit


def _minimal_topo():
    return {
        "meta": {"schema_version": "1.0", "title": "Network Topology (config-derived)",
                 "generated_from": ["a.cfg", "b.conf"]},
        "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
        "interfaces": [{"id": "r1::lo0", "device": "r1", "name": "lo0", "ip": "1.1.1.1/32",
                        "vlan": None, "description": None, "shutdown": False,
                        "admin_status": "up", "oper_status": None, "mtu": None, "speed": None,
                        "duplex": None, "l2_l3": "l3", "switchport": None,
                        "encapsulation": None, "source": "parsed",
                        "addresses": [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]}],
        "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }


def test_meta_yaml_serialization(tmp_path):
    dump_topology(_minimal_topo(), str(tmp_path))
    text = (tmp_path / "_meta.yaml").read_text(encoding="utf-8")
    # キー辞書順・ブロック表記・--- なし・schema_version は文字列でクォート
    assert text == (
        "generated_from:\n"
        "- a.cfg\n"
        "- b.conf\n"
        "schema_version: '1.0'\n"
        "title: Network Topology (config-derived)\n"
    )


def test_null_emitted_as_null(tmp_path):
    dump_topology(_minimal_topo(), str(tmp_path))
    devs = (tmp_path / "devices.yaml").read_text(encoding="utf-8")
    assert "bgp_router_id: null" in devs        # ~ ではなく null
    assert "ospf_router_id: null" in devs
    assert "sections: []" in devs


def test_physical_always_written_even_empty(tmp_path):
    dump_topology(_minimal_topo(), str(tmp_path))
    phys = (tmp_path / "physical.yaml").read_text(encoding="utf-8")
    assert phys == "links: []\nsegments: []\n"


def test_empty_routing_files_not_written(tmp_path):
    dump_topology(_minimal_topo(), str(tmp_path))
    assert not (tmp_path / "routing.bgp.yaml").exists()
    assert not (tmp_path / "routing.ospf.yaml").exists()
    assert not (tmp_path / "routing.static.yaml").exists()


def test_routing_written_when_present(tmp_path):
    topo = _minimal_topo()
    topo["routing"]["bgp"] = [{"af": "v4", "device": "r1", "local_as": 65001,
                               "local_ip": "10.0.0.1", "neighbor_ip": "10.0.0.2",
                               "peer_as": 65002, "type": "ebgp"}]
    dump_topology(topo, str(tmp_path))
    bgp = (tmp_path / "routing.bgp.yaml").read_text(encoding="utf-8")
    assert bgp.startswith("bgp:\n")
    assert "type: ebgp" in bgp


def test_area_string_quoted(tmp_path):
    topo = _minimal_topo()
    topo["routing"]["ospf"] = [{"af": "v4", "area": "0", "device": "r1",
                                "network": "192.168.1.0/24", "process": 1}]
    dump_topology(topo, str(tmp_path))
    ospf = (tmp_path / "routing.ospf.yaml").read_text(encoding="utf-8")
    assert "area: '0'" in ospf      # 文字列 "0" はクォートされる（int 0 と区別）
```

- [ ] **Step 2:** `cd rebuild/dev && python3 -m pytest tests/test_topology_io_dump.py -q` → FAIL。

- [ ] **Step 3: 実装** `rebuild/lib/topology_io.py`（書出のみ。読込は Task 3 で追記）:

```python
"""topology dict ⇄ 層別 YAML（要件書 §3.2 書出 / §5.6 読込・参照整合）。"""
import os

import yaml


def _dump_file(out_dir, name, data):
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True, default_flow_style=False,
                       allow_unicode=True)


def dump_topology(topo, out_dir):
    """topology dict を層別 YAML として out_dir に書き出す（§3.2）。

    _meta / devices / physical は常時生成。routing.* は非空のときのみ。
    """
    os.makedirs(out_dir, exist_ok=True)
    _dump_file(out_dir, "_meta.yaml", topo["meta"])
    _dump_file(out_dir, "devices.yaml",
               {"devices": topo["devices"], "interfaces": topo["interfaces"]})
    _dump_file(out_dir, "physical.yaml",
               {"links": topo["links"], "segments": topo["segments"]})
    routing = topo.get("routing", {})
    for proto in ("bgp", "ospf", "static"):
        entries = routing.get(proto) or []
        if entries:
            _dump_file(out_dir, "routing.%s.yaml" % proto, {proto: entries})
```

- [ ] **Step 4:** `cd rebuild/dev && python3 -m pytest tests/test_topology_io_dump.py -q` → PASS。
  - もし `test_meta_yaml_serialization` のバイト比較が落ちたら、原因は safe_dump の表記差（クォート規則・改行）である。**テスト期待値を緩めず**、safe_dump の引数（sort_keys/default_flow_style/allow_unicode）と PyYAML バージョン挙動を確認し、§3.2 規約と附録 B.3 に一致させること。
- [ ] **Step 5: Commit**
```bash
git add rebuild/lib/topology_io.py rebuild/dev/tests/test_topology_io_dump.py
git commit -m "feat(rebuild): add layered-YAML serializer (§3.2)"
```

---

## Task 3: 層別 YAML 読込＋参照整合検証 `topology_io.load_topology`（要件書 §5.6）

**Files:** Modify `rebuild/lib/topology_io.py`; Test `rebuild/dev/tests/test_topology_io_load.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_topology_io_load.py`:

```python
"""§5.6 読込・参照整合検証のテスト（dangling 参照を ValueError で弾く）。"""
import pytest

from lib.topology_io import dump_topology, load_topology

pytestmark = pytest.mark.unit


def _topo():
    return {
        "meta": {"schema_version": "1.0", "title": "T", "generated_from": ["a.cfg"]},
        "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
        "interfaces": [{"id": "r1::Gi0", "device": "r1", "name": "Gi0", "ip": None,
                        "vlan": None, "description": None, "shutdown": False,
                        "admin_status": "up", "oper_status": None, "mtu": None,
                        "speed": None, "duplex": None, "l2_l3": None, "switchport": None,
                        "encapsulation": None, "source": "parsed", "addresses": []}],
        "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }


def test_roundtrip(tmp_path):
    dump_topology(_topo(), str(tmp_path))
    loaded = load_topology(str(tmp_path))
    assert loaded["devices"][0]["id"] == "r1"
    assert loaded["interfaces"][0]["device"] == "r1"
    assert loaded["routing"]["bgp"] == []      # 欠落 routing ファイルは空リスト扱い


def test_dangling_interface_device(tmp_path):
    topo = _topo()
    topo["interfaces"][0]["device"] = "rX"     # 存在しない device
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    msg = str(ei.value)
    assert "devices.yaml" in msg and "device" in msg and "rX" in msg   # ファイル名・フィールド・値


def test_dangling_link_endpoint(tmp_path):
    topo = _topo()
    topo["links"] = [{"a_device": "r1", "a_if": "Gi0", "b_device": "rZ", "b_if": "Gi9",
                      "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}]
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    assert "physical.yaml" in str(ei.value) and "rZ" in str(ei.value)


def test_dangling_link_if_name(tmp_path):
    topo = _topo()
    topo["links"] = [{"a_device": "r1", "a_if": "Gi9", "b_device": "r1", "b_if": "Gi0",
                      "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}]
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    assert "a_if" in str(ei.value) and "Gi9" in str(ei.value)


def test_dangling_segment_member(tmp_path):
    topo = _topo()
    topo["segments"] = [{"id": "seg-x", "subnet": "10.0.0.0/24", "members": ["r1::ghost"]}]
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    assert "members" in str(ei.value) and "r1::ghost" in str(ei.value)


def test_dangling_routing_device(tmp_path):
    topo = _topo()
    topo["routing"]["static"] = [{"af": "v4", "device": "rQ", "next_hop": "1.1.1.1",
                                  "prefix": "0.0.0.0/0"}]
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    assert "routing.static.yaml" in str(ei.value) and "rQ" in str(ei.value)
```

- [ ] **Step 2:** `cd rebuild/dev && python3 -m pytest tests/test_topology_io_load.py -q` → FAIL（load_topology 未定義）。

- [ ] **Step 3: 実装** `rebuild/lib/topology_io.py` に追記:

```python
def _load_file(in_dir, name):
    with open(os.path.join(in_dir, name), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_topology(in_dir):
    """層別 YAML を読み込み topology dict を返す。参照整合違反は ValueError（§5.6）。"""
    meta = _load_file(in_dir, "_meta.yaml")
    devs = _load_file(in_dir, "devices.yaml")
    phys = _load_file(in_dir, "physical.yaml")
    routing = {}
    for proto in ("bgp", "ospf", "static"):
        path = os.path.join(in_dir, "routing.%s.yaml" % proto)
        routing[proto] = _load_file(in_dir, "routing.%s.yaml" % proto)[proto] \
            if os.path.exists(path) else []
    topo = {
        "meta": meta,
        "devices": devs["devices"], "interfaces": devs["interfaces"],
        "links": phys["links"], "segments": phys["segments"],
        "routing": routing,
    }
    _validate_refs(topo)
    return topo


def _validate_refs(topo):
    """device/interface ID の dangling 参照を検証（§5.6）。違反はファイル名・フィールド・値付き ValueError。"""
    dev_ids = {d["id"] for d in topo["devices"]}
    if_names_by_dev = {}
    if_ids = set()
    for itf in topo["interfaces"]:
        if itf["device"] not in dev_ids:
            raise ValueError(
                "devices.yaml: interfaces[].device '%s' (interface id=%s) は未知の device を参照"
                % (itf["device"], itf["id"]))
        if_names_by_dev.setdefault(itf["device"], set()).add(itf["name"])
        if_ids.add(itf["id"])
    for ln in topo["links"]:
        for side in ("a", "b"):
            dev = ln["%s_device" % side]
            ifn = ln["%s_if" % side]
            if dev not in dev_ids:
                raise ValueError(
                    "physical.yaml: links[].%s_device '%s' は未知の device を参照" % (side, dev))
            if ifn not in if_names_by_dev.get(dev, set()):
                raise ValueError(
                    "physical.yaml: links[].%s_if '%s' は device '%s' に存在しない" % (side, ifn, dev))
    for seg in topo["segments"]:
        for m in seg["members"]:
            if m not in if_ids:
                raise ValueError(
                    "physical.yaml: segments[].members '%s' (segment %s) は未知の interface を参照"
                    % (m, seg["id"]))
    for proto, entries in topo["routing"].items():
        for e in entries:
            if e["device"] not in dev_ids:
                raise ValueError(
                    "routing.%s.yaml: %s[].device '%s' は未知の device を参照" % (proto, proto, e["device"]))
```

- [ ] **Step 4:** `cd rebuild/dev && python3 -m pytest tests/test_topology_io_load.py -q` → PASS。
- [ ] **Step 5:** `cd rebuild/dev && python3 -m pytest -m unit -q`（リグレッションなし）。
- [ ] **Step 6: Commit**
```bash
git add rebuild/lib/topology_io.py rebuild/dev/tests/test_topology_io_load.py
git commit -m "feat(rebuild): add layered-YAML loader + reference-integrity validation (§5.6)"
```

---

## Task 4: ビルド①: devices/interfaces 構築（要件書 §5.2・§7.5）

`build.py` に正規化 Device 群 → devices[]/interfaces[] dict（ID 付与・全キー出力・順序）を実装する。

**Files:** Create `rebuild/lib/build.py`; Test `rebuild/dev/tests/test_build_devices.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_build_devices.py`:

```python
"""§5.2/§7.5 devices/interfaces 構築のテスト。"""
import pytest

from lib.models import Address, Device, Interface
from lib.build import build_devices_interfaces

pytestmark = pytest.mark.unit


def _dev(hostname, vendor="cisco_ios", **kw):
    return Device(hostname=hostname, vendor=vendor, **kw)


def test_device_dict_full_keys():
    d = _dev("R1", as_=65001)
    ids, devices, interfaces = build_devices_interfaces([d])
    assert ids == ["r1"]
    assert devices[0] == {"id": "r1", "hostname": "R1", "vendor": "cisco_ios",
                          "as": 65001, "ospf_router_id": None, "bgp_router_id": None,
                          "sections": []}


def test_interface_dict_full_keys():
    itf = Interface(name="GigabitEthernet0/0", description="to-R2",
                    addresses=[Address("v4", "10.0.0.1", 30)], l2_l3="l3", admin_status="up")
    d = _dev("R1", interfaces=[itf])
    _, _, interfaces = build_devices_interfaces([d])
    assert interfaces[0] == {
        "id": "r1::GigabitEthernet0/0", "device": "r1", "name": "GigabitEthernet0/0",
        "ip": "10.0.0.1/30", "vlan": None, "description": "to-R2", "shutdown": False,
        "admin_status": "up", "oper_status": None, "mtu": None, "speed": None,
        "duplex": None, "l2_l3": "l3", "switchport": None, "encapsulation": None,
        "source": "parsed", "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
    }


def test_devices_sorted_by_id_interfaces_in_appearance_order():
    # 出現順 r2, r1 → devices は id 昇順 [r1, r2]、interfaces は出現順（r2 の IF が先）
    d2 = _dev("R2", vendor="juniper_junos", interfaces=[Interface(name="ge-0/0/0")])
    d1 = _dev("R1", interfaces=[Interface(name="Gi0/0")])
    ids, devices, interfaces = build_devices_interfaces([d2, d1])
    assert ids == ["r2", "r1"]                       # appearance 順の採番
    assert [d["id"] for d in devices] == ["r1", "r2"]  # 出力は id 昇順
    assert [i["id"] for i in interfaces] == ["r2::ge-0/0/0", "r1::Gi0/0"]  # interfaces は出現順


def test_interface_addresses_sorted_and_derived_ip():
    itf = Interface(name="x", addresses=[
        Address("v6", "2001:db8::1", 64), Address("v4", "10.0.0.1", 24)])
    _, _, interfaces = build_devices_interfaces([_dev("R1", interfaces=[itf])])
    assert interfaces[0]["ip"] == "10.0.0.1/24"      # 派生 ip は v4
    assert [a["af"] for a in interfaces[0]["addresses"]] == ["v4", "v6"]  # 並び順
```

- [ ] **Step 2:** `cd rebuild/dev && python3 -m pytest tests/test_build_devices.py -q` → FAIL。

- [ ] **Step 3: 実装** `rebuild/lib/build.py`:

```python
"""正規化 Device 群 → topology dict（要件書 §5・§7）。"""
from .idgen import assign_device_ids, interface_id

DEFAULT_TITLE = "Network Topology (config-derived)"


def build_devices_interfaces(parsed):
    """parsed(appearance 順) → (device_ids, devices[id昇順], interfaces[出現順×config順])。"""
    device_ids = assign_device_ids(parsed)
    devices, interfaces = [], []
    for dev_id, dev in zip(device_ids, parsed):
        devices.append({
            "id": dev_id, "hostname": dev.hostname, "vendor": dev.vendor,
            "as": dev.as_, "ospf_router_id": dev.ospf_router_id,
            "bgp_router_id": dev.bgp_router_id, "sections": [],
        })
        for itf in dev.interfaces:                    # config 記述順を保持
            interfaces.append({
                "id": interface_id(dev_id, itf.name), "device": dev_id, "name": itf.name,
                "ip": itf.derived_ip(), "vlan": itf.vlan, "description": itf.description,
                "shutdown": itf.shutdown, "admin_status": itf.admin_status,
                "oper_status": itf.oper_status, "mtu": itf.mtu, "speed": itf.speed,
                "duplex": itf.duplex, "l2_l3": itf.l2_l3, "switchport": itf.switchport,
                "encapsulation": itf.encapsulation, "source": "parsed",
                "addresses": [a.to_dict() for a in itf.sorted_addresses()],
            })
    devices_sorted = sorted(devices, key=lambda d: d["id"])   # 出力は id 昇順（§7.5）
    return device_ids, devices_sorted, interfaces
```

- [ ] **Step 4:** PASS を確認。
- [ ] **Step 5: Commit**
```bash
git add rebuild/lib/build.py rebuild/dev/tests/test_build_devices.py
git commit -m "feat(rebuild): build devices/interfaces dicts with IDs and ordering (§5.2/§7.5)"
```

---

## Task 5: ビルド②: 結線推論 links/segments ＋ admin_down（要件書 §7.1・§7.2）

**Files:** Modify `rebuild/lib/build.py`; Test `rebuild/dev/tests/test_build_links.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_build_links.py`:

```python
"""§7.1 結線推論・§7.2 admin_down のテスト。"""
import pytest

from lib.build import infer_links_segments

pytestmark = pytest.mark.unit


def _if(iid, device, name, addrs, shutdown=False):
    # addrs: [(af, ip, prefix[, scope])]
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
    # 自己ループ回避: 同一機器内 2 IF 同一サブネット → link 化しない
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 30)]),
           _if("r1::Gi1", "r1", "Gi1", [("v4", "10.0.0.2", 30)])]
    links, segments = infer_links_segments(ifs)
    assert links == [] and segments == []


def test_link_local_excluded():
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v6", "fe80::1", 64, "link-local")]),
           _if("r2::ge0", "r2", "ge0", [("v6", "fe80::2", 64, "link-local")])]
    links, segments = infer_links_segments(ifs)
    assert links == [] and segments == []            # link-local は結線から除外


def test_admin_down_when_endpoint_shutdown():
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 30)], shutdown=True),
           _if("r2::ge0", "r2", "ge0", [("v4", "10.0.0.2", 30)])]
    links, _ = infer_links_segments(ifs)
    assert links[0]["admin_down"] is True


def test_no_admin_down_key_when_both_up():
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 30)]),
           _if("r2::ge0", "r2", "ge0", [("v4", "10.0.0.2", 30)])]
    links, _ = infer_links_segments(ifs)
    assert "admin_down" not in links[0]              # 両端 up → キー省略（false は出さない）


def test_same_iface_multiple_addr_same_net_dedup_member():
    # 同一 IF が同一ネットに複数アドレス → メンバーは 1 回のみ
    ifs = [_if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 24), ("v4", "10.0.0.5", 24)]),
           _if("r2::ge0", "r2", "ge0", [("v4", "10.0.0.2", 24)])]
    links, segments = infer_links_segments(ifs)
    assert len(links) == 1 and segments == []        # 2 メンバー（重複なし）→ link


def test_link_endpoint_ordering():
    # a_device < b_device で安定化（入力順が逆でも）
    ifs = [_if("r2::ge0", "r2", "ge0", [("v4", "10.0.0.2", 30)]),
           _if("r1::Gi0", "r1", "Gi0", [("v4", "10.0.0.1", 30)])]
    links, _ = infer_links_segments(ifs)
    assert links[0]["a_device"] == "r1" and links[0]["b_device"] == "r2"
```

- [ ] **Step 2:** FAIL を確認。

- [ ] **Step 3: 実装** `rebuild/lib/build.py` に追記:

```python
import ipaddress

from .idgen import segment_id


def _iface_subnets(itf):
    """IF の addresses から所属ネットワーク CIDR 集合（link-local 除外・重複除去）を返す。"""
    nets = []
    seen = set()
    for a in itf["addresses"]:
        if a["af"] == "v6" and a.get("scope") == "link-local":
            continue
        net = ipaddress.ip_network("%s/%s" % (a["ip"], a["prefix"]), strict=False)
        cidr = "%s/%s" % (net.network_address, net.prefixlen)
        if cidr not in seen:
            seen.add(cidr)
            nets.append(cidr)
    return nets


def infer_links_segments(interfaces):
    """サブネット一致で links/segments を推論（§7.1）＋ admin_down 付与（§7.2）。"""
    groups = {}   # cidr -> [iface dict, ...]（同一 IF は 1 回）
    for itf in interfaces:
        for cidr in _iface_subnets(itf):
            groups.setdefault(cidr, []).append(itf)

    links, segments = [], []
    for cidr, members in groups.items():
        if len(members) == 2 and members[0]["device"] != members[1]["device"]:
            a, b = members
            if (b["device"], b["name"]) < (a["device"], a["name"]):
                a, b = b, a                            # a_device<b_device で安定化
            link = {"a_device": a["device"], "a_if": a["name"],
                    "b_device": b["device"], "b_if": b["name"],
                    "subnet": cidr, "kind": "inferred-subnet"}
            if a["shutdown"] or b["shutdown"]:         # §7.2 片端/両端 shutdown → true
                link["admin_down"] = True
            links.append(link)
        elif len(members) >= 3:
            segments.append({"id": segment_id(cidr), "subnet": cidr,
                             "members": sorted(m["id"] for m in members)})
        # len==1、または同一機器 2 メンバー → スタブ/自己ループ（生成しない）
    return links, segments
```

- [ ] **Step 4:** PASS を確認。
- [ ] **Step 5: Commit**
```bash
git add rebuild/lib/build.py rebuild/dev/tests/test_build_links.py
git commit -m "feat(rebuild): infer links/segments by subnet + admin_down (§7.1/§7.2)"
```

---

## Task 6: ビルド③: BGP 対向解決（要件書 §7.3）

**Files:** Modify `rebuild/lib/build.py`; Test `rebuild/dev/tests/test_build_bgp.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_build_bgp.py`:

```python
"""§7.3 BGP 対向解決（local_ip / type / 片側オーバーレイ）のテスト。"""
import pytest

from lib.models import Address, BgpNeighbor, Device, Interface
from lib.build import build_bgp

pytestmark = pytest.mark.unit


def _dev(hostname, asn, ifs, nbs):
    d = Device(hostname=hostname, vendor="cisco_ios", as_=asn)
    d.interfaces = ifs
    d.bgp = nbs
    return d


def test_ebgp_with_local_ip_resolved():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    bgp = build_bgp([("r1", r1)])
    assert bgp == [{"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                    "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"}]


def test_ibgp_same_as():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65001, "v4")])
    assert build_bgp([("r1", r1)])[0]["type"] == "ibgp"


def test_unknown_peer_as_none():
    r1 = _dev("R1", 65001, [], [BgpNeighbor("203.0.113.9", None, "v4")])
    e = build_bgp([("r1", r1)])[0]
    assert e["type"] == "unknown" and e["peer_as"] is None and e["local_ip"] is None


def test_local_ip_none_when_no_matching_subnet():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "192.168.1.1", 24)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    assert build_bgp([("r1", r1)])[0]["local_ip"] is None   # 同一サブネットなし → null（片側オーバーレイ）


def test_v6_neighbor_uses_v6_local_ip():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v6", "2001:db8::1", 64),
                                                Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("2001:db8::2", 65002, "v6")])
    e = build_bgp([("r1", r1)])[0]
    assert e["af"] == "v6" and e["local_ip"] == "2001:db8::1"
```

- [ ] **Step 2:** FAIL を確認。

- [ ] **Step 3: 実装** `rebuild/lib/build.py` に追記:

```python
def _resolve_local_ip(dev, neighbor):
    """neighbor_ip と同一サブネットにある自機 IF の IP（af 一致）を返す。無ければ None（§7.3）。"""
    try:
        nbip = ipaddress.ip_address(neighbor.neighbor_ip)
    except ValueError:
        return None
    for itf in dev.interfaces:
        for a in itf.addresses:
            if a.af != neighbor.af:
                continue
            if a.af == "v6" and a.scope == "link-local":
                continue
            net = ipaddress.ip_network("%s/%s" % (a.ip, a.prefix), strict=False)
            if nbip in net:
                return a.ip
    return None


def _bgp_type(local_as, peer_as):
    if peer_as is None:
        return "unknown"
    if local_as == peer_as:
        return "ibgp"
    return "ebgp"


def build_bgp(id_dev):
    """id_dev: [(device_id, Device)] → routing.bgp エントリ列（§7.3）。"""
    out = []
    for dev_id, dev in id_dev:
        for nb in dev.bgp:
            out.append({
                "device": dev_id, "local_as": dev.as_,
                "local_ip": _resolve_local_ip(dev, nb),
                "neighbor_ip": nb.neighbor_ip, "peer_as": nb.peer_as,
                "type": _bgp_type(dev.as_, nb.peer_as), "af": nb.af,
            })
    return out
```

- [ ] **Step 4:** PASS を確認。
- [ ] **Step 5: Commit**
```bash
git add rebuild/lib/build.py rebuild/dev/tests/test_build_bgp.py
git commit -m "feat(rebuild): resolve BGP local_ip/type/local_as (§7.3)"
```

---

## Task 7: ビルド④: OSPF/static フラット化 ＋ OSPF area 注釈 ＋ 全体組立・順序（要件書 §5.4・§7.4・§7.5）

**Files:** Modify `rebuild/lib/build.py`; Test `rebuild/dev/tests/test_build_assemble.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_build_assemble.py`:

```python
"""§7.4 OSPF area 注釈・§7.5 順序・全体組立のテスト。"""
import pytest

from lib.models import Address, BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute
from lib.build import build_ospf, build_static, annotate_ospf, aggregate_areas, build_topology

pytestmark = pytest.mark.unit


def test_build_ospf_and_static_flatten():
    d = Device(hostname="R1", vendor="cisco_ios", as_=1)
    d.ospf = [OspfNetwork(1, "192.168.1.0/24", "0", "v4")]
    d.static = [StaticRoute("0.0.0.0/0", "10.0.0.2", "v4")]
    assert build_ospf([("r1", d)]) == [{"device": "r1", "process": 1,
                                        "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    assert build_static([("r1", d)]) == [{"device": "r1", "prefix": "0.0.0.0/0",
                                          "next_hop": "10.0.0.2", "af": "v4"}]


def test_aggregate_areas():
    assert aggregate_areas(["0"]) == "0"
    assert aggregate_areas(["0", "0"]) == "0"
    assert aggregate_areas(["1", "0"]) == "0/1"          # 数値昇順
    assert aggregate_areas(["10", "2"]) == "2/10"         # 数値昇順（辞書順なら 10/2 になる）
    assert aggregate_areas(["backbone", "0"]) == "0/backbone"  # 非数値混在 → 辞書式


def test_annotate_ospf_on_link():
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "192.168.1.0/24", "kind": "inferred-subnet"}]
    ospf = [{"device": "r1", "process": 1, "network": "192.168.1.0/24", "area": "0", "af": "v4"},
            {"device": "r2", "process": None, "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    annotate_ospf(links, [], ospf, {})
    assert links[0]["ospf_area"] == "0" and links[0]["ospf_network"] == "192.168.1.0/24"


def test_annotate_skips_admin_down_link():
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "192.168.1.0/24", "kind": "inferred-subnet", "admin_down": True}]
    ospf = [{"device": "r1", "process": 1, "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    annotate_ospf(links, [], ospf, {})
    assert "ospf_area" not in links[0]                   # §7.2 admin_down は注釈しない


def test_annotate_segment_area():
    segments = [{"id": "seg-192_168_1_0_24", "subnet": "192.168.1.0/24",
                 "members": ["r1::Gi0", "r2::Gi0"]}]
    ospf = [{"device": "r1", "process": 1, "network": "192.168.1.0/24", "area": "1", "af": "v4"},
            {"device": "r2", "process": 1, "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    iface_dev = {"r1::Gi0": "r1", "r2::Gi0": "r2"}
    annotate_ospf([], segments, ospf, iface_dev)
    assert segments[0]["ospf_area"] == "0/1"             # 異 area 集約


def test_build_topology_orders_and_routing_keys():
    r1 = Device(hostname="R1", vendor="cisco_ios", as_=65001)
    r1.interfaces = [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)],
                               admin_status="up")]
    r1.bgp = [BgpNeighbor("10.0.0.2", 65002, "v4")]
    r2 = Device(hostname="R2", vendor="juniper_junos", as_=65002)
    r2.interfaces = [Interface(name="ge0", addresses=[Address("v4", "10.0.0.2", 30)],
                               admin_status="up")]
    r2.bgp = [BgpNeighbor("10.0.0.1", 65001, "v4")]
    topo = build_topology([r1, r2], ["r1.cfg", "r2.conf"])
    assert topo["meta"]["schema_version"] == "1.0"
    assert [d["id"] for d in topo["devices"]] == ["r1", "r2"]
    assert len(topo["links"]) == 1
    assert [e["device"] for e in topo["routing"]["bgp"]] == ["r1", "r2"]   # device 昇順
    assert topo["routing"]["ospf"] == [] and topo["routing"]["static"] == []
```

- [ ] **Step 2:** FAIL を確認。

- [ ] **Step 3: 実装** `rebuild/lib/build.py` に追記:

```python
def build_ospf(id_dev):
    out = []
    for dev_id, dev in id_dev:
        for o in dev.ospf:
            out.append({"device": dev_id, "process": o.process,
                        "network": o.network, "area": o.area, "af": o.af})
    return out


def build_static(id_dev):
    out = []
    for dev_id, dev in id_dev:
        for s in dev.static:
            out.append({"device": dev_id, "prefix": s.prefix,
                        "next_hop": s.next_hop, "af": s.af})
    return out


def aggregate_areas(areas):
    """端点の area を集約（§5.3.1/§7.4）。単一→そのまま、複数→昇順スラッシュ連結。"""
    uniq = sorted(set(areas))
    if len(uniq) == 1:
        return uniq[0]
    if all(a.isdigit() for a in uniq):
        uniq = sorted(uniq, key=int)                 # 全数値 → 数値昇順
    return "/".join(uniq)                            # 非数値混在 → 辞書式（既に sorted）


def annotate_ospf(links, segments, ospf_entries, iface_device_map):
    """link/segment に subnet 一致の OSPF area/network を注釈（§7.4）。admin_down は除外（§7.2）。"""
    by_subnet = {}   # network CIDR -> [(device, area)]
    for o in ospf_entries:
        by_subnet.setdefault(o["network"], []).append((o["device"], o["area"]))

    for link in links:
        if link.get("admin_down"):
            continue
        devs = {link["a_device"], link["b_device"]}
        areas = [area for (d, area) in by_subnet.get(link["subnet"], []) if d in devs]
        if areas:
            link["ospf_area"] = aggregate_areas(areas)
            link["ospf_network"] = link["subnet"]

    for seg in segments:
        devs = {iface_device_map[m] for m in seg["members"]}
        areas = [area for (d, area) in by_subnet.get(seg["subnet"], []) if d in devs]
        if areas:
            seg["ospf_area"] = aggregate_areas(areas)
            seg["ospf_network"] = seg["subnet"]


def build_topology(parsed, generated_from, title=DEFAULT_TITLE):
    """正規化 Device 群 → topology dict（§5・§7）。全リストを §7.5 の決定的順序で出力。"""
    device_ids, devices, interfaces = build_devices_interfaces(parsed)
    id_dev = list(zip(device_ids, parsed))

    links, segments = infer_links_segments(interfaces)
    bgp = build_bgp(id_dev)
    ospf = build_ospf(id_dev)
    static = build_static(id_dev)

    iface_device_map = {itf["id"]: itf["device"] for itf in interfaces}
    annotate_ospf(links, segments, ospf, iface_device_map)

    # §7.5 決定的順序
    links.sort(key=lambda l: (l["a_device"], l["a_if"], l["b_device"], l["b_if"], l["subnet"]))
    segments.sort(key=lambda s: s["id"])
    bgp.sort(key=lambda e: (e["device"], e["af"], e["neighbor_ip"]))
    ospf.sort(key=lambda e: (e["device"], e["af"], e["area"], e["network"]))
    static.sort(key=lambda e: (e["device"], e["af"], e["prefix"], e["next_hop"]))

    return {
        "meta": {"schema_version": "1.0", "title": title,
                 "generated_from": list(generated_from)},
        "devices": devices, "interfaces": interfaces,
        "links": links, "segments": segments,
        "routing": {"bgp": bgp, "ospf": ospf, "static": static},
    }
```

- [ ] **Step 4:** PASS を確認。`cd rebuild/dev && python3 -m pytest -m unit -q`（リグレッションなし）。
- [ ] **Step 5: Commit**
```bash
git add rebuild/lib/build.py rebuild/dev/tests/test_build_assemble.py
git commit -m "feat(rebuild): OSPF/static flatten + area annotation + assembly/order (§5.4/§7.4/§7.5)"
```

---

## Task 8: CLI `build_topology.py`（要件書 §10.1・§10.2。history/summary は M4）

**Files:** Create `rebuild/scripts/build_topology.py`; Test `rebuild/dev/tests/test_build_cli.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_build_cli.py`:

```python
"""§10.1/§10.2 build_topology.py CLI（出力先・stdout/stderr・終了コード）のテスト。"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REBUILD_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REBUILD_ROOT / "dev" / "examples" / "configs"
CLI = REBUILD_ROOT / "scripts" / "build_topology.py"


def _run(args):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True, text=True)


def test_cli_generates_layered_yaml(tmp_path):
    out = tmp_path / "topology"
    proc = _run([str(CONFIG_DIR / "sample-ios-r1.cfg"),
                 str(CONFIG_DIR / "sample-junos-r2.conf"), "-o", str(out)])
    assert proc.returncode == 0
    for fn in ["_meta.yaml", "devices.yaml", "physical.yaml",
               "routing.bgp.yaml", "routing.ospf.yaml", "routing.static.yaml"]:
        assert (out / fn).exists()
    assert "Generated" in proc.stdout                # 成果物パスを stdout に明示
    assert "[INFO]" in proc.stderr


def test_cli_unknown_vendor_skipped(tmp_path):
    weird = tmp_path / "weird.cfg"
    weird.write_text("foo bar\nbaz qux\n", encoding="utf-8")
    out = tmp_path / "topology"
    proc = _run([str(weird), "-o", str(out)])
    assert proc.returncode == 0                      # スキップして継続
    assert "[WARN]" in proc.stderr
    assert (out / "devices.yaml").exists()           # 空でも devices/physical は生成
```

- [ ] **Step 2:** FAIL を確認。

- [ ] **Step 3: 実装** `rebuild/scripts/build_topology.py`:

```python
#!/usr/bin/env python3
"""CLI②: parse + 推論を実行し層別 YAML を生成（要件書 §10.1・§10.2）。

history 退避・実行サマリーは M4 で追加する（本 CLI には未実装）。
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # rebuild/ を import パスへ

from lib.inputs import collect_inputs                # noqa: E402
from lib.parsers import detect_vendor, parse_config  # noqa: E402
from lib.build import build_topology                 # noqa: E402
from lib.topology_io import dump_topology            # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Build layered topology YAML from configs.")
    p.add_argument("paths", nargs="*", help="config files / dirs / glob（省略時 ./workspace/）")
    p.add_argument("-o", "--output", default="topology", help="出力ディレクトリ（既定 ./topology）")
    args = p.parse_args(argv)

    files = collect_inputs(args.paths)
    if not files:
        print("[WARN] 対象 config が見つかりません（拡張子: .cfg/.conf/.txt）", file=sys.stderr)

    parsed, basenames, warnings = [], [], []
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
            continue
        try:
            dev = parse_config(text, warnings)
        except Exception as e:                        # noqa: BLE001
            print("[WARN] %s: パース中の例外につきスキップ (%s)" % (name, e), file=sys.stderr)
            continue
        if dev is None:
            continue
        parsed.append(dev)
        basenames.append(name)
        print("[INFO] %s: %s" % (name, vendor), file=sys.stderr)

    topo = build_topology(parsed, basenames)
    try:
        dump_topology(topo, args.output)
    except OSError as e:
        print("[ERROR] 出力失敗: %s (%s)" % (args.output, e), file=sys.stderr)
        return 1

    print("Generated: %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4:** PASS を確認。
- [ ] **Step 5: Commit**
```bash
git add rebuild/scripts/build_topology.py rebuild/dev/tests/test_build_cli.py
git commit -m "feat(rebuild): add build_topology.py CLI (§10.1/§10.2)"
```

---

## Task 9: ゴールデン受け入れ ＋ 決定性（要件書 §11.1・§11.3・附録 B.3）— **M2 受け入れゲート**

附録 B.3 を `rebuild/dev/examples/topology/` に転記し、B.1/B.2 → topology/ が**全ファイルバイト一致**することと、2 回実行でバイト一致（決定性）を検証する。

**Files:** Create `rebuild/dev/examples/topology/{_meta,devices,physical,routing.bgp,routing.ospf,routing.static}.yaml`; Test `rebuild/dev/tests/test_golden_e2e.py`

- [ ] **Step 1: 附録 B.3 を `rebuild/dev/examples/topology/` に転記**（要件書 附録 B.3 と一字一句一致。手で改変しない）

`_meta.yaml`:
```yaml
generated_from:
- sample-ios-r1.cfg
- sample-junos-r2.conf
schema_version: '1.0'
title: Network Topology (config-derived)
```

`devices.yaml`: 要件書 附録 B.3 の `devices.yaml` ブロック全体を転記（devices 2 件＋interfaces 6 件。各 interface は全 17 キー。`addresses`/`ip`/`l2_l3`/`admin_status` 等の値も B.3 のとおり）。

`physical.yaml`:
```yaml
links:
- a_device: r1
  a_if: GigabitEthernet0/0
  b_device: r2
  b_if: ge-0/0/0
  kind: inferred-subnet
  subnet: 10.0.0.0/30
segments: []
```

`routing.bgp.yaml`:
```yaml
bgp:
- af: v4
  device: r1
  local_as: 65001
  local_ip: 10.0.0.1
  neighbor_ip: 10.0.0.2
  peer_as: 65002
  type: ebgp
- af: v4
  device: r2
  local_as: 65002
  local_ip: 10.0.0.2
  neighbor_ip: 10.0.0.1
  peer_as: 65001
  type: ebgp
```

`routing.ospf.yaml`:
```yaml
ospf:
- af: v4
  area: '0'
  device: r1
  network: 192.168.1.0/24
  process: 1
```

`routing.static.yaml`:
```yaml
static:
- af: v4
  device: r1
  next_hop: 10.0.0.2
  prefix: 0.0.0.0/0
- af: v4
  device: r2
  next_hop: 10.0.0.1
  prefix: 0.0.0.0/0
```

> 実装者注: `devices.yaml` は長いため、要件書 `docs/requirements.md` の附録 B.3 `devices.yaml` セクション（`#### devices.yaml` 見出し直下のコードブロック）を**そのまま**コピーすること。値を推測で書かない。

- [ ] **Step 2: ゴールデン受け入れ／決定性テスト** — `rebuild/dev/tests/test_golden_e2e.py`:

```python
"""§11.1 ゴールデン受け入れ・§11.3 決定性（附録 B.3 バイト一致）。"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REBUILD_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REBUILD_ROOT / "dev" / "examples" / "configs"
GOLDEN_DIR = REBUILD_ROOT / "dev" / "examples" / "topology"
CLI = REBUILD_ROOT / "scripts" / "build_topology.py"

GOLDEN_FILES = ["_meta.yaml", "devices.yaml", "physical.yaml",
                "routing.bgp.yaml", "routing.ospf.yaml", "routing.static.yaml"]


def _build(out_dir):
    proc = subprocess.run(
        [sys.executable, str(CLI),
         str(CONFIG_DIR / "sample-ios-r1.cfg"),
         str(CONFIG_DIR / "sample-junos-r2.conf"), "-o", str(out_dir)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return out_dir


def test_golden_byte_match(tmp_path):
    out = _build(tmp_path / "topology")
    produced = sorted(p.name for p in out.iterdir())
    assert produced == sorted(GOLDEN_FILES)          # 生成ファイル集合が一致（余分・欠落なし）
    for fn in GOLDEN_FILES:
        got = (out / fn).read_bytes()
        want = (GOLDEN_DIR / fn).read_bytes()
        assert got == want, "ゴールデン不一致: %s" % fn   # バイト一致


def test_determinism_two_runs(tmp_path):
    a = _build(tmp_path / "a")
    b = _build(tmp_path / "b")
    for fn in GOLDEN_FILES:
        assert (a / fn).read_bytes() == (b / fn).read_bytes()
```

- [ ] **Step 3:** `cd rebuild/dev && python3 -m pytest tests/test_golden_e2e.py -q`。
  - **不一致が出たら**: それは推論/直列化/順序のいずれかが附録 B.3 とずれている証拠。テスト期待値（ゴールデン）を改変せず、生成側を §3.2/§5/§7 に合わせて修正する。`diff <(python3 ... -o /tmp/g) GOLDEN_DIR` で差分箇所を特定。よくある原因: safe_dump のキー順・クォート、リスト順（§7.5）、null 表記、`area` のクォート、interfaces の出現順。

- [ ] **Step 4: 全テスト** `cd rebuild/dev && python3 -m pytest -q`（unit + integration + e2e すべて green）。

- [ ] **Step 5: 最終 E2E（手動・受け入れ前確認）**
```bash
python3 rebuild/scripts/build_topology.py \
  rebuild/dev/examples/configs/sample-ios-r1.cfg \
  rebuild/dev/examples/configs/sample-junos-r2.conf -o /tmp/m2-accept
diff -r /tmp/m2-accept rebuild/dev/examples/topology   # 差分ゼロ
python3 rebuild/scripts/build_topology.py \
  rebuild/dev/examples/configs/sample-ios-r1.cfg \
  rebuild/dev/examples/configs/sample-junos-r2.conf -o /tmp/m2-accept-2
diff -r /tmp/m2-accept /tmp/m2-accept-2               # 差分ゼロ（決定性）
```

- [ ] **Step 6: Commit**
```bash
git add rebuild/dev/examples/topology rebuild/dev/tests/test_golden_e2e.py
git commit -m "test(rebuild): add golden acceptance + determinism (§11.1/§11.3)"
```

---

## M2 Done 条件（実装指示書 §4 M2 と対応）

- [ ] **ゴールデンテスト合格**: 附録 B.1/B.2 → 出力が `dev/examples/topology/`（=附録 B.3）と**全ファイルバイト一致**（Task 9）。
- [ ] **決定性テスト合格**: 同一入力 2 回でバイト一致（§11.3、Task 9）。
- [ ] ID 採番の衝突ケーステスト合格（`r1,r1,r2` / `R1,R1,R1-2` / 空 hostname。§5.5、Task 1）。
- [ ] 参照整合エラーテスト合格: dangling 参照がファイル名・フィールド・値付き ValueError で停止（§5.6、Task 3）。
- [ ] 結線推論の境界テスト合格（メンバー 1=スタブ / 2=link / 3+=segment、shutdown、自己ループ、link-local 除外、重複アドレス。§7.1/§7.2、Task 5）。

---

## Self-Review（計画作成者・実施済み）

- **Spec coverage:** §3.2（dump Task2）/§5.2-5.4 schema（devices Task4・links/seg Task5・routing Task6-7）/§5.5 ID（Task1）/§5.6 参照整合（Task3）/§7.1 推論（Task5）/§7.2 admin_down（Task5）/§7.3 BGP（Task6）/§7.4 OSPF area（Task7）/§7.5 順序（Task7）/§10.1-10.2 CLI（Task8）/§11.1・§11.3 受け入れ（Task9）を割当済み。
- **スコープ外（M3/M4）:** HTML レンダ（§8）は M3、history 退避（§10.3）・実行サマリー（§10.4）は M4。本計画では未実装。
- **Type consistency:** topology dict の形・公開 API シグネチャを冒頭「確定インターフェース」で固定。`build_devices_interfaces`/`infer_links_segments`/`build_bgp`/`build_ospf`/`build_static`/`annotate_ospf`/`aggregate_areas`/`build_topology`/`dump_topology`/`load_topology`/`idgen.*` を全タスクで一貫使用。
- **未確定の軽微点（実装に影響小）:** §5.5 v6 segment_id の下線数表記の曖昧さ（Task1 注記。ゴールデンは segments=[] のため受け入れ非依存）。要件書 §5.5 の device_id 例は本計画着手前に自己整合へ訂正済み（`R1,R1,R1-2 → r1,r1-2,r1-3`）。
- **No placeholders:** 各ステップに完全なテスト＋実装コードを記載（Task9 の `devices.yaml` ゴールデンのみ、長さのため要件書附録 B.3 からの転記指示）。
