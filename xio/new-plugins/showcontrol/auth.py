"""
Show token -- the `muros` node applied to showcontrol.

The xio server binds 0.0.0.0 with open CORS, so on an audience-shared hotspot
ANY client could POST /artnet and disrupt a live rig. This module is the wall:
an optional shared secret that, once set, is required on every mutating (POST)
showcontrol endpoint. Read-only GETs (state/telemetry/panel) stay open.

Design:
  - OFF by default (no token configured -> open, trusted-crew mode unchanged).
  - TOFU (trust-on-first-use): POST /auth/set works freely only while NO token
    exists; after that, rotating or clearing requires the current token. This
    solves the bootstrap paradox (protecting the endpoint that sets the secret)
    without touching the server core.
  - Constant-time comparison (hmac.compare_digest): a plain == short-circuits
    on the first differing byte and leaks the token to a timing attacker.

Pure stdlib, no Flask here -- unit-tested off-device (test_auth.py).
"""

import hmac
import secrets

MIN_TOKEN_LEN = 8
MAX_TOKEN_LEN = 128


def new_token() -> str:
    """Generate a fresh URL-safe show token (~128 bits)."""
    return secrets.token_urlsafe(16)


def valid_token_format(token) -> bool:
    """A settable token: printable ASCII string, sane length, no whitespace."""
    if not isinstance(token, str):
        return False
    if not (MIN_TOKEN_LEN <= len(token) <= MAX_TOKEN_LEN):
        return False
    return all(33 <= ord(c) <= 126 for c in token)   # printable, no spaces/control


def check_token(configured, presented) -> bool:
    """True if access is allowed.

    No token configured -> open (True). Token configured -> the presented
    value must match, compared in constant time. None/non-str presented
    values never match.
    """
    if not configured:
        return True
    if not isinstance(presented, str):
        return False
    return hmac.compare_digest(configured.encode("utf-8"),
                               presented.encode("utf-8"))
