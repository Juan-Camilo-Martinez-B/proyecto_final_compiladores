"""Orquestador del pipeline: ninguna fase puede tumbar la aplicación."""
from .ast_nodes import node_to_dict
from .codegen import CodeGenerator
from .errors import ErrorReporter, Phase
from .ir_generator import IRGenerator
from .lexer import tokenize
from .memory_model import build_memory_layout
from .parser import Parser
from .semantic_analyzer import SemanticAnalyzer
from .vm import TacVM

PHASE_KEYS = ("tokens", "ast", "symbols", "memory", "ir", "assembly", "execution")
# La ejecucion no es parte de la compilacion: un error en tiempo de ejecucion
# (por ejemplo, division entre cero) no convierte la compilacion en fallida.
COMPILE_PHASES = PHASE_KEYS[:-1]


class _PhaseRunner:
    """Ejecuta cada fase de forma aislada y registra su estado."""

    def __init__(self, reporter: ErrorReporter) -> None:
        self._reporter = reporter
        self.phases = {key: None for key in PHASE_KEYS}
        self.status = {key: "skipped" for key in PHASE_KEYS}

    def run(self, key, phase, action, serialize, failed=None):
        """failed(value) permite marcar error en fases que no reportan diagnosticos."""
        try:
            value = action()
            self.phases[key] = serialize(value)
        except NotImplementedError:
            self.status[key] = "not_implemented"
            self._reporter.warning(phase, f"La fase '{key}' aún no está implementada.", 0, 0)
            return None
        except Exception as exc:  # noqa: BLE001 - se convierte en diagnóstico interno
            self.status[key] = "error"
            self._reporter.error(Phase.INTERNAL, f"Error interno en la fase '{key}': {exc}", 0, 0)
            return None
        has_failed = self._reporter.has_errors(phase) or (failed is not None and failed(value))
        self.status[key] = "error" if has_failed else "ok"
        return value

    def can_continue(self, key) -> bool:
        return self.status[key] == "ok"

    def response(self) -> dict:
        success = (not self._reporter.has_errors()
                   and all(self.status[key] == "ok" for key in COMPILE_PHASES))
        return {"success": success, "status": self.status,
                "diagnostics": self._reporter.to_list(), "phases": self.phases}


def compile_source(source: str, register_count: int = 4) -> dict:
    """Compila el código fuente y devuelve la respuesta del contrato de la API."""
    reporter = ErrorReporter()
    runner = _PhaseRunner(reporter)

    tokens = runner.run("tokens", Phase.LEXICAL, lambda: tokenize(source, reporter),
                        lambda value: [token.to_dict() for token in value])
    if not runner.can_continue("tokens"):
        return runner.response()

    program = runner.run("ast", Phase.SYNTAX, lambda: Parser(tokens, reporter).parse(),
                         node_to_dict)
    if not runner.can_continue("ast"):
        return runner.response()

    semantic = runner.run("symbols", Phase.SEMANTIC,
                          lambda: SemanticAnalyzer(reporter).analyze(program),
                          lambda value: value.to_dict())
    if not runner.can_continue("symbols"):
        return runner.response()
    # El AST se vuelve a serializar para incluir los inferred_type del semántico.
    runner.phases["ast"] = node_to_dict(program)

    runner.run("memory", Phase.SEMANTIC, lambda: build_memory_layout(semantic),
               lambda value: value.to_dict())

    quads = runner.run("ir", Phase.IR, lambda: IRGenerator().generate(program),
                       lambda value: [quad.to_dict(i) for i, quad in enumerate(value)])
    if not runner.can_continue("ir"):
        return runner.response()

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
