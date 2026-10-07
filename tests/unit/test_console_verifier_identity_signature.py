"""验证者身份页的「节点自有 key 签名」接线。

后端那闸门（``VERIFIER_REQUIRE_NODE_SIGNATURE``）打开之后，登记节点必须带
节点钱包签出来的 ``signature`` —— 页面要是还照旧发三件套，生产环境上就会
「填完表单按下去没反应」。这个门禁钉住四件事：

1. 页面**不自己拼签名消息**（格式只有服务端一处，见 services/verifier_wallet.py），
   而是跟 ``POST /v1/verifiers/sign-message`` 要待签文字；
2. 登记请求真的带上 ``signature`` + ``signature_nonce``；
3. 只有「当前连接的钱包 == 节点钱包」时才用 ``personal_sign`` 代签，其余情况
   把文字摊出来让节点自己签 —— 页面不代持私钥；
4. 待签文字放进 ``<pre>``：机器可读的原文不许被语言包翻掉。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
SCRIPTS = CONSOLE / "scripts"
PAGE = CONSOLE / "pages/cyber/index.html"
JS = SCRIPTS / "cyber-verifier-identity.js"
PACK_DIR = SCRIPTS / "i18n-phrase"
SHIPPED_LANGS = ("en", "ja", "ko", "es-AR", "es-SV")


def test_the_page_asks_the_server_for_the_canonical_message():
    js = JS.read_text(encoding="utf-8")
    assert 'NODE_SIGN_PATH = NODE_PATH + "/sign-message"' in js
    assert 'kind: "register"' in js
    # 消息格式不许在页面里再写一份 —— 两边各写一份迟早漂。
    assert "Karma Verifier Node Register" not in js


def test_register_sends_the_signature_and_the_nonce():
    js = JS.read_text(encoding="utf-8")
    assert "signature: signature" in js
    assert "signature_nonce: nonce" in js
    assert "function nodeNonce()" in js


def test_only_the_connected_node_wallet_signs_in_the_browser():
    js = JS.read_text(encoding="utf-8")
    assert 'method: "personal_sign", params: [message, wallet]' in js
    assert 'toLowerCase() !== String(nodeWallet' in js
    # 签名拿不到时把待签文字摊出来，而不是硬发一次注定 401 的请求。
    assert "showSignMessage(message)" in js


def test_the_text_to_sign_is_shown_in_a_pre_so_i18n_never_touches_it():
    html = PAGE.read_text(encoding="utf-8")
    assert '<pre id="vi-sign-msg" hidden></pre>' in html
    assert 'id="vi-signature"' in html


def test_the_new_copy_is_in_every_shipped_pack():
    samples = (
        "节点签名",
        "0x…（用节点钱包签名后贴进来）",
        "读取待签文字…",
        "请用节点钱包对下面这段文字签名，再把签名贴进「节点签名」。",
        "节点签名没通过：请用节点钱包对页面给出的待签文字签名。",
        "节点签名对不上这个节点钱包，换用节点钱包再签一次。",
    )
    for lang in SHIPPED_LANGS:
        pack = (PACK_DIR / f"{lang}.js").read_text(encoding="utf-8")
        missing = [s for s in samples if f'"{s}":' not in pack]
        assert not missing, f"{lang} 缺译文：{missing}"


def test_every_pack_still_has_the_same_number_of_entries():
    entry = re.compile(r"^\s*\"((?:[^\"\\]|\\.)*)\"\s*:", re.M)
    sizes = {
        lang: len(entry.findall((PACK_DIR / f"{lang}.js").read_text(encoding="utf-8")))
        for lang in SHIPPED_LANGS
    }
    assert len(set(sizes.values())) == 1, f"语言包条数不一致：{sizes}"
