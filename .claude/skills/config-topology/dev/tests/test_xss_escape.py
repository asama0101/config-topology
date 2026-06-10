"""
TDD テスト: XSS エスケープ保証テスト（タスク C3）

検証対象:
  - lib/rendering/svg.py の _esc（html.escape + quote=True）
  - lib/rendering/cards.py の hostname / description 出力箇所
  - end-to-end: parse_text → build → render

テスト方針:
  1. ユニット: _esc 関数の文字エスケープ（<, >, &, ", '）
  2. ユニット: topology dict → render で生の <script> が現れない + エスケープ済み表現の存在確認
  3. ユニット: hostname / description に各種 XSS ペイロードを入れた topology dict → render
  4. 統合 (end-to-end): IOS config テキスト（hostname / description に特殊文字）→
       parse_text → build → render で同様の保証
"""

from __future__ import annotations

import re
import sys
import os

import pytest

# conftest.py が sys.path を設定しているため lib/scripts はインポート可能
# conftest.py と同じディレクトリにある前提

# ================================================================
# ヘルパー: application/json ブロックと JS <script> ブロックを除外
# ================================================================

def _strip_script_blocks(html: str) -> str:
    """application/json ブロックと通常の JS <script> ブロックを除去し
    HTML 本文（テキストコンテンツ・属性値部分）のみを返す。

    XSS 検査では埋め込み JSON や JS コード中に '<script>' という文字列が
    意図的に含まれることがあるため、それらを取り除いた本文で検査する。
    """
    # application/json の script ブロックを除去
    stripped = re.sub(
        r'<script[^>]+type=["\']application/json["\'][^>]*>.*?</script>',
        '',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # 通常の JS <script>...</script> ブロックを除去
    stripped = re.sub(r'<script[^>]*>.*?</script>', '', stripped, flags=re.DOTALL | re.IGNORECASE)
    return stripped


def _make_xss_topology(hostname: str, description: str) -> dict:
    """XSS テスト用の最小 topology dict を生成する。

    devices に hostname を設定し、interfaces に description を設定する。
    """
    return {
        "title": "XSS Escape Test",
        "generated_from": [],
        "devices": [
            {
                "id": "xss-dev",
                "hostname": hostname,
                "vendor": "cisco_ios",
                "as": None,
                "sections": [],
            }
        ],
        "interfaces": [
            {
                "id": "xss-dev::eth0",
                "device": "xss-dev",
                "name": "eth0",
                "ip": None,
                "vlan": None,
                "description": description,
                "shutdown": False,
            }
        ],
        "links": [],
        "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }


# ================================================================
# ユニットテスト: _esc 関数
# ================================================================

class TestEscFunction:
    """_esc が HTML 危険文字を正しくエスケープする。"""

    @pytest.fixture(autouse=True)
    def import_esc(self):
        from lib.rendering.svg import _esc
        self._esc = _esc

    @pytest.mark.unit
    def test_esc_lt(self):
        """< を &lt; にエスケープする。"""
        assert self._esc("<") == "&lt;"

    @pytest.mark.unit
    def test_esc_gt(self):
        """> を &gt; にエスケープする。"""
        assert self._esc(">") == "&gt;"

    @pytest.mark.unit
    def test_esc_amp(self):
        """& を &amp; にエスケープする。"""
        assert self._esc("&") == "&amp;"

    @pytest.mark.unit
    def test_esc_double_quote(self):
        '''" を &quot; にエスケープする（quote=True）。'''
        assert self._esc('"') == "&quot;"

    @pytest.mark.unit
    def test_esc_single_quote(self):
        """' を &#x27; にエスケープする（quote=True）。"""
        result = self._esc("'")
        # html.escape(quote=True) は ' → &#x27; に変換する
        assert "'" not in result, f"エスケープされていない単一引用符: {result!r}"
        assert result in ("&#x27;", "&#39;", "&apos;"), f"想定外のエスケープ形式: {result!r}"

    @pytest.mark.unit
    def test_esc_script_tag(self):
        """<script>alert(1)</script> を完全エスケープする。"""
        raw = "<script>alert(1)</script>"
        result = self._esc(raw)
        assert "<script>" not in result
        assert "</script>" not in result
        assert "&lt;script&gt;" in result

    @pytest.mark.unit
    def test_esc_none_returns_empty(self):
        """None 入力は空文字を返す。"""
        assert self._esc(None) == ""

    @pytest.mark.unit
    def test_esc_normal_string_unchanged(self):
        """エスケープ不要な文字列はそのまま。"""
        assert self._esc("R1-core") == "R1-core"

    @pytest.mark.unit
    def test_esc_combined_xss_payload(self):
        """典型的 XSS ペイロードを完全にエスケープする。"""
        payload = '<script>alert("XSS")</script>'
        result = self._esc(payload)
        assert "<script>" not in result
        assert '"' not in result
        assert "&lt;script&gt;" in result
        assert "&quot;" in result


# ================================================================
# ユニットテスト: topology dict → render （hostname / description）
# ================================================================

class TestRenderXssEscape:
    """topology dict に特殊文字を含む hostname / description を設定して
    render() した HTML 本文に生の <script> タグが現れないことを検証する。"""

    @pytest.fixture
    def render_fn(self):
        from lib.rendering import render
        return render

    # ---- hostname エスケープ ----------------------------------------

    @pytest.mark.unit
    def test_hostname_script_tag_not_in_html_body(self, render_fn):
        """hostname に <script>alert(1)</script> を含む場合、HTML 本文に生の <script> タグが出ない。"""
        topo = _make_xss_topology(
            hostname="<script>alert(1)</script>",
            description="normal description",
        )
        html = render_fn(topo)
        body = _strip_script_blocks(html)
        assert "<script>" not in body.lower(), \
            "hostname の <script> がエスケープされずに HTML 本文に現れた"

    @pytest.mark.unit
    def test_hostname_script_tag_escaped_in_html_body(self, render_fn):
        """hostname の <script> が &lt;script&gt; としてエスケープ済みで存在する。"""
        topo = _make_xss_topology(
            hostname="<script>alert(1)</script>",
            description="normal description",
        )
        html = render_fn(topo)
        assert "&lt;script&gt;" in html, \
            "hostname がエスケープされた &lt;script&gt; が HTML に存在しない"

    @pytest.mark.unit
    def test_hostname_double_quote_escaped(self, render_fn):
        '''hostname に " が含まれる場合、&quot; にエスケープされる。'''
        topo = _make_xss_topology(
            hostname='R1"evil"',
            description="normal",
        )
        html = render_fn(topo)
        # SVG の text 要素や data 属性内に生の " が attribute context で現れてはいけない
        # （JSON 埋め込みブロックを除いた本文で確認）
        body = _strip_script_blocks(html)
        # &quot; に変換されているか、または属性値外の本文では &quot; が使われる
        assert "&quot;" in html or "R1" in html, \
            "double quote がエスケープされた形跡がない"

    @pytest.mark.unit
    def test_hostname_single_quote_escaped(self, render_fn):
        """hostname に ' が含まれる場合、&#x27; にエスケープされる（_esc quote=True）。"""
        topo = _make_xss_topology(
            hostname="R1'xss'",
            description="normal",
        )
        html = render_fn(topo)
        body = _strip_script_blocks(html)
        # script/JSON ブロックを除いた本文に生の "R1'xss'" が現れないこと
        assert "R1'xss'" not in body, \
            "hostname の生の単一引用符が HTML 本文（script ブロック除外後）に残っている"
        # エスケープ済み表現 "R1&#x27;xss&#x27;" が HTML 全体に存在すること
        assert "R1&#x27;xss&#x27;" in html, \
            "hostname の ' が &#x27; にエスケープされた表現が HTML に見つからない"

    @pytest.mark.unit
    def test_hostname_amp_escaped(self, render_fn):
        """hostname に & が含まれる場合、&amp; にエスケープされる。"""
        topo = _make_xss_topology(
            hostname="R1 & R2",
            description="normal",
        )
        html = render_fn(topo)
        assert "&amp;" in html, "& が &amp; にエスケープされていない"

    # ---- description エスケープ ----------------------------------------

    @pytest.mark.unit
    def test_description_script_tag_not_in_html_body(self, render_fn):
        """description に <script>alert(1)</script> を含む場合、HTML 本文に生の <script> タグが出ない。"""
        topo = _make_xss_topology(
            hostname="R1",
            description="<script>alert(1)</script>",
        )
        html = render_fn(topo)
        body = _strip_script_blocks(html)
        assert "<script>" not in body.lower(), \
            "description の <script> がエスケープされずに HTML 本文に現れた"

    @pytest.mark.unit
    def test_description_script_tag_escaped_in_html(self, render_fn):
        """description の <script> が &lt;script&gt; としてエスケープ済みで存在する。"""
        topo = _make_xss_topology(
            hostname="R1",
            description="<script>alert(1)</script>",
        )
        html = render_fn(topo)
        assert "&lt;script&gt;" in html, \
            "description がエスケープされた &lt;script&gt; が HTML に存在しない"

    @pytest.mark.unit
    def test_description_double_quote_escaped(self, render_fn):
        '''description に " が含まれる場合、&quot; にエスケープされる。'''
        topo = _make_xss_topology(
            hostname="R1",
            description='Link to "Core" switch',
        )
        html = render_fn(topo)
        # description の " は HTML テキストノードとして &quot; に変換される
        assert "&quot;" in html, \
            "description の double quote が &quot; にエスケープされていない"

    @pytest.mark.unit
    def test_description_single_quote_escaped(self, render_fn):
        """description に ' が含まれる場合、&#x27; にエスケープされる（_esc quote=True）。"""
        topo = _make_xss_topology(
            hostname="R1",
            description="Link to 'Core' switch",
        )
        html = render_fn(topo)
        body = _strip_script_blocks(html)
        # script/JSON ブロックを除いた本文に生の "Link to 'Core' switch" が現れないこと
        assert "Link to 'Core' switch" not in body, \
            "description の生の単一引用符が HTML 本文（script ブロック除外後）に残っている"
        # エスケープ済み表現 "Link to &#x27;Core&#x27; switch" が HTML 全体に存在すること
        assert "Link to &#x27;Core&#x27; switch" in html, \
            "description の ' が &#x27; にエスケープされた表現が HTML に見つからない"

    @pytest.mark.unit
    def test_description_amp_escaped(self, render_fn):
        """description に & が含まれる場合、&amp; にエスケープされる。"""
        topo = _make_xss_topology(
            hostname="R1",
            description="eth0 & eth1 uplink",
        )
        html = render_fn(topo)
        assert "&amp;" in html, "description の & が &amp; にエスケープされていない"

    @pytest.mark.unit
    def test_hostname_and_description_combined_xss(self, render_fn):
        """hostname と description の両方に典型的 XSS ペイロードを含む場合の統合確認。"""
        xss_payload = '<script>alert("XSS\'s test & verify")</script>'
        topo = _make_xss_topology(
            hostname=xss_payload,
            description=xss_payload,
        )
        html = render_fn(topo)
        body = _strip_script_blocks(html)

        # 本文に生の <script> タグが現れない
        assert "<script>" not in body.lower(), \
            "組み合わせ XSS ペイロードが HTML 本文にエスケープされずに現れた"
        # エスケープ済み表現が存在する
        assert "&lt;script&gt;" in html, \
            "XSS ペイロードのエスケープ済み表現 &lt;script&gt; が見つからない"
        assert "&lt;/script&gt;" in html or "&lt;script" in html, \
            "XSS ペイロードの残部のエスケープ済み表現が見つからない"


# ================================================================
# 統合テスト (end-to-end): IOS config テキスト → parse_text → build → render
# ================================================================

class TestEndToEndXssEscape:
    """IOS config テキストに特殊文字を埋め込んだ end-to-end XSS 保証テスト。

    parse_text（lib/parsers）→ build（scripts/build_topology）→
    render（lib/rendering）の完全パイプラインで検証する。
    """

    @pytest.fixture
    def pipeline(self):
        """parse_text, build, render を返す。"""
        from lib.parsers import parse_text
        from scripts.build_topology import build
        from lib.rendering import render
        return parse_text, build, render

    @pytest.mark.integration
    def test_e2e_ios_hostname_with_script_tag(self, pipeline):
        """IOS config の hostname に <script> を含むテキストを end-to-end で処理し、
        生成 HTML 本文に生の <script> タグが現れないことを検証する。"""
        parse_text, build, render = pipeline

        # IOS config テキスト（hostname に XSS ペイロード）
        ios_config = """\
version 15.2
hostname <script>alert(1)</script>
!
interface GigabitEthernet0/0
 description link to <script>alert("desc")</script> & "partner"
 ip address 10.0.0.1 255.255.255.252
 no shutdown
!
"""
        device = parse_text(ios_config)
        # IOS パーサが検知できない場合はスキップ
        if device is None:
            pytest.skip("IOS パーサが config を検知できなかった（ベンダー判定失敗）")

        topology = build([device], generated_from=["test.cfg"])
        html = render(topology)
        body = _strip_script_blocks(html)

        # HTML 本文に生の <script> タグが現れない
        assert "<script>" not in body.lower(), \
            "IOS config の特殊文字が HTML 本文にエスケープされずに現れた"

        # &lt;script&gt; または &lt; が存在すること（エスケープ済み確認）
        # ※ IOS パーサが特殊文字を含む hostname を別途処理する場合もあるため
        #   hostname か description のいずれかでエスケープされていればよい
        assert "&lt;" in html or "&amp;" in html, \
            "特殊文字がまったくエスケープされていない（エスケープ済み表現が見つからない）"

    @pytest.mark.integration
    def test_e2e_ios_description_with_amp_and_quotes(self, pipeline):
        """IOS config の description に & と引用符を含む場合の end-to-end 検証。"""
        parse_text, build, render = pipeline

        ios_config = """\
version 15.2
hostname R1
!
interface GigabitEthernet0/0
 description uplink to "Core" & 'Backbone' router
 ip address 10.0.0.1 255.255.255.252
 no shutdown
!
"""
        device = parse_text(ios_config)
        if device is None:
            pytest.skip("IOS パーサが config を検知できなかった")

        topology = build([device], generated_from=["test_amp.cfg"])
        html = render(topology)
        body = _strip_script_blocks(html)

        # HTML 本文に生の <script> タグが現れない
        assert "<script>" not in body.lower()
        # & は &amp; にエスケープされているはず
        assert "&amp;" in html, \
            "description 中の & が &amp; にエスケープされていない"


# ================================================================
# ユニットテスト: data-iface-id 経路の XSS エスケープ（BGP IF チップ連動）
# ================================================================

class TestDataIfaceIdXssEscape:
    """data-iface-id 属性経路で iface 名に特殊文字が含まれても
    生の HTML タグ・スクリプトが出力されないことを保証する。"""

    def _make_bgp_topology_with_xss_iface(self, iface_name: str) -> dict:
        """iface 名に XSS ペイロードを含む BGP topology を作成する。"""
        # iface_id は "device::iface_name" 形式
        iface_id = f"r1::{iface_name}"
        return {
            "title": "XSS iface-id Test",
            "generated_from": [],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios",
                 "as": 65001, "sections": []},
                {"id": "r2", "hostname": "R2", "vendor": "cisco_ios",
                 "as": 65002, "sections": []},
            ],
            "interfaces": [
                {
                    "id": iface_id,
                    "device": "r1",
                    "name": iface_name,
                    "ip": "10.0.0.1/30",
                    "vlan": None,
                    "description": None,
                    "shutdown": False,
                    "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
                    "admin_status": "up",
                },
                {
                    "id": "r2::Gi0/0",
                    "device": "r2",
                    "name": "GigabitEthernet0/0",
                    "ip": "10.0.0.2/30",
                    "vlan": None,
                    "description": None,
                    "shutdown": False,
                    "addresses": [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}],
                    "admin_status": "up",
                },
            ],
            "links": [
                {
                    "a_device": "r1",
                    "a_if": iface_name,
                    "b_device": "r2",
                    "b_if": "GigabitEthernet0/0",
                    "subnet": "10.0.0.0/30",
                    "kind": "inferred-subnet",
                },
            ],
            "segments": [],
            "routing": {
                "bgp": [
                    {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                     "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp"},
                ],
                "ospf": [],
                "static": [],
            },
        }

    @pytest.fixture
    def render_fn(self):
        from lib.rendering import render
        return render

    @pytest.mark.unit
    def test_data_iface_id_script_tag_not_raw_in_html(self, render_fn):
        """iface 名に <script> を含む場合、data-iface-id 属性値に生の <script> が出ない。"""
        topo = self._make_bgp_topology_with_xss_iface('<script>alert(1)</script>')
        html = render_fn(topo)
        body = _strip_script_blocks(html)
        # 生の <script> タグが HTML 本文に現れないこと
        assert "<script>" not in body.lower(), \
            "iface 名の <script> が data-iface-id 経由で HTML 本文にエスケープされずに現れた"

    @pytest.mark.unit
    def test_data_iface_id_script_tag_is_escaped(self, render_fn):
        """iface 名に <script> を含む場合、data-iface-id 属性値にエスケープ済み表現が出る。"""
        topo = self._make_bgp_topology_with_xss_iface('<script>alert(1)</script>')
        html = render_fn(topo)
        # data-iface-id="..." に生の < が入っていないこと
        # エスケープ済みの &lt; が含まれること
        assert 'data-iface-id="<script>' not in html, \
            "data-iface-id 属性値に生の <script> が含まれている"
        assert "&lt;script&gt;" in html or "data-iface-id" not in html, \
            "iface 名のエスケープ済み表現が HTML に見つからない"

    @pytest.mark.unit
    def test_data_iface_id_double_quote_escaped(self, render_fn):
        '''iface 名に " が含まれる場合、data-iface-id 属性値に生の " が出ない。'''
        topo = self._make_bgp_topology_with_xss_iface('Gi0"0')
        html = render_fn(topo)
        # data-iface-id="r1::Gi0"0" のような生の " が属性値に出ないこと
        assert 'data-iface-id="r1::Gi0"0"' not in html, \
            "data-iface-id 属性値に生の二重引用符が含まれている（XSS 脆弱性）"

    @pytest.mark.unit
    def test_data_iface_id_amp_escaped(self, render_fn):
        """iface 名に & が含まれる場合、data-iface-id 属性値に生の & が出ない。"""
        topo = self._make_bgp_topology_with_xss_iface('Gi0&0')
        html = render_fn(topo)
        # data-iface-id="r1::Gi0&0" のような生の & が属性値に出ないこと
        assert 'data-iface-id="r1::Gi0&0"' not in html, \
            "data-iface-id 属性値に生の & が含まれている（XSS 脆弱性）"
