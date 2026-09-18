import io
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "new"))
import hotspot_ui_probe as probe  # noqa: E402


def run_probe(monkeypatch, capsys, xml):
    monkeypatch.setattr(sys, "stdin", io.StringIO(xml))
    code = probe.main()
    return code, capsys.readouterr().out.strip()


def test_returns_only_semantic_hotspot_switch(monkeypatch, capsys):
    xml = """
    <hierarchy>
      <node text="Portable hotspot">
        <node resource-id="android:id/checkbox" checkable="true"
              checked="false" enabled="true" bounds="[100,200][300,260]" />
      </node>
    </hierarchy>
    """
    code, result = run_probe(monkeypatch, capsys, xml)
    assert code == 0
    assert result == "OFF|200|230|portable hotspot"


def test_normalizes_accents_and_hyphens(monkeypatch, capsys):
    xml = """
    <hierarchy>
      <node text="Punto de acceso portátil">
        <node checkable="true" checked="true" enabled="true"
              bounds="[10,20][110,80]" />
      </node>
    </hierarchy>
    """
    code, result = run_probe(monkeypatch, capsys, xml)
    assert code == 0
    assert result == "ON|60|50|punto de acceso portatil"


def test_refuses_ambiguous_or_unlabelled_checkbox(monkeypatch, capsys):
    ambiguous = """
    <hierarchy>
      <node text="Portable hotspot">
        <node checkable="true" checked="false" enabled="true" bounds="[0,0][10,10]" />
        <node checkable="true" checked="false" enabled="true" bounds="[20,0][30,10]" />
      </node>
    </hierarchy>
    """
    code, result = run_probe(monkeypatch, capsys, ambiguous)
    assert code == 1
    assert result == "UNKNOWN"

    unlabelled = """
    <hierarchy>
      <node text="Other setting">
        <node checkable="true" checked="false" enabled="true" bounds="[0,0][10,10]" />
      </node>
    </hierarchy>
    """
    code, result = run_probe(monkeypatch, capsys, unlabelled)
    assert code == 1
    assert result == "UNKNOWN"
