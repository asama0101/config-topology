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
- [ ] A1 area/AS でのノードクラスタリング（layout.py 初期座標にグループ重心）— M
- [ ] A2 リンクラベル重なり回避（決定的法線オフセット）— M
- [ ] A4 ノードサイズの情報量反映（degree 連動・決定的）— S
- [ ] A3 階層/直交レイアウトモード切替 — L（A1後）

### B. UI操作性
- [ ] B1 隣接フォーカスモード（選択ノードの N hop 隣接のみ強調・他を淡色化）— S
- [ ] B2 表ビューの列フィルタ/絞り込みチップ（vendor/area/AS）— M
- [ ] B3 URLハッシュ状態の保存/復元（選択・ビュー・フィルタを #state= に決定的エンコード）— M
- [ ] B4 凡例からの一括レイヤー操作＋ショートカット拡充 — S（A1後）

### C. BGP/OSPF 設定管理（parse→build→schema→render の加算フィールド）
- [ ] C1 BGP update-source / peer-group 抽出 → local_ip/iBGP判定精度向上 — M
- [ ] C2 OSPF interface cost / passive / network-type（interfaces[].ospf 加算）— M
- [ ] C3 OSPF area type (stub/nssa)＋area注釈（routing.ospf[].area_type）— M（C2後）
- [ ] C4 BGP timers / next-hop-self / RR-client / community（routing.bgp[].attrs）— M（C1後）
- [ ] C5 redistribute 抽出（sections or routing 注釈）— L（C2,C4後）

### D. 業務支援機能
- [x] D1 構成統計ダッシュボード（機器/IF/AS別/area別/リンク種別/dual-stack率/BGP/OSPF集計の新ビュー）— M ✅反復1完了
- [ ] D2 設計検証警告の集約パネル（MTU/速度不一致・重複IP・AS不整合・area不一致・未解決BGP local_ip・dangling next_hop）— M（D1後）
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

### 次: 反復2 B1 隣接フォーカスモード（assets.py JS のみ。選択ノードの N hop 隣接のみ強調・他を淡色化）
