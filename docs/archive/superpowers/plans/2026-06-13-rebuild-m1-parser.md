# M1: パーサ層 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** config テキスト（Cisco IOS / Juniper JunOS set 形式）を、ベンダー自動判定のうえベンダー中立な正規化データモデル（`Device`）へ変換するパーサ層と、その JSON を出力する `parse_configs.py` CLI を、0 から TDD で実装する。

**Architecture:** 入力収集（`inputs.py`）→ ベンダー判定（`parsers/__init__.py`）→ ベンダー別パーサ（`parsers/ios.py` / `parsers/junos.py`）→ 正規化モデル（`models.py`）。IP/CIDR/IPv6/OSPF area の正規化は `normalize.py` に集約（Python 標準 `ipaddress` を使用）。各パーサは IOS/JunOS の構文差異を吸収し、以降のパイプライン（M2/M3）はこの `Device` モデルのみを見る。本 M1 では **ID 採番・結線推論・YAML 直列化は行わない**（M2 の責務）。

**Tech Stack:** Python 3（pure Python、`python3` 実行）／ 外部依存は **PyYAML のみ**（M1 では未使用、依存追加禁止）／ 標準ライブラリ `ipaddress`・`re`・`glob`・`pathlib`・`json`・`dataclasses` を使用／ テストは pytest（マーカー `unit` / `integration`）。

**仕様正本:** `docs/requirements.md` v2.1（以下「要件書」）。本計画と要件書が食い違う場合は要件書を優先する。実装の進め方は `docs/implementation-instructions.md`（M1 = §2・§4・§6）。

---

## 横断制約（全タスク共通・違反禁止）

要件書 §9・実装指示書 §5 より。各タスクで常に守ること：

1. **実装先は新規 `rebuild/` 配下のみ**。`.claude/skills/config-topology/` には一切書き込まない（読み取り参照のみ可。コードのコピー・移植は禁止。要件書 §1.2 / 指示書 §1.2）。
2. **旧ゴールデン（`.claude/skills/config-topology/dev/examples/topology/`）を期待値に使わない**（古いスキーマ。`addresses` 欠落）。期待値は要件書 附録 B のみ。
3. **決定性**: 乱数・時刻・cwd 絶対パス等を成果物に混入させない（要件書 §9.1）。
4. **依存追加禁止**: PyYAML 以外のサードパーティ依存を入れない。M1 のコードは標準ライブラリのみで成立させる（要件書 §1.3）。
5. **クラッシュしない**: 個別行のパース失敗・未知ベンダーは warnings に積んで継続。例外でパイプラインを止めない（要件書 §6.3）。
6. **機密行を読まない**: `password` / `secret` / `snmp community`（IOS は `snmp-server community`）を含む行はパース前に除外（要件書 §9.2）。

## データモデル定義（全タスクが参照する確定インターフェース）

以下の dataclass 名・フィールド名・型は Task 2 で確定し、後続タスクはこれに従う（Type consistency の基準）。`as` は予約語のため属性名は `as_`、辞書化時にキー `as` へ写す。

```
Address(af:str, ip:str, prefix:int, secondary:bool=False, scope:str|None=None)
BgpNeighbor(neighbor_ip:str, peer_as:int|None, af:str)
OspfNetwork(process:int|None, network:str, area:str, af:str)
StaticRoute(prefix:str, next_hop:str, af:str)
Interface(name:str, addresses:list[Address]=[], description:str|None=None,
          shutdown:bool=False, admin_status:str|None=None, oper_status:str|None=None,
          mtu:int|None=None, speed:str|None=None, duplex:str|None=None,
          l2_l3:str|None=None, switchport:dict|None=None, encapsulation:str|None=None,
          vlan:int|None=None)
Device(hostname:str, vendor:str, as_:int|None=None, ospf_router_id:str|None=None,
       bgp_router_id:str|None=None, interfaces:list[Interface]=[],
       bgp:list[BgpNeighbor]=[], ospf:list[OspfNetwork]=[], static:list[StaticRoute]=[])
```

公開関数シグネチャ（後続タスクが呼ぶ確定 API）:

- `normalize.norm_ipv4(ip:str) -> str` / `norm_ipv6(ip:str) -> str`
- `normalize.mask_to_prefix(mask:str) -> int` / `normalize.wildcard_to_prefix(wild:str) -> int`
- `normalize.norm_cidr(ip:str, prefix:int) -> str` / `normalize.norm_cidr_str(cidr:str) -> str`
- `normalize.norm_ospf_area(area:str) -> str` / `normalize.v6_scope(ip:str) -> str|None`
- `parsers.detect_vendor(text:str) -> str|None`（`"cisco_ios"` / `"juniper_junos"` / `None`）
- `parsers.parse_config(text:str, warnings:list|None=None) -> Device|None`
- `parsers.ios.parse_ios(text:str, warnings:list) -> Device`
- `parsers.junos.parse_junos(text:str, warnings:list) -> Device`
- `inputs.collect_inputs(paths:list[str]) -> list[str]`

---

## File Structure

| ファイル | 責務 |
|---------|------|
| `rebuild/lib/__init__.py` | パッケージ marker（空） |
| `rebuild/lib/models.py` | 正規化 dataclass（上記 6 種）と並び替え・派生 `ip` ロジック |
| `rebuild/lib/normalize.py` | IP/CIDR/IPv6/wildcard/OSPF area 正規化・v6 scope 判定（`ipaddress` 使用） |
| `rebuild/lib/inputs.py` | 入力ファイル収集（拡張子・glob・dir 走査・dedupe・名前順ソート・workspace 既定） |
| `rebuild/lib/parsers/__init__.py` | ベンダー判定 `detect_vendor` と dispatch `parse_config` |
| `rebuild/lib/parsers/base.py` | 機密行判定 `is_sensitive_line` ほか共通ヘルパ |
| `rebuild/lib/parsers/ios.py` | IOS パーサ `parse_ios` |
| `rebuild/lib/parsers/junos.py` | JunOS パーサ `parse_junos` |
| `rebuild/scripts/parse_configs.py` | CLI①（正規化 Device の JSON を stdout、警告を stderr） |
| `rebuild/dev/pytest.ini` | pytest 設定（testpaths=tests、マーカー定義） |
| `rebuild/dev/examples/configs/sample-ios-r1.cfg` | 要件書 附録 B.1 を転記 |
| `rebuild/dev/examples/configs/sample-junos-r2.conf` | 要件書 附録 B.2 を転記 |
| `rebuild/dev/tests/test_*.py` | 各層のテスト |
| `rebuild/README.md` | 実行方法の簡潔な説明（M4 まで追記する土台） |

---

## Task 1: プロジェクト雛形とサンプル config

新規 `rebuild/` ツリー・pytest 設定・附録 B のサンプル config を用意する。テストはまだ無い（次タスク以降で TDD）。

**Files:**
- Create: `rebuild/lib/__init__.py`（空）
- Create: `rebuild/lib/parsers/__init__.py`（このタスクでは空。Task 5 で実装）
- Create: `rebuild/dev/pytest.ini`
- Create: `rebuild/dev/tests/__init__.py`（空）
- Create: `rebuild/dev/tests/conftest.py`
- Create: `rebuild/dev/examples/configs/sample-ios-r1.cfg`
- Create: `rebuild/dev/examples/configs/sample-junos-r2.conf`
- Create: `rebuild/README.md`

- [ ] **Step 1: ディレクトリと空 `__init__.py` を作成**

```bash
mkdir -p rebuild/lib/parsers rebuild/scripts rebuild/dev/tests rebuild/dev/examples/configs
: > rebuild/lib/__init__.py
: > rebuild/lib/parsers/__init__.py
: > rebuild/dev/tests/__init__.py
```

- [ ] **Step 2: `rebuild/dev/pytest.ini` を作成**

```ini
[pytest]
testpaths = tests
markers =
    unit: 単体テスト
    integration: 統合テスト
    e2e: エンドツーエンドテスト
```

- [ ] **Step 3: `rebuild/dev/tests/conftest.py` を作成**

`rebuild/lib` を import 可能にし、サンプル config パスを fixture 提供する。

```python
import sys
from pathlib import Path

import pytest

# rebuild/ をインポートパスに追加（rebuild/lib を import 可能にする）
REBUILD_ROOT = Path(__file__).resolve().parents[2]
if str(REBUILD_ROOT) not in sys.path:
    sys.path.insert(0, str(REBUILD_ROOT))

CONFIG_DIR = REBUILD_ROOT / "dev" / "examples" / "configs"


@pytest.fixture
def ios_cfg_text():
    return (CONFIG_DIR / "sample-ios-r1.cfg").read_text(encoding="utf-8")


@pytest.fixture
def junos_cfg_text():
    return (CONFIG_DIR / "sample-junos-r2.conf").read_text(encoding="utf-8")
```

- [ ] **Step 4: 附録 B.1 を `sample-ios-r1.cfg` に転記**（要件書 §附録 B.1 と一字一句一致させる）

```
!
! Cisco IOS / IOS-XE running-config (sample)
!
hostname R1
!
interface GigabitEthernet0/0
 description to-R2
 ip address 10.0.0.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description LAN
 ip address 192.168.1.1 255.255.255.0
!
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
!
router bgp 65001
 neighbor 10.0.0.2 remote-as 65002
!
router ospf 1
 network 192.168.1.0 0.0.0.255 area 0
!
ip route 0.0.0.0 0.0.0.0 10.0.0.2
!
end
```

- [ ] **Step 5: 附録 B.2 を `sample-junos-r2.conf` に転記**（要件書 §附録 B.2 と一致させる）

```
## Juniper JunOS configuration in `set` format (sample)
set system host-name R2
set interfaces ge-0/0/0 description to-R1
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30
set interfaces ge-0/0/1 description LAN2
set interfaces ge-0/0/1 unit 0 family inet address 192.168.2.1/24
set interfaces lo0 unit 0 family inet address 2.2.2.2/32
set routing-options autonomous-system 65002
set protocols bgp group ext type external
set protocols bgp group ext neighbor 10.0.0.1 peer-as 65001
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1
```

- [ ] **Step 6: `rebuild/README.md` を作成（最小）**

```markdown
# config-topology rebuild

config テキストからネットワーク・トポロジー（層別 YAML / HTML）を生成するパイプラインの再実装。

仕様正本: `../docs/requirements.md` v2.1 ／ 進め方: `../docs/implementation-instructions.md`

## テスト
    cd rebuild/dev && python3 -m pytest -q

## CLI（M1 時点）
    python3 rebuild/scripts/parse_configs.py <paths...>   # 正規化 Device を JSON 出力
```

- [ ] **Step 7: pytest が空でも起動することを確認**

Run: `cd rebuild/dev && python3 -m pytest -q`
Expected: `no tests ran`（collection エラーが出ないこと。conftest の import パスが通る）

- [ ] **Step 8: Commit**

```bash
git add rebuild/
git commit -m "chore(rebuild): scaffold M1 parser layer (dirs, pytest, sample configs)"
```

---

## Task 2: 正規化ヘルパ `normalize.py`（要件書 §6.3）

IP/CIDR/IPv6/wildcard/OSPF area の正規化を標準 `ipaddress` で実装する。最初に書く層（依存なし）。

**Files:**
- Create: `rebuild/lib/normalize.py`
- Test: `rebuild/dev/tests/test_normalize.py`

- [ ] **Step 1: 失敗するテストを書く**

`rebuild/dev/tests/test_normalize.py`:

```python
"""§6.3 共通規則: IP / CIDR / OSPF area 正規化のテスト。"""
import pytest

from lib import normalize as N

pytestmark = pytest.mark.unit


def test_norm_ipv4_strips_leading_zeros():
    assert N.norm_ipv4("010.000.000.001") == "10.0.0.1"
    assert N.norm_ipv4("10.0.0.1") == "10.0.0.1"


def test_mask_to_prefix():
    assert N.mask_to_prefix("255.255.255.252") == 30
    assert N.mask_to_prefix("255.255.255.0") == 24
    assert N.mask_to_prefix("255.255.255.255") == 32


def test_wildcard_to_prefix():
    # network <addr> <wildcard> area <a> の wildcard を prefix へ
    assert N.wildcard_to_prefix("0.0.0.255") == 24
    assert N.wildcard_to_prefix("0.0.0.0") == 32
    assert N.wildcard_to_prefix("0.0.0.3") == 30


def test_norm_cidr_removes_host_bits():
    assert N.norm_cidr("192.168.1.0", 24) == "192.168.1.0/24"
    assert N.norm_cidr("10.0.0.1", 30) == "10.0.0.0/30"  # ホストビット除去


def test_norm_cidr_str_v4_and_v6():
    assert N.norm_cidr_str("0.0.0.0/0") == "0.0.0.0/0"
    assert N.norm_cidr_str("2001:db8:0:0::/64") == "2001:db8::/64"  # 短縮形


def test_norm_ipv6_rfc5952():
    assert N.norm_ipv6("2001:0db8:0000:0000:0000:0000:0000:0001") == "2001:db8::1"
    assert N.norm_ipv6("FE80::1") == "fe80::1"


def test_v6_scope_link_local():
    assert N.v6_scope("fe80::1") == "link-local"
    assert N.v6_scope("2001:db8::1") is None


@pytest.mark.parametrize("raw,expected", [
    ("0", "0"),
    ("1", "1"),
    ("100", "100"),
    ("0.0.0.0", "0"),
    ("0.0.0.1", "1"),
    ("0.0.1.0", "256"),
    ("1.2.3.4", "16909060"),
    ("backbone", "backbone"),   # 不正値は原文のまま（クラッシュしない）
    ("0.0.0.999", "0.0.0.999"), # オクテット範囲外は原文
])
def test_norm_ospf_area(raw, expected):
    assert N.norm_ospf_area(raw) == expected
```

- [ ] **Step 2: テストが import 失敗で落ちることを確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_normalize.py -q`
Expected: FAIL（`ModuleNotFoundError: lib.normalize` または collection error）

- [ ] **Step 3: `rebuild/lib/normalize.py` を実装**

```python
"""IP / CIDR / IPv6 / OSPF area の正規化（要件書 §6.3）。標準 ipaddress のみ使用。"""
import ipaddress

_LINK_LOCAL = ipaddress.ip_network("fe80::/10")


def norm_ipv4(ip):
    """IPv4 を先行ゼロ除去の標準ドット 10 進へ。"""
    return str(ipaddress.IPv4Address(ip.strip()))


def norm_ipv6(ip):
    """IPv6 を RFC 5952 短縮形へ。"""
    return str(ipaddress.IPv6Address(ip.strip()))


def mask_to_prefix(mask):
    """サブネットマスク（255.255.255.252）を prefix 長（30）へ。"""
    return ipaddress.IPv4Network("0.0.0.0/" + mask.strip()).prefixlen


def wildcard_to_prefix(wildcard):
    """ワイルドカードマスク（0.0.0.255）を prefix 長（24）へ。"""
    mask_int = int(ipaddress.IPv4Address(wildcard.strip())) ^ 0xFFFFFFFF
    return bin(mask_int).count("1")


def norm_cidr(ip, prefix):
    """ホストアドレス + prefix からホストビットを除去した CIDR 文字列へ。"""
    net = ipaddress.ip_network("%s/%s" % (ip, prefix), strict=False)
    return "%s/%s" % (net.network_address, net.prefixlen)


def norm_cidr_str(cidr):
    """`a.b.c.d/len` 形式の CIDR を正規化（ホストビット除去・v6 短縮形）。"""
    net = ipaddress.ip_network(cidr.strip(), strict=False)
    return "%s/%s" % (net.network_address, net.prefixlen)


def v6_scope(ip):
    """fe80::/10 に属すなら 'link-local'、それ以外は None。"""
    return "link-local" if ipaddress.IPv6Address(ip) in _LINK_LOCAL else None


def norm_ospf_area(area):
    """OSPF area を整数文字列へ正規化（§6.3）。不正値は原文のまま返す。"""
    area = area.strip()
    if area.isdigit():
        return area
    parts = area.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        a, b, c, d = (int(p) for p in parts)
        return str((a << 24) | (b << 16) | (c << 8) | d)
    return area
```

- [ ] **Step 4: テスト合格を確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_normalize.py -q`
Expected: PASS（全 12+ ケース）

- [ ] **Step 5: Commit**

```bash
git add rebuild/lib/normalize.py rebuild/dev/tests/test_normalize.py
git commit -m "feat(rebuild): add IP/CIDR/OSPF-area normalization (§6.3)"
```

---

## Task 3: 正規化データモデル `models.py`（要件書 §4.1）

dataclass 群と、addresses 並び順（§4.1）・派生 `ip`（§4.1）ロジックを実装する。

**Files:**
- Create: `rebuild/lib/models.py`
- Test: `rebuild/dev/tests/test_models.py`

- [ ] **Step 1: 失敗するテストを書く**

`rebuild/dev/tests/test_models.py`:

```python
"""§4.1 データモデル: addresses 並び順・派生 ip・to_dict のテスト。"""
import pytest

from lib.models import Address, Interface, Device

pytestmark = pytest.mark.unit


def test_address_to_dict_omits_default_flags():
    # secondary=False / scope=None はキーを出力しない（§5.2 addresses[] 構造）
    assert Address("v4", "10.0.0.1", 30).to_dict() == {"af": "v4", "ip": "10.0.0.1", "prefix": 30}


def test_address_to_dict_includes_flags_when_set():
    d = Address("v4", "192.168.1.2", 24, secondary=True).to_dict()
    assert d == {"af": "v4", "ip": "192.168.1.2", "prefix": 24, "secondary": True}
    d6 = Address("v6", "fe80::1", 64, scope="link-local").to_dict()
    assert d6 == {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"}


def test_sorted_addresses_v4_before_v6_then_ip_then_prefix():
    addrs = [
        Address("v6", "2001:db8::1", 64),
        Address("v4", "192.168.1.1", 24),
        Address("v4", "10.0.0.1", 24),
        Address("v4", "10.0.0.1", 30),
    ]
    iface = Interface(name="x", addresses=addrs)
    order = [(a.af, a.ip, a.prefix) for a in iface.sorted_addresses()]
    assert order == [
        ("v4", "10.0.0.1", 24),
        ("v4", "10.0.0.1", 30),
        ("v4", "192.168.1.1", 24),
        ("v6", "2001:db8::1", 64),
    ]


def test_derived_ip_first_non_secondary_v4():
    iface = Interface(name="x", addresses=[
        Address("v4", "10.0.0.9", 24, secondary=True),
        Address("v4", "10.0.0.1", 24),
    ])
    assert iface.derived_ip() == "10.0.0.1/24"  # secondary を飛ばし sorted 先頭の非 secondary v4


def test_derived_ip_none_for_v6_only():
    iface = Interface(name="x", addresses=[Address("v6", "2001:db8::1", 64)])
    assert iface.derived_ip() is None


def test_derived_ip_none_when_no_address():
    assert Interface(name="x").derived_ip() is None


def test_device_as_key_mapping():
    dev = Device(hostname="R1", vendor="cisco_ios", as_=65001)
    # as_ 属性が辞書化で 'as' キーになる（§4.1）
    assert dev.to_dict()["as"] == 65001
    assert dev.to_dict()["hostname"] == "R1"
```

- [ ] **Step 2: テストが落ちることを確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_models.py -q`
Expected: FAIL（`ModuleNotFoundError: lib.models`）

- [ ] **Step 3: `rebuild/lib/models.py` を実装**

```python
"""ベンダー中立の正規化データモデル（要件書 §4.1）。パイプライン全体の中心。"""
import ipaddress
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Address:
    af: str            # "v4" | "v6"
    ip: str            # ホストアドレス（prefix なし・正規化済み）
    prefix: int
    secondary: bool = False
    scope: Optional[str] = None   # "link-local" | None

    def sort_key(self):
        fam = 0 if self.af == "v4" else 1
        return (fam, int(ipaddress.ip_address(self.ip)), self.prefix)

    def to_dict(self):
        d = {"af": self.af, "ip": self.ip, "prefix": self.prefix}
        if self.secondary:
            d["secondary"] = True
        if self.scope:
            d["scope"] = self.scope
        return d


@dataclass
class BgpNeighbor:
    neighbor_ip: str
    peer_as: Optional[int]
    af: str

    def to_dict(self):
        return {"neighbor_ip": self.neighbor_ip, "peer_as": self.peer_as, "af": self.af}


@dataclass
class OspfNetwork:
    process: Optional[int]
    network: str
    area: str
    af: str

    def to_dict(self):
        return {"process": self.process, "network": self.network,
                "area": self.area, "af": self.af}


@dataclass
class StaticRoute:
    prefix: str
    next_hop: str
    af: str

    def to_dict(self):
        return {"prefix": self.prefix, "next_hop": self.next_hop, "af": self.af}


@dataclass
class Interface:
    name: str
    addresses: List[Address] = field(default_factory=list)
    description: Optional[str] = None
    shutdown: bool = False
    admin_status: Optional[str] = None
    oper_status: Optional[str] = None
    mtu: Optional[int] = None
    speed: Optional[str] = None
    duplex: Optional[str] = None
    l2_l3: Optional[str] = None
    switchport: Optional[dict] = None
    encapsulation: Optional[str] = None
    vlan: Optional[int] = None

    def sorted_addresses(self):
        return sorted(self.addresses, key=lambda a: a.sort_key())

    def derived_ip(self):
        """addresses 中、並び順先頭の非 secondary v4 から `a.b.c.d/prefix` を派生（§4.1）。"""
        for a in self.sorted_addresses():
            if a.af == "v4" and not a.secondary:
                return "%s/%s" % (a.ip, a.prefix)
        return None

    def to_dict(self):
        return {
            "name": self.name,
            "addresses": [a.to_dict() for a in self.sorted_addresses()],
            "ip": self.derived_ip(),
            "description": self.description,
            "shutdown": self.shutdown,
            "admin_status": self.admin_status,
            "oper_status": self.oper_status,
            "mtu": self.mtu,
            "speed": self.speed,
            "duplex": self.duplex,
            "l2_l3": self.l2_l3,
            "switchport": self.switchport,
            "encapsulation": self.encapsulation,
            "vlan": self.vlan,
        }


@dataclass
class Device:
    hostname: str
    vendor: str
    as_: Optional[int] = None
    ospf_router_id: Optional[str] = None
    bgp_router_id: Optional[str] = None
    interfaces: List[Interface] = field(default_factory=list)
    bgp: List[BgpNeighbor] = field(default_factory=list)
    ospf: List[OspfNetwork] = field(default_factory=list)
    static: List[StaticRoute] = field(default_factory=list)

    def to_dict(self):
        return {
            "hostname": self.hostname,
            "vendor": self.vendor,
            "as": self.as_,
            "ospf_router_id": self.ospf_router_id,
            "bgp_router_id": self.bgp_router_id,
            "interfaces": [i.to_dict() for i in self.interfaces],
            "bgp": [n.to_dict() for n in self.bgp],
            "ospf": [o.to_dict() for o in self.ospf],
            "static": [s.to_dict() for s in self.static],
        }
```

- [ ] **Step 4: テスト合格を確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add rebuild/lib/models.py rebuild/dev/tests/test_models.py
git commit -m "feat(rebuild): add normalized data model (Device/Interface/Address …) (§4.1)"
```

---

## Task 4: 入力収集 `inputs.py`（要件書 §2.2）

ファイル・ディレクトリ・glob を受け、対象拡張子を名前順・重複排除で収集する。

**Files:**
- Create: `rebuild/lib/inputs.py`
- Test: `rebuild/dev/tests/test_inputs.py`

- [ ] **Step 1: 失敗するテストを書く**

`rebuild/dev/tests/test_inputs.py`:

```python
"""§2.2 入力ファイル収集: 拡張子・名前順・重複排除・dir/glob・workspace 既定。"""
import os

import pytest

from lib.inputs import collect_inputs

pytestmark = pytest.mark.unit


def _touch(p, text="x"):
    p.write_text(text, encoding="utf-8")


def test_collect_explicit_files_sorted_by_name(tmp_path):
    b = tmp_path / "b.cfg"; _touch(b)
    a = tmp_path / "a.cfg"; _touch(a)
    result = collect_inputs([str(b), str(a)])
    assert [os.path.basename(p) for p in result] == ["a.cfg", "b.cfg"]


def test_collect_directory_filters_by_extension(tmp_path):
    _touch(tmp_path / "r1.cfg")
    _touch(tmp_path / "r2.conf")
    _touch(tmp_path / "r3.txt")
    _touch(tmp_path / "ignore.log")   # 対象外拡張子
    _touch(tmp_path / "notes.md")     # 対象外
    result = collect_inputs([str(tmp_path)])
    assert [os.path.basename(p) for p in result] == ["r1.cfg", "r2.conf", "r3.txt"]


def test_collect_dedupes_same_path(tmp_path):
    f = tmp_path / "r1.cfg"; _touch(f)
    result = collect_inputs([str(f), str(f)])
    assert len(result) == 1


def test_collect_glob(tmp_path):
    _touch(tmp_path / "r1.cfg")
    _touch(tmp_path / "r2.cfg")
    _touch(tmp_path / "x.txt")
    result = collect_inputs([str(tmp_path / "*.cfg")])
    assert [os.path.basename(p) for p in result] == ["r1.cfg", "r2.cfg"]


def test_collect_default_workspace(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"; ws.mkdir()
    _touch(ws / "r1.cfg")
    monkeypatch.chdir(tmp_path)
    result = collect_inputs([])   # paths 省略 → ./workspace/ を走査
    assert [os.path.basename(p) for p in result] == ["r1.cfg"]


def test_collect_missing_workspace_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # workspace なし
    assert collect_inputs([]) == []
```

- [ ] **Step 2: テストが落ちることを確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_inputs.py -q`
Expected: FAIL（`ModuleNotFoundError: lib.inputs`）

- [ ] **Step 3: `rebuild/lib/inputs.py` を実装**

```python
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
```

- [ ] **Step 4: テスト合格を確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_inputs.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add rebuild/lib/inputs.py rebuild/dev/tests/test_inputs.py
git commit -m "feat(rebuild): add input file collection (§2.2)"
```

---

## Task 5: ベンダー判定 + 機密行フィルタ（要件書 §2.3・§9.2）

`detect_vendor` と `is_sensitive_line` を実装する（パーサ本体は次タスク）。

**Files:**
- Create: `rebuild/lib/parsers/base.py`
- Modify: `rebuild/lib/parsers/__init__.py`（`detect_vendor` を実装。`parse_config` は Task 6/7 完了後に有効化するため、このタスクでは detect のみ）
- Test: `rebuild/dev/tests/test_vendor_detect.py`

- [ ] **Step 1: 失敗するテストを書く**

`rebuild/dev/tests/test_vendor_detect.py`:

```python
"""§2.3 ベンダー自動判定・§9.2 機密行フィルタのテスト。"""
import pytest

from lib.parsers import detect_vendor
from lib.parsers.base import is_sensitive_line

pytestmark = pytest.mark.unit


def test_detect_ios(ios_cfg_text):
    assert detect_vendor(ios_cfg_text) == "cisco_ios"


def test_detect_junos(junos_cfg_text):
    assert detect_vendor(junos_cfg_text) == "juniper_junos"


def test_detect_junos_over_50pct_set():
    text = "## comment\n" + "\n".join("set x %d" % i for i in range(9))  # 9/10 = 90% set
    assert detect_vendor(text) == "juniper_junos"


def test_detect_ios_guard_excludes_over_40pct_set():
    # IOS 特徴行(hostname) を持つが set 行が 40% 超 50% 以下 → IOS 除外・JunOS にも届かず None。
    # 非空 20 行中 set 9 行 = 45%（>40% ガード該当・>50% JunOS 未満）→ None。
    lines = ["hostname R1"] + ["filler %d" % i for i in range(10)] + ["set x %d" % i for i in range(9)]
    assert detect_vendor("\n".join(lines)) is None


def test_detect_unknown_returns_none():
    assert detect_vendor("foo bar\nbaz qux\n") is None


def test_detect_blank_only_returns_none():
    assert detect_vendor("\n\n   \n") is None


def test_is_sensitive_line():
    assert is_sensitive_line(" enable secret 5 $1$abc")
    assert is_sensitive_line(" password cisco123")
    assert is_sensitive_line("set snmp community public")
    assert is_sensitive_line("snmp-server community public RO")
    assert not is_sensitive_line(" description to-R2")
    assert not is_sensitive_line(" ip address 10.0.0.1 255.255.255.252")
```

- [ ] **Step 2: テストが落ちることを確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_vendor_detect.py -q`
Expected: FAIL（`ImportError`: detect_vendor / is_sensitive_line 未定義）

- [ ] **Step 3: `rebuild/lib/parsers/base.py` を実装**

```python
"""パーサ共通ヘルパ。"""

_SENSITIVE = ("password", "secret", "snmp community", "snmp-server community")


def is_sensitive_line(line):
    """機密キーワードを含む行か（要件書 §9.2）。含む行はパースしない。"""
    low = line.lower()
    return any(k in low for k in _SENSITIVE)
```

- [ ] **Step 4: `rebuild/lib/parsers/__init__.py` に `detect_vendor` を実装**

このタスクでは detect のみ。`parse_config` は Task 7 で IOS/JunOS パーサ実装後に追記する（前方参照を避ける）。

```python
"""ベンダー判定と dispatch（要件書 §2.3）。"""
import re

from .base import is_sensitive_line  # noqa: F401  (再 export)

_IOS_IF_RE = re.compile(r"^\s*interface\s+\S*Ethernet", re.IGNORECASE)


def _nonempty_lines(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def _set_ratio(lines):
    if not lines:
        return 0.0
    n = sum(1 for ln in lines if ln.lstrip().startswith("set "))
    return n / len(lines)


def _has_ios_features(lines):
    for ln in lines:
        s = ln.strip()
        if s.startswith("hostname "):
            return True
        if _IOS_IF_RE.match(ln):
            return True
        if s == "!":
            return True
    return False


def detect_vendor(text):
    """特異度の高い順（JunOS → IOS）に判定。未知は None（§2.3）。"""
    lines = _nonempty_lines(text)
    ratio = _set_ratio(lines)
    if ratio > 0.5:                                  # JunOS: set 行が過半
        return "juniper_junos"
    if ratio <= 0.4 and _has_ios_features(lines):    # IOS: 40% ガードを通過し特徴行あり
        return "cisco_ios"
    return None
```

- [ ] **Step 5: テスト合格を確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_vendor_detect.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add rebuild/lib/parsers/base.py rebuild/lib/parsers/__init__.py rebuild/dev/tests/test_vendor_detect.py
git commit -m "feat(rebuild): add vendor detection + sensitive-line filter (§2.3/§9.2)"
```

---

## Task 6: IOS パーサ `ios.py`（要件書 §6.1）

`parse_ios(text, warnings)` を実装し、附録 B.1 と §6.1 マッピング表の各行を正規化モデルへ変換する。

**Files:**
- Create: `rebuild/lib/parsers/ios.py`
- Test: `rebuild/dev/tests/test_ios_parser.py`

- [ ] **Step 1: 失敗するテストを書く**（B.1 全フィールド + §6.1 各行の境界）

`rebuild/dev/tests/test_ios_parser.py`:

```python
"""§6.1 Cisco IOS パーサのテスト。附録 B.1 と各マッピング行を検証。"""
import pytest

from lib.parsers.ios import parse_ios

pytestmark = pytest.mark.unit


def _parse(text):
    warnings = []
    return parse_ios(text, warnings), warnings


def test_b1_device_fields(ios_cfg_text):
    dev, _ = _parse(ios_cfg_text)
    assert dev.hostname == "R1"
    assert dev.vendor == "cisco_ios"
    assert dev.as_ == 65001
    assert dev.ospf_router_id is None
    assert dev.bgp_router_id is None


def test_b1_interfaces(ios_cfg_text):
    dev, _ = _parse(ios_cfg_text)
    names = [i.name for i in dev.interfaces]
    assert names == ["GigabitEthernet0/0", "GigabitEthernet0/1", "Loopback0"]

    gi0 = dev.interfaces[0]
    assert gi0.description == "to-R2"
    assert [(a.af, a.ip, a.prefix) for a in gi0.addresses] == [("v4", "10.0.0.1", 30)]
    assert gi0.derived_ip() == "10.0.0.1/30"
    assert gi0.shutdown is False
    assert gi0.admin_status == "up"
    assert gi0.l2_l3 == "l3"
    # 全フィールドが既定値で埋まる
    assert gi0.mtu is None and gi0.speed is None and gi0.duplex is None
    assert gi0.switchport is None and gi0.encapsulation is None and gi0.vlan is None
    assert gi0.oper_status is None

    lo0 = dev.interfaces[2]
    assert lo0.description is None
    assert [(a.af, a.ip, a.prefix) for a in lo0.addresses] == [("v4", "1.1.1.1", 32)]


def test_b1_bgp(ios_cfg_text):
    dev, _ = _parse(ios_cfg_text)
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert (nb.neighbor_ip, nb.peer_as, nb.af) == ("10.0.0.2", 65002, "v4")


def test_b1_ospf(ios_cfg_text):
    dev, _ = _parse(ios_cfg_text)
    assert len(dev.ospf) == 1
    o = dev.ospf[0]
    assert (o.process, o.network, o.area, o.af) == (1, "192.168.1.0/24", "0", "v4")


def test_b1_static(ios_cfg_text):
    dev, _ = _parse(ios_cfg_text)
    assert len(dev.static) == 1
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("0.0.0.0/0", "10.0.0.2", "v4")


def test_shutdown_sets_admin_down():
    text = "hostname X\ninterface GigabitEthernet0/0\n shutdown\n!\n"
    dev, _ = _parse(text)
    assert dev.interfaces[0].shutdown is True
    assert dev.interfaces[0].admin_status == "down"


def test_secondary_address():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            " ip address 10.0.0.9 255.255.255.0 secondary\n!\n")
    dev, _ = _parse(text)
    addrs = dev.interfaces[0].addresses
    sec = [a for a in addrs if a.secondary]
    assert len(sec) == 1 and sec[0].ip == "10.0.0.9"
    assert dev.interfaces[0].derived_ip() == "10.0.0.1/24"  # 非 secondary が派生


def test_ipv6_address_and_link_local():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 address 2001:db8::1/64\n"
            " ipv6 address fe80::1/64 link-local\n!\n")
    dev, _ = _parse(text)
    addrs = {(a.af, a.ip, a.prefix, a.scope) for a in dev.interfaces[0].addresses}
    assert ("v6", "2001:db8::1", 64, None) in addrs
    assert ("v6", "fe80::1", 64, "link-local") in addrs


def test_switchport_access_l2():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " switchport mode access\n switchport access vlan 10\n!\n")
    dev, _ = _parse(text)
    i = dev.interfaces[0]
    assert i.switchport == {"mode": "access", "access_vlan": 10}
    assert i.l2_l3 == "l2"


def test_switchport_trunk_l2():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " switchport mode trunk\n switchport trunk allowed vlan 10,20-30\n!\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].switchport == {"mode": "trunk", "trunk_vlans": "10,20-30"}


def test_l3_priority_over_switchport():
    # ip address と switchport が両方あっても L3 が優先（§6.1 L2/L3 判定）
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " switchport mode access\n ip address 10.0.0.1 255.255.255.0\n!\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].l2_l3 == "l3"


def test_no_switchport_is_l3():
    text = "hostname X\ninterface GigabitEthernet0/0\n no switchport\n!\n"
    dev, _ = _parse(text)
    assert dev.interfaces[0].l2_l3 == "l3"


def test_mtu_speed_duplex_encapsulation():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " mtu 9000\n speed 1000\n duplex full\n encapsulation dot1Q 100\n!\n")
    dev, _ = _parse(text)
    i = dev.interfaces[0]
    assert i.mtu == 9000 and i.speed == "1000" and i.duplex == "full"
    assert i.encapsulation == "dot1q"


def test_ospf_dotted_area_normalized():
    text = ("hostname X\nrouter ospf 1\n"
            " network 10.1.0.0 0.0.255.255 area 0.0.0.1\n!\n")
    dev, _ = _parse(text)
    assert dev.ospf[0].area == "1"
    assert dev.ospf[0].network == "10.1.0.0/16"


def test_ipv6_route_static():
    text = "hostname X\nipv6 route 2001:db8:1::/48 2001:db8::2\n"
    dev, _ = _parse(text)
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("2001:db8:1::/48", "2001:db8::2", "v6")


def test_sensitive_lines_skipped():
    text = ("hostname X\nenable secret 5 $1$xyz\ninterface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n!\n")
    dev, _ = _parse(text)
    assert dev.hostname == "X"   # secret 行はスキップされクラッシュしない
    assert dev.interfaces[0].derived_ip() == "10.0.0.1/24"


def test_bad_line_warns_not_crash():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip address GARBAGE not-a-mask\n!\n")
    dev, warnings = _parse(text)
    assert dev.interfaces[0].addresses == []   # 不正行は無視
    assert len(warnings) >= 1                   # 警告に積まれる
```

- [ ] **Step 2: テストが落ちることを確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_ios_parser.py -q`
Expected: FAIL（`ModuleNotFoundError: lib.parsers.ios`）

- [ ] **Step 3: `rebuild/lib/parsers/ios.py` を実装**

```python
"""Cisco IOS / IOS-XE パーサ（要件書 §6.1）。"""
import re

from ..models import Address, BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute
from ..normalize import (mask_to_prefix, norm_cidr, norm_cidr_str, norm_ipv4,
                         norm_ipv6, norm_ospf_area, v6_scope, wildcard_to_prefix)
from .base import is_sensitive_line


def _set_l3(iface):
    iface.l2_l3 = "l3"   # L3 は switchport より優先（無条件上書き）


def _set_l2(iface):
    if iface.l2_l3 != "l3":   # L3 が既にあれば L2 にしない
        iface.l2_l3 = "l2"


def _parse_iface_line(iface, s, warnings):
    m = re.match(r"^description\s+(.*)$", s)
    if m:
        iface.description = m.group(1).strip().strip('"')
        return
    m = re.match(r"^ip address\s+(\S+)\s+(\S+)(\s+secondary)?\s*$", s)
    if m:
        ip, mask, sec = m.group(1), m.group(2), bool(m.group(3))
        try:
            iface.addresses.append(Address("v4", norm_ipv4(ip), mask_to_prefix(mask),
                                            secondary=sec))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("ip address parse failed: %s (%s)" % (s, e))
        return
    m = re.match(r"^ipv6 address\s+(\S+)(\s+link-local)?\s*$", s, re.IGNORECASE)
    if m:
        cidr, ll = m.group(1), bool(m.group(2))
        try:
            host, plen = cidr.split("/")
            ip = norm_ipv6(host)
            scope = "link-local" if ll else v6_scope(ip)
            iface.addresses.append(Address("v6", ip, int(plen), scope=scope))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("ipv6 address parse failed: %s (%s)" % (s, e))
        return
    if s == "shutdown":
        iface.shutdown = True
        return
    if s == "no shutdown":
        iface.shutdown = False
        return
    if s == "no switchport":
        _set_l3(iface)
        return
    m = re.match(r"^mtu\s+(\d+)", s)
    if m:
        iface.mtu = int(m.group(1))
        return
    m = re.match(r"^speed\s+(\S+)", s)
    if m:
        iface.speed = m.group(1)
        return
    m = re.match(r"^duplex\s+(\S+)", s)
    if m:
        iface.duplex = m.group(1)
        return
    m = re.match(r"^encapsulation\s+dot1q\b", s, re.IGNORECASE)
    if m:
        iface.encapsulation = "dot1q"
        return
    m = re.match(r"^switchport mode\s+(access|trunk)", s)
    if m:
        iface.switchport = iface.switchport or {}
        iface.switchport["mode"] = m.group(1)
        _set_l2(iface)
        return
    m = re.match(r"^switchport access vlan\s+(\d+)", s)
    if m:
        iface.switchport = iface.switchport or {}
        iface.switchport["access_vlan"] = int(m.group(1))
        _set_l2(iface)
        return
    m = re.match(r"^switchport trunk allowed vlan\s+(\S+)", s)
    if m:
        iface.switchport = iface.switchport or {}
        iface.switchport["trunk_vlans"] = m.group(1)
        _set_l2(iface)
        return


def parse_ios(text, warnings):
    dev = Device(hostname="", vendor="cisco_ios")
    cur = None            # 現在の Interface
    context = None        # None | "interface" | "bgp" | "ospf"
    ospf_pid = None
    bgp_af = ["v4"]       # address-family の現在値（list で可変参照）
    neighbors = {}        # neighbor_ip -> BgpNeighbor（af 昇格用）

    def finish_iface():
        nonlocal cur
        if cur is not None:
            cur.admin_status = "down" if cur.shutdown else "up"
            dev.interfaces.append(cur)
            cur = None

    for raw in text.splitlines():
        if is_sensitive_line(raw):
            continue
        s = raw.strip()
        if not s:
            continue

        if s == "!" or s == "end":
            finish_iface()
            context = None
            continue

        m = re.match(r"^hostname\s+(\S+)$", s)
        if m:
            if dev.hostname == "":
                dev.hostname = m.group(1)
            continue
        m = re.match(r"^interface\s+(\S+)", s)
        if m:
            finish_iface()
            cur = Interface(name=m.group(1))
            context = "interface"
            continue
        m = re.match(r"^router bgp\s+(\d+)", s)
        if m:
            finish_iface()
            dev.as_ = int(m.group(1))
            context, bgp_af[0] = "bgp", "v4"
            continue
        m = re.match(r"^router ospf\s+(\d+)", s)
        if m:
            finish_iface()
            ospf_pid = int(m.group(1))
            context = "ospf"
            continue
        if re.match(r"^ipv6 router ospf\s+\d+", s):
            finish_iface()
            context = None
            continue
        m = re.match(r"^ip route\s+(\S+)\s+(\S+)\s+(\S+)", s)
        if m:
            net, mask, nh = m.groups()
            try:
                prefix = mask_to_prefix(mask)
                dev.static.append(StaticRoute(norm_cidr(norm_ipv4(net), prefix),
                                              norm_ipv4(nh), "v4"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("ip route parse failed: %s (%s)" % (s, e))
            continue
        m = re.match(r"^ipv6 route\s+(\S+)\s+(\S+)", s)
        if m:
            cidr, nh = m.groups()
            try:
                dev.static.append(StaticRoute(norm_cidr_str(cidr), norm_ipv6(nh), "v6"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("ipv6 route parse failed: %s (%s)" % (s, e))
            continue

        if context == "interface" and cur is not None:
            _parse_iface_line(cur, s, warnings)
        elif context == "bgp":
            if s.startswith("address-family ipv6"):
                bgp_af[0] = "v6"
            elif s.startswith("address-family ipv4"):
                bgp_af[0] = "v4"
            else:
                _parse_bgp_line(dev, s, bgp_af, neighbors, warnings)
        elif context == "ospf":
            _parse_ospf_line(dev, s, ospf_pid, warnings)

    finish_iface()
    return dev


def _parse_bgp_line(dev, s, bgp_af, neighbors, warnings):
    m = re.match(r"^bgp router-id\s+(\S+)", s)
    if m:
        dev.bgp_router_id = m.group(1)
        return
    m = re.match(r"^neighbor\s+(\S+)\s+remote-as\s+(\d+)", s)
    if m:
        ip, peer = m.group(1), int(m.group(2))
        try:
            af = "v6" if ":" in ip else "v4"
            nip = norm_ipv6(ip) if af == "v6" else norm_ipv4(ip)
            nb = BgpNeighbor(nip, peer, af)
            dev.bgp.append(nb)
            neighbors[nip] = nb
        except Exception as e:                       # noqa: BLE001
            warnings.append("bgp neighbor parse failed: %s (%s)" % (s, e))
        return
    m = re.match(r"^neighbor\s+(\S+)\s+activate", s)
    if m and bgp_af[0] == "v6" and ":" in m.group(1):
        try:
            nip = norm_ipv6(m.group(1))
            if nip in neighbors:
                neighbors[nip].af = "v6"
        except Exception:                            # noqa: BLE001
            pass
        return


def _parse_ospf_line(dev, s, ospf_pid, warnings):
    m = re.match(r"^router-id\s+(\S+)", s)
    if m:
        dev.ospf_router_id = m.group(1)
        return
    m = re.match(r"^network\s+(\S+)\s+(\S+)\s+area\s+(\S+)", s)
    if m:
        net, wild, area = m.groups()
        try:
            prefix = wildcard_to_prefix(wild)
            dev.ospf.append(OspfNetwork(ospf_pid, norm_cidr(norm_ipv4(net), prefix),
                                        norm_ospf_area(area), "v4"))
        except Exception as e:                       # noqa: BLE001
            warnings.append("ospf network parse failed: %s (%s)" % (s, e))
        return
```

> 注（実装者向け・2026-06-13 ユーザー判断で IN SCOPE 化）: §6.1 の `ipv6 ospf <pid> area <a>`（interface 内 OSPFv3）行は当初スコープ外としていたが、ユーザー判断で M1 実装対象に変更。interface ブロック内で検出して `pending_ospf3=[(iface,pid,area)]` に積み、最終 `finish_iface()` 後に IF のグローバル v6 サブネット（`_iface_v6_network`、無ければ IF 名）から `OspfNetwork(process=pid, network, area=norm_ospf_area(a), af="v6")` を生成する。あわせて BGP ブランチに `exit-address-family` → `bgp_af[0]="v4"` リセットを追加（v6 AF 漏洩防止）。テスト3本（v6サブネット解決・IF名フォールバック・宣言が address 行より前）を追加。実装済み（commit 4ca6669）。

- [ ] **Step 4: テスト合格を確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_ios_parser.py -q`
Expected: PASS（全ケース）

- [ ] **Step 5: Commit**

```bash
git add rebuild/lib/parsers/ios.py rebuild/dev/tests/test_ios_parser.py
git commit -m "feat(rebuild): add Cisco IOS parser (§6.1)"
```

---

## Task 7: JunOS パーサ `junos.py` + dispatch（要件書 §6.2）

`parse_junos(text, warnings)` を実装し、附録 B.2 と §6.2 マッピングを変換する。最後に `parse_config` dispatch を有効化する。

**Files:**
- Create: `rebuild/lib/parsers/junos.py`
- Modify: `rebuild/lib/parsers/__init__.py`（`parse_config` を追記）
- Test: `rebuild/dev/tests/test_junos_parser.py`

- [ ] **Step 1: 失敗するテストを書く**

`rebuild/dev/tests/test_junos_parser.py`:

```python
"""§6.2 Juniper JunOS パーサのテスト。附録 B.2 と各マッピング行を検証。"""
import pytest

from lib.parsers.junos import parse_junos

pytestmark = pytest.mark.unit


def _parse(text):
    warnings = []
    return parse_junos(text, warnings), warnings


def test_b2_device_fields(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert dev.hostname == "R2"
    assert dev.vendor == "juniper_junos"
    assert dev.as_ == 65002
    assert dev.ospf_router_id is None
    assert dev.bgp_router_id is None


def test_b2_interfaces(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    names = [i.name for i in dev.interfaces]
    assert names == ["ge-0/0/0", "ge-0/0/1", "lo0"]

    ge0 = dev.interfaces[0]
    assert ge0.description == "to-R1"
    assert [(a.af, a.ip, a.prefix) for a in ge0.addresses] == [("v4", "10.0.0.2", 30)]
    assert ge0.derived_ip() == "10.0.0.2/30"
    assert ge0.shutdown is False
    assert ge0.admin_status == "up"
    assert ge0.l2_l3 == "l3"
    assert ge0.switchport is None   # JunOS は常に null


def test_b2_bgp(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert (nb.neighbor_ip, nb.peer_as, nb.af) == ("10.0.0.1", 65001, "v4")


def test_b2_static(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert len(dev.static) == 1
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("0.0.0.0/0", "10.0.0.1", "v4")


def test_b2_no_ospf(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert dev.ospf == []


def test_unit_aggregation_multiple_addresses():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.1.1/24\n")
    dev, _ = _parse(text)
    assert len(dev.interfaces) == 1                       # unit は IF 名に含めず集約
    assert len(dev.interfaces[0].addresses) == 2


def test_disable_sets_admin_down():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 disable\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].shutdown is True
    assert dev.interfaces[0].admin_status == "down"


def test_inet6_and_link_local():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64\n"
            "set interfaces ge-0/0/0 unit 0 family inet6 address fe80::1/64\n")
    dev, _ = _parse(text)
    addrs = {(a.af, a.ip, a.scope) for a in dev.interfaces[0].addresses}
    assert ("v6", "2001:db8::1", None) in addrs
    assert ("v6", "fe80::1", "link-local") in addrs       # fe80::/10 を自動判定
    assert dev.interfaces[0].l2_l3 == "l3"


def test_ethernet_switching_is_l2():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family ethernet-switching\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].l2_l3 == "l2"


def test_l2_priority_over_l3():
    # ethernet-switching と inet address が両方 → L2 優先（§6.2 L2/L3 判定）
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family ethernet-switching\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].l2_l3 == "l2"


def test_mtu_speed_encapsulation():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 mtu 9000\n"
            "set interfaces ge-0/0/0 speed 10g\n"
            "set interfaces ge-0/0/0 encapsulation flexible-ethernet-services\n")
    dev, _ = _parse(text)
    i = dev.interfaces[0]
    assert i.mtu == 9000 and i.speed == "10g"
    assert i.encapsulation == "flexible-ethernet-services"


def test_router_id_sets_bgp_and_ospf_fallback():
    text = ("set system host-name X\n"
            "set routing-options router-id 9.9.9.9\n")
    dev, _ = _parse(text)
    assert dev.bgp_router_id == "9.9.9.9"
    assert dev.ospf_router_id == "9.9.9.9"   # OSPF 専用が無いのでフォールバック（§5.2.1）


def test_v6_bgp_neighbor():
    text = ("set system host-name X\n"
            "set protocols bgp group g neighbor 2001:db8::2 peer-as 65010\n")
    dev, _ = _parse(text)
    nb = dev.bgp[0]
    assert (nb.neighbor_ip, nb.peer_as, nb.af) == ("2001:db8::2", 65010, "v6")


def test_ospf_v2_network_from_if_subnet():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 192.168.5.1/24\n"
            "set protocols ospf area 0.0.0.0 interface ge-0/0/0.0\n")
    dev, _ = _parse(text)
    o = dev.ospf[0]
    assert (o.process, o.network, o.area, o.af) == (None, "192.168.5.0/24", "0", "v4")


def test_ospf3_network_is_base_if_name():
    text = ("set system host-name X\n"
            "set protocols ospf3 area 0.0.0.1 interface ge-0/0/0.0\n")
    dev, _ = _parse(text)
    o = dev.ospf[0]
    assert (o.process, o.network, o.area, o.af) == (None, "ge-0/0/0", "1", "v6")


def test_v6_static_route():
    text = ("set system host-name X\n"
            "set routing-options rib inet6.0 static route 2001:db8:1::/48 next-hop 2001:db8::2\n")
    dev, _ = _parse(text)
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("2001:db8:1::/48", "2001:db8::2", "v6")


def test_dispatch_parse_config(ios_cfg_text, junos_cfg_text):
    from lib.parsers import parse_config
    assert parse_config(ios_cfg_text).vendor == "cisco_ios"
    assert parse_config(junos_cfg_text).vendor == "juniper_junos"
    assert parse_config("foo bar\nbaz qux\n") is None   # 未知ベンダー
```

- [ ] **Step 2: テストが落ちることを確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_junos_parser.py -q`
Expected: FAIL（`ModuleNotFoundError: lib.parsers.junos`）

- [ ] **Step 3: `rebuild/lib/parsers/junos.py` を実装**

```python
"""Juniper JunOS（set 形式）パーサ（要件書 §6.2）。"""
import re

from ..models import Address, BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute
from ..normalize import (norm_cidr_str, norm_ipv4, norm_ipv6, norm_ospf_area, v6_scope)
from .base import is_sensitive_line


def _set_l3(iface):
    if iface.l2_l3 != "l2":   # L2 が既にあれば上書きしない（L2 優先）
        iface.l2_l3 = "l3"


def _base_if(ifname):
    """unit 付き IF 名（ge-0/0/0.0）から base（ge-0/0/0）を返す。"""
    return ifname.split(".")[0]


def _parse_if_body(iface, rest, warnings):
    m = re.match(r"^description\s+(.*)$", rest)
    if m:
        iface.description = m.group(1).strip().strip('"')
        return
    if rest == "disable":
        iface.shutdown = True
        return
    m = re.match(r"^mtu\s+(\d+)", rest)
    if m:
        iface.mtu = int(m.group(1))
        return
    m = re.match(r"^speed\s+(\S+)", rest)
    if m:
        iface.speed = m.group(1)
        return
    m = re.match(r"^encapsulation\s+(\S+)", rest)
    if m:
        iface.encapsulation = m.group(1)
        return
    m = re.match(r"^unit\s+\d+\s+family\s+inet\s+address\s+(\S+)", rest)
    if m:
        cidr = m.group(1)
        try:
            host, plen = cidr.split("/")
            iface.addresses.append(Address("v4", norm_ipv4(host), int(plen)))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("junos inet address parse failed: %s (%s)" % (rest, e))
        return
    m = re.match(r"^unit\s+\d+\s+family\s+inet6\s+address\s+(\S+)", rest)
    if m:
        cidr = m.group(1)
        try:
            host, plen = cidr.split("/")
            ip = norm_ipv6(host)
            iface.addresses.append(Address("v6", ip, int(plen), scope=v6_scope(ip)))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("junos inet6 address parse failed: %s (%s)" % (rest, e))
        return
    if re.match(r"^unit\s+\d+\s+family\s+ethernet-switching", rest):
        iface.l2_l3 = "l2"
        return


def parse_junos(text, warnings):
    dev = Device(hostname="", vendor="juniper_junos")
    ifaces = {}        # name -> Interface（出現順保持）
    ospf_decls = []    # (area, base_if, af) を後で解決

    def get_if(name):
        if name not in ifaces:
            ifaces[name] = Interface(name=name)
        return ifaces[name]

    for raw in text.splitlines():
        if is_sensitive_line(raw):
            continue
        s = raw.strip()
        if not s.startswith("set "):
            continue
        body = s[4:].strip()

        m = re.match(r"^system host-name\s+(\S+)", body)
        if m:
            dev.hostname = m.group(1).strip('"')
            continue
        m = re.match(r"^interfaces\s+(\S+)\s+(.*)$", body)
        if m:
            _parse_if_body(get_if(m.group(1)), m.group(2), warnings)
            continue
        m = re.match(r"^routing-options autonomous-system\s+(\d+)", body)
        if m:
            dev.as_ = int(m.group(1))
            continue
        m = re.match(r"^routing-options router-id\s+(\S+)", body)
        if m:
            dev.bgp_router_id = m.group(1)
            continue
        m = re.match(r"^protocols bgp group \S+ neighbor\s+(\S+)\s+peer-as\s+(\d+)", body)
        if m:
            ip, peer = m.group(1), int(m.group(2))
            try:
                af = "v6" if ":" in ip else "v4"
                nip = norm_ipv6(ip) if af == "v6" else norm_ipv4(ip)
                dev.bgp.append(BgpNeighbor(nip, peer, af))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos bgp neighbor parse failed: %s (%s)" % (body, e))
            continue
        m = re.match(r"^protocols ospf area\s+(\S+)\s+interface\s+(\S+)", body)
        if m:
            ospf_decls.append((m.group(1), _base_if(m.group(2)), "v4"))
            continue
        m = re.match(r"^protocols ospf3 area\s+(\S+)\s+interface\s+(\S+)", body)
        if m:
            ospf_decls.append((m.group(1), _base_if(m.group(2)), "v6"))
            continue
        m = re.match(r"^routing-options rib inet6\.0 static route\s+(\S+)\s+next-hop\s+(\S+)", body)
        if m:
            pfx, nh = m.groups()
            try:
                dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv6(nh), "v6"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos v6 static parse failed: %s (%s)" % (body, e))
            continue
        m = re.match(r"^routing-options static route\s+(\S+)\s+next-hop\s+(\S+)", body)
        if m:
            pfx, nh = m.groups()
            try:
                dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv4(nh), "v4"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos static parse failed: %s (%s)" % (body, e))
            continue

    # interface 確定後に OSPF network を解決
    for area, base_if, af in ospf_decls:
        if af == "v4":
            network = _ospf_v4_network(ifaces.get(base_if)) or base_if
        else:
            network = base_if
        dev.ospf.append(OspfNetwork(None, network, norm_ospf_area(area), af))

    # admin_status 確定・出現順で interfaces 確定
    for iface in ifaces.values():
        iface.admin_status = "down" if iface.shutdown else "up"
        dev.interfaces.append(iface)

    # OSPF 専用 router-id 不在時は routing-options router-id をフォールバック（§5.2.1）
    if dev.ospf_router_id is None:
        dev.ospf_router_id = dev.bgp_router_id

    return dev


def _ospf_v4_network(iface):
    if iface is None:
        return None
    for a in iface.sorted_addresses():
        if a.af == "v4":
            return norm_cidr_str("%s/%s" % (a.ip, a.prefix))
    return None
```

- [ ] **Step 4: `rebuild/lib/parsers/__init__.py` に `parse_config` を追記**

ファイル末尾に以下を追加（detect_vendor は既存）:

```python
def parse_config(text, warnings=None):
    """ベンダー判定 → 対応パーサへ dispatch。未知は None（§2.3）。"""
    if warnings is None:
        warnings = []
    vendor = detect_vendor(text)
    if vendor == "juniper_junos":
        from .junos import parse_junos
        return parse_junos(text, warnings)
    if vendor == "cisco_ios":
        from .ios import parse_ios
        return parse_ios(text, warnings)
    return None
```

- [ ] **Step 5: テスト合格を確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_junos_parser.py -q`
Expected: PASS（全ケース）

- [ ] **Step 6: 全 unit テストを通す**

Run: `cd rebuild/dev && python3 -m pytest -m unit -q`
Expected: PASS（normalize/models/inputs/vendor/ios/junos の全テスト）

- [ ] **Step 7: Commit**

```bash
git add rebuild/lib/parsers/junos.py rebuild/lib/parsers/__init__.py rebuild/dev/tests/test_junos_parser.py
git commit -m "feat(rebuild): add JunOS parser + parse_config dispatch (§6.2)"
```

---

## Task 8: 統合テスト + `parse_configs.py` CLI（要件書 §10.1・§10.2）

附録 B.1/B.2 を入力に正規化モデルを検証する統合テストと、JSON を stdout・警告を stderr に出す CLI を実装する。

**Files:**
- Create: `rebuild/scripts/parse_configs.py`
- Test: `rebuild/dev/tests/test_parse_integration.py`

- [ ] **Step 1: 失敗する統合テストを書く**

`rebuild/dev/tests/test_parse_integration.py`:

```python
"""§附録 B / §10: 統合 — サンプル config が正しい正規化モデルになり CLI が JSON を出す。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lib.inputs import collect_inputs
from lib.parsers import parse_config

pytestmark = pytest.mark.integration

REBUILD_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REBUILD_ROOT / "dev" / "examples" / "configs"
CLI = REBUILD_ROOT / "scripts" / "parse_configs.py"


def test_full_pipeline_models():
    files = collect_inputs([str(CONFIG_DIR / "sample-ios-r1.cfg"),
                            str(CONFIG_DIR / "sample-junos-r2.conf")])
    assert [Path(f).name for f in files] == ["sample-ios-r1.cfg", "sample-junos-r2.conf"]

    devs = [parse_config(Path(f).read_text(encoding="utf-8")) for f in files]
    r1, r2 = devs
    assert r1.hostname == "R1" and r1.vendor == "cisco_ios" and r1.as_ == 65001
    assert r2.hostname == "R2" and r2.vendor == "juniper_junos" and r2.as_ == 65002
    # R1 の point-to-point IF
    gi0 = r1.interfaces[0]
    assert gi0.derived_ip() == "10.0.0.1/30"
    # R2 の対向 IF
    ge0 = r2.interfaces[0]
    assert ge0.derived_ip() == "10.0.0.2/30"


def test_cli_outputs_json_to_stdout():
    proc = subprocess.run(
        [sys.executable, str(CLI),
         str(CONFIG_DIR / "sample-ios-r1.cfg"),
         str(CONFIG_DIR / "sample-junos-r2.conf")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)          # stdout は妥当な JSON
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["hostname"] == "R1" and data[0]["vendor"] == "cisco_ios"
    assert data[0]["as"] == 65001
    assert data[1]["hostname"] == "R2"
    # 判定サマリー等は stderr に出る（stdout を汚さない）
    assert "[INFO]" in proc.stderr or "cisco_ios" in proc.stderr


def test_cli_skips_unknown_vendor_with_warning(tmp_path):
    unknown = tmp_path / "weird.cfg"
    unknown.write_text("foo bar\nbaz qux\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), str(unknown)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0             # 未知ベンダーでもクラッシュしない（§6.3）
    assert json.loads(proc.stdout) == []    # スキップされ空リスト
    assert "[WARN]" in proc.stderr          # スキップ警告
```

- [ ] **Step 2: テストが落ちることを確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_parse_integration.py -q`
Expected: FAIL（CLI 未作成で `parse_configs.py` 実行が失敗 / モデルテストは PASS する場合あり）

- [ ] **Step 3: `rebuild/scripts/parse_configs.py` を実装**

```python
#!/usr/bin/env python3
"""CLI①: 正規化 Device リストを JSON で stdout に出力（要件書 §10.1・§10.2）。

警告・進捗は stderr（[INFO]/[WARN]）。stdout は JSON のみ（パイプ可能）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # rebuild/ を import パスへ

from lib.inputs import collect_inputs            # noqa: E402
from lib.parsers import detect_vendor, parse_config  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Parse network configs into normalized Device JSON.")
    parser.add_argument("paths", nargs="*", help="config files / dirs / glob（省略時 ./workspace/）")
    args = parser.parse_args(argv)

    files = collect_inputs(args.paths)
    if not files:
        print("[WARN] 対象 config が見つかりません（拡張子: .cfg/.conf/.txt）", file=sys.stderr)

    devices, warnings = [], []
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
        dev = parse_config(text, warnings)
        devices.append(dev.to_dict())
        print("[INFO] %s: %s" % (name, vendor), file=sys.stderr)

    if warnings:
        print("[WARN] パース警告 %d 件" % len(warnings), file=sys.stderr)

    json.dump(devices, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: テスト合格を確認**

Run: `cd rebuild/dev && python3 -m pytest tests/test_parse_integration.py -q`
Expected: PASS（全 3 ケース）

- [ ] **Step 5: 全テストを通す**

Run: `cd rebuild/dev && python3 -m pytest -q`
Expected: PASS（unit + integration の全件）

- [ ] **Step 6: CLI を手動実行して JSON を目視確認**

Run:
```bash
python3 rebuild/scripts/parse_configs.py \
  rebuild/dev/examples/configs/sample-ios-r1.cfg \
  rebuild/dev/examples/configs/sample-junos-r2.conf
```
Expected: stdout に 2 デバイス分の JSON、stderr に `[INFO] sample-ios-r1.cfg: cisco_ios` 等

- [ ] **Step 7: Commit**

```bash
git add rebuild/scripts/parse_configs.py rebuild/dev/tests/test_parse_integration.py
git commit -m "feat(rebuild): add parse_configs.py CLI + integration tests (§10.1/§10.2)"
```

---

## M1 Done 条件（実装指示書 §4 M1 と対応）

すべて満たしたら M1 完了。証拠（テスト実行コマンドと passed 数）を付けて報告する。

- [ ] §6.1・§6.2 マッピング表の各行に対応する unit テストがあり合格（test_ios_parser.py / test_junos_parser.py）
- [ ] ベンダー判定の境界テスト合格（test_vendor_detect.py: set 50%/40% ガード/未知スキップ）
- [ ] OSPF area 正規化テスト合格（test_normalize.py: `"0"` 不変・`"0.0.0.0"`→`"0"`・`"1.2.3.4"`→`"16909060"`・`"backbone"` 不変）
- [ ] 附録 B.1/B.2 が正しい正規化モデルにパースされる統合テスト合格（test_parse_integration.py）
- [ ] 機密行スキップ・不正行 warning・未知ベンダースキップでクラッシュしない（§6.3）

---

## Self-Review（計画作成者による確認・済）

- **Spec coverage:** §2.2（inputs Task4）/§2.3（detect Task5）/§4.1（models Task3）/§6.1（ios Task6）/§6.2（junos Task7）/§6.3（normalize Task2）/§9.2（base Task5）/§10.1-10.2（CLI Task8）を各タスクに割当済み。
- **M1 スコープ外（意図的に未実装）:** ID 採番（§5.5）・結線推論（§7）・YAML 直列化（§3.2・§5）・参照整合検証（§5.6）・history 退避/サマリー（§10.3-10.4）は M2/M4。
- **2026-06-13 スコープ変更:** `ipv6 ospf … area`（IOS interface 内 OSPFv3）はユーザー判断で M1 IN SCOPE 化し実装済み（Task6 注記参照）。JunOS の ospf3 は元から Task7 で実装。機密行フィルタ `is_sensitive_line` は §9.2 安全側の広め部分一致を維持（§1.4 description との衝突は既知・ユーザー承認済み）。
- **Type consistency:** dataclass フィールド名・公開関数シグネチャは冒頭「データモデル定義」で固定。`as_`↔キー`as`、`l2_l3` 優先順（IOS=L3 優先 / JunOS=L2 優先）、`detect_vendor` 戻り値文字列を全タスクで統一。
- **No placeholders:** 各実装・テストステップに完全なコードを記載。
```
