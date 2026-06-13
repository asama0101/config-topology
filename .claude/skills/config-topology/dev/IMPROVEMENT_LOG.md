# 継続改善ループ ログ (improvement-loop-20260613)

30分間隔の自動ループ。各サイクル: 立案 → TDD実装 → ゴールデン再生成（必要時）→ run-reviewers → doc更新 → 1コミット。

## 不変条件（厳守）
- 決定性: 乱数・時刻非依存。同一入力→同一YAML→同一HTML。
- 加算的拡張: 既存フィールドの意味/型を変えない。新規はキー/フィールド追加で吸収。変える時のみ `_meta.yaml` schema_version をバンプ。
- 参照整合: `topology_io.load_topology` の検証を通す。
- 依存は PyYAML のみ（pure Python, safe_load/safe_dump）。python3。

## 運用方針（QA確定 2026-06-13）
- スコープ: 自律判断。原則は既存(BGP/OSPF/render)の深掘り、基盤が揃えば新領域へ。
- 順序: 自律判断。提案順を基本に、触るファイルが衝突しない順で交互に。
- 品質ゲート: **TDD必須＋毎回 run-reviewers**。
- ブランチ: improvement-loop-20260613、各サイクル1コミット。

## バックログ（優先度順・適宜更新）

### A. レイアウト視認性
- [x] A1 AS でのノードクラスタリング（layout.py 初期円周配置を AS グループ順に）— M ✅反復5完了
- [ ] A1b area でのノードクラスタリング（device 単位 area 集約が必要・cluster_order 拡張）— M
- [ ] A2 リンクラベル重なり回避（決定的法線オフセット）— M
- [ ] A4 ノードサイズの情報量反映（degree 連動・決定的）— S
- [ ] A3 階層/直交レイアウトモード切替 — L（A1後）

### B. UI操作性
- [ ] B1 隣接フォーカスモード（選択ノードの N hop 隣接のみ強調・他を淡色化）— S
- [ ] B2 表ビューの列フィルタ/絞り込みチップ（vendor/area/AS）— M
- [ ] B3 URLハッシュ状態の保存/復元（選択・ビュー・フィルタを #state= に決定的エンコード）— M
- [ ] B4 凡例からの一括レイヤー操作＋ショートカット拡充 — S（A1後）

### C. BGP/OSPF 設定管理（parse→build→schema→render の加算フィールド）
- [x] C1 BGP update-source 抽出 → local_ip 解決フォールバック — M ✅反復4完了（peer-group は C1b に分割・未着手）
- [ ] C1b BGP peer-group のメンバー継承（remote-as/update-source をグループから継承）— M
- [x] C2 OSPF interface cost / passive / network-type（interfaces[].ospf 加算）— M ✅反復2完了
- [ ] C3 OSPF area type (stub/nssa)＋area注釈（routing.ospf[].area_type）— M（C2後）
- [ ] C4 BGP timers / next-hop-self / RR-client / community（routing.bgp[].attrs）— M（C1後）
- [ ] C5 redistribute 抽出（sections or routing 注釈）— L（C2,C4後）

### D. 業務支援機能
- [x] D1 構成統計ダッシュボード（機器/IF/AS別/area別/リンク種別/dual-stack率/BGP/OSPF集計の新ビュー）— M ✅反復1完了
- [x] D2 設計検証警告の集約パネル（重複IP・MTU不一致・未解決BGP local_ip・dangling next_hop）— M ✅反復3完了
- [ ] D3 前回トポロジー差分レポート（history/ 旧YAML と現YAML を時刻非依存で diff）— L（D1後）
- [ ] D4 IPアドレス計画/サブネット使用率ビュー — M（D1後）

## 推奨順序
D1 → B1 → C2 → A1 → C1 → D2 → B2 → C3 → C4 → A2 → D3 → 残り

## 進捗

### 反復1: D1 構成統計ダッシュボード — ✅完了（2026-06-13）
- `build_stats(topo, links=None, bgp_edges=None)` を data_transform.py に新設、`build_data()` に `DATA.stats` 加算。
- tabs.py に常設 STATS タブ、assets.py に `renderStatsView()`＋CSS。
- 12項目集計（機器/IF/links/segments/by_vendor/by_as/by_area/link_kinds/dualstack_ifs/bgp_sessions/ospf_networks/static_routes）。
- レビュー対応: by_as/by_area を数値ソート（Python・JS両側）、build_links 二重呼び出し解消、bgp_sessions=重複排除済みセッション数（golden=1）、stub 実値検証（golden=4）。
- doc: requirements.md §8.2 / SKILL.md / .claude/CLAUDE.md に STATS を反映。
- テスト 257 passed（+28）。render層のみ・層別YAMLゴールデン不変。
- 見送り(LOW・既存事象): esc() のシングルクォート未対応、norm_ospf_area フォールスルー、tbl のモジュール化、_BODY 静的nav、pytestmark分割。

### 反復2: C2 OSPF interface パラメータ抽出 — ✅完了（2026-06-14）
- Interface に `ospf: Optional[dict]`（cost/network_type/passive）追加。None/空dict は to_dict・build で省略（golden byte 不変）。
- IOS: `ip ospf cost`/`ip ospf network`/`passive-interface <if>` 抽出。JunOS: metric/interface-type/passive（ospf/ospf3）。
- build 透過・data_transform._build_if 公開・assets.py INTERFACES 表に OSPF バッジ表示。
- レビュー対応: バッジ title の二重エスケープ修正、`_ensure_ospf`→base.ensure_ospf に DRY 集約、空dict防御（`if self.ospf:`）、passive-interface default ネガティブテスト、junos 正規表現 `(.*)?$`→`(.*)$`。
- doc: requirements.md §5.2 出力規約に interfaces[].ospf を条件付き省略の例外として加筆＋§6.1/§6.2 マッピング行、schema.md 整形、vendor-parsing.md・.claude/CLAUDE.md にフィールド/マッピング反映。
- テスト 287 passed（+30）。golden byte 不変・render 決定性維持。
- 非対応（明記済み）: `passive-interface default`・`no passive-interface`。
- 見送り(LOW): `_build_if` private import、IOS/JunOS 拡張パス非対称(YAGNI)、pytestmark分割。

### 反復3: D2 設計検証パネル（CHECKS ビュー）— ✅完了（2026-06-14）
- `build_checks(topo, links=None)` を data_transform.py に新設、`build_data` に `DATA.checks` 加算。4ルール: duplicate_ip(error)/mtu_mismatch/bgp_unresolved_local_ip/static_dangling_next_hop(warning)。severity→kind→refs 安定ソート。
- 新規 CHECKS 表ビュー（tabs.py / assets.py renderChecksView）。0件時は肯定メッセージ。
- レビュー対応: link-local 偽陽性除外（duplicate_ip・static_dangling、最重要）、mtu_mismatch を build_links 統合済みリンク基準にして dual-stack 重複解消、bgp local_ip キー欠如ガード、template `_json` の `</script>` エスケープ（XSS ハードニング）、`_SPECIAL_NH` モジュール定数化、テスト堅牢化（ソート3段検証・重複テスト除去）。
- doc: schema.md DATA.checks ルール表、requirements.md §8.2（「到達不可」→正確表現）、SKILL.md、.claude/CLAUDE.md render層索引に build_checks/renderChecksView 反映。
- テスト 336 passed（+48）。golden byte 不変・render 決定性維持。
- 見送り(LOW): duplicate_ip refs の list→set 微最適化、型ヒント（build_stats と様式統一で無し）。

### 反復4: C1 BGP update-source 抽出＋local_ip 解決フォールバック — ✅完了（2026-06-14）
- BgpNeighbor に update_source 追加（IOS=update-source IF名 / JunOS=local-address IP、omit-when-None）。
- build._resolve_local_ip にフォールバック: サブネット一致 None 時、IP直指定(AF一致・link-local除外) or IF名解決(config順・v6 link-local除外)。サブネット一致成功時は挙動不変。
- iBGP over loopback の local_ip 解決 → D2 の bgp_unresolved_local_ip 警告が消える相乗効果。render の BGP SESSIONS 表に src 列。
- レビュー対応: IP直指定ブランチの link-local 除外、YAMLラウンドトリップテスト、v6/AF-ipv6配下のupdate-sourceテスト、src列render テスト、孤立 pending ドロップを意図的と docstring 明記。
- doc: schema.md/vendor-parsing.md/requirements.md §6・§8.5/link-inference.md §2 を同期。
- テスト 366 passed（+30）。golden byte 不変・render 決定性維持。
- 見送り(LOW): pending dict命名非対称、フィールドdocstringスタイル、型ヒント具体化。

### 反復5: A1 AS ノードクラスタリング初期配置 — ✅完了（2026-06-14）
- layout.py に `cluster_order()` 追加。初期円周配置を AS 昇順→同一AS内 id 昇順に並べ同一 AS を隣接配置。force 本体は無変更。
- 発動ガード: 2台以上の AS グループがある時のみ発動。AS 未設定・全 singleton・1台は現行 ID 昇順に厳密 no-op（既存テスト・golden 不変）。
- `_initial_circle` は `_initial_circle_ordered(sorted())` のラッパーに一本化（DRY）。AS ソートは `(asn is None, asn)` タプルキーで型安全・数値昇順。
- レビュー対応(ブロッカー含む): 近接テストが stub で確実にREDになるよう fixture を sorted≠cluster＋links無しに作り直し実証、AS型ロバスト性、docstring修正、A1b 拡張コメント。
- doc: requirements.md §8.3/§9.1/用語集の「機器 ID 昇順」を AS クラスタリング反映に更新、CLAUDE.md 索引に cluster_order。
- テスト 366→385 passed（+19）。golden byte 不変・render 決定性維持。観点A(視認性)に初進出。

### 次候補: 反復6 B1 隣接フォーカスモード（render JS・観点B 未着手）/ C3 OSPF area type（parser）/ D4 サブネット使用率ビュー（render）/ A2 リンクラベル重なり回避（layout/JS）。観点B(操作性)が未着手なので B1 を推奨。または観点C継続で C3。
推奨順序の残り目安: B1 → C3 → D4 → A2 → C4 → B2 → A1b → D3 → C5 → 残り。
