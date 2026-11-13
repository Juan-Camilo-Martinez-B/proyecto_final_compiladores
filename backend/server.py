"""Servidor HTTP del compilador RPGScript (solo biblioteca estandar).

Uso:
    python server.py            # http://127.0.0.1:8000
    python server.py --port 9000

Rutas:
    POST /api/compile    {"source": "...", "register_count": 4} -> respuesta del contrato
    GET  /api/examples   lista los programas .rpg de backend/examples
    GET  /...            archivos estaticos de frontend/
"""
# ======================================================================
# server.py - Servidor web (API + vista web)
# ----------------------------------------------------------------------
# Un unico servidor sirve la API del compilador y los archivos de frontend/,
# asi la web y la API comparten origen (sin problemas de CORS).
#
# Flujo de una compilacion desde la web:
#   navegador --POST /api/compile--> do_POST -> parse_compile_request
#             -> compile_source() -> JSON con todas las fases -> navegador
#
# Seguridad:
#   - Solo escucha en 127.0.0.1 (no es accesible desde otros equipos).
#   - Limita el cuerpo de cada peticion a 64 KB (413 si se excede).
#   - Valida el JSON de entrada (400 si es invalido).
#   - Sirve archivos solo dentro de frontend/ (bloquea el path traversal).
#   - Nunca ejecuta el codigo del usuario como Python: solo lo compila.
# ======================================================================
import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from rpg_compiler.pipeline import compile_source

# Rutas absolutas, calculadas desde la ubicacion de este archivo.
BACKEND_DIR = Path(__file__).resolve().parent
EXAMPLES_DIR = BACKEND_DIR / "examples"
FRONTEND_DIR = (BACKEND_DIR.parent / "frontend").resolve()

HOST = "127.0.0.1"  # solo accesible desde el propio equipo
MAX_BODY_BYTES = 64 * 1024                               # tamano maximo de una peticion
MIN_REGISTERS, MAX_REGISTERS, DEFAULT_REGISTERS = 2, 16, 4

# Extension del archivo -> tipo de contenido que se envia al navegador.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


# Error de una peticion invalida. Guarda el codigo HTTP (400, 411, 413) y el
# mensaje en espanol que se devuelve al cliente.
class RequestError(Exception):
    """Error de validacion de la peticion, con su codigo HTTP."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# ----------------------------------------------------------------------
# CompilerRequestHandler: atiende cada peticion HTTP. http.server crea una
# instancia por peticion y llama a do_GET o do_POST segun el metodo.
# ----------------------------------------------------------------------
class CompilerRequestHandler(BaseHTTPRequestHandler):
    server_version = "RPGScriptServer/1.0"

    # ------------------------------------------------------------------
    # Enrutamiento
    # ------------------------------------------------------------------

    # GET: /api/examples devuelve los ejemplos; otra ruta /api/* es 404;
    # cualquier otra ruta se busca como archivo de frontend/.
    def do_GET(self) -> None:  # noqa: N802 - nombre exigido por BaseHTTPRequestHandler
        path = urlparse(self.path).path
        if path == "/api/examples":
            self._send_json(HTTPStatus.OK, {"examples": list_examples()})
        elif path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})
        else:
            self._serve_static(path)

    # POST /api/compile: valida la peticion, compila el codigo y responde con
    # el JSON del contrato. Una peticion invalida recibe su codigo de error.
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
    # Lee el cuerpo de la peticion validando Content-Length: debe existir
    # (411), ser un entero no negativo (400) y no superar 64 KB (413).
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

    # Envia un archivo de frontend/ con su tipo de contenido, o 404.
    def _serve_static(self, url_path: str) -> None:
        file_path = resolve_static_path(url_path)
        if file_path is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})
            return
        body = file_path.read_bytes()
        content_type = CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
        self._send(HTTPStatus.OK, body, content_type)

    # Responde con un JSON (UTF-8, sin cache: cada compilacion es distinta).
    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", cache=False)

    # Envia la respuesta HTTP: codigo, encabezados y cuerpo.
    # X-Content-Type-Options: nosniff impide que el navegador "adivine" otro
    # tipo de contenido (medida de seguridad).
    def _send(self, status: HTTPStatus, body: bytes, content_type: str, cache: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if not cache:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # Registro de cada peticion en la consola, con el prefijo [servidor].
    def log_message(self, format: str, *args) -> None:  # noqa: A002 - firma de la clase base
        sys.stderr.write(f"[servidor] {self.address_string()} - {format % args}\n")


# ----------------------------------------------------------------------
# Logica independiente del protocolo (facil de probar)
# ----------------------------------------------------------------------
# Valida el cuerpo de /api/compile:
#   - debe ser JSON valido en UTF-8 y un objeto;
#   - "source" es obligatorio y debe ser texto;
#   - "register_count" es opcional (4 por defecto), entero entre 2 y 16.
# Retorna (source, register_count) o lanza RequestError con codigo 400.
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


# Lista los programas .rpg de backend/examples con su contenido, en orden
# alfabetico. Se lee en cada peticion, asi un ejemplo nuevo aparece sin
# reiniciar el servidor.
def list_examples() -> list[dict]:
    return [{"name": path.name, "source": path.read_text(encoding="utf-8")}
            for path in sorted(EXAMPLES_DIR.glob("*.rpg"))]


# Traduce una URL a un archivo dentro de frontend/.
# PROTECCION CONTRA PATH TRAVERSAL: una URL como /../backend/server.py
# intentaria salir de la carpeta. resolve() calcula la ruta real (eliminando
# los ".."), y si el resultado no queda dentro de frontend/ se rechaza.
# Retorna la ruta del archivo, o None si no existe o no esta permitido.
def resolve_static_path(url_path: str) -> Path | None:
    """Traduce la URL a un archivo de frontend/, bloqueando el path traversal."""
    relative = unquote(url_path).lstrip("/") or "index.html"   # "/" sirve index.html
    candidate = (FRONTEND_DIR / relative).resolve()
    if not candidate.is_relative_to(FRONTEND_DIR):
        return None
    if candidate.is_dir():
        candidate = candidate / "index.html"
    return candidate if candidate.is_file() else None


# Crea el servidor en 127.0.0.1 y el puerto indicado. ThreadingHTTPServer
# atiende cada peticion en su propio hilo. Las pruebas usan el puerto 0
# (el sistema asigna uno libre).
def create_server(port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), CompilerRequestHandler)


# Punto de entrada: lee --port, inicia el servidor y lo mantiene activo hasta
# Ctrl + C. Si el puerto esta ocupado, muestra el error y retorna 1.
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
