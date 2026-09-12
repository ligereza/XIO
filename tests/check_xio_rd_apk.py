"""Static contract check for the native XIO-RD field client."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "projects" / "rd-field" / "android" / "app" / "src" / "main" / "java" / "cl" / "reduciendodano" / "xiofield" / "MainActivity.java"


def main() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert 'addColorRampControl(content, "COLOR", sample.observedColor' in source
    assert 'engine.setObservedColor(value); persist();' in source
    assert 'String observedColorLabel = row.observedColor' in source
    assert 'info.addView(body(observedColorLabel));' in source
    assert 'database.insertCapture(sample.id, capture);' in source
    assert 'database.insertCapture(engine.snapshot().id, pendingCapture);' in source
    assert 'database.deleteCapture(engine.snapshot().id, pendingCapture.id);' in source
    print("OK: XIO-RD native APK ramp persistence/capture registry contract")


if __name__ == "__main__":
    main()
