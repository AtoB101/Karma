#!/usr/bin/env python3
"""CI gate: Agent Guard frontend security invariants + landing.js SRI drift check."""

from __future__ import annotations

import base64
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "apps/agent-service-guard/frontend"
INDEX = FRONTEND / "index.html"
LANDING = FRONTEND / "landing.js"
LOGIN = FRONTEND / "web3-login.html"
STUDIO = FRONTEND / "studio" / "index.html"


def fail(msg: str) -> None:
    print(f"ERR  agent-guard-security-gate: {msg}", file=sys.stderr)
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"OK   agent-guard-security-gate: {msg}")


def _lower(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").lower()


def _landing_integrity(text: str) -> str | None:
    anchor = './landing.js'
    idx = text.find(anchor)
    if idx == -1:
        return None
    window = text[max(0, idx - 380) : idx + len(anchor) + 220]
    m = re.search(r'integrity="(sha384-[A-Za-z0-9+/=]+)"', window, flags=re.IGNORECASE)
    return m.group(1) if m else None


def gate_portal_surface() -> None:
    text = INDEX.read_text(encoding="utf-8", errors="replace")
    lc = text.lower()
    for needle, reason in (
        ("@walletconnect", "portal must not bundle WalletConnect"),
        ("sign-client", "portal must not bundle WalletConnect SignClient"),
        ("karma_web3_session", "auth session only on sign-in + studio"),
        ("fromphrase", "no mnemonic derivation on marketing surface"),
        ("mnemonic-login", "demo mnemonic login removed from portal"),
        ('"ethers"', "no ethers on portal (use landing.js only if needed)"),
        ("esm.sh/ethers", "no remote ethers on portal"),
        ("qrcode.min.js", "QR only on dedicated sign-in"),
    ):
        if needle.lower() in lc:
            fail(f"index.html must not contain {needle!r} ({reason})")
    if "./landing.js" not in text:
        fail("index.html must load ./landing.js")
    li = _landing_integrity(text)
    if not li or not li.startswith("sha384-"):
        fail("index.html landing.js script tag must declare integrity=sha384-… (near landing.js)")
    ok("portal surface is wallet-free")


def gate_landing_sri() -> None:
    text = INDEX.read_text(encoding="utf-8", errors="replace")
    declared = _landing_integrity(text)
    if not declared:
        fail("index.html: missing landing.js integrity attribute")
    data = LANDING.read_bytes()
    digest = base64.b64encode(hashlib.sha384(data).digest()).decode("ascii")
    expected = f"sha384-{digest}"
    if declared != expected:
        fail(f"landing.js SRI mismatch: HTML has {declared}, file hashes to {expected}")
    ok("landing.js SRI matches file hash")


def gate_signin_wallet_only() -> None:
    lc = _lower(LOGIN)
    for needle in ("fromphrase", "ethers", "mnemonic-", "word-grid", "12-word"):
        if needle in lc:
            fail(f"web3-login.html must stay wallet-only QR (found {needle!r})")
    if "noindex" not in lc or "nofollow" not in lc:
        fail("web3-login.html must set robots noindex,nofollow")
    ok("sign-in page is WalletConnect-only + not indexed")


def gate_studio_headers() -> None:
    t = STUDIO.read_text(encoding="utf-8", errors="replace").lower()
    if "content-security-policy" not in t:
        fail("studio/index.html must declare Content-Security-Policy meta")
    if "referrer" not in t:
        fail("studio/index.html must declare referrer policy")
    ok("studio ships defense-in-depth meta policies")


def gate_openssl_sri_optional() -> None:
    """Double-check with openssl if available (matches deploy docs)."""
    try:
        proc = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha384",
                "-binary",
                str(LANDING),
            ],
            check=True,
            capture_output=True,
        )
        digest = base64.b64encode(proc.stdout).decode("ascii")
    except (FileNotFoundError, subprocess.CalledProcessError):
        ok("openssl SRI verify skipped (openssl unavailable)")
        return
    text = INDEX.read_text(encoding="utf-8", errors="replace")
    declared = _landing_integrity(text)
    if not declared:
        return
    expected = f"sha384-{digest}"
    if declared != expected:
        fail(f"openssl SRI mismatch: {declared} vs {expected}")
    ok("openssl confirms landing.js sha384")


def main() -> None:
    for path in (INDEX, LANDING, LOGIN, STUDIO):
        if not path.exists():
            fail(f"missing {path.relative_to(ROOT)}")
    gate_portal_surface()
    gate_landing_sri()
    gate_signin_wallet_only()
    gate_studio_headers()
    gate_openssl_sri_optional()


if __name__ == "__main__":
    main()
