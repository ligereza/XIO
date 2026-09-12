"""Static contract check for the native XIO-RD field client."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "projects" / "rd-field" / "android" / "app" / "src" / "main" / "java" / "cl" / "reduciendodano" / "xiofield" / "MainActivity.java"
VISION = ROOT / "projects" / "rd-field" / "android" / "app" / "src" / "main" / "java" / "cl" / "reduciendodano" / "xiofield" / "visual" / "VisualFeatureExtractor.java"
MEMORY = ROOT / "projects" / "rd-field" / "android" / "app" / "src" / "main" / "java" / "cl" / "reduciendodano" / "xiofield" / "visual" / "VisualMemory.java"


def main() -> None:
    source = MAIN.read_text(encoding="utf-8")
    vision = VISION.read_text(encoding="utf-8")
    memory = MEMORY.read_text(encoding="utf-8")
    assert 'addColorRampControl(content, "COLOR", sample.observedColor' in source
    assert 'engine.setObservedColor(value)' in source
    assert 'ramp.setOnCommit(commit);' in source
    assert 'String observedColorLabel = row.observedColor' in source
    assert 'info.addView(body(observedColorLabel));' in source
    assert 'new PorterDuffColorFilter(fallbackColor, PorterDuff.Mode.SRC_IN)' in source
    assert 'Color.parseColor(value.trim())' in source
    assert 'database.insertCapture(sample.id, capture);' in source
    assert 'database.insertCapture(engine.snapshot().id, pendingCapture);' not in source
    assert 'AVANZAR A COLORIMETRÍA' in source
    assert 'entryReadyForTests' in source
    assert 'pendingCaptures' in source
    assert 'this::render' in source
    assert 'saveSession(sample, includeTests)' in source
    assert 'CONFIRMAR Y NUEVA MUESTRA' in source
    assert 'selectLocalSample(row)' in source
    assert 'GUARDAR TESTS' in source
    assert 'testTimingReady' in source
    assert 'Inicia y detén el cronómetro antes de guardar este test.' in source
    assert 'engine.snapshot().status = "tests_ready"' in source
    assert 'confirmed.status = "confirmed"' in source
    assert 'sendSample(confirmed, false)' in source
    assert 'Toca un ingreso para revisarlo' in source
    assert 'MUESTRA ACTIVA' in source
    assert 'TESTS Y REACCIONES' in source
    assert 'reacción  ·  ' in source
    assert 'silueta no disponible' in source
    assert 'cleanupUncommittedDraftEvidence' in source
    assert 'Confirma la muestra antes de sincronizar' in source
    assert 'Termina o confirma la muestra antes de cambiar de evento' in source
    assert 'RdFieldExporter.exportLocalBackup(this)' in source
    assert 'RESPALDAR RD ANTES DE ACTUALIZAR' in source
    assert 'database.deleteCapture(engine.snapshot().id, pendingCapture.id);' not in source
    assert 'reconcileOrphanCaptureFiles();' in source
    assert 'for (RdFieldDb.SampleRow local : database.recentSamples())' in source
    assert 'reconcileOrphanCaptureFiles(local.id, local.id.equals(currentSampleId));' in source
    assert 'String captureId = photo.getName().substring' in source
    assert 'database.insertCapture(sampleId, capture);' in source
    assert 'existing.features.circularity >= .12f' in source
    assert 'bestCluster(relaxedRaw, width, height)' in vision
    assert 'aspectBalance' in vision
    assert 'VISUAL_MODEL_VERSION = "visual-contour-v0.4"' in (ROOT / "projects" / "rd-field" / "android" / "app" / "src" / "main" / "java" / "cl" / "reduciendodano" / "xiofield" / "core" / "SampleSessionEngine.java").read_text(encoding="utf-8")
    assert 'fillEnclosedHoles' in vision
    assert 'directionalThreshold' in vision
    assert 'findMoldMatches' in memory
    assert 'mold_design' in memory
    assert 'RECONOCIMIENTO DE MOLDE / DISEÑO' in source
    assert 'moldDesign' in (ROOT / "projects" / "rd-field" / "android" / "app" / "src" / "main" / "java" / "cl" / "reduciendodano" / "xiofield" / "data" / "FlujoGateway.java").read_text(encoding="utf-8")
    assert 'moldFingerprint' in (ROOT / "projects" / "rd-field" / "android" / "app" / "src" / "main" / "java" / "cl" / "reduciendodano" / "xiofield" / "data" / "FlujoGateway.java").read_text(encoding="utf-8")
    assert 'suggestedMoldDesigns' in source
    assert 'OTRA VISTA' in source
    assert 'moldDesigns' in (ROOT / "xio" / "new-plugins" / "rd_field" / "bridge.py").read_text(encoding="utf-8")
    assert 'loadSamples' in source
    assert 'HISTORIA HOST RD' in source
    assert 'addRemoteSampleRow' in source
    assert 'loadSamples(rdEndpoint()' in source
    assert 'loadVisualCatalog' in source
    assert 'memory.addApproved' in source
    assert 'submitVisualCandidate' in source
    assert 'pending_review' in (ROOT / "projects" / "rd-field" / "android" / "app" / "src" / "main" / "java" / "cl" / "reduciendodano" / "xiofield" / "MainActivity.java").read_text(encoding="utf-8")
    assert 'ensureFieldDraft' in source
    assert 'ensureDemo()' not in source
    print("OK: XIO-RD native APK ramp persistence/capture registry contract")


if __name__ == "__main__":
    main()
