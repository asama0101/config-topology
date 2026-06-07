# ベンダー別パース要点と新ベンダー追加手順

各パーサは config テキストを受け取り、ベンダー中立な**正規化モデル**（`lib/parsers/base.py` の `Device`）を返す。`build_topology.py` はこのモデルだけを見るので、パーサが差異を吸収する。

## 正規化モデル（base.py）
```python
# モジュール定数（マジック文字列を一元管理）
ADMIN_UP: str = "up"
ADMIN_DOWN: str = "down"
L2: str = "l2"
L3: str = "l3"
SOURCE_PARSED: str = "parsed"

@dataclass
class Interface:
    name: str
    ip: str | None          # "a.b.c.d/prefixlen"（CIDR 正規化済み）
    description: str | None
    shutdown: bool = False
    vlan: int | None = None
    admin_status: str | None = None   # ADMIN_UP / ADMIN_DOWN（shutdown 由来）
    oper_status: str | None = None    # None（config 取得不可・将来 SNMP 拡張で string | null）
    mtu: int | None = None            # int | None
    speed: str | None = None          # 文字列（"1000", "1g" 等。ベンダー表記のまま）
    duplex: str | None = None         # "full" / "half" / None（JunOS set では通常 None）
    l2_l3: str | None = None          # L2 / L3 / None
    switchport: dict | None = None    # {mode, access_vlan?, trunk_vlans?} | None（IOS 専用）
    encapsulation: str | None = None  # "dot1q", "flexible-ethernet-services" 等
    source: str = SOURCE_PARSED       # 常に "parsed"

@dataclass
class BgpNeighbor:
    neighbor_ip: str
    peer_as: int | None

@dataclass
class OspfNetwork:
    process: int | None
    network: str            # CIDR
    area: str

@dataclass
class StaticRoute:
    prefix: str             # CIDR
    next_hop: str

@dataclass
class Device:
    hostname: str
    vendor: str             # "cisco_ios" / "juniper_junos"
    asn: int | None
    interfaces: list[Interface]
    bgp: list[BgpNeighbor]
    ospf: list[OspfNetwork]
    static: list[StaticRoute]
```

## パーサ共通インターフェース
各ベンダーモジュールは 2 つの関数を公開する（`lib/parsers/__init__.py` の registry が利用）:
- `detect(text: str) -> bool` — その config が当該ベンダーか判定
- `parse(text: str) -> Device` — 正規化モデルを返す

`parse_configs.py` はファイルごとに registry を回し、`detect` が真の最初のパーサを使う。

## Cisco IOS / IOS-XE（cisco_ios.py）
- 行指向・`!` 区切り。`interface <name>` ブロック内をインデントで把握。
- `hostname X` → hostname。
- `ip address A.B.C.D MASK` → addresses に `{af:"v4", ip:"...", prefix:n}` エントリを追加。secondary あり → `secondary:True` で収録（無視せず全アドレスを保持）。
  - **`ip` フィールド**: addresses 中の最初の非 secondary v4 から派生（後方互換）。
  - **l2_l3 判定**: `ip address`（v4）**または** `ipv6 address`（v6）の存在 → L3。`switchport` → L2。
- `ipv6 address X:Y:Z/PL` → addresses に `{af:"v6", ip:"正規化済みアドレス", prefix:n}` エントリを追加（ipaddress 正規化済み）。
- `ipv6 address FE80::X link-local` → addresses に `{af:"v6", ip:"fe80::...", prefix:64, scope:"link-local"}` エントリを追加。
- **link-local アドレスは `addresses` には保持されるが結線推論（`_infer_links_and_segments`）から除外**される。
- `no ip address` は「IP 未設定」の明示構文だが、ip address コマンドがなければ ip=None になるため特別対応しない設計判断。
- `shutdown`（ブロック内・`no` なし）→ `shutdown=True`。
- `description X` → description。
- `mtu <val>` → `mtu`（int）。`\d+` マッチ後のため ValueError は不発生。
- `speed <val>` → `speed`（文字列のまま格納。例: `"1000"`, `"auto"`）。
- `duplex <val>` → `duplex`（例: `"full"`, `"half"`）。
- `switchport mode access|trunk` → `switchport.mode`。`switchport access vlan <id>` → `switchport.access_vlan`（int）。`switchport trunk allowed vlan <range>` → `switchport.trunk_vlans`（文字列）。`no switchport` フラグを検知して L3 と判定する。
- `encapsulation dot1Q|DOT1Q <vlan>` → `encapsulation="dot1q"`（IGNORECASE で DOT1Q 等も許容）。
- **l2_l3 判定（IOS）**: `ip address` あり または `no switchport` あり → L3。`switchport` あり → L2。それ以外 None。
  - IOS は ip あり／no switchport が L3 判定で優先され（switchport より先に評価）、switchport は L2 の根拠となる。
- **admin_status 導出**: `shutdown` = True → `ADMIN_DOWN`、それ以外 → `ADMIN_UP`。
- `router bgp <asn>` → asn。配下 `neighbor <ip> remote-as <peer>` → BgpNeighbor（v4/v6 仮登録）。
  - **Phase 3G**: `address-family ipv6` 配下 `neighbor <v6ip> activate` → BgpNeighbor(af="v6")。グローバルスコープの `neighbor <ip> remote-as <peer>` のみで `activate` されていないネイバーは af="v4" として確定する。
- `router ospf <pid>` 配下 `network <addr> <wildcard> area <a>` → OspfNetwork（af="v4"。wildcard を逆マスクして CIDR 化）。
- **Phase 3G**: `ipv6 router ospf <pid>` ブロック: **PID 宣言のみ**。配下行（`router-id` 等）は無視する。OSPFv3 の確定は interface ブロック内の `ipv6 ospf <pid> area <a>` で行う（IOS の `_ospfv3_if_buf` で仮収集し、パース後処理で OspfNetwork(af="v6") に変換）。インターフェースブロック内の `ipv6 ospf <pid> area <a>` → OspfNetwork(af="v6", network=当該 IF の v6 GUA サブネット CIDR, process=pid, area=a)。v6 アドレスが不明な場合は IF 名を network に格納（JunOS fallback と同様）。
- `ip route <prefix> <mask> <next_hop>` → StaticRoute(af="v4"。`0.0.0.0 0.0.0.0` → `0.0.0.0/0`）。
- **Phase 3G**: `ipv6 route <prefix/len> <nexthop>` → StaticRoute(af="v6", prefix=ipaddress 正規化済み CIDR, next_hop=normalize_v6(nexthop))。
- **detect**: `^hostname `・`^interface .*Ethernet`・`^!` 等の IOS 特徴で判定。非空行のうち `^set ` が **40% 超**を占める場合は JunOS とみなし false（registry は JunOS → IOS の順で試すため通常はこのガードに到達しない。閾値が JunOS の 50% とずれているのは、IOS の特徴行が無い純 set 形式を確実に JunOS 側へ寄せるための非対称な安全マージン）。

## Juniper JunOS（juniper_junos.py）— set 形式
- 全行 `set ...` 前提。
- `set system host-name X` → hostname。
- `set interfaces <if> description "X"` → description（クォート除去）。
- `set interfaces <if> unit N family inet address A.B.C.D/PL` → addresses に `{af:"v4", ip:"...", prefix:n}` エントリを追加。
  - `ip` フィールド: addresses 中の最初の非 secondary v4 から派生（後方互換）。旧来の「先勝ち」は廃止し全アドレスを収集する。
- `set interfaces <if> unit N family inet6 address X:Y:Z/PL` → addresses に `{af:"v6", ip:"正規化済みアドレス", prefix:n}` エントリを追加（Phase 3F 追加）。
  - fe80::/10（link-local）アドレスには `scope:"link-local"` を付与する（IOS と対称）。link-local は addresses には保持されるが結線推論から除外される。
  - 注記: unit は IF 名に含めない（unit 集約方針踏襲）。複数 unit / 複数アドレスは全て収集する（将来 unit を区別する場合は Phase X で変更）。
- `set interfaces <if> disable` → shutdown=True。
- `set interfaces <if> mtu <val>` → `mtu`（int）。`\d+` マッチ後のため ValueError は不発生。
- `set interfaces <if> speed <val>` → `speed`（文字列のまま格納。例: `"1g"`, `"10g"`）。duplex は JunOS set 形式では通常出現しないため常に None。
- `set interfaces <if> encapsulation <val>` → `encapsulation`（値はそのまま格納。例: `"flexible-ethernet-services"`）。
- `set interfaces <if> unit N family ethernet-switching ...` → `l2_flag=True`。
- **l2_l3 判定（JunOS）**: `family ethernet-switching` あり → L2。`family inet`（v4）**または** `family inet6`（v6）→ L3。それ以外 None。
  - JunOS は ethernet-switching が L2 判定で優先され（inet より先に評価）、ethernet-switching は L2 の根拠となる。
  - `switchport` フィールドは常に None（JunOS には IOS の switchport コマンドが存在しない。L2 は l2_l3='l2' で表現）。
- **admin_status 導出**: `disable` あり → `ADMIN_DOWN`、それ以外 → `ADMIN_UP`。
- `set routing-options autonomous-system <asn>` → asn。
- `set protocols bgp group <g> neighbor <ip> peer-as <peer>` → BgpNeighbor。neighbor_ip が v6 アドレスなら af="v6"（normalize_v6 で正規化）、v4 なら af="v4"。
- `set ... ospf area <a> interface <if>` があれば OspfNetwork(af="v4")（area, network は IF の IP から導出可能なら CIDR、無理なら IF 名を network に格納）。v1 は best-effort。
- **Phase 3G**: `set protocols ospf3 area <a> interface <if>` → OspfNetwork(af="v6", process=None, network=ベース IF 名, area=a)。IF 名のユニット表記（ge-0/0/0.0）はドット以降を除去してベース名を格納。build_topology の `_resolve_ospf_area_for_device` で v6 サブネットと照合。
- `set routing-options static route <prefix> next-hop <ip>` → StaticRoute(af="v4")。
- **Phase 3G**: `set routing-options rib inet6.0 static route <prefix> next-hop <ip>` → StaticRoute(af="v6", prefix=`ipaddress.ip_network(prefix, strict=False)` で正規化済み CIDR（ホストビット除去）, next_hop=normalize_v6(ip))。不正な prefix は try/except ValueError でスキップ。IOS の `ipv6 route` と対称の正規化を保証。
- **detect**: 非空行の **過半数（50% 超）** が `^set ` で始まる。

## 新ベンダー追加手順（例: Cisco NX-OS）
1. `lib/parsers/nxos.py` を作り `detect` / `parse` を実装（`Device` を返す）。
2. `lib/parsers/__init__.py` の registry リストに追加（detect の特異度が高い順に並べる）。
3. `tests/test_parsers.py` にサンプル config とアサーションを追加。
4. スキーマ・build_topology・renderer は**変更不要**（正規化モデルに合わせるだけ）。
