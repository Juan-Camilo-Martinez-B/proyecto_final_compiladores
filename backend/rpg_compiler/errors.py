"""Diagnósticos compartidos: permiten reportar todos los errores sin detener el análisis."""
from dataclasses import dataclass
from enum import Enum


class Phase(str, Enum):
    LEXICAL = "lexico"
    SYNTAX = "sintactico"
    SEMANTIC = "semantico"
    IR = "ir"
    CODEGEN = "codegen"
    RUNTIME = "ejecucion"
    INTERNAL = "interno"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Diagnostic:
    phase: Phase
    severity: Severity
    message: str
    line: int
    column: int

    def to_dict(self) -> dict:
        return {"phase": self.phase.value, "severity": self.severity.value,
                "message": self.message, "line": self.line, "column": self.column}

    def __str__(self) -> str:
        return (f"[{self.phase.value.upper()}] {self.severity.value} en línea {self.line}, "
                f"columna {self.column}: {self.message}")


class ErrorReporter:
    """Acumula los diagnósticos de todas las fases."""

    def __init__(self) -> None:
        self._diagnostics: list[Diagnostic] = []

    def error(self, phase: Phase, message: str, line: int, column: int) -> None:
        self._diagnostics.append(Diagnostic(phase, Severity.ERROR, message, line, column))

    def warning(self, phase: Phase, message: str, line: int, column: int) -> None:
        self._diagnostics.append(Diagnostic(phase, Severity.WARNING, message, line, column))

    def has_errors(self, phase: Phase | None = None) -> bool:
        return any(d.severity is Severity.ERROR and (phase is None or d.phase is phase)
                   for d in self._diagnostics)

    @property
    def diagnostics(self) -> list[Diagnostic]:
        return sorted(self._diagnostics, key=lambda d: (d.line, d.column))

    def to_list(self) -> list[dict]:
        return [d.to_dict() for d in self.diagnostics]
