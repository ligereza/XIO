from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "projects" / "rd-field" / "bridge"
MANIFEST = ROOT / "XIO_MANIFEST.sha256"


def test_remote_hub_is_a_compatibility_alias_not_a_second_implementation() -> None:
    canonical = BRIDGE / "hub.py"
    alias = BRIDGE / "hub_remote.py"

    assert canonical.is_file()
    assert alias.stat().st_size < 4096
    assert "from hub import *" in alias.read_text(encoding="utf-8")

    expected = next(
        line.split()[0]
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.endswith("  projects/rd-field/bridge/hub_remote.py")
    )
    assert hashlib.sha256(alias.read_bytes()).hexdigest() == expected
