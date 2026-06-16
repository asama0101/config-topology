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
| | `route_reflector_client`（bool）| RR client フラグ（既定 False・True 時のみ to_dict 出力）。IOS `neighbor route-reflector-client` / JunOS `group cluster`。 |
| | `next_hop_self`（bool）| next-hop-self フラグ（既定 False・True 時のみ to_dict 出力）。IOS `neighbor next-hop-self`。JunOS はポリシーベースで非対応（常に False）。 |
| | `timers`（tuple[int,int] \| None）| `(keepalive, holdtime)`。IOS `neighbor <ip> timers <ka> <hold>`。to_dict では `{keepalive,holdtime}` dict 化・未設定は省略。JunOS 非対応。 |
| | `send_community`（str \| None）| `"standard"`/`"extended"`/`"both"`。IOS `neighbor <ip> send-community [both\|standard\|extended]`（無印=standard）。未対応キーワード（large 等）はスキップ。to_dict では未設定省略。JunOS 非対応。 |
| | `peer_group`（str \| None）| IOS peer-group 名（メンバーが属する group・継承元）。未設定は None（to_dict では省略）。JunOS は group を peer_group にマッピングしない（非出力）。 |
| **OspfNetwork** | `process`（int \| None）| プロセス ID |
| | `network`（str）| CIDR またはインターフェース名 |
| | `area`（str）| エリア（正規化前） |
| | `af`（str）| `"v4"` / `"v6"` |
| **StaticRoute** | `prefix`（str）| 宛先 CIDR |
| | `next_hop`（str）| ネクストホップ IP |
| | `af`（str）| `"v4"` / `"v6"` |
| **Redistribute** | `into`（str）| 再配布先プロトコル＝宣言ブロック文脈（`"bgp"` / `"ospf"`） |
| | `source`（str）| 再配布元（`connected`/`static`/`ospf`/`bgp`/`rip`/`eigrp`/`isis` 等） |
| | `metric`（int \| None）| メトリック（設定時のみ・to_dict 省略） |
| | `route_map`（str \| None）| route-map 名（設定時のみ・to_dict 省略） |
| **Device** | `hostname`（str）| ホスト名 |
| | `vendor`（str）| `"cisco_ios"` / `"juniper_junos"` |
| | `as_`（int \| None）| ローカル AS |
| | `ospf_router_id`, `bgp_router_id` | router-id（§5.2.1） |
| | `interfaces`（list[Interface]）| インターフェース群 |
| | `bgp`, `ospf`, `static`, `redistribute` | ルーティング情報（redistribute は IOS のみ。JunOS はポリシーベースで非対応） |

## パーサ共通インターフェース（lib/parsers/__init__.py）

- `detect_vendor(text: str) -> str | None` — ベンダー ID を返す（JunOS → IOS の順で特異度高い順に判定。一元管理）
- `parse_config(text, warnings=None, line_status=None, diagnostics=None, filename=None) -> Device | None` — ベンダー判定 → 対応パーサへ dispatch・正規化モデルを返す。`diagnostics` 指定時は JunOS の apply-groups 多用診断を末尾に `append`。`filename` は診断の `refs` に使用（省略可）
- `diagnose_input(text, filename) -> dict | None` — ベンダー判定できなかった（`detect_vendor` が `None` を返した）テキストに対して入力形式診断を実行。JunOS 波括弧形式と推定される場合に `junos_brace_format` 診断 dict を返す（条件: 波括弧行 ≥3 かつ `set` 行比率 ≤0.05）。それ以外は `None`

`lib/inputs.py` / `scripts/parse_configs.py` はファイルごとに `parse_config()` を呼び、`Device` または `None` を受け取る。

**`line_status` opt-in（CONFIG parse 状態モード用）**: `parse_config`／各パーサ（`parse_ios`/`parse_junos`）は任意の出力リスト `line_status` を受け取る。
指定時は各行を `"parsed"`（モデルに寄与＝認識した行）/`"ignored"`（コメント・空行・`end`・機密行〔`is_sensitive_line`〕）/`"unparsed"`（パーサが見たが拾えない＝見落とし候補）に分類し、末尾で `extend` する。
**判定基準は「正規表現/キーワードが一致したか」**（値が未対応・パース失敗でも認識すれば `"parsed"`）。`line_status` 未指定時はモデル出力・挙動は完全に従来通り。
**新ベンダー追加時もこの opt-in を実装すること**（メインループを `enumerate` 化し、認識分岐で `"parsed"`・無視行で `"ignored"` を立て、未指定時は記録しない）。`build_topology` が device id をキーに `topo["parse_status"]` へ集約し `raw_config.yaml` に保存、`DATA.parse_status` 経由で CONFIG ビューが 3 色分け描画する。

## Cisco IOS / IOS-XE（lib/parsers/ios.py）

**構文 → 正規化マッピング（要件書 §6.1）**:

| 構文 | 抽出先 | 正規化 |
|------|--------|--------|
| `hostname <name>` | Device | hostname |
| `interface <name>` | Interface | name（ブロック内属性を解析） |
| `ip address <ip> <mask>` | addresses | `{af:"v4", ip:..., prefix:...}` |
| `ip address ... secondary` | addresses | `{af:"v4", ..., secondary:True}` |
| `ip address dhcp` / `ip address negotiated` | — | IP 未確定。warnings に追記しリンク推論から除外（アドレスを addresses に追加しない） |
| `ip unnumbered <ifname>` | — | IP 未確定。warnings に追記しリンク推論から除外 |
| `ipv6 address autoconfig` | — | IP 未確定。warnings に追記しリンク推論から除外 |
| `ipv6 address <prefix/len>` | addresses | `{af:"v6", ip:..., prefix:...}` |
| `ipv6 address <prefix/len> eui-64` | addresses | prefix のみ抽出。`{af:"v6", ip:..., prefix:...}`（eui-64 キーワードは無視） |
| `ipv6 address <prefix/len> anycast` | addresses | prefix のみ抽出。`{af:"v6", ip:..., prefix:...}`（anycast キーワードは無視） |
| `ipv6 address fe80::.../len` | addresses | `{af:"v6", ..., scope:"link-local"}` |
| `shutdown` | shutdown | True（`no shutdown` で False） |
| `description <text>` | description | テキスト（クォート除去） |
| `router bgp <asn>` | Device.as_ | asn |
| `neighbor <ip> remote-as <peer>` | BgpNeighbor | (af は IP アドレス形式で v4/v6 判定) |
| `ip vrf forwarding <vrf>` / `vrf forwarding <vrf>` (IF内) | Interface.vrf | VRF 名を格納（omit-when-None） |
| `neighbor <ip> update-source <ifname>` | BgpNeighbor.update_source | インターフェース名を格納（remote-as と順不同可）。address-family 配下も対応 |
| `neighbor <ip> route-reflector-client` | BgpNeighbor.route_reflector_client | True（remote-as と順不同可。address-family 配下も対応）。他 neighbor には影響しない |
| `neighbor <ip> next-hop-self` | BgpNeighbor.next_hop_self | True（remote-as と順不同可）。他 neighbor には影響しない |
| `neighbor <ip> timers <ka> <hold>` | BgpNeighbor.timers | `(keepalive, holdtime)`（remote-as と順不同可。address-family 配下も対応） |
| `neighbor <ip> send-community [both\|standard\|extended]` | BgpNeighbor.send_community | 無印=standard。large 等の未対応キーワードはスキップ（remote-as と順不同可。address-family 配下も対応） |
| `neighbor <name> remote-as/update-source/...`（name が IP でない）| pg_template[name] | peer-group 定義。group に属性を集約 |
| `neighbor <ip> peer-group <name>` | BgpNeighbor.peer_group ＋ 継承 | メンバー割当。group 属性（remote-as/update-source/rr/nhs/timers/send-community）を欠落分だけ継承（**個別指定が優先**）。個別 remote-as 無しメンバーは末尾解決で生成。未定義 group 参照は neighbor を生成しない |
| `address-family ipv4\|ipv6 vrf <vrf>` (router bgp 内) | BgpNeighbor.vrf 文脈 | `exit-address-family` で global に復帰。配下の `neighbor remote-as` が BgpNeighbor.vrf に設定される |
| `address-family ipv6` + `neighbor ... activate` | BgpNeighbor.af | "v6" に更新 |
| `router bgp <asdot>` / `neighbor <ip> remote-as <asdot>` | Device.as_ / BgpNeighbor.peer_as | asdot 形式（`1.0` 等）を asplain（`65536` 等）に変換（`asdot_to_asplain`）。範囲外は ValueError |
| `router ospf <pid>` / `network ... area <a>` | OspfNetwork | (af="v4", area は§6.3で正規化) |
| `ip ospf <pid> area <a>` (IF内・IPv4) | OspfNetwork | IF の v4 サブネット（最初の非 secondary v4 → CIDR）を network に・af="v4"・area は§6.3で正規化（ドット `0.0.0.0`→`0` 含む）。network 文と同一 (network,process,af) は重複排除。v4 アドレス無し IF はスキップ |
| `ipv6 ospf <pid> area <a>` (IF内・レガシー形式) | OspfNetwork | (af="v6", network は v6 CIDR または IF 名) |
| `ospfv3 <pid> ipv6 area <a>` (IF内・新形式) | OspfNetwork | af="v6"。`ipv6 ospf` と同じ pending_ospf3 パスに合流（`ospfv3 ... ipv4` は対象外） |
| `ip ospf cost <n>` / `ip ospf network <type>` (IF内) | Interface.ospf | cost=int / network_type=str |
| `passive-interface <if>` (router ospf 内) | Interface.ospf | 該当 IF の passive=True（`default`・`no passive-interface` は非対応） |
| `area <a> stub` (router ospf 内) | OspfNetwork.area_type | "stub"（同一 (process, area)・af="v4" の OspfNetwork に末尾適用。プロセス/v6 に漏れない） |
| `area <a> stub no-summary` (router ospf 内) | OspfNetwork.area_type | "totally-stubby" |
| `area <a> nssa` (router ospf 内) | OspfNetwork.area_type | "nssa" |
| `area <a> nssa no-summary` (router ospf 内) | OspfNetwork.area_type | "totally-nssa" |
| `ip route <prefix> <mask> <next_hop> [AD] [name X] [track N] [tag N] [permanent] [multicast] [global]` | StaticRoute | next-hop トークン解析（`_resolve_static_tokens`）。IF名+IP 併記時は IP を優先。数字単独は AD として無視。`name`/`track`/`tag`/`permanent`/`multicast`/`global` とその直後の値トークンもスキップ。`Null0` は IF 名として格納 |
| `ip route vrf <vrf> <prefix> <mask> <next_hop> ...` | StaticRoute | 上記と同じ next-hop 解析＋ StaticRoute.vrf に VRF 名を設定 |
| `ipv6 route <prefix/len> <nexthop> [...]` | StaticRoute | (af="v6", prefix 正規化。同じ next-hop トークン解析を適用) |
| `ipv6 route vrf <vrf> <prefix/len> <nexthop> ...` | StaticRoute | af="v6"・StaticRoute.vrf に VRF 名を設定 |
| `redistribute <source> [<pid/AS>] [metric <n>] [route-map <name>] [subnets ...]` (router bgp / router ospf 内) | Redistribute | `into` = 現在のブロック文脈（"bgp"/"ospf"）、`source` = 直後のトークン（connected/static/ospf/bgp/rip/eigrp/isis 等）、プロセス ID・AS 番号・subnets 等の付加引数は無視。metric/route-map は値があるときのみ出力。`no redistribute ...` はスキップ |

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
| `set protocols bgp group <g> peer-as <peer>`（neighbor 無し）| BgpNeighbor.peer_as | group レベル peer-as。**その group の peer_as 未設定 neighbor のみ**に継承（個別 peer-as が優先）。peer_group フィールドは出力しない |
| `set protocols bgp group <g> neighbor <ip> local-address <localip>` | BgpNeighbor.update_source | ローカル IP 文字列を格納（peer-as と順不同可） |
| `set protocols bgp group <g> cluster <id>` | BgpNeighbor.route_reflector_client | cluster を持つ group に属する全 neighbor を True に設定（末尾一括適用。複数 neighbor 対応） |
| `set protocols bgp group <g> type internal\|external` | BgpNeighbor.bgp_type | "ibgp"/"ebgp"。group→member 末尾一括継承（個別指定が優先） |
| `set protocols bgp group <g> local-as <asn>` | BgpNeighbor.local_as | group レベル local-as。neighbor 個別の `neighbor <ip> local-as <asn>` が優先（末尾一括継承） |
| JunOS next_hop_self | BgpNeighbor.next_hop_self | **非対応（常に False）**。JunOS は next-hop-self をポリシー（export policy）ベースで制御するため、set 形式 config から直接抽出できない |
| `set routing-instances <vrf> interface <if>` | Interface.vrf | base IF 名（unit 除去）に VRF 名を設定（omit-when-None） |
| `set routing-instances <vrf> routing-options static route <pfx> next-hop <nh>` | StaticRoute | af は prefix の `:` 有無で v4/v6 判定。StaticRoute.vrf に VRF 名を設定 |
| `set routing-instances <vrf> routing-options static route <pfx> discard\|reject` | StaticRoute | next_hop に `"discard"`/`"reject"` を格納（blackhole 化）。StaticRoute.vrf に VRF 名を設定 |
| `set routing-instances <vrf> routing-options static route <pfx> qualified-next-hop <nh>` | StaticRoute | 複数行で ECMP。各行が独立した StaticRoute として追加。StaticRoute.vrf に VRF 名を設定 |
| `set routing-instances <vrf> routing-options rib <rib_name> static route <pfx> next-hop\|discard\|reject\|qualified-next-hop <nh>` | StaticRoute | rib 名に `inet6` を含む場合のみ v6（それ以外は v4）。StaticRoute.vrf に VRF 名を設定 |
| `set routing-instances <vrf> protocols bgp group <g> neighbor <ip> peer-as <peer>` | BgpNeighbor | BgpNeighbor.vrf に VRF 名を設定。同 IP でも VRF が異なれば別エントリ |
| `set routing-instances <vrf> protocols bgp group <g> neighbor <ip>` | BgpNeighbor | BgpNeighbor.vrf に VRF 名。peer-as は group_peer_as から末尾継承 |
| `set routing-options static route <pfx> discard\|reject` | StaticRoute | next_hop に `"discard"`/`"reject"` を格納（v4/v6 両対応） |
| `set routing-options static route <pfx> qualified-next-hop <nh>` | StaticRoute | 複数行で ECMP。各行が独立した StaticRoute として追加（v4/v6 両対応） |
| `set routing-options rib inet6.0 static route <pfx> discard\|reject` | StaticRoute | af="v6"・next_hop に `"discard"`/`"reject"` を格納 |
| `set routing-options rib inet6.0 static route <pfx> qualified-next-hop <nh>` | StaticRoute | af="v6"・ECMP |
| `set protocols ospf[3] area <a> interface all` | OspfNetwork | 当該 af のアドレスを持つ全 L3 IF に展開（末尾一括・`interface-type`/`metric`/`passive` パラメータも適用） |
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
| redistribute | **非対応**（常に空リスト）。JunOS はルート再配布をポリシーベース（export policy 経由）で制御するため、set 形式 config から直接抽出できない。 |

## 入力形式診断（lib/parsers/__init__.py・lib/parsers/junos.py）

`parse_config` に `diagnostics` リストを渡すと、以下の診断が末尾に `append` される（後方互換: `diagnostics` 省略時は従来通り診断なし）。
`build_topology` 経由で `topo["diagnostics"]` に格納され `diagnostics.yaml`（非空時のみ生成）に保存される。
render 層の `build_data` が `DATA.checks` の末尾に出現順でマージし、CHECKS パネルに表示する。

| kind | 発火条件 | severity | 担当 |
|------|---------|----------|------|
| `junos_brace_format` | `detect_vendor` が None を返した（IOS/JunOS どちらとも判定されない）かつ波括弧行 ≥3 かつ `set` 行比率 ≤0.05 | warning | `diagnose_input` |
| `junos_apply_groups_unexpanded` | JunOS set config 内に groups 系行（`set groups` / `set apply-groups`）が ≥3 件かつ実体行数（interfaces/protocols/routing-options/routing-instances/policy-options）の 50% 以上を占める | warning | `_check_apply_groups`（parse_junos 末尾） |

診断 dict の形式: `{"severity": "warning", "kind": str, "message": str, "refs": [filename, ...]}`

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
