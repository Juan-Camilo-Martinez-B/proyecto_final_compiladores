# ======================================================================
# Pruebas del servidor web (server.py).
# Levantan un servidor real en un puerto libre y le hacen peticiones HTTP:
# contrato de /api/compile, validaciones (400, 413), /api/examples, archivos
# estaticos y la proteccion contra path traversal.
#
# Ejecutar (desde backend/): python -m unittest tests.test_server -v
# ======================================================================
import json
import threading
import unittest
import urllib.error
import urllib.request

import server


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.CompilerRequestHandler.log_message = lambda *args: None  # silencia los logs en las pruebas
        cls.httpd = server.create_server(0)
        cls.base = f"http://{server.HOST}:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def test_compile_returns_contract(self):
        status, headers, body = self.request("/api/compile", {"source": "int vida = 100;"})
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(set(data), {"success", "status", "diagnostics", "phases"})
        self.assertEqual(data["status"]["tokens"], "ok")

    def test_invalid_json_is_rejected(self):
        status, _, body = self.request("/api/compile", raw=b"{no es json")
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))

    def test_source_must_be_text(self):
        self.assertEqual(self.request("/api/compile", {"source": 5})[0], 400)
        self.assertEqual(self.request("/api/compile", {})[0], 400)

    def test_register_count_is_validated(self):
        self.assertEqual(self.request("/api/compile", {"source": "", "register_count": 1})[0], 400)
        self.assertEqual(self.request("/api/compile", {"source": "", "register_count": True})[0], 400)
        self.assertEqual(self.request("/api/compile", {"source": "", "register_count": 8})[0], 200)

    def test_body_too_large(self):
        big = json.dumps({"source": "a" * (server.MAX_BODY_BYTES + 1)}).encode()
        self.assertEqual(self.request("/api/compile", raw=big)[0], 413)

    def test_examples_endpoint(self):
        status, _, body = self.request("/api/examples")
        names = [example["name"] for example in json.loads(body)["examples"]]
        self.assertEqual(status, 200)
        self.assertIn("batalla_ok.rpg", names)

    def test_serves_frontend_index(self):
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"RPGScript", body)

    def test_blocks_path_traversal(self):
        self.assertEqual(self.request("/../backend/server.py")[0], 404)
        self.assertEqual(self.request("/%2e%2e/backend/server.py")[0], 404)
        self.assertIsNone(server.resolve_static_path("/../../README.md"))

    def test_unknown_routes(self):
        self.assertEqual(self.request("/api/nada")[0], 404)
        self.assertEqual(self.request("/api/otra", {"source": ""})[0], 404)


if __name__ == "__main__":
    unittest.main()
