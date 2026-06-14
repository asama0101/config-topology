# topology スキーマ仕様（レイヤー別 YAML 正本）

`config-topology` の中間表現。**ベンダー中立**で、パーサ層の出力（正規化モデル）を `build_topology.py` が結線推論して
組み立てる。正本は **レイヤー別 YAML**（後述）で、`lib/topology_io.py` が **topology dict ⇄ 層別 YAML** を相互変換する。
レンダラー（`render_topology.py`）と将来の別出力（Mermaid 等）は、この dict（＝層別 YAML を `load_topology` で読んだもの）を入力とする。
**以下のフィールド定義は「メモリ上の topology dict」の構造**であり、それを下記レイアウトで YAML に分割して保存する。

## ファイルレイアウト（層別 YAML 正本）
出力ディレクトリ（既定 `topology/`）に層別ファイルを置く。`lib/topology_io.py` の `dump_topology`/`load_topology` が読み書きする。
```
topology/
  _meta.yaml                      # schema_version: "1.0", title, generated_from
  devices.yaml                    # devices: [...]  /  interfaces: [...]   ← 全層が ID 参照する基盤
  physical.yaml                   # links: [...]    /  segments: [...]
  routing.bgp.yaml                # bgp: [...]      （空プロトコルはファイルを書き出さない）
  routing.ospf.yaml               # ospf: [...]
  routing.static.yaml             # static: [...]
  routing.redistribute.yaml       # redistribute: [...]（非空時のみ生成）
```
- **devices と interfaces は同居**（links / routing が interface・device の ID を外部キー参照するため、基盤として 1 ファイルに集約）。
- **空の routing.\*** は書き出さない／読込時は欠落＝空リスト扱い。
- **`_meta.yaml` の `schema_version`**（現行 `"1.0"`）。未知メジャーは読込時に警告（前方互換）。
- **直列化**: `yaml.safe_dump(sort_keys=True, default_flow_style=False, allow_unicode=True)` で決定的。読込は `yaml.safe_load` のみ（任意オブジェクト復元を禁止）。
- **参照整合の検証**（`load_topology`）: `interfaces[].device`・`links[].{a,b}_device`/`{a,b}_if`・`segments[].members`・`routing[*][].device` が
  devices / interface-ID 集合に存在するか検査し、不正（人手編集での dangling 参照等）は **ファイル名・フィールド・値を示す `ValueError`** を送出する。

## 目次
- [設計原則](#設計原則)
- [トップレベル構造](#トップレベル構造)
- [devices](#devices)
- [interfaces](#interfaces)
- [links](#links)
- [segments](#segments)
- [routing](#routing)
- [ID 採番規則](#id-採番規則)
- [拡張方法](#拡張方法)

## 設計原則
- **IP は interface に帰属する**。機器に直接 IP を持たせない（実機と同じ構造）。
- **物理層（devices / interfaces / links / segments）と論理層（routing）を分離**。レンダラーはレイヤートグルで重ねる。
- **由来を保持する**: `links[].kind` で結線の根拠（初版は `inferred-subnet`）を残し、将来 CDP/LLDP 由来を加算できるようにする。
- **破壊しない拡張**: 新しいプロトコルは `routing` のキー追加、機器固有の追加情報は `devices[].sections` で吸収する。既存フィールドの意味は変えない。

## トップレベル構造
| キー | 型 | 説明 |
|-----|----|------|
| `title` | string | 図のタイトル。既定 `"Network Topology (config-derived)"` |
| `generated_from` | string[] | 元になった config ファイル名（読み込み順） |
| `devices` | object[] | 機器 |
| `interfaces` | object[] | インターフェース（IP はここ） |
| `links` | object[] | 2 機器間の point-to-point 結線 |
| `segments` | object[] | 3 メンバー以上が同一サブネットを共有する L2 セグメント |
| `routing` | object | プロトコル名をキーにした論理オーバーレイ |

## devices
| フィールド | 型 | 説明 |
|-----------|----|------|
| `id` | string | 機器 ID（[採番規則](#id-採番規則)） |
| `hostname` | string | config 上のホスト名（verbatim） |
| `vendor` | string | `cisco_ios` / `juniper_junos`（パーサ識別子） |
| `as` | int \| null | ローカル AS 番号（BGP/autonomous-system が無ければ null） |
| `ospf_router_id` | string \| null | OSPF router-id（§5.2.1。未設定は null） |
| `bgp_router_id` | string \| null | BGP router-id（§5.2.1。未設定は null） |
| `sections` | object[] | 拡張枠（初版は空配列）。`{"title": "...", "rows": [...]}` 形式で任意データを添付可能 |

## interfaces
| フィールド | 型 | 説明 |
|-----------|----|------|
| `id` | string | `"<device_id>::<name>"` |
| `device` | string | 所属機器 ID |
| `name` | string | IF 名（config 上の表記。例 `GigabitEthernet0/0` / `ge-0/0/0`） |
| `addresses` | object[] | dual-stack アドレス正本（§4.1）。`[{af, ip, prefix, secondary?, scope?}]` 形式。`af`=`"v4"`/`"v6"`、`ip`=ホストアドレス（プレフィックス長なし）、`prefix`=int。`secondary`=True（IOS secondary、省略=False）、`scope`=`"link-local"`（省略=グローバル）。空の IF は空配列。ソート: af 順（v4 < v6）→ ip 昇順 → prefix 昇順。 |
| `ip` | string \| null | 後方互換フィールド。`addresses` 中の最初の非 secondary v4 から派生（§4.1）。v6-only / 未設定は null |
| `vlan` | int \| null | access/SVI の VLAN（初版は基本 null。L2 は将来拡張）。 |
| `description` | string \| null | IF の description |
| `shutdown` | bool | 管理停止状態（true/false）。true の IF も結線推論に含める（§7.1）。 |
| `admin_status` | string \| null | 管理状態（`"up"` / `"down"`. shutdown 由来）。取得不能は null。 |
| `oper_status` | string \| null | 運用状態（config から取得不可のため現状常に null。将来 SNMP 連携用予約）。 |
| `mtu` | int \| null | MTU 値（バイト）。未設定は null。 |
| `speed` | string \| null | インターフェース速度（ベンダー表記のまま）。取得不能は null。 |
| `duplex` | string \| null | duplex 設定（`"full"` / `"half"` 等）。IOS のみ。JunOS では null。 |
| `l2_l3` | string \| null | レイヤー種別（`"l2"` / `"l3"` / null）。 |
| `switchport` | object \| null | IOS switchport 情報（§5.2.2）。JunOS では常に null。 |
| `encapsulation` | string \| null | カプセル化種別（`"dot1q"` など）。未設定は null。 |
| `ospf` | object | OSPF interface パラメータ（任意・条件付き省略）。サブキー `cost`(int)・`network_type`(str: "point-to-point"/"broadcast"/"p2p" 等)・`passive`(true)。**設定があるサブキーのみ格納**し、1つも無い IF では `ospf` キー自体を省略する（null・空 object は出力しない）。設定の無い既存ゴールデン YAML は byte 完全一致のまま。新フィールド追加のため `schema_version` は据え置き（既存フィールドの意味・型は不変）。 |
| `source` | string | データソース識別子。現行は常に `"parsed"`。 |

## links
2 機器のちょうど 2 つの IF が同一サブネットを共有するとき 1 本生成。
| フィールド | 型 | 説明 |
|-----------|----|------|
| `a_device` / `b_device` | string | 端点機器 ID（`a` < `b` で安定ソート） |
| `a_if` / `b_if` | string | 端点 IF 名 |
| `subnet` | string | 共有サブネット CIDR（IPv4 例 `10.0.0.0/30`、IPv6 例 `2001:db8:1::/127`）。IPv4 または IPv6 CIDR どちらも取り得る |
| `kind` | string | 結線の由来。初版は常に `"inferred-subnet"` |
| `admin_down` | bool | **任意**。`true` のとき、片端または両端の IF が `shutdown` 状態のリンク（グレー破線で表示）。両端 up のリンクには付かない（フィールド欠如）。`admin_down=true` のリンクには `ospf_area` / `ospf_network` を付けない（shutdown IF は OSPF 隣接を張れないため）。 |
| `ospf_area` | string \| null | **任意**。OSPF 参加リンクの area 番号。両端が同一 area なら単一値（例 `"0"`）。両端で異なる場合は昇順スラッシュ区切り（例 `"0/1"`）。OSPF 非参加リンクおよび `admin_down=true` リンクには付かない（フィールド欠如）。 |
| `ospf_network` | string \| null | **任意**。`ospf_area` が付くリンクの subnet CIDR（`subnet` フィールドと同値）。OSPF 非参加リンクおよび `admin_down=true` リンクには付かない（フィールド欠如）。 |

`links` には `id` を設けない（`segments` とは異なる）。リンクは `(subnet, a_device, a_if, b_device, b_if)` の複合キーで一意に定まるため。将来 CDP/LLDP 由来の結線を混在させる際は `kind` で由来を区別する。

## segments
同一サブネットに **3 つ以上** の IF が属するとき、L2 セグメント（スイッチ/共有メディア相当）として 1 ノード生成し、各 IF を接続する。
| フィールド | 型 | 説明 |
|-----------|----|------|
| `id` | string | `"seg-<subnet>"`（`/` と `.` は `_` に置換。例 `seg-192_168_1_0_24`） |
| `subnet` | string | サブネット CIDR（IPv4 または IPv6 CIDR どちらも取り得る。例 `192.168.1.0/24`、`2001:db8:10::/64`） |
| `members` | string[] | 接続する interface ID の配列（安定ソート） |
| `ospf_area` | string \| null | **任意**。OSPF 参加セグメントの area 番号。メンバー機器が同一 area なら単一値（例 `"1"`）。異なる場合は昇順スラッシュ区切り（例 `"0/1"`）。OSPF 非参加セグメントには付かない（フィールド欠如）。 |
| `ospf_network` | string \| null | **任意**。`ospf_area` が付くセグメントの subnet CIDR（`subnet` フィールドと同値）。OSPF 非参加セグメントには付かない（フィールド欠如）。 |

## routing
プロトコル名をキーにした dict。**新プロトコルはキーを足すだけ**でスキーマを壊さない。

### `bgp`（object[]）
| フィールド | 型 | 説明 |
|-----------|----|------|
| `device` | string | 機器 ID（devices[].id への参照） |
| `local_as` | int | ローカル AS |
| `local_ip` | string \| null | neighbor と同一サブネットにある自 IF の IP（§7.3）。v6 neighbor に対しては v6 local_ip を返す。解決不能は null。update_source による解決フォールバックが成功した場合も非 null になる。 |
| `neighbor_ip` | string | ネイバー IP（v4 または v6） |
| `peer_as` | int \| null | ピア AS。不明なら null。 |
| `type` | string | `"ebgp"` / `"ibgp"` / `"unknown"`（§7.3） |
| `af` | string | アドレスファミリ（`"v4"` / `"v6"`） |
| `update_source` | string \| null | **任意・設定時のみ出力**。IOS の `neighbor update-source <ifname>`（インターフェース名）または JunOS の `local-address <ip>`（ローカル IP 文字列）。未設定の場合はキー自体を省略する（null 値は出力しない）。build.py の `_resolve_local_ip` が `update_source` フィールドを参照してサブネット一致失敗時のフォールバックに使用する。 |
| `route_reflector_client` | bool | **任意・True 時のみ出力**。その neighbor が route reflector client であるとき `true`。IOS `neighbor route-reflector-client`、JunOS `group cluster` で設定。False の場合はキー自体を省略する（golden byte 不変）。 |
| `next_hop_self` | bool | **任意・True 時のみ出力**。IOS `neighbor next-hop-self` が設定されているとき `true`。False の場合はキー自体を省略する（golden byte 不変）。JunOS はポリシーベースのため常に False（キー省略）。 |
| `timers` | object \| null | **任意・設定時のみ出力**。IOS `neighbor <ip> timers <keepalive> <holdtime>` から `{keepalive: int, holdtime: int}`。未設定はキー省略（null 値は出力しない）。JunOS は非対応。 |
| `send_community` | string \| null | **任意・設定時のみ出力**。IOS `neighbor <ip> send-community [both\|standard\|extended]`（無印は `"standard"`）。`large` 等の未対応キーワードは誤分類せずスキップ（キー省略）。JunOS は非対応。 |
| `peer_group` | string \| null | **任意・設定時のみ出力**。IOS peer-group 名（`neighbor <ip> peer-group <name>` のメンバーが属する group。属性は group 定義から継承し個別指定が優先）。未設定はキー省略。JunOS は group を peer_group にマッピングしない（非出力）。 |

### `ospf`（object[]）
network 宣言 1 件につき 1 エントリ。
| フィールド | 型 | 説明 |
|-----------|----|------|
| `device` | string | 機器 ID（devices[].id への参照） |
| `process` | int \| null | プロセス ID（JunOS は null 可） |
| `network` | string | CIDR（§6.3 正規化）またはインターフェース名。IPv4 / IPv6 どちらも取り得る。 |
| `area` | string | エリア（正規化済み文字列。§6.3 参照。例: `"0"`、`"16909060"`） |
| `af` | string | アドレスファミリ（`"v4"` = OSPFv2 / `"v6"` = OSPFv3） |
| `area_type` | string \| null | **任意・設定時のみ出力**。OSPF エリアタイプ。正規化値: `"stub"` / `"totally-stubby"`（stub + no-summary）/ `"nssa"` / `"totally-nssa"`（nssa + no-summary）。通常エリア（backbone/regular）の場合はキー自体を省略する（null 値は出力しない。golden byte 不変を保つ）。 |

### `static`（object[]）
| フィールド | 型 | 説明 |
|-----------|----|------|
| `device` | string | 機器 ID（devices[].id への参照） |
| `prefix` | string | 宛先 CIDR（例: `"0.0.0.0/0"`、`"::/0"`） |
| `next_hop` | string | ネクストホップ IP（v4 または v6） |
| `af` | string | アドレスファミリ（`"v4"` / `"v6"`） |

### `redistribute`（object[]）
ルーティングプロトコル間の再配布設定（IOS `redistribute` コマンドから抽出。§C5）。
非空のとき `routing.redistribute.yaml` に出力される。

| フィールド | 型 | 説明 |
|-----------|----|------|
| `device` | string | 機器 ID（devices[].id への参照） |
| `into` | string | 再配布先プロトコル（`"bgp"` / `"ospf"`）= config の文脈（router bgp / router ospf ブロック） |
| `source` | string | 再配布元プロトコル（`connected` / `static` / `ospf` / `bgp` / `rip` / `eigrp` / `isis` 等） |
| `metric` | int | **任意・設定時のみ出力**。`metric <n>` の値。未設定時はキー省略。 |
| `route_map` | string | **任意・設定時のみ出力**。`route-map <name>` の名前。未設定時はキー省略。 |

**JunOS 非対応**: JunOS はルート再配布をポリシーベース（export policy）で制御するため、set 形式 config から直接 redistribute エントリを抽出しない（常に空リスト）。

## ID 採番規則
- **device id**: `hostname` を小文字化し、英数字・ハイフン以外を `-` に置換。**最初の出現はサフィックスなし、2 番目は `-2`、3 番目は `-3`**（例: hostname が `R1`,`R1` → `r1`,`r1-2`）。さらに、既存の別 id（例 hostname `R1-2` 由来の `r1-2`）と衝突する場合は、衝突しない番号までカウントを繰り上げて一意性を保証する。空 hostname は `device`,`device-2`,...。
- **interface id**: `"<device_id>::<name>"`（name は config 表記のまま）。
- **segment id**: `"seg-" + subnet`（`.` と `/` を `_` に置換）。

## 後方互換・移行メモ

- **`af` フィールドなし旧 YAML**: `load_topology` は af フィールドを補完しない。利用側（render/build 等）が `entry.get("af", "v4")` で既定 v4 扱いする設計。`schema_version` は `"1.0"` に据え置き（af は addition-only の拡張フィールドであり、旧 YAML の読み書き互換性を破壊しない）。
- **`schema_version` 据え置き方針**: フィールド追加（addition-only）は `schema_version` を上げない。スキーマ変更（既存フィールドの型変更・廃止等）のときのみバンプする。

## 拡張方法
| 追加したいもの | 方法 | スキーマ影響 |
|--------------|------|------------|
| 新ベンダー | パーサを足す（正規化モデルに合わせる） | なし |
| 新プロトコル（VRRP 等） | `routing` に新キー（→ `routing.<proto>.yaml` 層が増える） | なし（加算） |
| 機器固有の追加情報 | `devices[].sections` に append | なし（加算） |
| CDP/LLDP 由来リンク | `links[].kind` に新値 | なし（加算） |

## render 層 DATA 派生（層別 YAML スキーマ外）

以下は **render 層の `build_data()` が topology dict から生成する JS 用 DATA オブジェクト** のフィールドであり、
**層別 YAML スキーマには含まれない**（YAML ファイルへの出力・schema_version への影響なし）。

### DATA.devices[].degree（A4 degree 連動ノードサイズ）

`lib/rendering/data_transform.build_devices(topo)` が各デバイスに追加するフィールド。

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `degree` | int | 物理接続数。その device に隣接する**相異なるノード数**（set で重複排除）。links の端点として接続している device 数 ＋ そのデバイスが member の segment における他メンバー device 数の合計。link-local アドレスによる影響なし（結線は IP/サブネット一致ベース）。リンク・セグメントのない孤立機器は 0 |

`degree` は `build_data()` 経由で `DATA.devices[id].degree` として HTML に埋め込まれ、
ブラウザ側の `nodeScale(d.degree||0)` が `{w, h}` を算出してデバイスノードの描画サイズを決定する。

**決定的**: 同一 topology dict から常に同一の degree 値を算出する。dual-stack（同一端点ペアの v4/v6 リンク 2 行）は set により 1 接続として計上。

**加算的**: 既存 `DATA.devices[id]` フィールドの意味・型は不変。`degree` キーを追加するのみ。

### DATA.checks（D2 設計検証パネル）

`lib/rendering/data_transform.build_checks(topo)` が返すリスト。各要素の型:

```
{
  "severity": "error" | "warning",    # 重大度
  "kind": str,                         # ルール識別子（下表）
  "message": str,                      # 人間向けメッセージ
  "refs": [str, ...]                   # 参照先（device::ifname・IP・subnet 等）
}
```

返却順は `severity`（error→warning）→ `kind` → `refs` の安定ソート（決定的）。

| kind | severity | 検出条件 |
|------|----------|---------|
| `duplicate_ip` | error | 同一ホスト IP（v4/v6・secondary 含む）が複数 IF に存在。link-local（`scope="link-local"`、fe80::/10）は除外 |
| `duplicate_bgp_router_id` | error | 同一 `bgp_router_id` を 2 台以上の device が持つ場合、router-id ごとに 1 件。None は無視。同一機器内での ospf/bgp 共用は機器間重複ではないため対象外。`refs` = 該当 device id 群（昇順）＋ 重複 router-id 値（ospf と同形式） |
| `duplicate_ospf_router_id` | error | 同一 `ospf_router_id` を 2 台以上の device が持つ場合、router-id ごとに 1 件。None は無視。`refs` = 該当 device id 群（昇順）＋ 重複 router-id 値 |
| `mtu_mismatch` | warning | 同一物理リンク両端の MTU が双方非 None かつ不一致。`build_links()` 統合済みリンク（端点ペア単位）を基準とするため、dual-stack（同一端点に v4+v6 の raw 行 2 件）でも 1 件のみ検出される |
| `bgp_unresolved_local_ip` | warning | routing.bgp エントリで `local_ip` が None またはキー欠如 |
| `static_dangling_next_hop` | warning | static の next_hop がトポロジー全体のどの IF サブネットにも属さず、どの IF のホスト IP とも一致しない。スキップ対象: 特殊値（`0.0.0.0`・`::`・`255.255.255.255`）、デフォルトルート prefix（`0.0.0.0/0`・`::/0`）、IF 名等の非 IP 文字列（Null0 等）。link-local アドレスは all_subnets から除外（fe80:: 帯への誤属を防ぐ） |
| `ospf_area0_disconnected` | warning | area 0（backbone）を持つ device が 1 台以上存在する混在環境で、OSPF area を持つが area 0 を持たない device を列挙。area 0 不在環境では非発火（偽陽性抑制）。結線でなく **config 保有 area で近似**。ABR（area0＋他 area）は対象外。`refs` = `[device] + 数値優先ソートした非0 area 群` |
| `ibgp_fullmesh_incomplete` | warning | RR 不在の AS 内 iBGP で full-mesh が崩れているピア対。いずれかのセッションに `route_reflector_client=True` があれば当該 AS をスキップ（RR 構成は full-mesh 不要）。neighbor_ip を IF ホスト IP で device 解決し、解決不能 neighbor を持つ device が絡むペアはスキップ（偽陽性抑制）。`refs` = `[di, dj, str(asn)]`（di<dj 昇順） |
| `ospf_area_mismatch` | warning | リンク/セグメントの両端が異なる OSPF area を宣言（`ospf_area` が `aggregate_areas` により `"0/1"` 等の `/` 連結値になる）。実機では area 不一致で OSPF 隣接が張れない＝設定誤り。リンク `refs` = `sorted([a_device, b_device]) + [subnet]`、セグメント `refs` = `[seg_id, subnet]` |

`build_data()` は `"checks": build_checks(topo, links=links)` を返り値に追加するため、
埋め込み `DATA.checks` として HTML に含まれ、ブラウザ側の `renderChecksView()` が描画する。

### DATA.subnet_usage（D4 サブネット使用率ビュー）

`build_subnet_usage(topo)` が返す v4 サブネット使用率集約のリスト。`DATA.subnet_usage` として HTML に埋め込まれ、`renderSubnetUsageView()`（SUBNETS タブ）が描画する。**層別 YAML スキーマ外の render 層導出**。

| フィールド | 型 | 説明 |
|-----------|----|------|
| `subnet` | string | v4 サブネット CIDR（`ipaddress.ip_network(strict=False)` で正規化） |
| `af` | string | 常に `"v4"` |
| `usable` | int | 収容可能ホスト数。`/31`→2、他は `2^(32-p)-2` |
| `used` | int | そのサブネットに属する一意ホスト IP 数（secondary も計上） |
| `free` | int | `max(usable - used, 0)` |
| `util` | float | `round(used/usable, 4)`（usable=0 のとき 0.0） |
| `exhausted` | bool | `util >= _EXHAUSTED_THRESHOLD`（=0.8） |

集計対象は interface address のうち **af=="v4"・非 link-local・prefix≠32**（`/32` ホスト/ループバックは除外）。同一サブネットは host IP の set で重複排除（複数 IF/device 跨ぎでも二重計上なし）。ソートは **util 降順 → subnet 文字列昇順**で決定的。

---

## diff ツール出力構造（独立ツール・HTML とは別）

`lib/diff.diff_topology(old, new)` が返す構造化 diff。**render 層 DATA とは独立**したツール出力であり、
層別 YAML を読み込んだ topology dict を直接比較する（`load_topology` を通す）。

### セクション別キーと比較フィールド

| セクション（dict キー） | 自然キー（識別子） | changed で比較するフィールド |
|---|---|---|
| `devices` | `id` | `hostname`, `vendor`, `as`, `ospf_router_id`, `bgp_router_id` |
| `interfaces` | `id` | `description`, `shutdown`, `mtu`, `speed`, `addresses`, `ospf` |
| `links` | `(subnet, a_device, a_if, b_device, b_if)` ※端点は辞書順で安定化 | added/removed のみ（changed なし） |
| `segments` | `id` | `members`（集合比較） |
| `routing_bgp` | `(device, neighbor_ip, af)` | `peer_as`, `type`, `local_ip`, `update_source`, `route_reflector_client`, `next_hop_self`, `timers`, `send_community`, `peer_group` |
| `routing_ospf` | `(device, network, af)` | `process`, `area`, `area_type` |
| `routing_static` | `(device, prefix, af)` | `next_hop` |

各セクションは `{"added": [...], "removed": [...], "changed": [...]}` を返す。
全リストはキー昇順ソートで決定的。同一入力→空 diff。

### CLI

```bash
python3 "$SKILL/scripts/diff_topology.py" old_topology/ new_topology/
python3 "$SKILL/scripts/diff_topology.py" old_topology/ new_topology/ -o diff_report.md
```

- 引数: `old_dir`, `new_dir`（層別 YAML ディレクトリ）、`-o/--output`（省略時 stdout）。
- 終了コード: 常に 0（差分あり/なし問わずレポート生成は成功。エラー時のみ 1）。
- 出力: Markdown 形式のレポート（見出し・件数サマリ `+N -M ~K`・added(+)/removed(-)/changed(~) 行）。
