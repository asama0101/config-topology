# 結線推論ルール（scripts/build_topology.py・lib/build.py）

正規化済みの全機器・全 IF から、topology dict（→ レイヤー別 YAML 正本）の `links` / `segments` / `routing` を組み立てる。Config 以外の入力（CDP/LLDP 等）は v1 では使わず、**IP/サブネット一致のみ**で推論する（要件書 §7）。

## 1. サブネットによる結線

**アルゴリズム（要件書 §7.1）**:

1. 全 IF を走査し、`addresses`（IP アドレス群）を取得。`addresses` は正本で、`ip` フィールドはその派生のため、フォールバック未実装：`addresses==[]` ⟺ `ip is None` は同値（§4.1）。
2. 各アドレスの `{ip, prefix}` から所属ネットワーク CIDR を算出。link-local（fe80::/10）は**結線から除外**。
3. ネットワーク CIDR ごとにインターフェースをグループ化。
4. **結線 / セグメント判定**:
   - **メンバー = 2**（異機器）→ `links` に 1 本（point-to-point）。`a_device` < `b_device` で辞書式安定化。
   - **メンバー ≥ 3** → `segments` に 1 ノード生成し、全メンバー IF を接続。
   - **メンバー = 1** → スタブ（リンク化しない）。loopback（`/32`）や LAN 側 IF に該当。
5. `/30`・`/31` は典型的な P2P だが、**判定はメンバー数のみで統一**（マスク長に特別扱いなし）。

**admin_down フラグ（§7.2）**:
- **片端 shutdown && 対向 up** → `admin_down = true`（グレー破線・淡色表示）。
- **両端 shutdown** → `admin_down = true`。
- **両端 up** → `admin_down` フィールド省略（付与しない）。**`admin_down: false` という出力は行わない**（`true` か省略の二値）。
- **segment には admin_down フラグを付与しない**（メンバー IF の shutdown 状態は詳細パネルで確認）。

**OSPF area 非付与**（§5.3、§7.2）:
- `admin_down = true` のリンクには `ospf_area` / `ospf_network` を付けない（shutdown IF は OSPF 隣接を張れない）。

### 特別な考慮

- 同一機器内同一サブネット複数 IF：メンバー数に含めるが、`links` では `a_device != b_device` のペアのみ採用（自己ループ回避）。
- IP 重複（同一サブネット同一 IP）：members に含める；警告は呼び出し側ログに委ねる（初版はクラッシュしない）。
- shutdown IF：結線推論に含める（`admin_down` フラグで視覚的区別）。
- 同一 IF が同一ネットワークに複数アドレス属していても members には IF を 1 回のみ登録（重複除去）。

## 2. BGP 対向解決（§7.3）

1. 各 BGP neighbor の `neighbor_ip` を、全機器のすべてのインターフェース IP と突合。
2. 突合した IF が見つかれば、その機器の AS を参照。
3. `local_ip` = 「neighbor_ip と同一サブネットにある自機のインターフェース IP」を採用（無ければ null）。**v6 neighbor に対しては v6 local_ip を返す**（af ファミリ一致）。
4. `type` 判定:
   - `local_as == peer_as` → `ibgp`（内部）
   - `local_as != peer_as`（両者既知） → `ebgp`（外部）
   - `peer_as` が null → `unknown`
5. 対向機器が config に存在しない外部 AS でも、BGP エントリは残す（外部隣接の可視化）。

## 3. OSPF area 注釈（§7.4）

link / segment が対応する subnet について、OSPF network エントリが存在するか検索。存在する場合、`ospf_area` / `ospf_network` を付与。

**area 値の決定**:
- 両端/全メンバー同一 area（§6.3 正規化後）→ 単一値（例: `"0"`、`"16909060"`）
- 異なる area が混在（正規化後）→ 昇順スラッシュ区切り（例: `"0/1"`）。全要素が数値文字列なら数値昇順、非数値が混在するなら辞書式昇順で連結。

## 4. 出力の決定性（§7.5）

- 前提：同一入力 → 同一の層別 YAML → 同一 HTML。
- すべてのリスト（devices / interfaces / links / segments / routing.*）は**決定的順序**で出力:
  - `devices`: device_id 昇順
  - `interfaces`: device の出現順（`generated_from` の処理順）× 各 device 内は **config 記述順**
  - `links`: `(a_device, a_if, b_device, b_if, subnet)` 昇順
  - `segments`: `id` 昇順
  - `routing.*`: device_id 昇順 → その他フィールド昇順
- 乱数・時刻に依存しない（テスト・diff・eval がこの前提に依存）。

## 5. レンダラー側の前提
- `links` と `segments` が物理層、`routing` が論理オーバーレイ。
- `lib/rendering/data_transform.py` が topology dict → レンダリング用 DATA を変換し、
  layout.py・svg.py・tabs.py 等が図を組み立てる。結線ロジック変更は build.py に閉じる。
