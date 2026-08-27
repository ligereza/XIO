"""
Off-device tests for the show token (the muros wall on mutating endpoints).
    py xio/new-plugins/showcontrol/test_auth.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth import check_token, new_token, valid_token_format  # noqa: E402


def test_open_when_unconfigured():
    assert check_token(None, None)
    assert check_token(None, "anything")
    assert check_token("", None)             # empty config == no token == open
    print("OK no token configured -> open (backwards compatible)")


def test_match_and_reject():
    assert check_token("secret-token-1", "secret-token-1")
    assert not check_token("secret-token-1", "secret-token-2")
    assert not check_token("secret-token-1", "")
    assert not check_token("secret-token-1", None)
    assert not check_token("secret-token-1", 12345)      # non-str never matches
    assert not check_token("secret-token-1", "SECRET-TOKEN-1")  # case-sensitive
    print("OK configured token matches exactly, rejects everything else")


def test_new_token_format_and_uniqueness():
    seen = set()
    for _ in range(50):
        t = new_token()
        assert valid_token_format(t), t
        seen.add(t)
    assert len(seen) == 50                   # no collisions in 50 draws
    print("OK new_token generates valid, unique tokens")


def test_valid_token_format():
    assert valid_token_format("abcd1234")            # min length
    assert valid_token_format("A-b_c.d~1234!")
    assert not valid_token_format("short")            # < 8
    assert not valid_token_format("x" * 200)          # > 128
    assert not valid_token_format("has space123")     # whitespace
    assert not valid_token_format("tab\tchar123")
    assert not valid_token_format(12345678)           # not a string
    assert not valid_token_format(None)
    assert not valid_token_format("con-acento-\xe9x")  # non-ASCII
    print("OK token format validation")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))
