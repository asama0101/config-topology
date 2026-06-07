# 結線推論ルール（scripts/build_topology.py）

正規化済みの全機器・全 IF から、topology dict（→ レイヤー別 YAML 正本）の `links` / `segments` / `routing` を組み立てる。Config 以外の入力（CDP/LLDP 等）は v1 では使わず、**IP/サブネット一致のみ**で推論する。

## 1. サブネットによる結線
1. 全 IF を走査し、`ip` を持ち `shutdown=False` のものだけを対象にする。
2. 各 IF の `ip`（CIDR）から `ipaddress.ip_interface(ip).network` でネットワークを算出。
3. ネットワークをキーに IF をグルーピング。
   - **メンバー 2** → `links` に 1 本（point-to-point）。`a`/`b` は device id の昇順で安定化。
   - **メンバー ≥ 3** → `segments` に 1 ノード生成し、全メンバー IF を接続。
   - **メンバー 1** → スタブ（リンクなし）。LAN 側 IF や Loopback はここに該当することが多い。
4. `/30`・`/31` は典型的な P2P だが、**判定はサブネット一致で統一**しマスク長に特別扱いを設けない（メンバー数だけで links / segments を決める）。
5. ループバック（`/32`）は単独メンバーになりスタブ扱い。

### 注意点（境界値）
- 同一機器内に同一サブネットの IF が複数ある異常設定 → メンバー数にそのまま含めるが、`links` では `a_device != b_device` のペアのみ採用（自己ループを作らない）。
- IP 重複（同一サブネットに同一 IP）→ そのまま members に含め、警告は呼び出し側ログに委ねる（v1 はクラッシュしない方針）。
- **Phase 3F 以降**: IPv6 グローバルアドレスも対象。`ip` フィールドではなく `addresses` リストの各エントリから `ipaddress.ip_interface(f"{ip}/{prefix}").network` でネットワークを算出してグルーピングする。
- **link-local（fe80::/10 = `is_link_local`）は結線推論から除外**。`fe80::` 系アドレスで誤結線しない。
- 同一 IF が同一ネットワークに複数アドレスで属していても members には IF を 1 回のみ登録（重複除去）。
- **IPv4-only config（`addresses` が空または v4 のみ）では links/segments が従来と完全一致**（後方互換保証）。`addresses` が空の場合は `ip` フィールドにフォールバックする。

## 2. BGP 対向解決
1. 各機器の BgpNeighbor について、`neighbor_ip` を全機器の IF IP（ホスト部）と突合。
2. 突合した IF が見つかれば、その機器の AS を `peer_as` の裏付けに使える。`local_ip` は「neighbor_ip と同一サブネットにある自機の IF IP」を採用（無ければ null）。
3. `type` 判定:
   - `local_as == peer_as` → `ibgp`
   - `local_as != peer_as`（両方既知） → `ebgp`
   - `peer_as` 不明 → `unknown`
4. 突合不能（外部 AS で対向機器が config に無い）でも BGP エントリは残す（片側オーバーレイ）。

## 3. 出力の安定性（決定性）
- すべてのリスト（devices / interfaces / links / segments / routing.*）は**決定的順序**で出力する（device id 昇順、IF は config 出現順、links は (a_device, a_if) 昇順 等）。
- 乱数・時刻に依存しない。同じ入力からは毎回同一の層別 YAML（topology dict）が出る（テスト・diff・eval の前提）。

## 4. レンダラーが使う前提
- `links` と `segments` が物理層、`routing` が論理オーバーレイ。
- レンダラーはこの JSON 以外を読まない。結線ロジックの変更は build_topology に閉じる。
