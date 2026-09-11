# XIO-RD field surface

This is the RD field surface, separate from `foh_monitor`, `showcontrol` and
the FLUJO Hub. It is served by the existing XIO listener on port `5000`:

- FLUJO-RD hub (desktop/mobile): `/api/plugins/rd_field/view`
- Active browser field surface (optional): `/api/plugins/rd_field/field`
- read/bootstrap: `/api/plugins/rd_field/bootstrap`
- read samples: `/api/plugins/rd_field/samples?eventRef=...`
- write samples: `/api/plugins/rd_field/sync`

The browser client uses same-origin relative requests. The hotspot password is
the access boundary; this surface does not add a login or an app token.

## Authority and persistence

`rd_field` accepts a sample only when `eventRef` is present in the host RD
bootstrap. It never creates an event as a side effect of a sample sync. The
host owns the RD SQLite file and the external evidence directory. The FOH
JSONL logs and showcontrol state remain in their existing plugin paths.

Before a field runtime is started, stage a reviewed session snapshot of the
canonical FLUJO RD database as `<XIO_RD_PERSIST>/rd.db`. The current authority
is MAK `/home/mak/flujo/data/rd.db`; `C:\IA\flujo\data\rd.db` is only a
Windows working copy and must not be used for field staging unless the
read-only gate explicitly proves that it is current. Do not substitute the
small `rd_datos.db` file or an empty database: this plugin fails closed when
the host catalog/events are absent and never invents an event. The snapshot
becomes the host-owned field database for that offline session; its samples
must be reconciled back through the existing RD workflow after the event.

Read-only preflight from the XIO repository root:

```text
python tests/check_xio_field_staging.py --rd-db /home/mak/flujo/data/rd.db
```

Runtime paths can be supplied with:

- `XIO_RD_PERSIST`: durable host directory (default `/sdcard/xio_termux/rd_field`)
- `XIO_RD_DB`: explicit RD SQLite path (otherwise `<persist>/rd.db`)
- `XIO_RD_EVIDENCE`: explicit evidence root (otherwise `<persist>/evidence`)
- `XIO_RD_FIELD_ROOT`: deployed PWA files (otherwise this plugin's `static/`)
- `XIO_RD_BRIDGE`: bridge module (otherwise this plugin's `bridge.py`)

`bridge.py` is a deployment copy of the current portable
`flujo.rd.xio_ingest` module. The source of truth remains the existing FLUJO
implementation; do not hand-edit the copy without updating its source hash.

## Deployment boundary

The reviewed plugin and both hub bundles are staged under
`/sdcard/xio_termux/new-plugins/rd_field/` on the current Xiaomi. The running
Termux process is intentionally not force-restarted by ADB: `run_server.sh`
copies the staged files into its private runtime on the next normal launch.
Until that normal launch, the old in-memory/static process remains the live
surface. The durable host DB and evidence are not replaced by this staging.
