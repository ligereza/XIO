"""
Off-device tests for the optional XIO_SHOWCONTROL_TOKEN gate on the xio
showcontrol plugin (xio/new-plugins/showcontrol/__init__.py).

The xio server binds 0.0.0.0 on the show hotspot, so any joined client can
hit every showcontrol route. `_xio_token_required` (and the plugin's
`register_route()` override that applies it to every registered route) is
the optional whole-server lock for "public on the hotspot" shows. It is
layered outside the pre-existing muros `_guard`/`_token` wall (a
config-persisted, POST-only secret rotated via /auth/set) -- this one is a
single env var read at request time, applies to GETs too, and defaults OFF.

These tests boot the real ShowControlPlugin against a stub PluginContext and
wire its routes into a throwaway Flask app -- the same wiring
xio/new/server.py's init_plugins() does -- so they exercise the actual
register_route() override, not a reimplementation of it.

    py -m pytest tests/test_showcontrol_token.py -q
"""

import logging
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_XIO_NEW = _REPO_ROOT / "xio" / "new"                    # importable `plugins` package
_XIO_NEW_PLUGINS = _REPO_ROOT / "xio" / "new-plugins"     # importable `showcontrol` package
for _p in (str(_XIO_NEW), str(_XIO_NEW_PLUGINS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("flask")  # xio/new/requirements.txt, not a core flujo dependency

from flask import Flask  # noqa: E402
from plugins.base import PluginContext  # noqa: E402
import showcontrol  # noqa: E402

TOKEN_ENV = "XIO_SHOWCONTROL_TOKEN"
# GET /status is registered WITHOUT the pre-existing muros `_guard` wrapper,
# so a 401 here can only come from the new env-token gate under test.
STATUS_URL = "/api/plugins/showcontrol/status"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    ctx = PluginContext(controller=None,
                        logger=logging.getLogger("test-showcontrol"),
                        data_dir=tmp_path / "data")
    plugin = showcontrol.ShowControlPlugin(ctx)
    plugin.on_load()
    flask_app = Flask(__name__)
    for route in plugin.get_routes():
        flask_app.add_url_rule(route["rule"], endpoint=route["endpoint"],
                               view_func=route["view_func"], methods=route["methods"])
    try:
        yield flask_app
    finally:
        plugin.on_unload()


@pytest.fixture
def client(app):
    return app.test_client()


def test_token_unset_status_unchanged(client, monkeypatch):
    """No env token configured -> behavior EXACTLY as before this gate."""
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    r = client.get(STATUS_URL)
    assert r.status_code == 200
    assert r.get_json()["name"] == "Show Control"


def test_token_set_missing_header_401(client, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "s3cr3t-show-token")
    r = client.get(STATUS_URL)
    assert r.status_code == 401
    assert r.get_json() == {"error": "token requerido o invalido"}


def test_token_set_wrong_header_401(client, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "s3cr3t-show-token")
    r = client.get(STATUS_URL, headers={"X-Xio-Token": "wrong-token"})
    assert r.status_code == 401
    assert r.get_json() == {"error": "token requerido o invalido"}


def test_token_set_correct_header_200(client, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "s3cr3t-show-token")
    r = client.get(STATUS_URL, headers={"X-Xio-Token": "s3cr3t-show-token"})
    assert r.status_code == 200
    assert r.get_json()["name"] == "Show Control"


def test_compares_with_hmac_compare_digest(client, monkeypatch):
    """The match must go through hmac.compare_digest (constant-time), not a
    plain == that would short-circuit on the first differing byte."""
    monkeypatch.setenv(TOKEN_ENV, "s3cr3t-show-token")
    calls = []
    real_compare = showcontrol.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real_compare(a, b)

    monkeypatch.setattr(showcontrol.hmac, "compare_digest", spy)
    r = client.get(STATUS_URL, headers={"X-Xio-Token": "s3cr3t-show-token"})
    assert r.status_code == 200
    assert calls, "hmac.compare_digest was never called by the token gate"
    assert calls[0] == (b"s3cr3t-show-token", b"s3cr3t-show-token")


def test_env_read_at_request_time_not_import_time(client, monkeypatch):
    """Same running app/client, no reimport: setting the env var mid-session
    must start gating immediately -- proves the read happens per-request."""
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    assert client.get(STATUS_URL).status_code == 200   # open before the env is set

    monkeypatch.setenv(TOKEN_ENV, "late-token")
    assert client.get(STATUS_URL).status_code == 401    # gated the moment it's set

    monkeypatch.delenv(TOKEN_ENV, raising=False)
    assert client.get(STATUS_URL).status_code == 200   # open again once cleared
