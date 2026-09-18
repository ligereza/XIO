"""Compatibility name for the canonical RD bridge hub.

The candidate repository used to carry a second 131 KB copy of ``hub.py``
under this name. Keeping the import name preserves older callers while one
file remains authoritative and reviewable.
"""

from hub import *  # noqa: F401,F403 - preserve the historical public surface
