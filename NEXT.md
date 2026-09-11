# NEXT — open work, observations, suggestions

Written from memory at the end of the 2026-09-07 session, without re-reading
the tree. Re-measure any number here before acting on it. Not a contract.

## Operational, and the reason this file leads with it

**Private IPs are hardcoded as defaults in running code**, not only in guides.
From memory the sites are `xio/show_kit/artnet_relay.py`,
`xio/show_kit/check_show.py`, `xio/actual/server.py`,
`xio/new/pc_reboot_watch.sh`, and `cultura/mak_xio_puente/staged/mak_link.py`,
which carries one with a comment naming the host's role.

The one that matters most is in `xio/new/run_server.sh`: a private address sits
in the `XIO_DENY_IPS` security denylist. If that value is stale, the denylist
does not error -- it simply stops denying the host it was written to deny, and
nothing says so. The README already warns that some guides keep historical show
network values; this is the same residue inside a security control.

The correct values are the operator's, which is why they were not changed. A
show is the wrong moment to discover it.

**`cultura/mak_xio_puente/monitor.py` inserts `/home/mak/research` on
`sys.path` and imports `research_lib` with no `try`/`except`.** It works on MAK
by coincidence, because that directory happens to exist there. In any fresh
clone, on any other machine, the import raises. `cultura/mak_plataforma/
xio_evidence.py` wraps a similar import and degrades; this one does not.

## Documentation that describes another repository

`xio/CAPACIDADES.md` now marks nine components as absent -- the RD NODO set,
`radio_monitor.py` and `PLAN_CONECTIVIDAD_CLARO_2026.md` -- because they live in
the origin monorepo and the extraction did not select them. The design record
was kept rather than deleted.

Worth watching: `projects/rd-field/` landed on `main` separately, and its own
README says it is a new base, separate from the RD NODO family. When it
matures, `CAPACIDADES.md` will want a row for it, distinct from the nine.

## Branches nobody documents

Three `codex/xio-*` branches carry a whole `XIO_LAYER/` package -- transport,
peer sessions, source registry, a Lucida bridge -- with their own tests. From
memory that is on the order of twenty thousand inserted lines. `main` has none
of it, and `XIO_LAYER` appears in neither the README nor `CAPACIDADES.md`.

Any plan based on `main` alone is measuring a fraction of what is here. And
before XIO can be declared the single source for that layer -- see handoff 002
in FARMAKSIA, where the same package was found duplicated into LUCIDA -- someone
has to decide which of these branches is it.

## Provenance

`MATERIAL_ORIGEN.md` declares the origin and the revision it was cut from, in
prose. There is no per-file hash manifest like FARMAKSIA's, so the claim cannot
be checked offline. That is a difference, not necessarily a defect.

## Not audited

The logic of the 77 Python files. The largest are `foh_monitor` at around 1145
lines, `showcontrol` at 881 and `xio/new/server.py` at 823, and none of them was
read beyond what a test or a grep touched. The security surface -- tokens,
`plugin_guardian`, `security_hook` -- was not reviewed; that is a different kind
of work than what this session did.

The 82 tests that now run do not touch the phone, the network or `adb`. Nothing
here has been verified against the Xiaomi, and `CAPACIDADES.md` says so first.
