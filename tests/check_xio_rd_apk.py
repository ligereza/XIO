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
    assert 'value -> engine.setObservedColor(value)' in source
    assert 'ramp.setOnCommit(commit);' in source
    assert 'String observedColorLabel = row.observedColor' in source
    assert 'info.addView(body(observedColorLabel));' in source
    assert 'new PorterDuffColorFilter(fallbackColor, PorterDuff.Mode.SRC_IN)' in source
    assert 'Color.parseColor(value.trim())' in source
    assert 'database.insertCapture(sample.id, capture);' in source
    assert 'database.insertCapture(engine.snapshot().id, pendingCapture);' in source
    assert 'database.deleteCapture(engine.snapshot().id, pendingCapture.id);' in source
    assert 'recoverOrphanCaptureFiles(row.id);' in source
    assert 'String captureId = photo.getName().substring' in source
    assert 'database.insertCapture(sampleId, capture);' in source
    assert 'existing.features.circularity >= .12f' in source
    assert 'bestCluster(relaxedRaw, width, height)' in vision
    assert 'fillEnclosedHoles' in vision
    assert 'directionalThreshold' in vision
    assert 'findMoldMatches' in memory
    assert 'mold_design' in memory
    assert 'RECONOCIMIENTO DE MOLDE / DISEÑO' in source
    assert 'moldDesign' in (ROOT / "projects" / "rd-field" / "android" / "app" / "src" / "main" / "java" / "cl" / "reduciendodano" / "xiofield" / "data" / "FlujoGateway.java").read_text(encoding="utf-8")
    print("OK: XIO-RD native APK ramp persistence/capture registry contract")


if __name__ == "__main__":
    main()
