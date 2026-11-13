"""CLI del compilador RPGScript: muestra la evolucion del programa fase por fase.

Uso:
    python main.py examples/batalla_ok.rpg
    python main.py examples/batalla_ok.rpg --phase tokens
    python main.py examples/batalla_ok.rpg --json
    python main.py examples/spill_registros.rpg --registers 2
    python main.py examples/notas.rpg --run        # compila y solo muestra lo que imprime el programa

Solo depende de pipeline.compile_source(): imprime a partir del diccionario del
contrato de la API, igual que lo consume la vista web.
"""
# ======================================================================
# main.py - Interfaz de linea de comandos (CLI)
# ----------------------------------------------------------------------
# Lee un archivo .rpg, lo compila con pipeline.compile_source() e imprime
# cada fase como tablas de texto. No importa los modulos de las fases:
# trabaja solo con el diccionario del contrato JSON, igual que la web, asi
# la consola y la web siempre muestran lo mismo.
#
# Modos:
#   (sin opciones)  todas las fases y los diagnosticos.
#   --phase X       una sola fase: tokens, ast, symbols, memory, ir, asm o run.
#   --json          la respuesta completa en JSON.
#   --run           solo la salida del programa, como al ejecutar un binario.
#   --registers N   registros de la CPU simulada (2 a 16).
#
# Codigo de salida: 0 si compila y se ejecuta sin errores; 1 en otro caso.
# ======================================================================
import argparse
import json
import sys
from pathlib import Path

from rpg_compiler.pipeline import compile_source

# Nombres de fase que acepta --phase, en orden de impresion.
PHASES = ("tokens", "ast", "symbols", "memory", "ir", "asm", "run")
# Opcion de la CLI -> (clave de la fase en el contrato, titulo que se imprime).
PHASE_TITLES = {
    "tokens": ("tokens", "FASE 1: TOKENS (ANÁLISIS LÉXICO)"),
    "ast": ("ast", "FASE 2: ÁRBOL DE SINTAXIS ABSTRACTA (AST)"),
    "symbols": ("symbols", "FASE 3: TABLA DE SÍMBOLOS Y ÁMBITOS"),
    "memory": ("memory", "FASE 4: MODELO DE MEMORIA"),
    "ir": ("ir", "FASE 5: CÓDIGO DE TRES DIRECCIONES (CUÁDRUPLAS)"),
    "asm": ("assembly", "FASE 6: PSEUDO-ENSAMBLADOR"),
    "run": ("execution", "EJECUCIÓN (MÁQUINA VIRTUAL DE TAC)"),
}
# Texto que se muestra cuando una fase no produjo datos.
STATUS_LABELS = {
    "skipped": "(fase omitida por errores en una fase anterior)",
    "not_implemented": "(fase aún no implementada)",
}
MAX_SOURCE_BYTES = 64 * 1024   # tamano maximo del archivo fuente (64 KB)


# ----------------------------------------------------------------------
# main(argv): punto de entrada de la CLI.
#   argv : argumentos de la linea de comandos (None = los reales); las
#          pruebas pasan una lista para simular la ejecucion.
# Pasos: configura la consola, lee los argumentos y el archivo, compila y
# muestra el resultado segun el modo elegido. Retorna el codigo de salida.
# ----------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    _configure_console()
    args = _parse_args(argv)

    source = _read_source(args.file)
    if source is None:
        return 1

    result = compile_source(source, register_count=args.registers)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return _exit_code(result)
    if args.run:
        return _run_only(result)

    # Modo normal: imprime las fases pedidas y al final los diagnosticos.
    selected = PHASES if args.phase == "all" else (args.phase,)
    for phase in selected:
        key, title = PHASE_TITLES[phase]
        _print_phase(title, key, result)
    _print_diagnostics(result["diagnostics"])
    return _exit_code(result)


# Codigo de salida del proceso (util para scripts): 0 = todo bien, 1 = error.
def _exit_code(result: dict) -> int:
    """0 solo si compilo sin errores y la ejecucion no fallo."""
    return 0 if result["success"] and result["status"].get("execution") != "error" else 1


# Modo --run: si el programa compila, imprime solo lo que imprimio la maquina
# virtual. Un error de ejecucion va a la salida de errores (stderr).
def _run_only(result: dict) -> int:
    """Modo --run: como ejecutar un programa compilado, solo se ve su salida."""
    if not result["success"]:
        print("El programa no compila; no se puede ejecutar.", file=sys.stderr)
        _print_diagnostics(result["diagnostics"])
        return 1
    execution = result["phases"].get("execution") or {}
    for line in execution.get("output", []):
        print(line)
    if execution.get("error"):
        sys.stdout.flush()  # la salida del programa debe verse antes que el error
        print(_runtime_error_text(execution["error"]), file=sys.stderr)
    return _exit_code(result)


# Mensaje de un error de ejecucion con la instruccion TAC donde ocurrio.
def _runtime_error_text(error: dict) -> str:
    return (f"Error en tiempo de ejecución en la instrucción {error['instruction']} "
            f"({error['text']}): {error['message']}")


# ----------------------------------------------------------------------
# Entrada
# ----------------------------------------------------------------------
def _configure_console() -> None:
    # La consola de Windows no usa UTF-8 por defecto; sin esto fallan las tildes y el arbol.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


# Define y lee las opciones de la linea de comandos con argparse.
def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compilador de RPGScript: muestra cada fase del pipeline.")
    parser.add_argument("file", help="archivo fuente con extensión .rpg")
    parser.add_argument("--phase", choices=(*PHASES, "all"), default="all",
                        help="fase a mostrar (por defecto: all)")
    parser.add_argument("--json", action="store_true", help="imprime la respuesta completa en JSON")
    parser.add_argument("--registers", type=_register_count, default=4,
                        help="cantidad de registros de la CPU simulada (2 a 16, por defecto 4)")
    parser.add_argument("--run", action="store_true",
                        help="ejecuta el programa y muestra solo lo que imprime")
    return parser.parse_args(argv)


# Valida --registers: debe ser un entero entre 2 y 16. Si no, argparse
# muestra el mensaje y termina.
def _register_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("debe ser un número entero") from None
    if not 2 <= count <= 16:
        raise argparse.ArgumentTypeError("debe estar entre 2 y 16")
    return count


# Lee el archivo fuente validando extension .rpg, que exista, el tamano maximo
# y la codificacion UTF-8. Retorna el texto, o None (con el mensaje ya impreso).
def _read_source(file_name: str) -> str | None:
    path = Path(file_name)
    if path.suffix != ".rpg":
        print(f"Error: el archivo '{file_name}' debe tener extensión .rpg.", file=sys.stderr)
        return None
    if not path.is_file():
        print(f"Error: no se encontró el archivo '{file_name}'.", file=sys.stderr)
        return None
    if path.stat().st_size > MAX_SOURCE_BYTES:
        print("Error: el archivo supera el tamaño máximo de 64 KB.", file=sys.stderr)
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"Error: el archivo '{file_name}' no está codificado en UTF-8.", file=sys.stderr)
        return None


# ----------------------------------------------------------------------
# Impresion de fases
# ----------------------------------------------------------------------
# Imprime el titulo de una fase y despacha a su funcion de impresion. Si la
# fase no produjo datos, muestra por que (omitida o no implementada).
def _print_phase(title: str, key: str, result: dict) -> None:
    print(f"\n=== {title} ===")
    data = result["phases"].get(key)
    status = result["status"].get(key, "skipped")
    if data is None:
        print(STATUS_LABELS.get(status, "(sin datos)"))
        return
    printers = {
        "tokens": _print_tokens, "ast": _print_ast, "symbols": _print_symbols,
        "memory": _print_memory, "ir": _print_ir, "assembly": _print_assembly,
        "execution": _print_execution,
    }
    printers[key](data)


# Fase 1: tabla con numero, tipo, lexema, linea y columna de cada token.
def _print_tokens(tokens: list[dict]) -> None:
    rows = [(i + 1, t["type"], t["lexeme"], t["line"], t["column"]) for i, t in enumerate(tokens)]
    _print_table(("#", "TIPO", "LEXEMA", "LÍNEA", "COL"), rows)


# Fase 2: dibuja el AST como arbol de texto, empezando por la raiz.
def _print_ast(ast: dict) -> None:
    print(_node_label(ast))
    _print_children(ast, prefix="")


# Dibuja los hijos de un nodo de forma recursiva. El ultimo hijo usa "└──" y
# los demas "├──"; prefix acumula las lineas verticales de los niveles de arriba.
def _print_children(node: dict, prefix: str) -> None:
    children = _ast_children(node)
    for index, child in enumerate(children):
        last = index == len(children) - 1
        print(f"{prefix}{'└── ' if last else '├── '}{_node_label(child)}")
        _print_children(child, prefix + ("    " if last else "│   "))


# Hijos de un nodo serializado: todos los valores que son nodos o listas de
# nodos, en el orden de sus campos.
def _ast_children(node: dict) -> list[dict]:
    if node.get("node") == "FuncDecl":
        return [node["body"]]  # los parametros ya aparecen en la etiqueta
    children = []
    for name, value in node.items():
        if isinstance(value, dict) and "node" in value:
            children.append(value)
        elif isinstance(value, list):
            children.extend(item for item in value if isinstance(item, dict) and "node" in item)
    return children


# Texto de un nodo: su tipo, sus datos clave, el tipo inferido y su posicion.
# Ejemplo: "BinaryOp '-' : int  [2:16]".
def _node_label(node: dict) -> str:
    kind = node.get("node", "?")
    labels = {
        "Literal": lambda n: f"Literal {json.dumps(n.get('value'), ensure_ascii=False)}",
        "Identifier": lambda n: f"Identifier {n.get('name')}",
        "BinaryOp": lambda n: f"BinaryOp '{n.get('operator')}'",
        "UnaryOp": lambda n: f"UnaryOp '{n.get('operator')}'",
        "Call": lambda n: f"Call {n.get('callee')}()",
        "VarDecl": lambda n: f"VarDecl {n.get('type_name')} {n.get('name')}",
        "Assign": lambda n: f"Assign {n.get('name')}",
        "FuncDecl": lambda n: "FuncDecl {}({}) -> {}".format(
            n.get("name"), ", ".join(f"{p['type_name']} {p['name']}" for p in n.get("params", [])),
            n.get("return_type")),
    }
    label = labels.get(kind, lambda n: kind)(node)
    if node.get("inferred_type"):
        label += f" : {node['inferred_type']}"
    return f"{label}  [{node.get('line')}:{node.get('column')}]"


# Fase 3: una fila por simbolo agrupada por ambito, y despues la traza de la
# pila de ambitos paso a paso.
def _print_symbols(symbols: dict) -> None:
    rows = []
    for scope in symbols.get("scopes", []):
        entries = scope.get("symbols", [])
        if not entries:
            rows.append((scope["name"], scope.get("level"), "(sin símbolos)", "", "", "", ""))
        for symbol in entries:
            signature = ""
            if symbol.get("kind") == "function":
                signature = f"({', '.join(symbol.get('params') or [])}) -> {symbol.get('return_type')}"
            rows.append((scope["name"], scope.get("level"), symbol["name"], symbol["type"],
                         symbol["kind"], symbol["line"], signature))
    _print_table(("ÁMBITO", "NIVEL", "SÍMBOLO", "TIPO", "CLASE", "LÍNEA", "FIRMA"), rows)

    trace = symbols.get("trace", [])
    if trace:
        print("\nTraza de la pila de ámbitos:")
        for event in trace:
            print("  " + _trace_line(event))


# Traduce un evento de la traza (enter_scope, exit_scope, define, lookup) a
# una frase en espanol.
def _trace_line(event: dict) -> str:
    action = event.get("action")
    step = f"{event.get('step', '')}.".ljust(5)
    line = f"(línea {event.get('line')})"
    if action == "enter_scope":
        return f"{step}entra al ámbito '{event.get('scope')}' {line}"
    if action == "exit_scope":
        return f"{step}sale del ámbito '{event.get('scope')}' {line}"
    if action == "define":
        return f"{step}define '{event.get('name')}' en '{event.get('scope')}' {line}"
    found = event.get("found_in")
    result = f"encontrado en '{found}'" if found else "NO encontrado"
    return f"{step}lookup '{event.get('name')}' desde '{event.get('scope')}': {result} {line}"


# Fase 4: segmento global, un bloque por frame y el heap de cadenas.
def _print_memory(memory: dict) -> None:
    globals_segment = memory.get("globals", {})
    print(f"Segmento global (data) · {globals_segment.get('size', 0)} bytes")
    _print_slots(globals_segment.get("slots", []))
    for frame in memory.get("frames", []):
        print(f"\nFrame de '{frame.get('function')}' · {frame.get('size', 0)} bytes")
        _print_slots(frame.get("slots", []))
    heap = memory.get("heap", [])
    if heap:
        print("\nHeap (cadenas)")
        _print_table(("DIRECCIÓN", "VALOR", "TAMAÑO"),
                     [(h["address"], json.dumps(h["value"], ensure_ascii=False), h["size"]) for h in heap])


# Tabla de slots: desplazamiento, nombre, tipo, clase y tamano.
def _print_slots(slots: list[dict]) -> None:
    rows = [(f"+{s['offset']}", s["name"], s.get("type") or "-", s.get("kind", ""), s["size"]) for s in slots]
    _print_table(("OFFSET", "NOMBRE", "TIPO", "CLASE", "BYTES"), rows)


# Fase 5: tabla de cuadruplas (op, arg1, arg2, result) y su texto TAC.
def _print_ir(quads: list[dict]) -> None:
    rows = [(q["index"], q["op"], _dash(q.get("arg1")), _dash(q.get("arg2")), _dash(q.get("result")), q.get("text", ""))
            for q in quads]
    _print_table(("#", "OP", "ARG1", "ARG2", "RESULT", "TAC"), rows)


# Fase 6: listado numerado del ensamblador y tabla de spills.
def _print_assembly(assembly: dict) -> None:
    for index, instruction in enumerate(assembly.get("instructions", [])):
        print(f"{index:>4}  {instruction}")
    spills = assembly.get("spills", [])
    print(f"\nRegistros disponibles: {assembly.get('register_count')} · Spills: {len(spills)}")
    if spills:
        _print_table(("VARIABLE", "SLOT", "INSTRUCCIÓN"),
                     [(s["variable"], s["slot"], s["instruction"]) for s in spills])


# Ejecucion: lo que imprimio el programa y como termino.
def _print_execution(execution: dict) -> None:
    print("--- salida del programa ---")
    for line in execution.get("output", []):
        print(line)
    if not execution.get("output"):
        print("(el programa no imprimió nada)")
    print("---")
    if execution.get("error"):
        print(_runtime_error_text(execution["error"]))
    else:
        print(f"Programa terminado: {execution.get('steps', 0)} instrucciones TAC ejecutadas.")


# Lista de errores y advertencias con su fase y posicion, y un resumen final.
def _print_diagnostics(diagnostics: list[dict]) -> None:
    print("\n=== DIAGNÓSTICOS ===")
    errors = [d for d in diagnostics if d["severity"] == "error"]
    warnings = [d for d in diagnostics if d["severity"] == "warning"]
    for d in diagnostics:
        print(f"[{d['phase'].upper()}] {d['severity']} en línea {d['line']}, columna {d['column']}: {d['message']}")
    if not errors and not warnings:
        print("Compilación exitosa: sin errores ni advertencias.")
    else:
        print(f"\nResumen: {len(errors)} error(es), {len(warnings)} advertencia(s).")


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
# Muestra "-" en lugar de None en las tablas.
def _dash(value) -> str:
    return "-" if value is None else str(value)


# Imprime una tabla de texto alineada: calcula el ancho de cada columna (el
# mas largo entre el encabezado y sus valores) y rellena con espacios.
def _print_table(headers: tuple, rows: list[tuple]) -> None:
    text_rows = [[str(value) for value in row] for row in rows]
    widths = [max([len(header)] + [len(row[i]) for row in text_rows]) for i, header in enumerate(headers)]
    print("  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)).rstrip())
    print("  ".join("-" * width for width in widths))
    for row in text_rows:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)).rstrip())


if __name__ == "__main__":
    sys.exit(main())
