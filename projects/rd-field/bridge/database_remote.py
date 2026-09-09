"""Constructor y consultas de la base de datos RD (SQLite).

Fuentes canonicas (unica verdad; la DB es su proyeccion):
- projects/cultura/identidad/reactivos.json  -> tabla `reactivos` + `meta` (disclaimer)
- src/flujo/plano/packs.py (PACKS)           -> tablas `packs` e `inclusiones`
- projects/piezas_vectoriales/suplementos_rd/01_contenido/contenido_suplementos_rd.json
                                             -> tabla `suplementos`
- data/productoras/*.json                    -> tabla `productoras` (promotoras conocidas)
- jobs/**/evento*.json + projects/plano/ejemplos/evento*.json
                                             -> tabla `eventos` (con pack sugerido por voluntarios)
- data/rd_fuentes/testeo_eventos_2025_evidence.json
                                             -> `testeo_*` tables (source evidence, not a public claim)

Regenerar: `build_rd_db()` borra y reescribe todo desde las fuentes. Nunca se
edita la DB a mano; si un dato cambia, se cambia la fuente y se reconstruye.

Nota de seguridad del dominio: el test de reactivo es PRESUNTIVO (indica familia
posible, no identifica ni mide pureza). El disclaimer canonico viaja en la tabla
`meta` y toda salida que muestre un color debe poder citarlo -- un color no
vuelve segura una sustancia.
"""
from __future__ import annotations

import json
import os
import hashlib
import importlib.util
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = _REPO / "data" / "rd.db"

# Fuentes canonicas
_REACTIVOS_JSON = _REPO / "projects" / "cultura" / "identidad" / "reactivos.json"
_SUPLEMENTOS_JSON = (
    _REPO / "projects" / "piezas_vectoriales" / "suplementos_rd"
    / "01_contenido" / "contenido_suplementos_rd.json"
)
_PRODUCTORAS_DIR = _REPO / "data" / "productoras"
_TESTING_EVIDENCE_JSON = _REPO / "data" / "rd_fuentes" / "testeo_eventos_2025_evidence.json"
_CANDIDATE_REGISTRIES = {
    "entity_universe_v0_1": (_REPO / "data" / "rd_fuentes" / "candidates" / "entity_universe_v0.1.json", "records"),
    "reagent_library_v0_1": (_REPO / "data" / "rd_fuentes" / "candidates" / "reagent_library_v0.1.json", "reagents"),
    "relation_graph_v0_1": (_REPO / "data" / "rd_fuentes" / "candidates" / "relation_graph_v0.1.json", "relations"),
    "relation_index_v0_1": (_REPO / "data" / "rd_fuentes" / "candidates" / "relation_index_v0.1.json", "records"),
}
# The RD source roster is MAK research material, not motor material. The
# portable motor may read it when the box is next to it, but must not require
# it: MAK_RESEARCH_ROOT overrides, and the default is the parent checkout
# because /home/mak/flujo sits inside /home/mak. Absent, the loader degrades
# instead of raising FileNotFoundError.
_MAK_RESEARCH_ROOT = Path(
    os.environ.get("MAK_RESEARCH_ROOT", str(_REPO.parent / "cultura" / "mak_research"))
)
_FUENTES_PY = _MAK_RESEARCH_ROOT / "fuentes.py"
MAK_RESEARCH_SOURCES_AVAILABLE = _FUENTES_PY.is_file()
_VENUES_DIR = _REPO / "knowledge" / "venues"     # *.yaml canonicos
_LOGOS_DIR = _REPO / "knowledge" / "logos"       # *.yaml canonicos
# Directorios donde viven jsons con forma de evento (voluntarios/asistentes/...)
_EVENTOS_GLOBS = (
    (_REPO / "jobs", "**/evento*.json"),
    (_REPO / "projects" / "plano" / "ejemplos", "evento*.json"),
)
# Campos minimos para considerar un json como "evento" (evita packs_servicios y otros)
_EVENTO_MARKERS = ("voluntarios", "asistentes_estimados")
_URL_RE = re.compile(r"https?://[^\s),;]+")
_FUENTES_MODULE: Any | None = None

_SCHEMA = """
CREATE TABLE meta (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
CREATE TABLE reactivos (
    id INTEGER PRIMARY KEY,
    reactivo TEXT NOT NULL,     -- Marquis, Mecke, ...
    familia  TEXT NOT NULL,     -- MDMA / MDA, anfetamina, opiaceos, ...
    reaccion TEXT NOT NULL,     -- descripcion del cambio de color
    hex      TEXT NOT NULL      -- color de referencia estetica (#rrggbb)
);
CREATE INDEX idx_reactivos_familia  ON reactivos(familia);
CREATE INDEX idx_reactivos_reactivo ON reactivos(reactivo);

-- Candidate research stays attributable and separate from canonical service
-- data. These records make associations inspectable; they are not public or
-- scientific claims merely because they share a database with observations.
CREATE TABLE rd_fuentes_registro (
    source_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    generated_at TEXT,
    schema_version TEXT,
    source_scope TEXT,
    raw_metadata TEXT NOT NULL
);
CREATE TABLE rd_entidades_candidatas (
    entity_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    entity_kind TEXT,
    aliases TEXT NOT NULL,
    matrix INTEGER NOT NULL DEFAULT 0,
    source_status TEXT,
    test_status TEXT,
    source_urls TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES rd_fuentes_registro(source_id),
    raw_record TEXT NOT NULL
);
CREATE TABLE rd_reactivos_candidatos (
    reagent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    reagent_type TEXT,
    components TEXT,
    observation_window TEXT,
    limitations TEXT NOT NULL,
    complements TEXT NOT NULL,
    source_url TEXT,
    source_id TEXT NOT NULL REFERENCES rd_fuentes_registro(source_id),
    raw_record TEXT NOT NULL
);
CREATE TABLE rd_reacciones_candidatas (
    reagent_id TEXT NOT NULL REFERENCES rd_reactivos_candidatos(reagent_id),
    target_ref TEXT NOT NULL,
    sequence TEXT,
    source_wording TEXT,
    PRIMARY KEY (reagent_id, target_ref, sequence)
);
CREATE TABLE rd_relaciones_candidatas (
    relation_id TEXT PRIMARY KEY,
    source_ref TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    source_kind TEXT,
    target_kind TEXT,
    relation_type TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence TEXT,
    matrix_relevance TEXT,
    notes TEXT,
    source_id TEXT NOT NULL REFERENCES rd_fuentes_registro(source_id),
    raw_record TEXT NOT NULL
);
CREATE TABLE rd_relacion_referencias (
    relation_id TEXT NOT NULL REFERENCES rd_relaciones_candidatas(relation_id),
    reference_kind TEXT NOT NULL,
    reference_value TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES rd_fuentes_registro(source_id),
    PRIMARY KEY (relation_id, reference_kind, reference_value)
);
CREATE INDEX idx_rd_relation_refs_source_target ON rd_relaciones_candidatas(source_ref, target_ref);
CREATE INDEX idx_rd_relation_refs_status ON rd_relaciones_candidatas(status);
CREATE TABLE packs (
    id          TEXT PRIMARY KEY,   -- INFO | TESTEO | COMPLETO
    nombre      TEXT NOT NULL,
    label       TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    precio      INTEGER NOT NULL,   -- CLP
    voluntarios INTEGER NOT NULL,
    m2          INTEGER NOT NULL,
    stands      INTEGER NOT NULL,
    orden       INTEGER NOT NULL
);
CREATE TABLE inclusiones (
    id      INTEGER PRIMARY KEY,
    pack_id TEXT NOT NULL REFERENCES packs(id),
    texto   TEXT NOT NULL,
    orden   INTEGER NOT NULL
);
CREATE INDEX idx_inclusiones_pack ON inclusiones(pack_id);
CREATE TABLE suplementos (
    id            TEXT PRIMARY KEY,
    titulo        TEXT NOT NULL,
    tag           TEXT,
    accent        TEXT,
    descripcion   TEXT,
    section_title TEXT,
    items         TEXT              -- JSON: lista de items del flyer
);
CREATE TABLE productoras (
    slug      TEXT PRIMARY KEY,     -- slug del nombre (match)
    nombre    TEXT NOT NULL,
    instagram TEXT,
    aliases   TEXT,                 -- JSON: formas literales que extrae la vision
    confirmado TEXT,                -- nota de confirmacion humana
    notas     TEXT
);
CREATE TABLE venues (
    id            TEXT PRIMARY KEY,   -- id canonico (espacio_riesco)
    nombre        TEXT NOT NULL,
    tipo          TEXT,               -- convention_center, club, ...
    escala        TEXT,               -- scale_default (mainstream/base/under)
    capacidad     TEXT,               -- capacity_bucket
    preset_reco   TEXT,               -- recommended_preset
    voluntarios_min INTEGER,
    requisitos    TEXT,               -- JSON: requirements_defaults
    notas         TEXT                -- JSON: notes[]
);
CREATE TABLE productora_tipos (
    id             INTEGER PRIMARY KEY,
    productora_slug TEXT NOT NULL REFERENCES productoras(slug),
    tipo           TEXT NOT NULL       -- vocab.TIPOS_FECHA
);
CREATE INDEX idx_prodtipos_slug ON productora_tipos(productora_slug);
CREATE INDEX idx_prodtipos_tipo ON productora_tipos(tipo);
CREATE TABLE productora_venues (
    id             INTEGER PRIMARY KEY,
    productora_slug TEXT NOT NULL REFERENCES productoras(slug),
    venue_nombre   TEXT NOT NULL,      -- nombre libre; venue_id si matchea uno canonico
    venue_id       TEXT REFERENCES venues(id),
    preferido      INTEGER NOT NULL,   -- 0/1: el reiterado/preferido
    estado         TEXT,               -- confirmado | inferido | ejemplo
    notas          TEXT
);
CREATE INDEX idx_prodvenues_slug ON productora_venues(productora_slug);
CREATE TABLE productora_logos (
    id             INTEGER PRIMARY KEY,
    productora_slug TEXT NOT NULL REFERENCES productoras(slug),
    logo_id        TEXT,               -- id del logo (thegrid_primary)
    knowledge      TEXT,               -- ruta al yaml de knowledge/logos
    estado         TEXT                -- status (source_needed, listo, ...)
);
CREATE INDEX idx_prodlogos_slug ON productora_logos(productora_slug);
-- OJO, dos cosas distintas se llamaron "eventos" y hay que no confundirlas:
--
--   `eventos`            = PLANTILLAS DE COTIZACION. Un tipo de evento con su
--                          duracion, voluntarios y pack sugerido, para
--                          presupuestar. Viene de jobs/ y projects/plano/.
--   `productora_eventos` = EVENTOS REALES de una productora (fecha, venue),
--                          registro curado a mano en data/productoras/*.json.
--
-- Antes solo existia la primera, asi que los eventos reales quedaban dentro del
-- json sin poder consultarse por SQL (2026-07-26: 7 eventos en 6 productoras
-- invisibles para `rd-db`). La tabla de abajo cierra ese hueco.
CREATE TABLE eventos (
    id                   INTEGER PRIMARY KEY,
    nombre               TEXT NOT NULL,
    fuente               TEXT NOT NULL,   -- ruta relativa del json de origen
    duracion_horas       INTEGER,
    voluntarios          INTEGER,
    asistentes_estimados INTEGER,
    incluye_testeo       INTEGER,         -- 0/1
    masivo               INTEGER,         -- 0/1
    ubicacion            TEXT,
    pack_sugerido        TEXT REFERENCES packs(id),  -- por match de voluntarios
    notas                TEXT
);
CREATE TABLE productora_eventos (
    id              INTEGER PRIMARY KEY,
    productora_slug TEXT NOT NULL REFERENCES productoras(slug),
    nombre          TEXT NOT NULL,
    fecha           TEXT,               -- prosa tal cual se registro; puede decir needs_confirmation
    venue           TEXT,
    estado          TEXT,               -- pasado | activo_anunciado | confirmado_usuario | ...
    fuente          TEXT,               -- de donde salio el dato; nunca se inventa
    fuentes_primarias TEXT,             -- JSON: primary URLs according to fuente gate
    sin_fuente_primaria INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_prodeventos_slug ON productora_eventos(productora_slug);

-- Historical testing evidence imported from a workbook. These tables are an
-- evidence projection: they do not turn a color observation into identity,
-- purity, dose, or safety, and they do not authorize automatic publication.
CREATE TABLE testeo_fuentes (
    id             TEXT PRIMARY KEY,
    archivo        TEXT NOT NULL,
    sha256         TEXT NOT NULL,
    periodo        TEXT,
    formula_count  INTEGER NOT NULL DEFAULT 0,
    generated_at   TEXT,
    status         TEXT NOT NULL,
    principios     TEXT NOT NULL
);
CREATE TABLE testeo_hojas (
    source_sheet_index INTEGER PRIMARY KEY,
    source_sheet_name  TEXT NOT NULL,
    data_row_count     INTEGER NOT NULL,
    source_sheet_hash  TEXT NOT NULL,
    duplicate_group_id TEXT,
    duplicate_group_size INTEGER,
    duplicate_status   TEXT
);
CREATE INDEX idx_testeo_hojas_duplicate ON testeo_hojas(duplicate_group_id);
CREATE TABLE testeo_eventos_fuente (
    event_id                       TEXT PRIMARY KEY,
    source_sheet_index             INTEGER NOT NULL REFERENCES testeo_hojas(source_sheet_index),
    source_sheet_name              TEXT NOT NULL,
    event_label_candidate          TEXT,
    event_label_status             TEXT,
    source_period_label            TEXT,
    date_raw_token                 TEXT,
    date_iso_candidate             TEXT,
    date_status                    TEXT,
    date_parse_style               TEXT,
    date_confidence                TEXT,
    outside_filename_period_candidate INTEGER NOT NULL DEFAULT 0,
    is_source_copy_candidate       INTEGER NOT NULL DEFAULT 0,
    duplicate_group_id             TEXT,
    duplicate_group_size           INTEGER,
    duplicate_status               TEXT,
    duplicate_canonical_sheet_candidate TEXT,
    venue_id_candidate             TEXT,
    venue_name_candidate           TEXT,
    producer_id_candidate          TEXT,
    producer_name_candidate        TEXT,
    link_status                    TEXT,
    link_evidence_ref              TEXT,
    link_confidence                TEXT,
    link_review_status             TEXT
);
CREATE INDEX idx_testeo_eventos_fuente_sheet ON testeo_eventos_fuente(source_sheet_index);
CREATE TABLE testeo_filas_fuente (
    test_id                         TEXT PRIMARY KEY,
    event_id                        TEXT NOT NULL REFERENCES testeo_eventos_fuente(event_id),
    source_sheet_name               TEXT NOT NULL,
    source_row                      INTEGER NOT NULL,
    row_status                      TEXT,
    substance_raw                   TEXT,
    substance_normalized_candidate  TEXT,
    substance_map_status            TEXT,
    format_raw                      TEXT,
    test_1_raw                      TEXT,
    result_1_raw                    TEXT,
    test_2_raw                      TEXT,
    result_2_raw                    TEXT,
    test_3_raw                      TEXT,
    result_3_raw                    TEXT,
    test_4_raw                      TEXT,
    result_4_raw                    TEXT,
    extra_1_raw                     TEXT,
    source_duplicate_group_id       TEXT,
    source_duplicate_status         TEXT,
    interpretation_policy           TEXT
);
CREATE INDEX idx_testeo_filas_event ON testeo_filas_fuente(event_id);
CREATE TABLE testeo_observaciones_fuente (
    observation_id                  TEXT PRIMARY KEY,
    test_id                         TEXT NOT NULL REFERENCES testeo_filas_fuente(test_id),
    event_id                        TEXT NOT NULL REFERENCES testeo_eventos_fuente(event_id),
    source_sheet_name               TEXT NOT NULL,
    source_row                      INTEGER NOT NULL,
    observation_ordinal             INTEGER NOT NULL,
    substance_raw                   TEXT,
    substance_normalized_candidate  TEXT,
    reagent_raw                     TEXT,
    reagent_normalized_candidate    TEXT,
    reagent_map_status               TEXT,
    result_raw                      TEXT,
    result_normalized_candidate     TEXT,
    result_map_status               TEXT,
    observation_status              TEXT,
    interpretation_policy           TEXT
);
CREATE INDEX idx_testeo_obs_event ON testeo_observaciones_fuente(event_id);
CREATE INDEX idx_testeo_obs_reagent ON testeo_observaciones_fuente(reagent_normalized_candidate);
CREATE TABLE testeo_mapa_sustancias (
    raw_label       TEXT PRIMARY KEY,
    count           INTEGER NOT NULL,
    normalized_id   TEXT,
    mapping_status  TEXT NOT NULL
);
CREATE TABLE testeo_mapa_reactivos (
    raw_label       TEXT PRIMARY KEY,
    count           INTEGER NOT NULL,
    normalized_id   TEXT,
    mapping_status  TEXT NOT NULL
);
CREATE TABLE testeo_enlaces_revision (
    link_id                 TEXT PRIMARY KEY,
    event_id                TEXT NOT NULL REFERENCES testeo_eventos_fuente(event_id),
    source_sheet_name       TEXT NOT NULL,
    target_kind             TEXT NOT NULL,
    target_id               TEXT,
    target_name             TEXT,
    relation_type           TEXT NOT NULL,
    evidence_ref            TEXT,
    confidence              TEXT,
    status                  TEXT NOT NULL,
    review_status           TEXT NOT NULL,
    not_inferred_from_sheet_name INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_testeo_links_event ON testeo_enlaces_revision(event_id);
CREATE INDEX idx_testeo_links_review ON testeo_enlaces_revision(review_status);
CREATE VIEW v_testeo_observaciones_reactivo AS
SELECT
    observation.observation_id,
    observation.test_id,
    observation.event_id,
    observation.reagent_normalized_candidate AS reagent_id,
    observation.result_raw,
    observation.result_normalized_candidate,
    observation.interpretation_policy,
    candidate.name AS reagent_name,
    candidate.observation_window,
    candidate.limitations AS candidate_limitations
FROM testeo_observaciones_fuente AS observation
JOIN rd_reactivos_candidatos AS candidate
  ON candidate.reagent_id = observation.reagent_normalized_candidate;
"""


# ---------------------------------------------------------------------------
# La columna vertebral: evento <-> productora(s) <-> venue, y la mesa de testeo.
#
# Hasta el 2026-09-05 los 42 eventos del cuaderno 2025 estaban `unlinked` y sin
# un solo candidato de productora o de venue: el testeo y el catalogo eran dos
# islas. Estas tablas las unen, y admiten lo que la realidad tiene y una clave
# foranea sola no: un evento con VARIAS productoras. "Espacio Riesco con
# THE GRID + SUNDECK + GLOVOX" no es un error de datos ni tres eventos; es una
# fecha en colaboracion, y cual de las tres es anfitriona se averigua, no se
# asume.
#
# Cada vinculo declara como se supo: MEDIDO (esta escrito en la fuente),
# DERIVADO (calculado desde otro dato) o SUPUESTO (inferencia). Ninguno se
# presenta como hecho, y `estado_revision` mantiene la compuerta humana que
# `data/rd_fuentes/README.md` exige antes de publicar un enlace.
# ---------------------------------------------------------------------------
_SCHEMA_RELACIONES = """
CREATE TABLE IF NOT EXISTS evento_productoras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_ref TEXT NOT NULL,
    evento_origen TEXT NOT NULL,
    productora_slug TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'sin_determinar',
    metodo TEXT NOT NULL,
    evidencia TEXT,
    confianza TEXT NOT NULL,
    estado_revision TEXT NOT NULL DEFAULT 'pendiente_revision_humana',
    UNIQUE(evento_ref, evento_origen, productora_slug)
);

CREATE TABLE IF NOT EXISTS evento_venues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_ref TEXT NOT NULL,
    evento_origen TEXT NOT NULL,
    venue_id TEXT,
    venue_nombre TEXT NOT NULL,
    metodo TEXT NOT NULL,
    origen TEXT NOT NULL,
    confianza TEXT NOT NULL,
    estado_revision TEXT NOT NULL DEFAULT 'pendiente_revision_humana',
    UNIQUE(evento_ref, evento_origen, venue_nombre)
);

CREATE TABLE IF NOT EXISTS mesas_testeo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evento_ref TEXT NOT NULL,
    evento_origen TEXT NOT NULL,
    numero INTEGER,
    etiqueta TEXT,
    origen TEXT NOT NULL,
    UNIQUE(evento_ref, evento_origen, etiqueta)
);
"""


# Lo que la app de ingreso de muestras va a escribir. Se declara ahora para que
# la relacion exista desde el primer dia y no haya que retro-encajarla: una
# muestra pertenece a una mesa, la mesa a un evento, y el evento ya tiene
# productoras y venue por las tablas de arriba.
#
# Es acumulativo, como `registros_testeo`: `build_rd_db()` lo rescata y lo
# repone, nunca lo rederiva. Hereda la misma regla de privacidad: ninguna
# columna de identidad, y `fecha` siempre YYYY-MM-DD sin hora.
_SCHEMA_MUESTRAS = """
CREATE TABLE IF NOT EXISTS muestras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    mesa_id INTEGER REFERENCES mesas_testeo(id),
    evento_ref TEXT,
    evento_origen TEXT,
    codigo_muestra TEXT,
    sustancia_declarada TEXT NOT NULL,
    tipo_muestra TEXT,
    color TEXT,
    textura TEXT,
    logo_o_marca TEXT,
    peso_mg REAL,
    foto_ref TEXT,
    notas TEXT,
    descartada INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS muestra_resultados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    muestra_id INTEGER NOT NULL REFERENCES muestras(id),
    reactivo TEXT NOT NULL,
    resultado_color TEXT,
    familia_detectada TEXT,
    coincide_con_declarada INTEGER,
    adulterante_sospechado TEXT,
    limitacion TEXT NOT NULL DEFAULT 'presuntivo: senal de presencia, no identidad ni pureza ni dosis',
    orden INTEGER
);
"""


def _load_fuentes_module():
    global _FUENTES_MODULE
    if _FUENTES_MODULE is not None:
        return _FUENTES_MODULE
    spec = importlib.util.spec_from_file_location("mak_research_fuentes", _FUENTES_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load source gate from {_FUENTES_PY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _FUENTES_MODULE = module
    return module


def _event_source_gate(source_text: Any) -> tuple[str, int]:
    """Evaluate the event source field through MAK's source gate.

    The RD database is a regenerable projection, so it can persist the verdict
    without owning the source-classification rules. Those stay in
    `cultura/mak_research/fuentes.py`.
    """
    text = "" if source_text is None else str(source_text)
    urls = _URL_RE.findall(text)
    evaluation = _load_fuentes_module().evaluar("evento productora RD", urls, "cl_eventos")
    return json.dumps(evaluation["fuentes_primarias"], ensure_ascii=False), int(
        bool(evaluation["sin_fuente_primaria"])
    )


def _load_yaml(path: Path) -> dict[str, Any] | None:
    """Lee un yaml canonico si PyYAML esta disponible. Sin yaml, devuelve None
    (la tabla venues queda vacia; el resto de la DB no se afecta)."""
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _astext(value: Any) -> str | None:
    """Coacciona un campo a texto para SQLite. None queda None; listas/dicts se
    serializan a JSON (algunos flyers traen `description` como lista de parrafos);
    escalares a str."""
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _load_packs() -> dict[str, dict[str, Any]]:
    """Importa PACKS del modulo canonico (no duplica los numeros aca)."""
    from flujo.plano.packs import ALL_PACKS, PACKS

    return {pid: PACKS[pid] for pid in ALL_PACKS}


def _pack_por_voluntarios(voluntarios: int | None) -> str | None:
    """Sugiere el pack cuyo numero de voluntarios coincide con el del evento.
    Pista derivada, no un dato del evento. Tras reconciliar precios con la
    fuente real (jefe area eventos 2026-07-02), INFO y TESTEO comparten 6
    voluntarios: para 6 el conteo NO distingue (lo hace incluye_testeo), asi
    que si mas de un pack matchea se devuelve None (ambiguo) en vez de adivinar.
    COMPLETO=15 sigue siendo unico."""
    if voluntarios is None:
        return None
    matches = [pid for pid, p in _load_packs().items() if int(p["voluntarios"]) == int(voluntarios)]
    return matches[0] if len(matches) == 1 else None


def _iter_evento_sources() -> list[tuple[str, dict[str, Any]]]:
    """Encuentra jsons con forma de evento y los devuelve como (ruta_rel, dict),
    ordenados por ruta para salida deterministica. Descarta jsons que no traen
    los marcadores de evento (packs_servicios, contenidos, etc.)."""
    encontrados: list[tuple[str, dict[str, Any]]] = []
    vistos: set[Path] = set()
    for base, patron in _EVENTOS_GLOBS:
        if not base.exists():
            continue
        for f in sorted(base.glob(patron)):
            if f in vistos:
                continue
            vistos.add(f)
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(d, dict):
                continue
            if not all(m in d for m in _EVENTO_MARKERS):
                continue
            encontrados.append((f.relative_to(_REPO).as_posix(), d))
    return encontrados


def _load_testing_evidence(path: Path | None = None) -> dict[str, Any] | None:
    """Load testing evidence without turning it into a public claim.

    The file is optional so a checkout without the controlled registry can
    still build the base projection. Its schema is checked by integration
    tests; this loader only accepts a JSON document with the expected
    collections and ignores unrecognized rows rather than inventing them.
    """
    source_path = path if path is not None else _TESTING_EVIDENCE_JSON
    if not source_path.exists():
        return None
    try:
        doc = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("source"), dict):
        return None
    if not isinstance(doc.get("events"), list) or not isinstance(doc.get("observations"), list):
        return None
    return doc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_candidate_registry(path: Path) -> dict[str, Any] | None:
    """Load a candidate registry exactly as supplied, never fabricating rows."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _insert_candidate_registries(conn: sqlite3.Connection) -> None:
    """Project RD candidate registries without promoting their contents.

    The tables preserve raw records and sources alongside the queryable fields.
    That lets the operator inspect why a relation is proposed without turning a
    site page, a scraped URL, or a color change into a scientific conclusion.
    """
    docs: dict[str, dict[str, Any]] = {}
    for source_id, (path, record_key) in _CANDIDATE_REGISTRIES.items():
        doc = _load_candidate_registry(path)
        if doc is None or not isinstance(doc.get(record_key), list):
            continue
        docs[source_id] = doc
        metadata = {key: value for key, value in doc.items() if key != record_key}
        conn.execute(
            "INSERT INTO rd_fuentes_registro("
            "source_id, path, sha256, status, generated_at, schema_version, source_scope, raw_metadata"
            ") VALUES (?,?,?,?,?,?,?,?)",
            (
                source_id,
                path.relative_to(_REPO).as_posix(),
                _sha256_file(path),
                str(doc.get("status", "candidate")),
                doc.get("generated_at"),
                doc.get("schema_version"),
                doc.get("source_scope") or doc.get("source"),
                _json(metadata),
            ),
        )

    for row in docs.get("entity_universe_v0_1", {}).get("records", []):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        conn.execute(
            "INSERT INTO rd_entidades_candidatas("
            "entity_id, display_name, entity_kind, aliases, matrix, source_status, test_status, "
            "source_urls, source_id, raw_record) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(row["id"]),
                str(row.get("display_name", row["id"])),
                row.get("entity_kind"),
                _json(row.get("aliases", [])),
                int(bool(row.get("matrix"))),
                row.get("source_status"),
                row.get("test_status"),
                _json(row.get("source_urls", [])),
                "entity_universe_v0_1",
                _json(row),
            ),
        )

    for row in docs.get("reagent_library_v0_1", {}).get("reagents", []):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        reagent_id = str(row["id"])
        conn.execute(
            "INSERT INTO rd_reactivos_candidatos("
            "reagent_id, name, reagent_type, components, observation_window, limitations, "
            "complements, source_url, source_id, raw_record) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                reagent_id,
                str(row.get("name", reagent_id)),
                row.get("type"),
                row.get("components"),
                row.get("observation_window"),
                _json(row.get("limitations", [])),
                _json(row.get("complements", [])),
                row.get("source_url"),
                "reagent_library_v0_1",
                _json(row),
            ),
        )
        for reaction in row.get("reactions", []):
            if not isinstance(reaction, dict) or not reaction.get("target"):
                continue
            conn.execute(
                "INSERT INTO rd_reacciones_candidatas("
                "reagent_id, target_ref, sequence, source_wording) VALUES (?,?,?,?)",
                (
                    reagent_id,
                    str(reaction["target"]),
                    reaction.get("sequence"),
                    reaction.get("source_wording"),
                ),
            )

    for row in docs.get("relation_graph_v0_1", {}).get("relations", []):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        relation_id = str(row["id"])
        conn.execute(
            "INSERT INTO rd_relaciones_candidatas("
            "relation_id, source_ref, target_ref, source_kind, target_kind, relation_type, "
            "status, confidence, matrix_relevance, notes, source_id, raw_record) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                relation_id,
                str(row.get("source_ref", "")),
                str(row.get("target_ref", "")),
                row.get("source_kind"),
                row.get("target_kind"),
                str(row.get("relation_type", "context")),
                str(row.get("status", "candidate")),
                row.get("confidence"),
                row.get("matrix_relevance"),
                row.get("notes"),
                "relation_graph_v0_1",
                _json(row),
            ),
        )
        for reference_kind, values in (("testing_ref", row.get("testing_refs", [])), ("evidence_url", row.get("evidence_urls", []))):
            for value in values if isinstance(values, list) else []:
                conn.execute(
                    "INSERT INTO rd_relacion_referencias(relation_id, reference_kind, reference_value, source_id) "
                    "VALUES (?,?,?,?)",
                    (relation_id, reference_kind, str(value), "relation_graph_v0_1"),
                )

    for row in docs.get("relation_index_v0_1", {}).get("records", []):
        if not isinstance(row, dict) or not row.get("relation_id"):
            continue
        relation_id = str(row["relation_id"])
        for reference_kind in ("rd_pages", "testing_guides", "product_resources", "research_posts", "scientific_sources", "other_sources", "testing_refs"):
            values = row.get(reference_kind, [])
            for value in values if isinstance(values, list) else []:
                conn.execute(
                    "INSERT OR IGNORE INTO rd_relacion_referencias("
                    "relation_id, reference_kind, reference_value, source_id) VALUES (?,?,?,?)",
                    (relation_id, reference_kind, str(value), "relation_index_v0_1"),
                )


def _fold_source_label(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.strip().casefold())


def _project_substance_label(
    raw: Any, candidate: Any, status: Any, *, header_row: bool = False
) -> tuple[Any, str]:
    """Refine obvious source-column errors without guessing identity."""
    key = _fold_source_label(raw)
    if header_row or key in {"sustancia", "column 1"}:
        return None, "repeated_header"
    if key in {"freedom explicito", "lamborghini dorada"}:
        return None, "misplaced_format_label"
    if key == "ketamina+m":
        return "ketamine_plus_unspecified_m", "mixture_candidate"
    if key == "polvo blanco":
        return "unknown", "substance_or_format_unresolved"
    return candidate, str(status or "")


def _is_testing_header_row(row: dict[str, Any]) -> bool:
    """Recognize a header copied into a data row by its column vocabulary."""
    if str(row.get("row_status") or "") == "repeated_header":
        return True
    values = [
        row.get("substance_raw"),
        row.get("format_raw"),
        row.get("test_1_raw"),
        row.get("result_1_raw"),
        row.get("test_2_raw"),
        row.get("result_2_raw"),
        row.get("test_3_raw"),
        row.get("result_3_raw"),
        row.get("test_4_raw"),
        row.get("result_4_raw"),
    ]
    keys = [_fold_source_label(value) for value in values if _fold_source_label(value)]
    if not keys or keys[0] != "column 1":
        return False
    return all(
        re.fullmatch(r"column \d+", key) is not None
        for key in keys
    )


def _project_reagent_label(
    raw: Any, candidate: Any, status: Any, *, header_row: bool = False
) -> tuple[Any, str]:
    """Separate test names, result spillover, and actual reagent candidates."""
    key = _fold_source_label(raw)
    if header_row or re.fullmatch(r"column [3579]", key):
        return None, "repeated_header"
    if key == "cannabis":
        return "cbd_thc", "candidate_catalog_test"
    if key == "fentanilo":
        return "fentanyl_strip", "non_colorimetric_test"
    if key == "sin reaccion":
        return None, "result_in_reagent_column"
    if key == "mireia":
        return None, "possible_typo_candidate"
    return candidate, str(status or "")


def _project_event_date(row: dict[str, Any]) -> tuple[Any, str, str]:
    """Resolve date-only sheet labels against the workbook period when safe."""
    existing = row.get("date_iso_candidate")
    if existing:
        return existing, str(row.get("date_status") or "parsed_candidate"), str(
            row.get("date_confidence") or "medium"
        )
    period = str(row.get("source_period_label") or "")
    if not re.fullmatch(r"\d{4}", period):
        return None, str(row.get("date_status") or "not_found"), str(
            row.get("date_confidence") or "none"
        )
    token = str(row.get("date_raw_token") or "")
    if not token:
        token_match = re.search(
            r"(?<!\d)(\d{1,2}[-/.]\d{1,2}|\d{2,8})(?!\d)",
            str(row.get("source_sheet_name") or ""),
        )
        token = token_match.group(0) if token_match else ""
    day = month = year = None
    separated = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})", token)
    if separated:
        day, month, year = int(separated.group(1)), int(separated.group(2)), int(period)
    elif token.isdigit() and len(token) == 4:
        # Prefer DDMM when valid; otherwise accept D(M)YY / DD(M)YY.
        candidates = []
        dd, mm = int(token[:2]), int(token[2:])
        if 1 <= dd <= 31 and 1 <= mm <= 12:
            candidates.append((dd, mm, int(period)))
        if token.endswith("25"):
            dd, m = int(token[:2]), int(token[2])
            if 1 <= dd <= 31 and 1 <= m <= 12:
                candidates.append((dd, m, 2025))
            d, m = int(token[0]), int(token[1])
            if 1 <= d <= 31 and 1 <= m <= 12:
                candidates.append((d, m, 2025))
        if candidates:
            day, month, year = candidates[0]
    elif token.isdigit() and len(token) == 5:
        # Compact names use either DMMYY or DDMYY (for example 51225, 18125).
        candidates = []
        d, m = int(token[0]), int(token[1:3])
        if 1 <= d <= 31 and 1 <= m <= 12:
            candidates.append((d, m, 2000 + int(token[3:])))
        dd, m = int(token[:2]), int(token[2])
        if 1 <= dd <= 31 and 1 <= m <= 12:
            candidates.append((dd, m, 2000 + int(token[3:])))
        if candidates:
            day, month, year = candidates[0]
    elif token.isdigit() and len(token) == 3:
        # Short forms in the workbook: D MM or DD M, always in the source period.
        candidates = [(int(token[0]), int(token[1:]), int(period)),
                      (int(token[:2]), int(token[2]), int(period))]
        for candidate_day, candidate_month, candidate_year in candidates:
            if 1 <= candidate_day <= 31 and 1 <= candidate_month <= 12:
                day, month, year = candidate_day, candidate_month, candidate_year
                break
    elif token.isdigit() and len(token) == 2:
        day, month, year = int(token[0]), int(token[1]), int(period)
    if day is None or month is None or year is None:
        return None, str(row.get("date_status") or "not_found"), str(
            row.get("date_confidence") or "none"
        )
    try:
        parsed = date(year, month, day).isoformat()
    except ValueError:
        return None, str(row.get("date_status") or "not_found"), str(
            row.get("date_confidence") or "none"
        )
    return parsed, "resolved_from_source_period" if year == int(period) else "parsed_candidate", "low"


def _project_duplicate_events(events: list[Any]) -> dict[str, tuple[str | None, bool]]:
    """Choose an aggregate representative while preserving every source row."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in events:
        if not isinstance(row, dict):
            continue
        group_id = row.get("duplicate_group_id")
        if group_id and int(row.get("duplicate_group_size") or 1) > 1:
            groups.setdefault(str(group_id), []).append(row)
    projected: dict[str, tuple[str | None, bool]] = {}
    for rows in groups.values():
        non_copy = [row for row in rows if not bool(row.get("is_source_copy_candidate"))]
        candidates = non_copy or rows
        canonical = min(
            candidates,
            key=lambda row: int(row.get("source_sheet_index") or 0),
        )
        canonical_name = str(canonical.get("source_sheet_name", ""))
        for row in rows:
            event_id = str(row.get("event_id", ""))
            projected[event_id] = (canonical_name, event_id != str(canonical.get("event_id", "")))
    return projected


def _insert_testing_evidence(conn: sqlite3.Connection, doc: dict[str, Any]) -> None:
    """Project the evidence document into isolated, traceable tables."""
    source = doc["source"]
    source_id = "testeo-" + str(source.get("sha256", "unknown"))[:16]
    conn.execute(
        "INSERT INTO testeo_fuentes(id, archivo, sha256, periodo, formula_count, "
        "generated_at, status, principios) VALUES (?,?,?,?,?,?,?,?)",
        (
            source_id,
            str(source.get("file_name", "")),
            str(source.get("sha256", "")),
            source.get("filename_period_label"),
            int(source.get("formula_count") or 0),
            doc.get("generated_at"),
            str(doc.get("status", "candidate_evidence_pending_human_review")),
            json.dumps(doc.get("principles", []), ensure_ascii=False),
        ),
    )

    projected_events: dict[str, tuple[Any, str, str]] = {}
    for row in doc.get("events", []):
        if isinstance(row, dict) and row.get("event_id"):
            projected_events[str(row["event_id"])] = _project_event_date(row)
    projected_duplicates = _project_duplicate_events(doc.get("events", []))

    projected_rows: dict[str, tuple[Any, str, bool]] = {}
    substance_counts: Counter[tuple[str, Any, str]] = Counter()
    for row in doc.get("test_rows", []):
        if not isinstance(row, dict):
            continue
        header_row = _is_testing_header_row(row)
        normalized, mapping_status = _project_substance_label(
            row.get("substance_raw"),
            row.get("substance_normalized_candidate"),
            row.get("substance_map_status"),
            header_row=header_row,
        )
        row_status = "repeated_header" if header_row else row.get("row_status")
        if row.get("substance_raw") not in (None, ""):
            substance_counts[(str(row.get("substance_raw")), normalized, mapping_status)] += 1
        if row.get("test_id"):
            projected_rows[str(row["test_id"])] = (normalized, mapping_status, header_row)

    reagent_counts: Counter[tuple[str, Any, str]] = Counter()
    for row in doc.get("observations", []):
        if not isinstance(row, dict) or row.get("reagent_raw") in (None, ""):
            continue
        header_row = projected_rows.get(str(row.get("test_id")), (None, "", False))[2]
        normalized, mapping_status = _project_reagent_label(
            row.get("reagent_raw"),
            row.get("reagent_normalized_candidate"),
            row.get("reagent_map_status"),
            header_row=header_row,
        )
        reagent_counts[(str(row.get("reagent_raw")), normalized, mapping_status)] += 1

    for row in doc.get("source_sheets", []):
        if not isinstance(row, dict):
            continue
        conn.execute(
            "INSERT INTO testeo_hojas(source_sheet_index, source_sheet_name, "
            "data_row_count, source_sheet_hash, duplicate_group_id, "
            "duplicate_group_size, duplicate_status) VALUES (?,?,?,?,?,?,?)",
            (
                row.get("source_sheet_index"),
                str(row.get("source_sheet_name", "")),
                int(row.get("data_row_count_including_anomalies") or 0),
                str(row.get("source_sheet_hash", "")),
                row.get("duplicate_group_id"),
                row.get("duplicate_group_size"),
                row.get("duplicate_status"),
            ),
        )

    for row in doc.get("events", []):
        if not isinstance(row, dict):
            continue
        conn.execute(
            "INSERT INTO testeo_eventos_fuente("
            "event_id, source_sheet_index, source_sheet_name, event_label_candidate, "
            "event_label_status, source_period_label, date_raw_token, date_iso_candidate, "
            "date_status, date_parse_style, date_confidence, outside_filename_period_candidate, "
            "is_source_copy_candidate, duplicate_group_id, duplicate_group_size, duplicate_status, "
            "duplicate_canonical_sheet_candidate, venue_id_candidate, venue_name_candidate, "
            "producer_id_candidate, producer_name_candidate, link_status, link_evidence_ref, "
            "link_confidence, link_review_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("event_id"),
                row.get("source_sheet_index"),
                str(row.get("source_sheet_name", "")),
                row.get("event_label_candidate"),
                row.get("event_label_status"),
                row.get("source_period_label"),
                row.get("date_raw_token"),
                projected_events.get(str(row.get("event_id")), (None, row.get("date_status"), row.get("date_confidence")))[0],
                projected_events.get(str(row.get("event_id")), (None, row.get("date_status"), row.get("date_confidence")))[1],
                row.get("date_parse_style"),
                projected_events.get(str(row.get("event_id")), (None, row.get("date_status"), row.get("date_confidence")))[2],
                int(bool(row.get("outside_filename_period_candidate")))
                or int(
                    bool(
                        projected_events.get(
                            str(row.get("event_id")), (None, None, None)
                        )[0]
                        and str(
                            projected_events[str(row.get("event_id"))][0]
                        )[:4]
                        != str(row.get("source_period_label") or "")
                    )
                ),
                int(
                    projected_duplicates.get(
                        str(row.get("event_id")),
                        (row.get("duplicate_canonical_sheet_candidate"), bool(row.get("is_source_copy_candidate"))),
                    )[1]
                ),
                row.get("duplicate_group_id"),
                row.get("duplicate_group_size"),
                row.get("duplicate_status"),
                projected_duplicates.get(
                    str(row.get("event_id")),
                    (row.get("duplicate_canonical_sheet_candidate"), bool(row.get("is_source_copy_candidate"))),
                )[0],
                row.get("venue_id"),
                row.get("venue_name"),
                row.get("producer_id"),
                row.get("producer_name"),
                row.get("link_status"),
                row.get("link_evidence_ref"),
                row.get("link_confidence"),
                row.get("link_review_status"),
            ),
        )

    for row in doc.get("test_rows", []):
        if not isinstance(row, dict):
            continue
        header_row = _is_testing_header_row(row)
        normalized, mapping_status = _project_substance_label(
            row.get("substance_raw"),
            row.get("substance_normalized_candidate"),
            row.get("substance_map_status"),
            header_row=header_row,
        )
        row_status = "repeated_header" if header_row else row.get("row_status")
        conn.execute(
            "INSERT INTO testeo_filas_fuente("
            "test_id, event_id, source_sheet_name, source_row, row_status, substance_raw, "
            "substance_normalized_candidate, substance_map_status, format_raw, test_1_raw, "
            "result_1_raw, test_2_raw, result_2_raw, test_3_raw, result_3_raw, test_4_raw, "
            "result_4_raw, extra_1_raw, source_duplicate_group_id, source_duplicate_status, "
            "interpretation_policy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("test_id"),
                row.get("event_id"),
                str(row.get("source_sheet_name", "")),
                int(row.get("source_row") or 0),
                row_status,
                row.get("substance_raw"),
                normalized,
                mapping_status,
                row.get("format_raw"),
                row.get("test_1_raw"),
                row.get("result_1_raw"),
                row.get("test_2_raw"),
                row.get("result_2_raw"),
                row.get("test_3_raw"),
                row.get("result_3_raw"),
                row.get("test_4_raw"),
                row.get("result_4_raw"),
                row.get("extra_1_raw"),
                row.get("source_duplicate_group_id"),
                row.get("source_duplicate_status"),
                row.get("interpretation_policy"),
            ),
        )

    for row in doc.get("observations", []):
        if not isinstance(row, dict):
            continue
        conn.execute(
            "INSERT INTO testeo_observaciones_fuente("
            "observation_id, test_id, event_id, source_sheet_name, source_row, "
            "observation_ordinal, substance_raw, substance_normalized_candidate, reagent_raw, "
            "reagent_normalized_candidate, reagent_map_status, result_raw, "
            "result_normalized_candidate, result_map_status, observation_status, "
            "interpretation_policy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("observation_id"),
                row.get("test_id"),
                row.get("event_id"),
                str(row.get("source_sheet_name", "")),
                int(row.get("source_row") or 0),
                int(row.get("observation_ordinal") or 0),
                row.get("substance_raw"),
                projected_rows.get(str(row.get("test_id")), (row.get("substance_normalized_candidate"), row.get("substance_map_status"), False))[0],
                row.get("reagent_raw"),
                _project_reagent_label(
                    row.get("reagent_raw"),
                    row.get("reagent_normalized_candidate"),
                    row.get("reagent_map_status"),
                    header_row=projected_rows.get(str(row.get("test_id")), (None, "", False))[2],
                )[0],
                _project_reagent_label(
                    row.get("reagent_raw"),
                    row.get("reagent_normalized_candidate"),
                    row.get("reagent_map_status"),
                    header_row=projected_rows.get(str(row.get("test_id")), (None, "", False))[2],
                )[1],
                row.get("result_raw"),
                row.get("result_normalized_candidate"),
                row.get("result_map_status"),
                row.get("observation_status"),
                row.get("interpretation_policy"),
            ),
        )

    for (raw_label, normalized_id, mapping_status), count in sorted(
        substance_counts.items(), key=lambda item: item[0][0]
    ):
        conn.execute(
            "INSERT INTO testeo_mapa_sustancias(raw_label, count, normalized_id, mapping_status) "
            "VALUES (?,?,?,?)",
            (
                raw_label,
                count,
                normalized_id,
                mapping_status,
            ),
        )

    for (raw_label, normalized_id, mapping_status), count in sorted(
        reagent_counts.items(), key=lambda item: item[0][0]
    ):
        conn.execute(
            "INSERT INTO testeo_mapa_reactivos(raw_label, count, normalized_id, mapping_status) "
            "VALUES (?,?,?,?)",
            (
                raw_label,
                count,
                normalized_id,
                mapping_status,
            ),
        )

    for row in doc.get("link_queue", []):
        if not isinstance(row, dict):
            continue
        conn.execute(
            "INSERT INTO testeo_enlaces_revision("
            "link_id, event_id, source_sheet_name, target_kind, target_id, target_name, "
            "relation_type, evidence_ref, confidence, status, review_status, "
            "not_inferred_from_sheet_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("link_id"),
                row.get("event_id"),
                str(row.get("source_sheet_name", "")),
                str(row.get("target_kind", "")),
                row.get("target_id"),
                row.get("target_name"),
                str(row.get("relation_type", "")),
                row.get("evidence_ref"),
                row.get("confidence"),
                str(row.get("status", "unlinked")),
                str(row.get("review_status", "pending_human_link")),
                int(bool(row.get("not_inferred_from_sheet_name", True))),
            ),
        )


def _rescatar_acumulativas(path: Path) -> dict[str, list[tuple]]:
    """Las filas de terreno que un rebuild no debe destruir.

    `build_rd_db()` borra el archivo y lo reescribe: eso esta bien para lo
    derivado de fuentes canonicas, que se puede volver a derivar, y seria
    destructivo para `registros_testeo`, `atenciones` y `encuestas`, que son
    registros de terreno que no existen en ninguna otra parte.

    Hasta el 2026-09-05 el problema se evitaba teniendolas en otro archivo,
    `data/rd_datos.db`. El operador pidio una sola base, asi que se rescatan
    aqui y se reponen despues del `CREATE`. Si `rd.db` todavia no las tiene y
    la DB previa si, se traen de ahi una sola vez: esa es la migracion.

    Devuelve por tabla la lista de filas, con las columnas en el orden en que
    el archivo las declara, para que la reinsercion no dependa del schema
    nuevo coincidiendo por posicion.
    """
    from . import datos as _datos

    rescatadas: dict[str, list[tuple]] = {}
    columnas: dict[str, list[str]] = {}
    # Lo que la app de muestras escribe se acumula igual que los registros de
    # terreno: una muestra fotografiada en una mesa no se puede volver a
    # derivar de ninguna fuente canonica.
    tablas = tuple(_datos.TABLAS_ACUMULATIVAS) + ("muestras", "muestra_resultados")
    for origen in (path, _datos.LEGACY_DB_PATH):
        if not origen.exists():
            continue
        conn = sqlite3.connect(f"file:{origen}?mode=ro", uri=True)
        try:
            for tabla in tablas:
                if rescatadas.get(tabla):
                    continue  # ya vino de una fuente anterior; no se duplica
                try:
                    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tabla})")]
                    if not cols:
                        continue
                    filas = list(conn.execute(f'SELECT * FROM "{tabla}"'))
                except sqlite3.DatabaseError:
                    continue
                if filas:
                    rescatadas[tabla] = filas
                    columnas[tabla] = cols
        finally:
            conn.close()
    _RESCATE_COLUMNAS.clear()
    _RESCATE_COLUMNAS.update(columnas)
    return rescatadas


_RESCATE_COLUMNAS: dict[str, list[str]] = {}


def _reponer_acumulativas(
    conn: sqlite3.Connection, rescatadas: dict[str, list[tuple]]
) -> None:
    """Crea las tablas acumulativas y devuelve sus filas al archivo nuevo."""
    from . import datos as _datos

    conn.executescript(_datos.SCHEMA_ACUMULATIVO)
    conn.executescript(_SCHEMA_MUESTRAS)
    for tabla, filas in rescatadas.items():
        cols = _RESCATE_COLUMNAS.get(tabla)
        if not cols or not filas:
            continue
        marcas = ",".join("?" for _ in cols)
        nombres = ",".join(f'"{c}"' for c in cols)
        conn.executemany(
            f'INSERT INTO "{tabla}" ({nombres}) VALUES ({marcas})', filas
        )


def _clave(texto: str) -> str:
    """Comparable sin acentos, espacios ni puntuacion.

    `Techno Youth`, `TECHNOYOUTH` y `technoyouth` son la misma productora
    escrita de tres formas en el cuaderno 2025, y `Explicito` y `Explícito` son
    la misma palabra. Comparar en crudo pierde esos vinculos en silencio.
    """
    limpio = unicodedata.normalize("NFKD", texto or "")
    limpio = limpio.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", limpio.lower())


# Tres letras es el piso: por debajo, un alias como `TY` aparece dentro de
# cualquier palabra y ata eventos que no le corresponden.
_MIN_ALIAS = 3


def _formas_por_productora(conn: sqlite3.Connection) -> dict[str, set[str]]:
    """Cada productora con todas las formas en que se la puede nombrar."""
    formas: dict[str, set[str]] = {}
    for slug, nombre, aliases in conn.execute(
        "SELECT slug, nombre, aliases FROM productoras"
    ):
        try:
            lista = json.loads(aliases or "[]")
        except (TypeError, ValueError):
            lista = []
        candidatas = {_clave(x) for x in ([slug, nombre] + list(lista)) if x}
        formas[slug] = {c for c in candidatas if len(c) >= _MIN_ALIAS}
    return formas


def _mesa_desde_etiqueta(etiqueta: str) -> tuple[int | None, str | None]:
    """La mesa de testeo, si el nombre de la hoja la nombra.

    El cuaderno 2025 trae hojas como `Fiesta Dame 504 mesa 1` y `mesa 2`: en un
    mismo evento hubo mas de una mesa y cada una llevo su planilla. Sin esto,
    dos mesas del mismo evento se leen como dos eventos distintos.
    """
    m = re.search(r"\bmesa\s*(\d+)\b", etiqueta or "", flags=re.IGNORECASE)
    if not m:
        return None, None
    return int(m.group(1)), m.group(0).strip()


def _vincular_eventos_de_testeo(conn: sqlite3.Connection) -> dict[str, int]:
    """Ata los 42 eventos del cuaderno 2025 al catalogo de productoras.

    El vinculo sale del nombre del evento: el cuaderno los llama `Cachorros
    0407`, `DAME 0911 A`, `Technoyouth 1209`. El nombre de la productora viene
    dentro del nombre del evento, asi que se busca cada alias conocido dentro de
    la etiqueta normalizada.

    Lo que NO hace, a proposito:

    - No inventa productoras. Un evento cuyo nombre no contiene ningun alias
      conocido queda sin vinculo, y eso es informacion: son productoras que
      faltan en el catalogo, no un fallo del emparejador.
    - No decide el rol. Si un evento nombra a dos productoras, las dos entran
      como `sin_determinar`: cual es anfitriona y cual colabora es un dato que
      se averigua.
    - No aprueba nada. Cada fila entra `pendiente_revision_humana`, que es la
      compuerta que `data/rd_fuentes/README.md` exige antes de publicar.

    El venue se propone solo si la productora tiene uno marcado `preferido`, y
    entra como `SUPUESTO` con origen `habitual_de_productora`: que una
    productora suela tocar en un lugar no prueba que esa fecha haya sido ahi.
    """
    formas = _formas_por_productora(conn)
    habituales: dict[str, tuple[str | None, str]] = {}
    for slug, venue_id, venue_nombre in conn.execute(
        "SELECT productora_slug, venue_id, venue_nombre FROM productora_venues"
        " WHERE preferido = 1"
    ):
        habituales.setdefault(slug, (venue_id, venue_nombre))

    cuenta = {"eventos": 0, "vinculos": 0, "sin_vinculo": 0, "venues": 0, "mesas": 0}

    for event_id, etiqueta in conn.execute(
        "SELECT event_id, event_label_candidate FROM testeo_eventos_fuente"
    ):
        cuenta["eventos"] += 1
        clave = _clave(etiqueta)
        encontradas = sorted(
            {
                (slug, forma)
                for slug, alias in formas.items()
                for forma in alias
                if forma and forma in clave
            },
            key=lambda par: (-len(par[1]), par[0]),
        )
        # Una productora puede coincidir por varios alias; se conserva el mas
        # largo, que es el mas especifico.
        mejor_por_slug: dict[str, str] = {}
        for slug, forma in encontradas:
            mejor_por_slug.setdefault(slug, forma)

        if not mejor_por_slug:
            cuenta["sin_vinculo"] += 1
        for slug, forma in mejor_por_slug.items():
            # Con una sola productora nombrada no se afirma que sea la
            # anfitriona: solo que el nombre la nombra.
            conn.execute(
                "INSERT OR IGNORE INTO evento_productoras"
                "(evento_ref, evento_origen, productora_slug, rol, metodo,"
                " evidencia, confianza, estado_revision)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    "testeo_2025",
                    slug,
                    "sin_determinar",
                    "DERIVADO",
                    f"alias '{forma}' dentro de la etiqueta '{etiqueta}'",
                    "alta" if len(forma) >= 6 else "media",
                    "pendiente_revision_humana",
                ),
            )
            cuenta["vinculos"] += 1

            venue = habituales.get(slug)
            if venue is not None:
                venue_id, venue_nombre = venue
                conn.execute(
                    "INSERT OR IGNORE INTO evento_venues"
                    "(evento_ref, evento_origen, venue_id, venue_nombre,"
                    " metodo, origen, confianza, estado_revision)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (
                        event_id,
                        "testeo_2025",
                        venue_id,
                        venue_nombre,
                        "SUPUESTO",
                        "habitual_de_productora",
                        "baja",
                        "pendiente_revision_humana",
                    ),
                )
                cuenta["venues"] += 1

        numero, texto = _mesa_desde_etiqueta(etiqueta)
        if texto is not None:
            conn.execute(
                "INSERT OR IGNORE INTO mesas_testeo"
                "(evento_ref, evento_origen, numero, etiqueta, origen)"
                " VALUES (?,?,?,?,?)",
                (event_id, "testeo_2025", numero, texto, "etiqueta_2025"),
            )
            cuenta["mesas"] += 1

    # El estado de enlace de la tabla de origen deja de mentir: ya no es
    # `unlinked` cuando hay un candidato con evidencia.
    conn.execute(
        "UPDATE testeo_eventos_fuente SET link_status = 'candidate_from_label',"
        " link_review_status = 'pendiente_revision_humana',"
        " link_confidence = 'derivado_de_etiqueta'"
        " WHERE event_id IN (SELECT evento_ref FROM evento_productoras"
        "                    WHERE evento_origen = 'testeo_2025')"
    )
    return cuenta


def build_rd_db(
    db_path: str | Path | None = None,
    *,
    productoras_dir: str | Path | None = None,
    venues_dir: str | Path | None = None,
) -> Path:
    """(Re)construye la DB RD desde las fuentes canonicas. Idempotente:
    borra el archivo previo y lo reescribe entero. Devuelve la ruta.

    productoras_dir/venues_dir permiten apuntar a directorios de prueba (los
    tests cargan una productora sintetica con venue preferido sin tocar el
    store real). Por defecto usan los canonicos del repo.
    """
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    prod_dir = Path(productoras_dir) if productoras_dir is not None else _PRODUCTORAS_DIR
    ven_dir = Path(venues_dir) if venues_dir is not None else _VENUES_DIR
    path.parent.mkdir(parents=True, exist_ok=True)
    # Antes de borrar nada: lo acumulado no se puede volver a derivar.
    acumuladas = _rescatar_acumulativas(path)
    if path.exists():
        path.unlink()

    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        conn.executescript(_SCHEMA_RELACIONES)
        _reponer_acumulativas(conn, acumuladas)

        # meta + reactivos
        reactivos_doc = json.loads(_REACTIVOS_JSON.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO meta(clave, valor) VALUES (?, ?)",
            ("reactivos_disclaimer", reactivos_doc.get("disclaimer", "")),
        )
        for i, r in enumerate(reactivos_doc.get("reacciones", []), start=1):
            conn.execute(
                "INSERT INTO reactivos(id, reactivo, familia, reaccion, hex) VALUES (?,?,?,?,?)",
                (i, r["reactivo"], r["familia"], r["reaccion"], r["hex"]),
            )

        _insert_candidate_registries(conn)

        # packs + inclusiones
        inc_id = 0
        for orden, (pid, p) in enumerate(_load_packs().items(), start=1):
            conn.execute(
                "INSERT INTO packs(id, nombre, label, descripcion, precio, voluntarios, m2, stands, orden) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, p["nombre"], p["label"], p["desc"], int(p["precio"]),
                 int(p["voluntarios"]), int(p["m2"]), int(p["stands"]), orden),
            )
            for j, texto in enumerate(p.get("inclusiones", []), start=1):
                inc_id += 1
                conn.execute(
                    "INSERT INTO inclusiones(id, pack_id, texto, orden) VALUES (?,?,?,?)",
                    (inc_id, pid, texto, j),
                )

        # suplementos (flyers del contenido canonico)
        sup_doc = json.loads(_SUPLEMENTOS_JSON.read_text(encoding="utf-8"))
        for f in sup_doc.get("flyers", []):
            conn.execute(
                "INSERT INTO suplementos(id, titulo, tag, accent, descripcion, section_title, items) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    str(f.get("id")),
                    str(f.get("title", "")),
                    _astext(f.get("tag")),
                    _astext(f.get("accent")),
                    _astext(f.get("description")),
                    _astext(f.get("section_title")),
                    json.dumps(f.get("items", []), ensure_ascii=False),
                ),
            )

        # venues canonicos (knowledge/venues/*.yaml)
        venue_ids: set[str] = set()
        if ven_dir.exists():
            for vf in sorted(ven_dir.glob("*.yaml")):
                v = _load_yaml(vf)
                if not v:
                    continue
                vid = str(v.get("id", vf.stem))
                venue_ids.add(vid)
                rs = v.get("recommended_service", {}) or {}
                conn.execute(
                    "INSERT OR REPLACE INTO venues(id, nombre, tipo, escala, capacidad, "
                    "preset_reco, voluntarios_min, requisitos, notas) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        vid,
                        str(v.get("name", vf.stem)),
                        v.get("type"),
                        v.get("scale_default"),
                        v.get("capacity_bucket"),
                        v.get("recommended_preset") or rs.get("default_preset"),
                        rs.get("volunteers_min") or (v.get("requirements_defaults", {}) or {}).get("volunteers_min"),
                        json.dumps(v.get("requirements_defaults", {}), ensure_ascii=False),
                        json.dumps(v.get("notes", []), ensure_ascii=False),
                    ),
                )

        # productoras conocidas (store) + tablas hijas: tipos, venues, logos
        tipo_id = vnk_id = logo_id = prodev_id = 0
        if prod_dir.exists():
            for pf in sorted(prod_dir.glob("*.json")):
                try:
                    d = json.loads(pf.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                slug = pf.stem
                conn.execute(
                    "INSERT OR REPLACE INTO productoras(slug, nombre, instagram, aliases, confirmado, notas) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        slug,
                        str(d.get("name", slug)),
                        d.get("instagram"),
                        json.dumps(d.get("aliases", []), ensure_ascii=False),
                        d.get("confirmed"),
                        d.get("notes"),
                    ),
                )
                # tipos de fecha (vocabulario controlado)
                from .vocab import normalize_tipos

                for tipo in normalize_tipos(d.get("tipos_fecha")):
                    tipo_id += 1
                    conn.execute(
                        "INSERT INTO productora_tipos(id, productora_slug, tipo) VALUES (?,?,?)",
                        (tipo_id, slug, tipo),
                    )
                # venues (anotados; preferido = el reiterado); venue_id si matchea uno canonico
                for v in d.get("venues", []) or []:
                    vnk_id += 1
                    vid = v.get("venue_id")
                    conn.execute(
                        "INSERT INTO productora_venues(id, productora_slug, venue_nombre, venue_id, "
                        "preferido, estado, notas) VALUES (?,?,?,?,?,?,?)",
                        (
                            vnk_id, slug,
                            str(v.get("nombre", vid or "")),
                            vid if vid in venue_ids else None,
                            1 if v.get("preferido") else 0,
                            v.get("estado", "confirmado"),
                            v.get("notas"),
                        ),
                    )
                # logos (enlace a knowledge/logos)
                for lg in d.get("logos", []) or []:
                    logo_id += 1
                    conn.execute(
                        "INSERT INTO productora_logos(id, productora_slug, logo_id, knowledge, estado) "
                        "VALUES (?,?,?,?,?)",
                        (logo_id, slug, lg.get("id"), lg.get("knowledge"), lg.get("estado")),
                    )
                # eventos REALES de la productora (distintos de las plantillas
                # de cotizacion: ver el comentario del esquema). Se copian tal
                # cual, incluida la fuente -- si un campo no esta, queda NULL,
                # nunca se rellena con un supuesto.
                for ev in d.get("eventos", []) or []:
                    prodev_id += 1
                    fuentes_primarias, sin_fuente_primaria = _event_source_gate(
                        ev.get("fuente")
                    )
                    conn.execute(
                        "INSERT INTO productora_eventos(id, productora_slug, nombre, fecha, "
                        "venue, estado, fuente, fuentes_primarias, sin_fuente_primaria) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            prodev_id, slug,
                            str(ev.get("nombre", "")),
                            ev.get("fecha"),
                            ev.get("venue"),
                            ev.get("estado"),
                            ev.get("fuente"),
                            fuentes_primarias,
                            sin_fuente_primaria,
                        ),
                    )

        # eventos (jsons con forma de evento) + pack sugerido por voluntarios
        for i, (rel, d) in enumerate(_iter_evento_sources(), start=1):
            vol = d.get("voluntarios")
            conn.execute(
                "INSERT INTO eventos(id, nombre, fuente, duracion_horas, voluntarios, "
                "asistentes_estimados, incluye_testeo, masivo, ubicacion, pack_sugerido, notas) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    i,
                    str(d.get("nombre", rel)),
                    rel,
                    d.get("duracion_horas"),
                    vol,
                    d.get("asistentes_estimados"),
                    1 if d.get("incluye_testeo") else 0,
                    1 if d.get("masivo") else 0,
                    d.get("ubicacion"),
                    _pack_por_voluntarios(vol),
                    d.get("notas"),
                ),
            )

        # Imported historical testing evidence stays separate from canonical
        # tables and is marked for human review.
        testing_doc = _load_testing_evidence()
        if testing_doc is not None:
            _insert_testing_evidence(conn, testing_doc)
        # Con las productoras, los venues y la evidencia de testeo ya cargados,
        # se atan: es lo ultimo porque necesita todo lo anterior en la misma
        # transaccion.
        _vincular_eventos_de_testeo(conn)

        conn.commit()
    finally:
        conn.close()
    return path


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Abre la DB (la construye si no existe). Filas como dict-like (Row)."""
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    if not path.exists():
        build_rd_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def reactivos_por_familia(familia: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Reacciones cuya familia contiene `familia` (case-insensitive).
    Ej: 'MDMA' -> las filas de Marquis/Mecke/... para MDMA."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT reactivo, familia, reaccion, hex FROM reactivos "
            "WHERE lower(familia) LIKE ? ORDER BY reactivo",
            (f"%{familia.lower()}%",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def reactivos_por_reactivo(reactivo: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Todas las reacciones de un reactivo dado (Marquis, Mecke, ...)."""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT reactivo, familia, reaccion, hex FROM reactivos "
            "WHERE lower(reactivo) = ? ORDER BY familia",
            (reactivo.lower(),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def packs(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Los packs de servicio con sus inclusiones anidadas, en orden."""
    conn = connect(db_path)
    try:
        out: list[dict[str, Any]] = []
        for p in conn.execute("SELECT * FROM packs ORDER BY orden").fetchall():
            d = dict(p)
            d["inclusiones"] = [
                r["texto"] for r in conn.execute(
                    "SELECT texto FROM inclusiones WHERE pack_id = ? ORDER BY orden", (d["id"],)
                ).fetchall()
            ]
            out.append(d)
        return out
    finally:
        conn.close()


def suplementos(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Los suplementos del catalogo (items deserializados)."""
    conn = connect(db_path)
    try:
        out: list[dict[str, Any]] = []
        for s in conn.execute("SELECT * FROM suplementos ORDER BY id").fetchall():
            d = dict(s)
            d["items"] = json.loads(d["items"]) if d.get("items") else []
            out.append(d)
        return out
    finally:
        conn.close()


def productoras(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Promotoras conocidas (aliases deserializados)."""
    conn = connect(db_path)
    try:
        out: list[dict[str, Any]] = []
        for p in conn.execute("SELECT * FROM productoras ORDER BY slug").fetchall():
            d = dict(p)
            d["aliases"] = json.loads(d["aliases"]) if d.get("aliases") else []
            out.append(d)
        return out
    finally:
        conn.close()


def eventos(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Eventos registrados con su pack sugerido por voluntarios."""
    conn = connect(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM eventos ORDER BY id").fetchall()]
    finally:
        conn.close()


def venues(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Venues canonicos (requisitos y notas deserializados)."""
    conn = connect(db_path)
    try:
        out: list[dict[str, Any]] = []
        for v in conn.execute("SELECT * FROM venues ORDER BY nombre").fetchall():
            d = dict(v)
            d["requisitos"] = json.loads(d["requisitos"]) if d.get("requisitos") else {}
            d["notas"] = json.loads(d["notas"]) if d.get("notas") else []
            out.append(d)
        return out
    finally:
        conn.close()


def productora(slug: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Perfil completo de una productora: datos base + tipos de fecha + venues
    (con el preferido marcado) + logos. None si no existe."""
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT * FROM productoras WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["aliases"] = json.loads(d["aliases"]) if d.get("aliases") else []
        d["tipos_fecha"] = [
            r["tipo"] for r in conn.execute(
                "SELECT tipo FROM productora_tipos WHERE productora_slug = ?", (slug,)
            ).fetchall()
        ]
        d["venues"] = [
            dict(r) for r in conn.execute(
                "SELECT venue_nombre, venue_id, preferido, estado, notas FROM productora_venues "
                "WHERE productora_slug = ? ORDER BY preferido DESC, venue_nombre", (slug,)
            ).fetchall()
        ]
        d["venue_preferido"] = next((v["venue_nombre"] for v in d["venues"] if v["preferido"]), None)
        d["logos"] = [
            dict(r) for r in conn.execute(
                "SELECT logo_id, knowledge, estado FROM productora_logos WHERE productora_slug = ?", (slug,)
            ).fetchall()
        ]
        return d
    finally:
        conn.close()


def productoras_por_tipo(tipo: str, db_path: str | Path | None = None) -> list[str]:
    """Slugs de productoras que hacen fechas de un tipo dado (vocab canonico)."""
    from .vocab import normalize_tipo

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT productora_slug FROM productora_tipos WHERE tipo = ? ORDER BY productora_slug",
            (normalize_tipo(tipo),),
        ).fetchall()
        return [r["productora_slug"] for r in rows]
    finally:
        conn.close()


def disclaimer(db_path: str | Path | None = None) -> str:
    """El disclaimer canonico del testeo presuntivo (tabla meta)."""
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT valor FROM meta WHERE clave = 'reactivos_disclaimer'").fetchone()
        return row["valor"] if row else ""
    finally:
        conn.close()


def testing_evidence_summary(db_path: str | Path | None = None) -> dict[str, Any]:
    """Summarize historical evidence without exposing rows in the public panel.

    Counts are descriptive. Observations preserve source wording, but this
    query does not claim identity, purity, dose, or safety.
    """
    conn = connect(db_path)
    try:
        source = conn.execute("SELECT * FROM testeo_fuentes ORDER BY id LIMIT 1").fetchone()
        if source is None:
            return {"available": False, "reason": "no_testing_evidence"}
        counts = {
            "source_sheets": conn.execute("SELECT COUNT(*) FROM testeo_hojas").fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM testeo_eventos_fuente").fetchone()[0],
            "test_rows": conn.execute("SELECT COUNT(*) FROM testeo_filas_fuente").fetchone()[0],
            "observations": conn.execute("SELECT COUNT(*) FROM testeo_observaciones_fuente").fetchone()[0],
            "pending_links": conn.execute(
                "SELECT COUNT(*) FROM testeo_enlaces_revision "
                "WHERE review_status = 'pending_human_link'"
            ).fetchone()[0],
            "exact_duplicate_rows_excluded_from_aggregate": conn.execute(
                "SELECT COUNT(*) FROM testeo_eventos_fuente "
                "WHERE is_source_copy_candidate = 1 AND duplicate_group_size > 1"
            ).fetchone()[0],
            "unresolved_substances": conn.execute(
                "SELECT COUNT(*) FROM testeo_mapa_sustancias "
                "WHERE mapping_status IN ("
                "'unresolved_candidate', 'misplaced_or_unresolved_candidate', "
                "'substance_or_format_unresolved', 'explicit_unknown')"
            ).fetchone()[0],
            "unresolved_reagents": conn.execute(
                "SELECT COUNT(*) FROM testeo_mapa_reactivos "
                "WHERE mapping_status IN ('unresolved_candidate', 'possible_typo_candidate')"
            ).fetchone()[0],
        }
        return {
            "available": True,
            "status": source["status"],
            "source": {
                "file_name": source["archivo"],
                "sha256": source["sha256"],
                "period": source["periodo"],
                "formula_count": source["formula_count"],
            },
            "counts": counts,
            "public_claims_allowed": False,
        }
    finally:
        conn.close()


def research_candidate_summary(db_path: str | Path | None = None) -> dict[str, Any]:
    """Summarize association candidates without upgrading them to claims."""
    conn = connect(db_path)
    try:
        return {
            "sources": conn.execute("SELECT COUNT(*) FROM rd_fuentes_registro").fetchone()[0],
            "entities": conn.execute("SELECT COUNT(*) FROM rd_entidades_candidatas").fetchone()[0],
            "reagents": conn.execute("SELECT COUNT(*) FROM rd_reactivos_candidatos").fetchone()[0],
            "reaction_patterns": conn.execute("SELECT COUNT(*) FROM rd_reacciones_candidatas").fetchone()[0],
            "relations": conn.execute("SELECT COUNT(*) FROM rd_relaciones_candidatas").fetchone()[0],
            "references": conn.execute("SELECT COUNT(*) FROM rd_relacion_referencias").fetchone()[0],
            "joined_observations": conn.execute(
                "SELECT COUNT(*) FROM v_testeo_observaciones_reactivo"
            ).fetchone()[0],
            "public_claims_allowed": False,
        }
    finally:
        conn.close()


def testing_observations(
    *,
    event_id: str | None = None,
    reagent_id: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return observation rows for internal review without inferring links."""
    conn = connect(db_path)
    try:
        clauses: list[str] = []
        params: list[str] = []
        if event_id:
            clauses.append("event_id = ?")
            params.append(event_id)
        if reagent_id:
            clauses.append("reagent_normalized_candidate = ?")
            params.append(reagent_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = conn.execute(
            "SELECT * FROM testeo_observaciones_fuente" + where
            + " ORDER BY event_id, source_row, observation_ordinal",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def lookup_familia(familia: str, db_path: str | Path | None = None) -> dict[str, Any]:
    """Consulta de operador en terreno: para una familia de sustancia devuelve el
    panel de reactivos que la marcan + que packs incluyen servicio de testeo +
    el disclaimer presuntivo. Es el JOIN que justifica la DB sobre JSON planos:
    cruza reactivos (colorimetria) con packs (servicio) en una sola llamada.

    'Incluye testeo' se detecta en las inclusiones del pack (palabra 'testeo'),
    derivado del texto canonico -- no un flag aparte que pueda desincronizarse.
    """
    conn = connect(db_path)
    try:
        reacts = [
            dict(r) for r in conn.execute(
                "SELECT reactivo, familia, reaccion, hex FROM reactivos "
                "WHERE lower(familia) LIKE ? ORDER BY reactivo",
                (f"%{familia.lower()}%",),
            ).fetchall()
        ]
        packs_testeo = [
            dict(p) for p in conn.execute(
                "SELECT DISTINCT p.id, p.nombre, p.precio FROM packs p "
                "JOIN inclusiones i ON i.pack_id = p.id "
                "WHERE lower(i.texto) LIKE '%testeo%' ORDER BY p.orden"
            ).fetchall()
        ]
        disc_row = conn.execute(
            "SELECT valor FROM meta WHERE clave = 'reactivos_disclaimer'"
        ).fetchone()
        return {
            "familia": familia,
            "reactivos": reacts,
            "packs_con_testeo": packs_testeo,
            "disclaimer": disc_row["valor"] if disc_row else "",
        }
    finally:
        conn.close()
