# ベンダー別パース要点と新ベンダー追加手順

各パーサは config テキストを受け取り、ベンダー中立な**正規化モデル**（`lib/models.py` の dataclass）を返す。`lib/build.py` はこのモデルだけを見るので、パーサが構文差異を吸収する。

## 正規化モデル（lib/models.py）

以下の dataclass を定義（要件書 §4.1）:

| クラス | フィールド | 説明 |
|--------|-----------|------|
| **Address** | `af`（str）| `"v4"` / `"v6"` |
| | `ip`（str）| ホストアドレス（プレフィックスなし・正規化済み） |
| | `prefix`（int）| プレフィックス長 |
| | `secondary`（bool）| IOS secondary フラグ（既定 False） |
| | `scope`（str \| None）| `"link-local"` / None（既定） |
| **Interface** | `name`（str）| IF 名 |
| | `addresses`（list[Address]）| IP アドレス群（dual-stack 正本） |
| | `ip`（str \| None）| 派生フィールド（後方互換。§4.1） |
| | `ospf`（dict \| None）| OSPF interface パラメータ（cost/network_type/passive。設定時のみ・None 時は dict 省略） |
| | `description`, `shutdown`, `admin_status` etc. | 各属性 |
| **BgpNeighbor** | `neighbor_ip`（str）| ネイバー IP |
| | `peer_as`（int \| None）| ピア AS |
| | `af`（str）| `"v4"` / `"v6"` |
| | `update_source`（str \| None）| IOS: `update-source <ifname>` のインターフェース名。JunOS: `local-address <ip>` のローカル IP 文字列。未設定は None（to_dict では省略）。build.py の `_resolve_local_ip` がサブネット一致失敗時のフォールバックに使用。 |
| **OspfNetwork** | `process`（int \| None）| プロセス ID |
| | `network`（str）| CIDR またはインターフェース名 |
| | `area`（str）| エリア（正規化前） |
| | `af`（str）| `"v4"` / `"v6"` |
| **StaticRoute** | `prefix`（str）| 宛先 CIDR |
| | `next_hop`（str）| ネクストホップ IP |
| | `af`（str）| `"v4"` / `"v6"` |
| **Device** | `hostname`（str）| ホスト名 |
| | `vendor`（str）| `"cisco_ios"` / `"juniper_junos"` |
| | `as_`（int \| None）| ローカル AS |
| | `ospf_router_id`, `bgp_router_id` | router-id（§5.2.1） |
| | `interfaces`（list[Interface]）| インターフェース群 |
| | `bgp`, `ospf`, `static` | ルーティング情報 |

## パーサ共通インターフェース（lib/parsers/__init__.py）

- `detect_vendor(text: str) -> str | None` — ベンダー ID を返す（JunOS → IOS の順で特異度高い順に判定。一元管理）
- `parse_config(text: str, warnings) -> Device | None` — ベンダー判定 → 対応パーサへ dispatch・正規化モデルを返す

`lib/inputs.py` / `scripts/parse_configs.py` はファイルごとに `parse_config()` を呼び、`Device` または `None` を受け取る。

## Cisco IOS / IOS-XE（lib/parsers/ios.py）

**構文 → 正規化マッピング（要件書 §6.1）**:

| 構文 | 抽出先 | 正規化 |
|------|--------|--------|
| `hostname <name>` | Device | hostname |
| `interface <name>` | Interface | name（ブロック内属性を解析） |
| `ip address <ip> <mask>` | addresses | `{af:"v4", ip:..., prefix:...}` |
| `ip address ... secondary` | addresses | `{af:"v4", ..., secondary:True}` |
| `ipv6 address <prefix/len>` | addresses | `{af:"v6", ip:..., prefix:...}` |
| `ipv6 address fe80::.../len` | addresses | `{af:"v6", ..., scope:"link-local"}` |
| `shutdown` | shutdown | True（`no shutdown` で False） |
| `description <text>` | description | テキスト（クォート除去） |
| `router bgp <asn>` | Device.as_ | asn |
| `neighbor <ip> remote-as <peer>` | BgpNeighbor | (af は IP アドレス形式で v4/v6 判定) |
| `neighbor <ip> update-source <ifname>` | BgpNeighbor.update_source | インターフェース名を格納（remote-as と順不同可）。address-family 配下も対応 |
| `address-family ipv6` + `neighbor ... activate` | BgpNeighbor.af | "v6" に更新 |
| `router ospf <pid>` / `network ... area <a>` | OspfNetwork | (af="v4", area は§6.3で正規化) |
| `ipv6 ospf <pid> area <a>` (IF内) | OspfNetwork | (af="v6", network は v6 CIDR または IF 名) |
| `ip ospf cost <n>` / `ip ospf network <type>` (IF内) | Interface.ospf | cost=int / network_type=str |
| `passive-interface <if>` (router ospf 内) | Interface.ospf | 該当 IF の passive=True（`default`・`no passive-interface` は非対応） |
| `area <a> stub` (router ospf 内) | OspfNetwork.area_type | "stub"（同一 (process, area)・af="v4" の OspfNetwork に末尾適用。プロセス/v6 に漏れない） |
| `area <a> stub no-summary` (router ospf 内) | OspfNetwork.area_type | "totally-stubby" |
| `area <a> nssa` (router ospf 内) | OspfNetwork.area_type | "nssa" |
| `area <a> nssa no-summary` (router ospf 内) | OspfNetwork.area_type | "totally-nssa" |
| `ip route <prefix> <mask> <next_hop>` | StaticRoute | (af="v4") |
| `ipv6 route <prefix/len> <nexthop>` | StaticRoute | (af="v6", prefix 正規化) |

**判定ルール**:
- **detect**: `hostname` / `interface ...Ethernet` / `!` 等の IOS 特徴行で判定（§2.3）。`set ` 行が40%超なら JunOS とみなす（ガード）。
- **l2_l3**: `ip address` または `no switchport` → L3。`switchport` → L2。それ以外 null。
- **admin_status**: shutdown=true → "down"。false → "up"。
- **addresses ソート**: af 順（v4 < v6）→ ip 昇順 → prefix 昇順（§5.2）。
- **link-local 除外**: `addresses` には fe80::/10 を保持するが結線推論（lib/build.py）から除外（§7.1）。

## Juniper JunOS（lib/parsers/junos.py）— set 形式

**構文 → 正規化マッピング（要件書 §6.2）**:

| 構文 | 抽出先 | 正規化 |
|------|--------|--------|
| `set system host-name <name>` | Device | hostname（クォート除去） |
| `set interfaces <if> unit <n> family inet address <prefix/len>` | addresses | `{af:"v4", ip:..., prefix:...}` |
| `set interfaces <if> unit <n> family inet6 address <prefix/len>` | addresses | `{af:"v6", ip:..., prefix:...}` |
| `set interfaces <if> unit <n> family inet6 address fe80::.../len` | addresses | `{af:"v6", ..., scope:"link-local"}` |
| `set interfaces <if> description <text>` | description | テキスト（クォート除去） |
| `set interfaces <if> disable` | shutdown | True（行がなければ False） |
| `set routing-options autonomous-system <asn>` | Device.as_ | asn |
| `set routing-options router-id <id>` | Device.bgp_router_id / ospf_router_id | ID（§5.2.1） |
| `set protocols bgp group <g> neighbor <ip> peer-as <peer>` | BgpNeighbor | (af は IP 形式で v4/v6 判定) |
| `set protocols bgp group <g> neighbor <ip> local-address <localip>` | BgpNeighbor.update_source | ローカル IP 文字列を格納（peer-as と順不同可） |
| `set protocols ospf area <a> interface <if>` | OspfNetwork | (af="v4", area は§6.3で正規化, network は v4 CIDR または IF 名) |
| `set protocols ospf3 area <a> interface <if>` | OspfNetwork | (af="v6", process=null, network=IF ベース名) |
| `… ospf[3] … interface <if> {metric\|interface-type\|passive}` | Interface.ospf | metric→cost / interface-type→network_type / passive→True |
| `set protocols ospf area <a> stub` | OspfNetwork.area_type | "stub"（v4 限定） |
| `set protocols ospf area <a> stub no-summaries` | OspfNetwork.area_type | "totally-stubby" |
| `set protocols ospf area <a> nssa` | OspfNetwork.area_type | "nssa" |
| `set protocols ospf area <a> nssa no-summaries` | OspfNetwork.area_type | "totally-nssa" |
| `set protocols ospf3 area <a> stub` | OspfNetwork.area_type | "stub"（v6 限定） |
| `set protocols ospf3 area <a> stub no-summaries` | OspfNetwork.area_type | "totally-stubby"（v6 限定） |
| `set protocols ospf3 area <a> nssa` | OspfNetwork.area_type | "nssa"（v6 限定） |
| `set protocols ospf3 area <a> nssa no-summaries` | OspfNetwork.area_type | "totally-nssa"（v6 限定） |
| `set routing-options static route <prefix> next-hop <ip>` | StaticRoute | (af="v4") |
| `set routing-options rib inet6.0 static route <prefix> next-hop <ip>` | StaticRoute | (af="v6", prefix 正規化・ホストビット除去) |

**判定ルール**:
- **detect**: 非空行のうち `set ` で始まる行が50%超（§2.3）。
- **l2_l3**: `family ethernet-switching` → L2。`family inet`/`family inet6` (address あり) → L3。それ以外 null。
- **admin_status**: disable 行あり → "down"。なし → "up"。
- **switchport**: 常に null（JunOS は IOS switchport コマンドが存在しない）。
- **addresses ソート**: af 順（v4 < v6）→ ip 昇順 → prefix 昇順。
- **unit 集約**: 複数 unit は一つの IF に集約。複数アドレスは全収集（§6.2）。
- **link-local 除外**: fe80::/10 は addresses に保持するが結線推論から除外。

## 新ベンダー追加手順

1. `lib/parsers/<vendor>.py` を作成し以下を実装:
   - `parse_<vendor>(text: str, warnings) -> Device | None` — 正規化モデルを返す
2. `lib/parsers/__init__.py` の `detect_vendor()` に判定分岐を追加（特異度が高い順）し、`parse_config()` の dispatch に登録。
3. `lib/models.py` の `Device` 等のモデルに合わせて属性を正規化（新フィールド追加は不要。既存スキーマで足りるなら変更不要）。
4. tests に判定・パース・結線推論のテストを追加。
5. スキーマ・build_topology・renderer は**変更不要**（正規化モデルが共通のため）。
