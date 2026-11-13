"""Orquestador del pipeline: ninguna fase puede tumbar la aplicación."""
# ======================================================================
# pipeline.py - Orquestador del compilador
# ----------------------------------------------------------------------
# Conecta todas las fases en orden; la salida de cada una es la entrada de
# la siguiente:
#
#   codigo -> [1 lexer] -> tokens -> [2 parser] -> AST
#          -> [3 semantico] -> AST con tipos + tabla de simbolos
#          -> [4 memoria] -> frames, global, heap
#          -> [5 IR] -> cuadruplas TAC -> [6 codegen] -> pseudo-ensamblador
#                                      -> [maquina virtual] -> salida del programa
#
# Politica de detencion: si una fase tiene errores, las siguientes no se
# ejecutan (no tiene sentido generar codigo de un programa mal escrito).
# Ninguna fase puede tumbar la aplicacion: una excepcion inesperada se
# convierte en un diagnostico "interno".
#
# La respuesta es el CONTRATO JSON que consumen la CLI (main.py) y la web
# (server.py): {"success", "status", "diagnostics", "phases"}.
# ======================================================================
from .ast_nodes import node_to_dict
from .codegen import CodeGenerator
from .errors import ErrorReporter, Phase
from .ir_generator import IRGenerator
from .lexer import tokenize
from .memory_model import build_memory_layout
from .parser import Parser
from .semantic_analyzer import SemanticAnalyzer
from .vm import TacVM

# Claves de las fases en la respuesta, en orden de ejecucion.
PHASE_KEYS = ("tokens", "ast", "symbols", "memory", "ir", "assembly", "execution")
# La ejecucion no es parte de la compilacion: un error en tiempo de ejecucion
# (por ejemplo, division entre cero) no convierte la compilacion en fallida.
COMPILE_PHASES = PHASE_KEYS[:-1]


# ----------------------------------------------------------------------
# _PhaseRunner: ejecuta cada fase de forma aislada y guarda su resultado.
#   phases : resultado serializado de cada fase (None si no se ejecuto).
#   status : estado de cada fase: "ok", "error", "skipped" o "not_implemented".
# ----------------------------------------------------------------------
class _PhaseRunner:
    """Ejecuta cada fase de forma aislada y registra su estado."""

    # Todas las fases empiezan como "skipped": si el pipeline se detiene antes,
    # quedan marcadas como omitidas.
    def __init__(self, reporter: ErrorReporter) -> None:
        self._reporter = reporter
        self.phases = {key: None for key in PHASE_KEYS}
        self.status = {key: "skipped" for key in PHASE_KEYS}

    # Ejecuta una fase.
    #   key       : clave de la fase en la respuesta ("tokens", "ast", ...).
    #   phase     : Phase con la que esa fase reporta sus diagnosticos.
    #   action    : funcion sin argumentos que ejecuta la fase y retorna su resultado.
    #   serialize : funcion que convierte el resultado a JSON.
    #   failed    : opcional; decide si el resultado es un fallo aunque no haya
    #               diagnosticos (lo usa la ejecucion, que guarda su error aparte).
    # Retorna el resultado de la fase, o None si fallo con una excepcion.
    def run(self, key, phase, action, serialize, failed=None):
        """failed(value) permite marcar error en fases que no reportan diagnosticos."""
        try:
            value = action()
            self.phases[key] = serialize(value)
        except NotImplementedError:
            # Una fase aun sin implementar (los stubs de la Fase 0).
            self.status[key] = "not_implemented"
            self._reporter.warning(phase, f"La fase '{key}' aún no está implementada.", 0, 0)
            return None
        except Exception as exc:  # noqa: BLE001 - se convierte en diagnóstico interno
            # Cualquier error inesperado del compilador: no tumba el servidor.
            self.status[key] = "error"
            self._reporter.error(Phase.INTERNAL, f"Error interno en la fase '{key}': {exc}", 0, 0)
            return None
        has_failed = self._reporter.has_errors(phase) or (failed is not None and failed(value))
        self.status[key] = "error" if has_failed else "ok"
        return value

    # La siguiente fase solo corre si esta termino en "ok".
    def can_continue(self, key) -> bool:
        return self.status[key] == "ok"

    # Arma la respuesta final del contrato. "success" indica que la
    # COMPILACION salio bien; la ejecucion tiene su propio estado.
    def response(self) -> dict:
        success = (not self._reporter.has_errors()
                   and all(self.status[key] == "ok" for key in COMPILE_PHASES))
        return {"success": success, "status": self.status,
                "diagnostics": self._reporter.to_list(), "phases": self.phases}


# ----------------------------------------------------------------------
# compile_source(source, register_count): punto de entrada del compilador.
#   source         : codigo fuente RPGScript.
#   register_count : registros de la CPU simulada para la fase 6 (por defecto 4).
# Retorna el diccionario del contrato JSON, aunque haya errores.
# ----------------------------------------------------------------------
def compile_source(source: str, register_count: int = 4) -> dict:
    """Compila el código fuente y devuelve la respuesta del contrato de la API."""
    reporter = ErrorReporter()          # un solo acumulador para todas las fases
    runner = _PhaseRunner(reporter)

    # Fase 1: lexico. Con errores lexicos no tiene sentido parsear.
    tokens = runner.run("tokens", Phase.LEXICAL, lambda: tokenize(source, reporter),
                        lambda value: [token.to_dict() for token in value])
    if not runner.can_continue("tokens"):
        return runner.response()

    # Fase 2: sintactico. Construye el AST.
    program = runner.run("ast", Phase.SYNTAX, lambda: Parser(tokens, reporter).parse(),
                         node_to_dict)
    if not runner.can_continue("ast"):
        return runner.response()

    # Fase 3: semantico. Tabla de simbolos, tipos y anotacion del AST.
    semantic = runner.run("symbols", Phase.SEMANTIC,
                          lambda: SemanticAnalyzer(reporter).analyze(program),
                          lambda value: value.to_dict())
    if not runner.can_continue("symbols"):
        return runner.response()
    # El AST se vuelve a serializar para incluir los inferred_type del semántico.
    runner.phases["ast"] = node_to_dict(program)

    # Fase 4: modelo de memoria (no bloquea las siguientes fases).
    runner.run("memory", Phase.SEMANTIC, lambda: build_memory_layout(semantic),
               lambda value: value.to_dict())

    # Fase 5: codigo intermedio (cuadruplas). Las fases 6 y la ejecucion lo necesitan.
    quads = runner.run("ir", Phase.IR, lambda: IRGenerator().generate(program),
                       lambda value: [quad.to_dict(i) for i, quad in enumerate(value)])
    if not runner.can_continue("ir"):
        return runner.response()

    # Fase 6: pseudo-ensamblador con asignacion de registros.
    runner.run("assembly", Phase.CODEGEN,
               lambda: CodeGenerator(register_count).generate(quads),
               lambda value: value.to_dict())

    # La maquina virtual ejecuta el TAC; necesita la tabla de simbolos para
    # distinguir variables locales de globales.
    runner.run("execution", Phase.RUNTIME,
               lambda: TacVM.from_symbols(semantic.symbols).run(quads),
               lambda value: value.to_dict(),
               failed=lambda value: value.error is not None)
    return runner.response()
