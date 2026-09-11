# XIO-FOH / ISKVW

This is the personal VJ/artistic field surface. It is separate from
`rd_field`, which belongs to the Reduciendo Daño domain.

The existing XIO listener on port `5000` serves this surface under:

- `/api/plugins/foh_monitor/panel` — passive FOH monitor
- `/api/plugins/foh_monitor/context` — exact VJ event selector
- `/api/plugins/foh_monitor/context/data` — read-only context API
- `/api/plugins/foh_monitor/mapping` — existing self-contained Mapping LED tool
- `/api/plugins/foh_monitor/registro` and `/log` — FOH evidence
- `/api/plugins/showcontrol/panel` — existing opt-in show-control tools

The context selector accepts only an exact `eventKey` from
`foh_vj_context.json`. It persists the current selection in the FOH log
directory and labels new JSONL records with `domain: vj_foh` and
`fohEventKey`. It does not accept or write RD `eventRef`.

When a setlist is loaded, it records the selected `fohEventKey`. `next` and
`prev` refuse to advance a setlist bound to a different event, so two dates of
the same artist cannot silently share an operational log.

`foh_vj_context.json` is a read-only deployment snapshot composed from the
existing FLUJO VJ read model plus the existing MAK DrefQuila/project and
portfolio authorities. Refresh it only from those sources; do not hand-edit a
show into the catalog and do not infer a layout, rider or venue from an artist
name. A layout/rider/show-kit relation is valid only after an explicit source
reference is added to the context record.

FOH is browser/PWA-compatible and needs no APK. Mapping LED is copied from the
existing FLUJO standalone asset without adding a backend dependency, so it can
run from the private hotspot when the phone is the field host. The hotspot
password is the normal access boundary. No additional login or token is
introduced here.
