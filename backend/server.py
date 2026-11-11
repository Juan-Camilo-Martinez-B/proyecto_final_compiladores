"""Servidor HTTP del compilador RPGScript (solo biblioteca estandar).

Uso:
    python server.py            # http://127.0.0.1:8000
    python server.py --port 9000

Rutas:
    POST /api/compile    {"source": "...", "register_count": 4} -> respuesta del contrato
    GET  /api/examples   lista los programas .rpg de backend/examples
    GET  /...            archivos estaticos de frontend/
"""
import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from rpg_compiler.pipeline import compile_source

BACKEND_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = BACKEND_DIR / "examples"
FRONTEND_DIR = (BACKEND_DIR.parent / "frontend").resolve()

HOST = "127.0.0.1"  # solo accesible desde el propio equipo
MAX_BODY_BYTES = 64 * 1024
MIN_REGISTERS, MAX_REGISTERS, DEFAULT_REGISTERS = 2, 16, 4

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class RequestError(Exception):
    """Error de validacion de la peticion, con su codigo HTTP."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class CompilerRequestHandler(BaseHTTPRequestHandler):
    server_version = "RPGScriptServer/1.0"

    # ------------------------------------------------------------------
    # Enrutamiento
    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - nombre exigido por BaseHTTPRequestHandler
        path = urlparse(self.path).path
        if path == "/api/examples":
            self._send_json(HTTPStatus.OK, {"examples": list_examples()})
        elif path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})
        else:
            self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/compile":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})
            return
        try:
            source, register_count = parse_compile_request(self._read_body())
        except RequestError as error:
            self._send_json(error.status, {"error": error.message})
            return
        self._send_json(HTTPStatus.OK, compile_source(source, register_count=register_count))

    # ------------------------------------------------------------------
    # Utilidades de la peticion y la respuesta
    # ------------------------------------------------------------------
    def _read_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise RequestError(HTTPStatus.LENGTH_REQUIRED, "Falta el encabezado Content-Length.")
        try:
            length = int(raw_length)
        except ValueError:
            raise RequestError(HTTPStatus.BAD_REQUEST, "Content-Length inválido.") from None
        if length < 0:
            raise RequestError(HTTPStatus.BAD_REQUEST, "Content-Length inválido.")
        if length > MAX_BODY_BYTES:
            raise RequestError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                               "El código fuente supera el tamaño máximo de 64 KB.")
        return self.rfile.read(length)

    def _serve_static(self, url_path: str) -> None:
        file_path = resolve_static_path(url_path)
        if file_path is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})
            return
        body = file_path.read_bytes()
        content_type = CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
        self._send(HTTPStatus.OK, body, content_type)

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", cache=False)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str, cache: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if not cache:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - firma de la clase base
        sys.stderr.write(f"[servidor] {self.address_string()} - {format % args}\n")


# ----------------------------------------------------------------------
# Logica independiente del protocolo (facil de probar)
# ----------------------------------------------------------------------
def parse_compile_request(body: bytes) -> tuple[str, int]:
    """Valida el cuerpo JSON de /api/compile y devuelve (source, register_count)."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RequestError(HTTPStatus.BAD_REQUEST, "El cuerpo de la petición debe ser JSON válido en UTF-8.") from None
    if not isinstance(payload, dict):
        raise RequestError(HTTPStatus.BAD_REQUEST, "El cuerpo debe ser un objeto JSON.")

    source = payload.get("source")
    if not isinstance(source, str):
        raise RequestError(HTTPStatus.BAD_REQUEST, "El campo 'source' es obligatorio y debe ser texto.")

    register_count = payload.get("register_count", DEFAULT_REGISTERS)
    # bool es subclase de int en Python, por eso se excluye explicitamente.
    if isinstance(register_count, bool) or not isinstance(register_count, int) \
            or not MIN_REGISTERS <= register_count <= MAX_REGISTERS:
        raise RequestError(HTTPStatus.BAD_REQUEST,
                           f"'register_count' debe ser un entero entre {MIN_REGISTERS} y {MAX_REGISTERS}.")
    return source, register_count


def list_examples() -> list[dict]:
    return [{"name": path.name, "source": path.read_text(encoding="utf-8")}
            for path in sorted(EXAMPLES_DIR.glob("*.rpg"))]


def resolve_static_path(url_path: str) -> Path | None:
    """Traduce la URL a un archivo de frontend/, bloqueando el path traversal."""
    relative = unquote(url_path).lstrip("/") or "index.html"
    candidate = (FRONTEND_DIR / relative).resolve()
    if not candidate.is_relative_to(FRONTEND_DIR):
        return None
    if candidate.is_dir():
        candidate = candidate / "index.html"
    return candidate if candidate.is_file() else None


def create_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), CompilerRequestHandler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Servidor web del compilador RPGScript.")
    parser.add_argument("--port", type=int, default=8000, help="puerto (por defecto 8000)")
    args = parser.parse_args(argv)

    try:
        server = create_server(args.port)
    except OSError as error:
        print(f"No se pudo iniciar el servidor en el puerto {args.port}: {error}", file=sys.stderr)
        return 1
    print(f"Servidor de RPGScript en http://{HOST}:{args.port} (Ctrl + C para detener)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
