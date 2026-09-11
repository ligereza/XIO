/* XIO RD Field — local-first prototype. No network calls, no chemical inference. */

const STORAGE_KEY = "xio-rd-field-state-v0.1";
const MODEL_VERSION = "visual-retrieval-v0.1";
const substanceChoices = ["MDMA", "Cocaína", "Ketamina", "Cannabis", "Opioide", "Benzodiacepina", "Desconocido", "Otro"];
const formatChoices = ["Polvo", "Comprimido", "Cristal", "Papel / blotter", "Líquido", "Planta", "Residuo", "Otro"];
const colorChoices = ["Blanco", "Beige", "Amarillo", "Naranja", "Rojo", "Rosado", "Verde", "Azul", "Morado", "Marrón", "Negro", "Transparente", "Multicolor", "Desconocido"];
const shapeChoices = ["Redondo", "Cuadrado", "Irregular", "Lámina", "Granulado", "Cristalino", "Líquido", "Desconocido"];
const textureChoices = ["Polvoriento", "Compacto", "Húmedo", "Granulado", "Cristalino", "Vegetal", "Desconocido"];
const reagentChoices = ["Marquis", "Mecke", "Mandelin", "Ehrlich", "Tira de fentanilo", "pH", "FTIR", "Otro / método local"];
const resultChoices = ["Sin reacción", "Cambio compatible", "Positivo presuntivo", "Negativo presuntivo", "No concluyente", "No aplica"];

const ui = {
  filter: "all",
  search: "",
  pendingPhotoTarget: { type: "sample" },
  toastTimer: null,
  timer: null,
  remote: { connected: false, events: [], lastBootstrapAt: null, error: "" }
};

function uid(prefix) {
  const random = globalThis.crypto?.randomUUID?.();
  return `${prefix}-${random || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`}`;
}

function isoNow() { return new Date().toISOString(); }

function formatDate(value, includeTime = true) {
  if (!value) return "Sin registrar";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sin registrar";
  return new Intl.DateTimeFormat("es-CL", includeTime ? { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" } : { day: "2-digit", month: "short", year: "numeric" }).format(date).replace(".", "");
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

function clone(value) { return JSON.parse(JSON.stringify(value)); }

function svgPhoto(color, label) {
  const safe = color || "#d6d6ca";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="720" viewBox="0 0 960 720"><rect width="960" height="720" fill="#e9e9e1"/><rect x="48" y="48" width="864" height="624" rx="22" fill="#f6f5ef" stroke="#c8cec7" stroke-width="4"/><ellipse cx="480" cy="380" rx="220" ry="135" fill="${safe}" opacity=".95"/><ellipse cx="415" cy="340" rx="76" ry="44" fill="#ffffff" opacity=".2"/><text x="480" y="590" text-anchor="middle" fill="#3a4d52" font-family="Arial, sans-serif" font-size="28" letter-spacing="4">${label}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function makeTest(overrides = {}) {
  return {
    id: uid("test"),
    method: "Colorimetría",
    reagent: "Marquis",
    startedAt: null,
    endedAt: null,
    elapsedSeconds: 0,
    observation: "",
    reactionColor: "",
    reactionEvolution: "",
    operatorResult: "",
    interpretation: "",
    evidence: [],
    status: "draft",
    ...overrides
  };
}

function makeSample(eventId, sequence, overrides = {}) {
  const createdAt = overrides.createdAt || isoNow();
  return {
    id: uid("sample"),
    eventId,
    code: `XIO-${new Date(createdAt).toISOString().slice(0, 10).replaceAll("-", "")}-${String(sequence).padStart(3, "0")}`,
    createdAt,
    updatedAt: createdAt,
    synthetic: true,
    declaredSubstance: "",
    declaredOther: "",
    format: "",
    appearance: { color: "", shape: "", texture: "", brand: "", notes: "" },
    photo: null,
    visualProposal: null,
    humanCorrection: null,
    tests: [],
    workflowStatus: "draft",
    syncStatus: "pending",
    remoteSampleId: null,
    audit: [{ at: createdAt, action: "sample_created", actor: "operator" }],
    ...overrides
  };
}

function createSeedState() {
  const eventId = uid("event");
  const sampleOne = makeSample(eventId, 1, {
    code: "XIO-20260905-001",
    declaredSubstance: "MDMA",
    format: "Comprimido",
    appearance: { color: "Rosado", shape: "Redondo", texture: "Compacto", brand: "Sin marca visible", notes: "Objeto inocuo de demostración; no corresponde a una muestra real." },
    photo: { id: uid("photo"), filename: "demo-comprimido.svg", mimeType: "image/svg+xml", dataUrl: svgPhoto("#df9a9c", "OBJETO SINTÉTICO"), capturedAt: "2026-09-05T18:12:14.000Z", synthetic: true, sha256: "demo-sha256-001" },
    visualProposal: { colorName: "Rosado", shapeName: "Redondo", brightness: 0.72, saturation: 0.34, modelVersion: MODEL_VERSION, createdAt: "2026-09-05T18:12:15.000Z", status: "proposal" },
    humanCorrection: { color: "Rosado", shape: "Redondo", reviewedAt: "2026-09-05T18:13:02.000Z", reviewer: "operator" },
    tests: [
      makeTest({ id: "test-demo-1", method: "Colorimetría", reagent: "Marquis", startedAt: "2026-09-05T18:14:00.000Z", endedAt: "2026-09-05T18:14:34.000Z", elapsedSeconds: 34, reactionColor: "Amarillo → marrón", reactionEvolution: "Cambio gradual en 34 s", observation: "Demostración visual con objeto inocuo.", operatorResult: "No concluyente", interpretation: "Solo demo de registro; no hay lectura química.", status: "done" }),
      makeTest({ id: "test-demo-2", method: "Tira", reagent: "pH", startedAt: "2026-09-05T18:15:00.000Z", endedAt: "2026-09-05T18:15:21.000Z", elapsedSeconds: 21, reactionColor: "Sin cambio visible", reactionEvolution: "Estable", observation: "Segunda prueba sintética para demostrar unidad múltiple.", operatorResult: "No aplica", interpretation: "Dato de demostración.", status: "done" })
    ],
    workflowStatus: "review"
  });
  const sampleTwo = makeSample(eventId, 2, {
    code: "XIO-20260905-002",
    declaredSubstance: "Desconocido",
    format: "Polvo",
    appearance: { color: "Blanco", shape: "Irregular", texture: "Polvoriento", brand: "", notes: "Demo: pendiente de revisión humana." },
    tests: [makeTest({ id: "test-demo-3", reagent: "Mecke", observation: "Pendiente de observar.", status: "draft" })],
    workflowStatus: "testing"
  });
  return {
    schemaVersion: "rd-field-v0.1",
    savedAt: isoNow(),
    meta: { sequence: 2, syntheticDemo: true },
    events: [
      { id: eventId, code: "RD-0509", name: "Turno de demostración", venue: "Mesa local · sin ubicación", scheduledAt: "2026-09-05T18:00:00.000Z", startedAt: "2026-09-05T18:07:00.000Z", status: "active", synthetic: true, createdAt: "2026-09-05T17:55:00.000Z" }
    ],
    samples: [sampleOne, sampleTwo],
    selectedEventId: eventId,
    selectedSampleId: sampleOne.id
  };
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && Array.isArray(parsed.events) && Array.isArray(parsed.samples)) return parsed;
    }
  } catch (error) {
    console.warn("No se pudo leer el estado local", error);
  }
  return createSeedState();
}

const state = loadState();

function availableEvents() {
  // Production/HTTP mode is host-gated: a client may select a known event or
  // stage already cached work, but it may never invent an operational event.
  // The synthetic fixture remains visible only when opening the static demo
  // directly from file:// during UI development.
  if (window.location.protocol === "file:") return state.events.filter((event) => event.synthetic);
  return state.events.filter((event) => event.remote === true);
}

function remoteUrl(path) {
  return new URL(path, window.location.href).toString();
}

function mapRemoteEvent(raw) {
  const eventRef = String(raw?.event_id || "").trim();
  if (!eventRef) return null;
  const venue = raw.venues?.find((item) => item.venue_nombre)?.venue_nombre || "Sin lugar";
  const producer = raw.productoras?.find((item) => item.productora_slug)?.productora_slug || "";
  return {
    id: `rd-remote-${eventRef}`,
    eventRef,
    code: eventRef,
    name: raw.event_label_candidate || eventRef,
    venue,
    producer,
    scheduledAt: raw.date_iso_candidate ? `${raw.date_iso_candidate}T12:00:00.000Z` : null,
    startedAt: null,
    status: raw.event_label_status || "planned",
    synthetic: false,
    remote: true,
    createdAt: isoNow()
  };
}

function mergeRemoteEvents(rawEvents) {
  const mapped = (Array.isArray(rawEvents) ? rawEvents : []).map(mapRemoteEvent).filter(Boolean);
  const byRef = new Map(mapped.map((event) => [event.eventRef, event]));
  state.events = state.events.filter((event) => !event.remote || byRef.has(event.eventRef));
  mapped.forEach((remoteEvent) => {
    const current = state.events.find((event) => event.remote && event.eventRef === remoteEvent.eventRef);
    if (current) Object.assign(current, remoteEvent, { startedAt: current.startedAt });
    else state.events.push(remoteEvent);
  });
  const first = availableEvents()[0];
  const selected = availableEvents().find((event) => event.id === state.selectedEventId) || first;
  state.selectedEventId = selected?.id || null;
  const currentSample = eventSamples(state.selectedEventId)[0];
  state.selectedSampleId = currentSample?.id || null;
}

async function loadRemoteBootstrap() {
  if (window.location.protocol === "file:") return;
  try {
    const response = await fetch(remoteUrl("bootstrap"), { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (!Array.isArray(payload.events)) throw new Error("bootstrap RD sin eventos");
    ui.remote = { connected: true, events: payload.events, lastBootstrapAt: isoNow(), error: "" };
    mergeRemoteEvents(payload.events);
    persist("Host RD conectado · eventos cargados");
    renderAll();
  } catch (error) {
    ui.remote = { connected: false, events: [], lastBootstrapAt: null, error: String(error?.message || error) };
    refreshStatus();
  }
}

function persist(message = "Guardado local") {
  state.savedAt = isoNow();
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    document.getElementById("saveLabel").textContent = message;
  } catch (error) {
    showToast("No se pudo guardar localmente; revisa el espacio disponible.", "error");
    console.error(error);
  }
}

function getEvent(eventId = state.selectedEventId) { return state.events.find((event) => event.id === eventId) || null; }
function getSample(sampleId = state.selectedSampleId) { return state.samples.find((sample) => sample.id === sampleId) || null; }
function eventSamples(eventId = state.selectedEventId) { return state.samples.filter((sample) => sample.eventId === eventId); }

function sampleProgress(sample) {
  if (!sample) return 0;
  if (sample.tests.some((test) => test.status === "done") && sample.humanCorrection) return 4;
  if (sample.tests.length) return 3;
  if (sample.photo) return 2;
  if (sample.declaredSubstance || sample.format) return 1;
  return 1;
}

function refreshStatus() {
  const connected = navigator.onLine;
  const label = document.getElementById("connectionLabel");
  if (ui.remote.connected) {
    label.textContent = "Host RD conectado · persistencia en servidor";
    document.querySelector(".live-dot").style.background = "#74c18f";
  } else {
    label.textContent = connected ? "Conexión disponible · modo local" : "Sin conexión · guardado local";
    document.querySelector(".live-dot").style.background = connected ? "#e6c96b" : "#74c18f";
  }
}

function showToast(message, type = "success") {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.style.background = type === "error" ? "#a8463b" : "#13242c";
  toast.classList.add("show");
  clearTimeout(ui.toastTimer);
  ui.toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
}

function renderChoices(items, selected, field, variant = "") {
  return items.map((item) => `<button type="button" class="choice-chip ${variant} ${item === selected ? "selected" : ""}" data-action="choose" data-field="${field}" data-value="${escapeHTML(item)}">${escapeHTML(item)}</button>`).join("");
}

function renderSidebar() {
  const event = getEvent();
  const samples = eventSamples();
  const allTests = samples.flatMap((sample) => sample.tests);
  const events = availableEvents();
  const pending = samples.filter((sample) => sample.workflowStatus !== "complete").length;
  const corrections = samples.filter((sample) => sample.humanCorrection).length;
  document.getElementById("eventName").textContent = event?.name || "Sin evento";
  document.getElementById("eventMeta").textContent = event ? `${event.code} · ${event.venue || "Sin lugar"}` : "Conecta el host RD para cargar un evento preparado";
  document.getElementById("eventSelect").innerHTML = events.map((item) => `<option value="${item.id}" ${item.id === state.selectedEventId ? "selected" : ""}>${escapeHTML(item.name)}${item.synthetic ? " · DEMO" : ""}</option>`).join("");
  document.getElementById("eventSelect").disabled = events.length === 0;
  const newEventButton = document.getElementById("newEventButton");
  newEventButton.disabled = true;
  newEventButton.title = "Los eventos RD se preparan en el host; aquí sólo se seleccionan";
  document.getElementById("emptyNewEventButton").disabled = true;
  const startButton = document.getElementById("eventStartButton");
  startButton.classList.toggle("started", Boolean(event?.startedAt));
  startButton.textContent = event?.startedAt ? `● En curso desde ${formatDate(event.startedAt)}` : "▶ Marcar inicio real del evento";
  document.getElementById("sampleCount").textContent = samples.length;
  document.getElementById("testCount").textContent = allTests.length;
  document.getElementById("pendingCount").textContent = pending;
  document.getElementById("correctionCount").textContent = corrections;

  const search = ui.search.trim().toLowerCase();
  const filtered = samples.filter((sample) => {
    const matchesSearch = !search || `${sample.code} ${sample.declaredSubstance} ${sample.format}`.toLowerCase().includes(search);
    const matchesFilter = ui.filter === "all" || (ui.filter === "tests" && sample.tests.length > 0) || (ui.filter === "pending" && sample.workflowStatus !== "complete") || (ui.filter === "corrections" && sample.humanCorrection);
    return matchesSearch && matchesFilter;
  });
  document.getElementById("sampleList").innerHTML = filtered.length ? filtered.map((sample) => {
    const statusClass = sample.workflowStatus === "complete" ? "complete" : sample.humanCorrection ? "review" : "";
    const statusText = sample.workflowStatus === "complete" ? "Completa" : sample.tests.length ? `${sample.tests.length} prueba${sample.tests.length === 1 ? "" : "s"}` : "Borrador";
    return `<button type="button" class="sample-item ${sample.id === state.selectedSampleId ? "selected" : ""}" data-action="select-sample" data-id="${sample.id}"><i class="sample-status ${statusClass}"></i><span><strong>${escapeHTML(sample.code)}</strong><span>${escapeHTML(sample.declaredSubstance || "Declaración pendiente")}</span></span><small>${statusText}</small></button>`;
  }).join("") : `<div class="no-samples">No hay muestras con este filtro.<br><button class="text-button" type="button" data-action="clear-filter">Mostrar todas</button></div>`;
}

function renderWorkflow(sample) {
  const progress = sampleProgress(sample);
  const steps = [["01", "Contexto", "declaración"], ["02", "Apariencia", "foto + forma"], ["03", "Pruebas", `${sample.tests.length} registradas`], ["04", "Revisión", sample.humanCorrection ? "humana" : "pendiente"]];
  return `<div class="workflow-rail">${steps.map((step, index) => `<div class="workflow-step ${progress === index + 1 ? "active" : progress > index + 1 ? "done" : ""}"><span class="step-number">${progress > index + 1 ? "✓" : step[0]}</span><span><strong>${step[1]}</strong><small>${step[2]}</small></span></div>`).join("")}</div>`;
}

function renderPhoto(sample) {
  if (!sample.photo) return `<div class="photo-box"><div class="photo-placeholder"><div class="camera-glyph" aria-hidden="true"></div><p>Añade una foto de referencia<br>desde cámara o archivo.</p></div></div>`;
  return `<div class="photo-box has-photo"><span class="photo-tag">${sample.photo.synthetic ? "Demo sintética" : "Evidencia local"}</span><img src="${sample.photo.dataUrl}" alt="Evidencia visual de ${escapeHTML(sample.code)}"><button type="button" class="photo-tag" style="left:auto;right:9px;border:0;cursor:pointer" data-action="remove-sample-photo">× quitar</button></div>`;
}

function renderVisualProposal(sample) {
  const proposal = sample.visualProposal;
  const correction = sample.humanCorrection;
  if (!proposal) return `<div class="proposal-box"><span class="micro-label">Observación asistida</span><div class="proposal-value"><strong>Aún no calculada</strong></div><p class="helper-note">Se calcula solo desde la imagen y queda como propuesta. No indica composición química.</p></div>`;
  return `<div class="proposal-box ${correction ? "reviewed" : ""}"><span class="micro-label">${correction ? "Anotación revisada" : "Propuesta visual · ${escapeHTML(proposal.modelVersion)}"}</span><div class="proposal-value"><strong>${escapeHTML(correction?.color || proposal.colorName || "Sin color")}</strong><span class="confidence">${correction ? "corregida por operador" : `brillo ${Math.round(proposal.brightness * 100)}%`}</span></div><p class="helper-note">${correction ? `Forma humana: ${escapeHTML(correction.shape || "sin definir")}. La propuesta original se conserva.` : `Forma sugerida: ${escapeHTML(proposal.shapeName || "sin determinar")}. Medición de imagen no calibrada.`}</p></div>`;
}

function renderIdentityPanel(sample) {
  return `<section class="panel"><div class="panel-header"><p class="eyebrow">01 · Identidad de registro</p><h3>Qué llegó a la mesa</h3><p>La declaración se guarda separada de la observación y de cualquier resultado posterior.</p></div><div class="panel-body"><div class="field-grid"><label class="field-label">ID automático<input readonly value="${escapeHTML(sample.code)}"></label><label class="field-label">Hora de registro<input readonly value="${formatDate(sample.createdAt)}"></label></div><div class="choice-block"><div class="choice-title"><span>Sustancia declarada</span><small>incluye desconocido y otro</small></div><div class="chip-row">${renderChoices(substanceChoices, sample.declaredSubstance, "declaredSubstance", "")}</div>${sample.declaredSubstance === "Otro" ? `<label class="field-label" style="margin-top:13px">Descripción libre<input data-field-input="declaredOther" value="${escapeHTML(sample.declaredOther)}" placeholder="Texto breve, sin datos personales"></label>` : ""}<p class="helper-note">Dato declarado por quien entrega la muestra; no es identidad confirmada.</p></div><div class="choice-block"><div class="choice-title"><span>Formato observado al recibir</span><small>selección rápida</small></div><div class="chip-row">${renderChoices(formatChoices, sample.format, "format", "neutral")}</div></div></div></section>`;
}

function renderAppearancePanel(sample) {
  const appearance = sample.appearance;
  return `<section class="panel"><div class="panel-header"><p class="eyebrow">02 · Apariencia</p><h3>Registrar antes del test</h3><p>Color, forma y textura describen la muestra tal como se ve. Pueden corregirse sin reescribir la declaración.</p></div><div class="panel-body"><div class="choice-block" style="margin-top:0"><div class="choice-title"><span>Color observado</span><small>${appearance.color ? "seleccionado" : "elige una opción"}</small></div><div class="chip-row">${renderChoices(colorChoices, appearance.color, "appearance.color", "")}</div></div><div class="choice-block"><div class="choice-title"><span>Forma / molde / marca</span><small>sin escritura obligatoria</small></div><div class="chip-row">${renderChoices(shapeChoices, appearance.shape, "appearance.shape", "neutral")}</div></div><div class="choice-block"><div class="choice-title"><span>Textura</span><small></small></div><div class="chip-row">${renderChoices(textureChoices, appearance.texture, "appearance.texture", "")}</div></div><div class="field-grid" style="margin-top:18px"><label class="field-label">Marca o estampado visible<input data-field-input="appearance.brand" value="${escapeHTML(appearance.brand)}" placeholder="Opcional"></label><label class="field-label">Notas del operador<textarea data-field-input="appearance.notes" placeholder="Descripción breve, sin identidad de personas">${escapeHTML(appearance.notes)}</textarea></label></div><div class="evidence-divider"></div><div class="capture-grid"><div>${renderPhoto(sample)}<div class="photo-actions" style="margin-top:9px"><button class="small-button" type="button" data-action="take-sample-photo">◎ Capturar / elegir foto</button><button class="small-button" type="button" data-action="use-synthetic-photo">Usar demo sintética</button></div></div><div class="photo-detail">${renderVisualProposal(sample)}<div class="photo-actions"><span class="evidence-chip">▣ archivo vinculado</span><span class="evidence-chip">⌁ sin red</span></div><p class="helper-note">La cámara y el análisis visual son evidencia de contexto. No se presenta extracción de píxeles como colorimetría calibrada.</p></div></div></div></section>`;
}

function formatElapsed(test) {
  let seconds = Number(test.elapsedSeconds || 0);
  if (test.startedAt && !test.endedAt) seconds += Math.max(0, Math.floor((Date.now() - new Date(test.startedAt).getTime()) / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function renderTestCard(test, index) {
  const running = test.startedAt && !test.endedAt;
  const done = test.status === "done";
  const evidenceCount = test.evidence?.length || 0;
  return `<article class="test-card"><div class="test-card-header"><div class="test-index"><b>${index + 1}</b><strong>Prueba ${index + 1}</strong></div><span class="test-state ${done ? "done" : running ? "running" : ""}">${done ? "Registrada" : running ? "En curso" : "Borrador"}</span></div><div class="field-grid"><label class="field-label">Método<select data-test-input="method" data-test-id="${test.id}"><option ${test.method === "Colorimetría" ? "selected" : ""}>Colorimetría</option><option ${test.method === "Tira" ? "selected" : ""}>Tira</option><option ${test.method === "Instrumental" ? "selected" : ""}>Instrumental</option><option ${test.method === "Observación" ? "selected" : ""}>Observación</option><option ${test.method === "Otro" ? "selected" : ""}>Otro</option></select></label><label class="field-label">Reactivo o herramienta<select data-test-input="reagent" data-test-id="${test.id}">${reagentChoices.map((choice) => `<option ${test.reagent === choice ? "selected" : ""}>${choice}</option>`).join("")}</select></label></div><div class="field-grid" style="margin-top:12px"><label class="field-label">Observación visual<textarea data-test-input="observation" data-test-id="${test.id}" placeholder="Qué se vio, sin concluir composición">${escapeHTML(test.observation)}</textarea></label><label class="field-label">Evolución del color<textarea data-test-input="reactionEvolution" data-test-id="${test.id}" placeholder="Ej. transparente → amarillo en 20 s">${escapeHTML(test.reactionEvolution)}</textarea></label></div><div class="field-grid" style="margin-top:12px"><label class="field-label">Color / resultado visible<input data-test-input="reactionColor" data-test-id="${test.id}" value="${escapeHTML(test.reactionColor)}" placeholder="Describe la señal"></label><label class="field-label">Resultado del operador<select data-test-input="operatorResult" data-test-id="${test.id}"><option value="">Seleccionar</option>${resultChoices.map((choice) => `<option ${test.operatorResult === choice ? "selected" : ""}>${choice}</option>`).join("")}</select></label></div><div class="test-meta"><span class="timer" data-timer-id="${test.id}">${formatElapsed(test)}</span>${test.startedAt ? `<span class="evidence-chip">inicio ${formatDate(test.startedAt)}</span>` : `<span class="helper-note" style="margin:0">El cronómetro fija el inicio de la reacción.</span>`}${evidenceCount ? `<span class="evidence-chip">▣ ${evidenceCount} evidencia${evidenceCount === 1 ? "" : "s"}</span>` : ""}</div><div class="test-meta" style="justify-content:space-between"><div class="photo-actions"><button class="small-button" type="button" data-action="test-photo" data-test-id="${test.id}">◎ Foto de reacción</button><button class="small-button" type="button" data-action="toggle-test-timer" data-test-id="${test.id}">${running ? "■ Detener cronómetro" : "▶ Iniciar cronómetro"}</button></div><button class="small-button danger" type="button" data-action="delete-test" data-test-id="${test.id}">Eliminar prueba</button></div></article>`;
}

function renderTestsPanel(sample) {
  return `<section class="panel"><div class="panel-header"><p class="eyebrow">03 · Pruebas</p><h3>Una muestra, varias pruebas</h3><p>Cada prueba tiene reactivo, inicio, observación, evidencia y resultado del operador.</p></div><div class="panel-body">${sample.tests.length ? sample.tests.map(renderTestCard).join("") : `<div class="no-samples" style="border:1px dashed var(--line-strong);border-radius:9px">Todavía no hay pruebas. Añade la primera cuando la muestra esté lista.</div>`}<div class="add-test-row"><p>${sample.tests.length ? "Puedes volver y corregir cualquier prueba." : "El registro se puede interrumpir y reabrir."}</p><button class="small-button" type="button" data-action="add-test">+ Añadir prueba</button></div></div></section>`;
}

function renderReviewPanel(sample) {
  const proposal = sample.visualProposal;
  return `<section class="panel"><div class="panel-header"><p class="eyebrow">04 · Revisión</p><h3>Propuesta, corrección y límite</h3><p>La persona operadora decide qué queda registrado. La propuesta original nunca se sobreescribe.</p></div><div class="panel-body"><div class="field-grid"><label class="field-label">Corrección humana · color<select data-review-input="color"><option value="">Sin corregir</option>${colorChoices.map((choice) => `<option ${sample.humanCorrection?.color === choice ? "selected" : ""}>${choice}</option>`).join("")}</select></label><label class="field-label">Corrección humana · forma<select data-review-input="shape"><option value="">Sin corregir</option>${shapeChoices.map((choice) => `<option ${sample.humanCorrection?.shape === choice ? "selected" : ""}>${choice}</option>`).join("")}</select></label></div><div class="data-strip" style="margin-top:16px"><span>Propuesta original</span><strong>${proposal ? `${escapeHTML(proposal.colorName || "sin color")} · ${escapeHTML(proposal.shapeName || "sin forma")}` : "No calculada"}</strong></div><div class="data-strip"><span>Versión visual</span><strong>${proposal?.modelVersion || "—"}</strong></div><div class="boundary-note"><strong>Límite de interpretación.</strong> La apariencia y los testeos rápidos se conservan como observaciones. No permiten afirmar composición, pureza, potencia, cantidad ni seguridad.</div><button class="button button-primary primary-full" type="button" data-action="save-review">${sample.humanCorrection ? "Actualizar corrección humana" : "Confirmar revisión humana"}</button></div></section>`;
}

function renderAside(sample, event) {
  const testsDone = sample.tests.filter((test) => test.status === "done").length;
  const timeline = [
    [sample.createdAt, "Registro creado", "ID y hora generados localmente"],
    [sample.photo?.capturedAt, "Evidencia visual", sample.photo ? `${sample.photo.filename} vinculado` : "Pendiente"],
    [sample.tests[0]?.startedAt, "Primera prueba", sample.tests.length ? `${sample.tests.length} prueba${sample.tests.length === 1 ? "" : "s"} asociadas` : "Pendiente"],
    [sample.humanCorrection?.reviewedAt, "Revisión humana", sample.humanCorrection ? "Corrección conservada" : "Pendiente"]
  ];
  return `<aside class="record-aside"><div class="aside-card"><h3>Rastro de la muestra</h3><p>${escapeHTML(event?.name || "Evento")} · todo queda vinculado al ID.</p><div class="timeline">${timeline.map((item) => `<div class="timeline-item"><strong>${item[1]}</strong><span>${item[0] ? formatDate(item[0]) : "Aún no"}<br>${item[2]}</span></div>`).join("")}</div></div><div class="aside-card"><h3>Capas del registro</h3><div class="data-strip"><span>Declarada</span><strong>${escapeHTML(sample.declaredSubstance || "pendiente")}</strong></div><div class="data-strip"><span>Apariencia</span><strong>${escapeHTML(sample.appearance.color || "pendiente")}</strong></div><div class="data-strip"><span>Propuesta visual</span><strong>${sample.visualProposal ? "presente" : "pendiente"}</strong></div><div class="data-strip"><span>Operador</span><strong>${sample.humanCorrection ? "corregido" : "pendiente"}</strong></div><div class="data-strip"><span>Analítico posterior</span><strong>no registrado</strong></div></div><div class="aside-card"><h3>Aprendizaje supervisado</h3><p>Las imágenes revisadas pueden participar en recuperación por similitud. Eso no equivale a entrenar pesos ni a confirmar identidad química.</p><div class="review-queue"><div class="queue-row"><span>Ejemplos revisados en este evento</span><b>${eventSamples(event?.id).filter((item) => item.humanCorrection).length}</b></div><div class="queue-row"><span>Modelo de recuperación</span><b>${MODEL_VERSION}</b></div><div class="queue-row"><span>Pesos especializados</span><b>0</b></div></div><button class="small-button primary-full" type="button" data-action="find-similar">⌁ Buscar muestras similares</button></div><div class="aside-card"><h3>Evento</h3><div class="data-strip"><span>Inicio programado</span><strong>${formatDate(event?.scheduledAt)}</strong></div><div class="data-strip"><span>Inicio real</span><strong>${formatDate(event?.startedAt)}</strong></div><div class="data-strip"><span>Pruebas completas</span><strong>${testsDone}/${sample.tests.length || 0}</strong></div></div></aside>`;
}

function renderWorkspace() {
  const event = getEvent();
  const sample = getSample();
  const empty = document.getElementById("emptyState");
  const root = document.getElementById("sampleWorkspace");
  if (!event || !sample) {
    empty.hidden = false;
    root.innerHTML = "";
    return;
  }
  empty.hidden = true;
  const statusLabel = sample.workflowStatus === "complete" ? "Completa" : sample.humanCorrection ? "En revisión" : sample.tests.length ? "En proceso" : "Borrador";
  const syncLabel = sample.syncStatus === "synced" ? "Sincronizada con host RD" : sample.syncStatus === "syncing" ? "Sincronizando…" : "Pendiente de sincronizar";
  root.innerHTML = `<div class="workspace-header"><div><p class="eyebrow">Registro interno · ${event.synthetic ? "DEMO SINTÉTICA" : "DATOS LOCALES"}</p><h2>${escapeHTML(sample.code)}</h2><p class="subhead">Una muestra con historia propia. Declara, observa, prueba, corrige y exporta sin perder el contexto.</p></div><div class="saved-state"><span class="check">✓</span><span>${escapeHTML(statusLabel)} · ${formatDate(sample.updatedAt)}</span></div></div>${renderWorkflow(sample)}<div class="record-layout"><div class="record-main">${renderIdentityPanel(sample)}${renderAppearancePanel(sample)}${renderTestsPanel(sample)}${renderReviewPanel(sample)}<div class="record-footer"><p>Último cambio local: ${formatDate(sample.updatedAt)} · ${ui.remote.connected ? syncLabel : "sin sincronización automática"}</p><div class="footer-actions"><button class="button button-quiet" type="button" data-action="duplicate-sample">Duplicar como demo</button><button class="button button-quiet" type="button" data-action="sync-current" ${!ui.remote.connected || sample.syncStatus === "syncing" ? "disabled" : ""}>⇧ ${ui.remote.connected ? "Sincronizar con host RD" : "Host RD no disponible"}</button><button class="button button-primary" type="button" data-action="export-current">Exportar muestra</button></div></div></div>${renderAside(sample, event)}</div>`;
}

function renderAll() {
  renderSidebar();
  renderWorkspace();
  refreshStatus();
}

function updateSampleValue(field, value) {
  const sample = getSample();
  if (!sample) return;
  const segments = field.split(".");
  let target = sample;
  segments.slice(0, -1).forEach((segment) => { target = target[segment]; });
  target[segments.at(-1)] = value;
  sample.updatedAt = isoNow();
  sample.workflowStatus = sample.tests.length ? "testing" : sample.workflowStatus;
  persist();
}

function updateTestValue(testId, field, value) {
  const sample = getSample();
  const test = sample?.tests.find((item) => item.id === testId);
  if (!test) return;
  test[field] = value;
  if (field === "operatorResult" && value && test.startedAt) test.status = "done";
  sample.updatedAt = isoNow();
  persist();
}

function ensureVisualProposal(sample) {
  if (!sample.photo || sample.visualProposal) return;
  const palette = { "#df9a9c": ["Rosado", "Redondo"], "#c7c5bc": ["Blanco", "Irregular"], "#d8bf62": ["Amarillo", "Redondo"] };
  const match = Object.entries(palette).find(([key]) => sample.photo.dataUrl.includes(encodeURIComponent(key)) || sample.photo.dataUrl.includes(key));
  const [colorName, shapeName] = match?.[1] || [sample.appearance.color || "Desconocido", sample.appearance.shape || "Desconocido"];
  sample.visualProposal = { colorName, shapeName, brightness: .68, saturation: .31, modelVersion: MODEL_VERSION, createdAt: isoNow(), status: "proposal" };
  sample.updatedAt = isoNow();
}

async function hashDataUrl(dataUrl) {
  if (!globalThis.crypto?.subtle) return "hash-unavailable";
  const bytes = new TextEncoder().encode(dataUrl);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function handlePhoto(file) {
  const sample = getSample();
  if (!file || !sample) return;
  const dataUrl = await readFileAsDataUrl(file);
  const hash = await hashDataUrl(dataUrl);
  if (ui.pendingPhotoTarget.type === "test") {
    const test = sample.tests.find((item) => item.id === ui.pendingPhotoTarget.testId);
    if (!test) return;
    test.evidence = test.evidence || [];
    test.evidence.push({ id: uid("evidence"), filename: file.name || "reaction-photo", mimeType: file.type, dataUrl, capturedAt: isoNow(), sha256: hash, synthetic: false });
    sample.audit.push({ at: isoNow(), action: "reaction_evidence_added", actor: "operator", testId: test.id });
    showToast("Evidencia de reacción vinculada a la prueba.");
  } else {
    sample.photo = { id: uid("photo"), filename: file.name || "sample-photo", mimeType: file.type, dataUrl, capturedAt: isoNow(), sha256: hash, synthetic: false };
    sample.visualProposal = null;
    ensureVisualProposal(sample);
    sample.audit.push({ at: isoNow(), action: "sample_photo_added", actor: "operator" });
    showToast("Foto guardada y vinculada localmente.");
  }
  sample.updatedAt = isoNow();
  persist();
  renderAll();
}

function useSyntheticPhoto() {
  const sample = getSample();
  if (!sample) return;
  sample.photo = { id: uid("photo"), filename: "demo-objeto-inocuo.svg", mimeType: "image/svg+xml", dataUrl: svgPhoto("#d8bf62", "OBJETO SINTÉTICO"), capturedAt: isoNow(), sha256: "demo-synthetic", synthetic: true };
  sample.visualProposal = null;
  ensureVisualProposal(sample);
  sample.synthetic = true;
  sample.updatedAt = isoNow();
  sample.audit.push({ at: isoNow(), action: "synthetic_photo_added", actor: "operator" });
  persist();
  showToast("Imagen sintética añadida; no es una validación química.");
  renderAll();
}

function toggleTimer(testId) {
  const sample = getSample();
  const test = sample?.tests.find((item) => item.id === testId);
  if (!test) return;
  if (test.startedAt && !test.endedAt) {
    const elapsed = Math.max(0, Math.floor((Date.now() - new Date(test.startedAt).getTime()) / 1000));
    test.elapsedSeconds = Number(test.elapsedSeconds || 0) + elapsed;
    test.endedAt = isoNow();
    test.status = test.operatorResult ? "done" : "draft";
    showToast(`Cronómetro detenido en ${formatElapsed(test)}.`);
  } else {
    test.startedAt = isoNow();
    test.endedAt = null;
    test.status = "running";
    showToast("Inicio de reacción marcado.");
  }
  sample.updatedAt = isoNow();
  sample.workflowStatus = "testing";
  sample.audit.push({ at: isoNow(), action: test.endedAt ? "test_stopped" : "test_started", actor: "operator", testId: test.id });
  persist();
  renderAll();
}

function addTest() {
  const sample = getSample();
  if (!sample) return;
  sample.tests.push(makeTest());
  sample.workflowStatus = "testing";
  sample.updatedAt = isoNow();
  sample.audit.push({ at: isoNow(), action: "test_added", actor: "operator" });
  persist("Prueba añadida · guardado local");
  renderAll();
  setTimeout(() => document.querySelector(".test-card:last-of-type")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
}

function addSample() {
  const event = getEvent();
  if (!event || !event.remote) {
    showToast("Selecciona un evento RD preparado por el host antes de registrar muestras.", "error");
    return;
  }
  state.meta.sequence = Number(state.meta.sequence || 0) + 1;
  const sample = makeSample(event.id, state.meta.sequence);
  state.samples.push(sample);
  state.selectedSampleId = sample.id;
  ui.filter = "all";
  persist("Nueva muestra · ID generado");
  renderAll();
  showToast(`${sample.code} lista para registrar.`);
}

function startEvent() {
  const event = getEvent();
  if (!event) return;
  if (!event.startedAt) {
    event.startedAt = isoNow();
    event.status = "active";
    persist("Inicio real del evento guardado");
    showToast("Inicio real del evento registrado.");
  } else {
    showToast(`Evento en curso desde ${formatDate(event.startedAt)}.`);
  }
  renderAll();
}

function createEventFromForm() {
  document.getElementById("eventDialog").close();
  showToast("Los eventos RD deben existir en el host; esta superficie sólo selecciona eventos preparados.", "error");
}

function makeExportPayload(eventId = state.selectedEventId, onlySampleId = null) {
  const event = getEvent(eventId);
  const samples = state.samples.filter((sample) => sample.eventId === eventId && (!onlySampleId || sample.id === onlySampleId));
  return { exportVersion: "rd-field-export-v0.1", exportedAt: isoNow(), privacy: "local-only", disclaimer: "Las observaciones y pruebas rápidas no demuestran composición, pureza, potencia, cantidad ni seguridad.", event: clone(event), samples: clone(samples), assets: samples.flatMap((sample) => [sample.photo, ...sample.tests.flatMap((test) => test.evidence || [])].filter(Boolean).map((asset) => ({ id: asset.id, filename: asset.filename, mimeType: asset.mimeType, linkedTo: sample.code, dataUrl: asset.dataUrl, sha256: asset.sha256, synthetic: asset.synthetic }))) };
}

function csvCell(value) { return `"${String(value ?? "").replaceAll('"', '""')}"`; }
function makeCSV(payload) {
  const rows = [["event_code", "sample_code", "created_at", "declared_substance", "format", "appearance_color", "appearance_shape", "test_id", "method", "reagent", "started_at", "elapsed_seconds", "reaction_color", "reaction_evolution", "operator_result", "synthetic"]];
  payload.samples.forEach((sample) => {
    if (!sample.tests.length) rows.push([payload.event.code, sample.code, sample.createdAt, sample.declaredSubstance, sample.format, sample.appearance.color, sample.appearance.shape, "", "", "", "", "", "", "", "", sample.synthetic]);
    sample.tests.forEach((test) => rows.push([payload.event.code, sample.code, sample.createdAt, sample.declaredSubstance, sample.format, sample.appearance.color, sample.appearance.shape, test.id, test.method, test.reagent, test.startedAt, test.elapsedSeconds, test.reactionColor, test.reactionEvolution, test.operatorResult, sample.synthetic]));
  });
  return rows.map((row) => row.map(csvCell).join(",")).join("\n");
}

function downloadFile(name, contents, mime) {
  const blob = new Blob([contents], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportEvent(onlySampleId = null) {
  const event = getEvent();
  if (!event) return;
  const payload = makeExportPayload(event.id, onlySampleId);
  const suffix = onlySampleId ? `-${getSample(onlySampleId)?.code || "muestra"}` : `-${event.code}`;
  downloadFile(`xio-rd-expediente${suffix}.json`, JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
  setTimeout(() => downloadFile(`xio-rd-registros${suffix}.csv`, makeCSV(payload), "text/csv;charset=utf-8"), 120);
  showToast("Exportación preparada: registros + imágenes vinculadas.");
}

function directorSummary() {
  const event = getEvent();
  const samples = eventSamples();
  const tests = samples.flatMap((sample) => sample.tests);
  const completed = samples.filter((sample) => sample.workflowStatus === "complete").length;
  const pending = samples.length - completed;
  const totalSeconds = tests.reduce((sum, test) => sum + Number(test.elapsedSeconds || 0), 0);
  const average = tests.length ? Math.round(totalSeconds / tests.length) : 0;
  document.getElementById("directorTitle").textContent = event ? `Vista directiva · ${event.name}` : "Vista directiva";
  document.getElementById("directorContent").innerHTML = `<div class="director-stats"><div class="director-stat"><strong>${samples.length}</strong><span>muestras registradas</span></div><div class="director-stat"><strong>${tests.length}</strong><span>pruebas asociadas</span></div><div class="director-stat"><strong>${pending}</strong><span>pendientes</span></div><div class="director-stat"><strong>${average ? `${average}s` : "—"}</strong><span>tiempo medio registrado</span></div></div><table class="director-table"><thead><tr><th>Indicador</th><th>Resultado</th></tr></thead><tbody><tr><td>Muestras con foto vinculada</td><td>${samples.filter((sample) => sample.photo).length}/${samples.length}</td></tr><tr><td>Muestras con corrección humana</td><td>${samples.filter((sample) => sample.humanCorrection).length}/${samples.length}</td></tr><tr><td>Pruebas con resultado del operador</td><td>${tests.filter((test) => test.operatorResult).length}/${tests.length}</td></tr><tr><td>Inicio programado / real</td><td>${formatDate(event?.scheduledAt, false)} / ${formatDate(event?.startedAt)}</td></tr></tbody></table><p class="disclaimer">Los denominadores son explícitos y el resumen puede abrir cada registro. No se agregan afirmaciones de composición ni se publica nada desde esta vista.</p><div class="modal-actions"><button class="button button-primary" type="button" data-action="export-event-from-director">Exportar este evento</button></div>`;
}

function findSimilar() {
  const sample = getSample();
  const candidates = eventSamples().filter((item) => item.id !== sample?.id && item.visualProposal && item.humanCorrection);
  if (!candidates.length) {
    showToast("Aún no hay ejemplos revisados suficientes en este evento.");
    return;
  }
  const best = candidates[0];
  showToast(`Recuperación demo: ${best.code} comparte rasgos visuales revisados.`);
}

function epochSeconds(value) {
  if (!value) return null;
  const stamp = new Date(value).getTime();
  return Number.isFinite(stamp) ? Math.floor(stamp / 1000) : null;
}

function capturePayload(asset, kind) {
  if (!asset || asset.synthetic || !asset.dataUrl) return null;
  return {
    id: asset.id,
    kind,
    capturedAt: epochSeconds(asset.capturedAt),
    sha256: asset.sha256 || "",
    photoBase64: asset.dataUrl
  };
}

function sampleSyncPayload(sample, event) {
  const captures = [capturePayload(sample.photo, "sample")];
  sample.tests.forEach((test) => (test.evidence || []).forEach((asset) => captures.push(capturePayload(asset, "reaction"))));
  return {
    date: new Date(sample.createdAt).toISOString().slice(0, 10),
    eventRef: event.eventRef || event.code,
    eventOrigin: "xio-rd-pwa",
    sampleCode: sample.code,
    substanceDeclared: sample.declaredSubstance === "Otro" ? (sample.declaredOther || "Otro") : (sample.declaredSubstance || "Desconocido"),
    sampleType: sample.format || "",
    color: sample.appearance?.color || "",
    texture: sample.appearance?.texture || "",
    logoOrMark: sample.appearance?.brand || "",
    notes: sample.appearance?.notes || "",
    mesa: { label: "PWA RD", number: null },
    captures: captures.filter(Boolean),
    tests: sample.tests.map((test, index) => ({
      reagent: test.reagent || "Otro / método local",
      resultColor: test.reactionColor || "",
      family: "",
      suspectedAdulterant: "",
      matchesDeclared: null,
      order: index + 1
    }))
  };
}

async function syncCurrentSample() {
  const sample = getSample();
  const event = getEvent();
  if (!sample || !event || !ui.remote.connected || !event.remote) {
    showToast("Selecciona un evento RD del host antes de sincronizar.", "error");
    return;
  }
  sample.syncStatus = "syncing";
  persist("Sincronización RD en curso");
  renderAll();
  try {
    const response = await fetch(remoteUrl("sync"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sampleSyncPayload(sample, event))
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) throw new Error(result.error || `HTTP ${response.status}`);
    sample.syncStatus = "synced";
    sample.remoteSampleId = result.sampleId || null;
    sample.remoteSyncedAt = isoNow();
    sample.audit.push({ at: isoNow(), action: "sample_synced_to_rd_host", actor: "operator", remoteSampleId: sample.remoteSampleId });
    persist("Muestra guardada en el host RD");
    renderAll();
    showToast(`${sample.code} guardada en el host RD.`);
  } catch (error) {
    sample.syncStatus = "pending";
    persist("Host RD no confirmó la muestra");
    renderAll();
    showToast(`No se pudo sincronizar: ${error?.message || error}`, "error");
  }
}

function duplicateSample() {
  const current = getSample();
  if (!current) return;
  state.meta.sequence = Number(state.meta.sequence || 0) + 1;
  const copy = clone(current);
  copy.id = uid("sample");
  copy.code = `XIO-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}-${String(state.meta.sequence).padStart(3, "0")}`;
  copy.createdAt = isoNow();
  copy.updatedAt = copy.createdAt;
  copy.synthetic = true;
  copy.audit = [{ at: copy.createdAt, action: "sample_duplicated_as_demo", actor: "operator" }];
  state.samples.push(copy);
  state.selectedSampleId = copy.id;
  persist("Copia de demostración creada");
  renderAll();
  showToast("Se creó una copia sintética para explorar el flujo.");
}

document.addEventListener("click", (event) => {
  const actionTarget = event.target.closest("[data-action]");
  if (!actionTarget) return;
  const action = actionTarget.dataset.action;
  if (action === "choose") {
    updateSampleValue(actionTarget.dataset.field, actionTarget.dataset.value);
    renderAll();
  } else if (action === "select-sample") {
    state.selectedSampleId = actionTarget.dataset.id;
    renderAll();
  } else if (action === "clear-filter") {
    ui.filter = "all";
    ui.search = "";
    document.getElementById("sampleSearch").value = "";
    renderAll();
  } else if (action === "add-test") addTest();
  else if (action === "toggle-test-timer") toggleTimer(actionTarget.dataset.testId);
  else if (action === "delete-test") {
    const sample = getSample();
    sample.tests = sample.tests.filter((test) => test.id !== actionTarget.dataset.testId);
    sample.updatedAt = isoNow();
    persist("Prueba eliminada · guardado local");
    renderAll();
  } else if (action === "take-sample-photo" || action === "test-photo") {
    ui.pendingPhotoTarget = action === "test-photo" ? { type: "test", testId: actionTarget.dataset.testId } : { type: "sample" };
    document.getElementById("photoInput").value = "";
    document.getElementById("photoInput").click();
  } else if (action === "use-synthetic-photo") useSyntheticPhoto();
  else if (action === "remove-sample-photo") {
    const sample = getSample();
    sample.photo = null;
    sample.visualProposal = null;
    sample.updatedAt = isoNow();
    persist("Foto retirada · registro conservado");
    renderAll();
  } else if (action === "save-review") {
    const sample = getSample();
    const color = document.querySelector("[data-review-input='color']")?.value || "";
    const shape = document.querySelector("[data-review-input='shape']")?.value || "";
    if (!color && !shape) {
      sample.humanCorrection = null;
      showToast("La revisión quedó pendiente; puedes corregirla después.");
    } else {
      sample.humanCorrection = { color, shape, reviewedAt: isoNow(), reviewer: "operator" };
      sample.workflowStatus = sample.tests.some((test) => test.status === "done") ? "complete" : "review";
      sample.audit.push({ at: isoNow(), action: "human_visual_correction", actor: "operator" });
      showToast("Corrección humana conservada como anotación separada.");
    }
    sample.updatedAt = isoNow();
    persist();
    renderAll();
  } else if (action === "find-similar") findSimilar();
  else if (action === "duplicate-sample") duplicateSample();
  else if (action === "sync-current") syncCurrentSample();
  else if (action === "export-current") exportEvent(state.selectedSampleId);
  else if (action === "export-event-from-director") exportEvent();
});

document.addEventListener("change", (event) => {
  const input = event.target;
  if (input.matches("[data-field-input]")) {
    updateSampleValue(input.dataset.fieldInput, input.value);
  } else if (input.matches("[data-test-input]")) {
    updateTestValue(input.dataset.testId, input.dataset.testInput, input.value);
    if (input.dataset.testInput === "operatorResult") renderAll();
  } else if (input.matches("[data-review-input]")) {
    // Review is committed by the explicit button to avoid accidental overwrite.
  } else if (input.id === "eventSelect") {
    state.selectedEventId = input.value;
    const first = eventSamples(input.value)[0];
    state.selectedSampleId = first?.id || null;
    ui.filter = "all";
    renderAll();
  }
});

document.getElementById("sampleSearch").addEventListener("input", (event) => {
  ui.search = event.target.value;
  renderSidebar();
});

document.querySelectorAll(".metric-block").forEach((button) => button.addEventListener("click", () => { ui.filter = button.dataset.filter; renderSidebar(); }));
document.getElementById("newSampleButton").addEventListener("click", addSample);
document.getElementById("eventStartButton").addEventListener("click", startEvent);
document.getElementById("newEventButton").addEventListener("click", () => document.getElementById("eventDialog").showModal());
document.getElementById("emptyNewEventButton").addEventListener("click", () => document.getElementById("eventDialog").showModal());
document.getElementById("eventForm").addEventListener("submit", (event) => { event.preventDefault(); if (event.submitter?.value === "cancel") document.getElementById("eventDialog").close(); else createEventFromForm(); });
document.getElementById("exportButton").addEventListener("click", () => exportEvent());
document.getElementById("openDirectorButton").addEventListener("click", () => { directorSummary(); document.getElementById("directorDialog").showModal(); });
document.getElementById("closeDirectorButton").addEventListener("click", () => document.getElementById("directorDialog").close());
document.getElementById("photoInput").addEventListener("change", (event) => { const file = event.target.files?.[0]; if (file) handlePhoto(file); });
window.addEventListener("online", refreshStatus);
window.addEventListener("online", loadRemoteBootstrap);
window.addEventListener("offline", refreshStatus);

if ("serviceWorker" in navigator && location.protocol !== "file:") navigator.serviceWorker.register("./sw.js").catch(() => {});

ui.timer = setInterval(() => {
  document.querySelectorAll("[data-timer-id]").forEach((node) => { const test = getSample()?.tests.find((item) => item.id === node.dataset.timerId); if (test) node.textContent = formatElapsed(test); });
}, 1000);

renderAll();
loadRemoteBootstrap();
