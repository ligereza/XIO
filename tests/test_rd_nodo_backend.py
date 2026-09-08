import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / "xio" / "new"
sys.path.insert(0, str(NEW))

import rd_nodo_build_pack  # noqa: E402
import rd_nodo_public_server  # noqa: E402


class RDNodoBackendTests(unittest.TestCase):
    def test_pack_reads_catalog_only_and_excludes_traceability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "rd.db"
            output = root / "public_pack.json"
            connection = sqlite3.connect(source)
            try:
                connection.execute(
                    "CREATE TABLE reactivos (id INTEGER, reactivo TEXT, familia TEXT, reaccion TEXT, hex TEXT)"
                )
                connection.execute(
                    "INSERT INTO reactivos VALUES (7, 'Marquis', 'presuntivo', 'orientativo', '#123456')"
                )
                connection.commit()
            finally:
                connection.close()

            rd_nodo_build_pack.write_json(output, rd_nodo_build_pack.build_pack(source, "piloto", publish=True))
            pack = json.loads(output.read_text(encoding="utf-8"))
            reagent = pack["testeo"]["reagents"][0]
            self.assertEqual(reagent["name"], "Marquis")
            self.assertEqual(pack["publication_status"], "ready")
            self.assertNotIn("id", reagent)
            self.assertNotIn("event_id", output.read_text(encoding="utf-8"))
            self.assertNotIn("source_row", output.read_text(encoding="utf-8"))

    def test_public_server_is_read_only_and_returns_no_private_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "public_pack.json").write_text(
                '{"schema_version":1,"publication_status":"ready"}', encoding="utf-8"
            )
            (root / "state.json").write_text(
                json.dumps({"notice": "normal", "zones": {"test": {"status": "espera"}}}),
                encoding="utf-8",
            )
            server = rd_nodo_public_server.RDPublicHTTPServer(
                ("127.0.0.1", 0),
                rd_nodo_public_server.RDPublicHandler,
                content_dir=root,
                state_file=root / "state.json",
                max_inflight=2,
                rate_limit=60,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                with urlopen(base + "/healthz", timeout=2) as response:
                    self.assertEqual(response.status, 200)
                with urlopen(base + "/api/state", timeout=2) as response:
                    state = json.loads(response.read())
                    self.assertEqual(state["zones"]["test"]["status"], "espera")
                    self.assertNotIn("rd.db", json.dumps(state))
                with urlopen(base + "/content/pack.json", timeout=2) as response:
                    self.assertEqual(json.loads(response.read())["schema_version"], 1)
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/api/state", method="POST"), timeout=2)
                self.assertEqual(error.exception.code, 405)
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + "/../state.json", timeout=2)
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
