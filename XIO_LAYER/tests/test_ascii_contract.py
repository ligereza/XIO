"""Ensure technical source files remain ASCII-only."""

from pathlib import Path
import unittest


TECHNICAL_SUFFIXES = {".json", ".py", ".toml", ".yaml", ".yml"}


class TechnicalAsciiContractTests(unittest.TestCase):
    def test_technical_files_are_ascii_only(self):
        root = Path(__file__).resolve().parents[1]
        offenders = []
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in TECHNICAL_SUFFIXES:
                data = path.read_bytes()
                if any(byte > 127 for byte in data):
                    offenders.append(path.relative_to(root).as_posix())
        self.assertEqual(offenders, [], "Non-ASCII technical files: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
