"""Diagnósticos compartidos: permiten reportar todos los errores sin detener el análisis."""
# ======================================================================
# errors.py - Diagnosticos de todas las fases
# ----------------------------------------------------------------------
# Un compilador no debe detenerse en el primer error: debe reportarlos todos,
# con la linea y la columna exactas. Para eso todas las fases comparten un
# ErrorReporter, donde van acumulando diagnosticos (errores y advertencias).
# Al final, el pipeline decide con has_errors() si la siguiente fase puede
# ejecutarse.
# ======================================================================
from dataclasses import dataclass
from enum import Enum


# ----------------------------------------------------------------------
# Phase: fase del compilador que produjo el diagnostico.
# El valor (en espanol) es el que se muestra en la CLI y en la web.
# ----------------------------------------------------------------------
class Phase(str, Enum):
    LEXICAL = "lexico"        # lexer.py
    SYNTAX = "sintactico"     # parser.py
    SEMANTIC = "semantico"    # semantic_analyzer.py
    IR = "ir"                 # ir_generator.py
    CODEGEN = "codegen"       # codegen.py
    RUNTIME = "ejecucion"     # vm.py (errores al ejecutar)
    INTERNAL = "interno"      # excepcion inesperada capturada por pipeline.py


# ----------------------------------------------------------------------
# Severity: gravedad del diagnostico.
#   ERROR   : el programa es invalido; detiene el pipeline al final de la fase.
#   WARNING : algo sospechoso pero legal (por ejemplo, shadowing); no detiene.
# ----------------------------------------------------------------------
class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


# ----------------------------------------------------------------------
# Diagnostic: un error o advertencia con su ubicacion exacta.
# Es inmutable (frozen=True). line y column valen 0 cuando el problema no
# corresponde a una posicion del fuente (por ejemplo, un error interno).
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Diagnostic:
    phase: Phase
    severity: Severity
    message: str
    line: int
    column: int

    # Formato JSON del contrato de la API.
    def to_dict(self) -> dict:
        return {"phase": self.phase.value, "severity": self.severity.value,
                "message": self.message, "line": self.line, "column": self.column}

    # Formato de texto para la consola, por ejemplo:
    # [SEMANTICO] error en linea 6, columna 13: El operador '-' no esta definido...
    def __str__(self) -> str:
        return (f"[{self.phase.value.upper()}] {self.severity.value} en línea {self.line}, "
                f"columna {self.column}: {self.message}")


# ----------------------------------------------------------------------
# ErrorReporter: acumulador de diagnosticos.
# Se crea uno por compilacion (en pipeline.compile_source) y se pasa a cada
# fase. Las fases solo agregan; nunca lanzan una excepcion por un error del
# programa del usuario.
# ----------------------------------------------------------------------
class ErrorReporter:
    """Acumula los diagnósticos de todas las fases."""

    def __init__(self) -> None:
        self._diagnostics: list[Diagnostic] = []

    # Registra un error de la fase indicada en la posicion (line, column).
    def error(self, phase: Phase, message: str, line: int, column: int) -> None:
        self._diagnostics.append(Diagnostic(phase, Severity.ERROR, message, line, column))

    # Registra una advertencia: se muestra al usuario pero no detiene el pipeline.
    def warning(self, phase: Phase, message: str, line: int, column: int) -> None:
        self._diagnostics.append(Diagnostic(phase, Severity.WARNING, message, line, column))

    # Indica si hay errores (no advertencias).
    #   phase=None : de cualquier fase.
    #   phase=X    : solo de esa fase. El pipeline la usa para decidir si sigue.
    def has_errors(self, phase: Phase | None = None) -> bool:
        return any(d.severity is Severity.ERROR and (phase is None or d.phase is phase)
                   for d in self._diagnostics)

    # Devuelve los diagnosticos ordenados por posicion en el fuente, para que
    # el usuario los lea de arriba hacia abajo aunque se detectaran en otro orden.
    @property
    def diagnostics(self) -> list[Diagnostic]:
        return sorted(self._diagnostics, key=lambda d: (d.line, d.column))

    # Lista de diagnosticos en formato JSON (ya ordenados).
    def to_list(self) -> list[dict]:
        return [d.to_dict() for d in self.diagnostics]
