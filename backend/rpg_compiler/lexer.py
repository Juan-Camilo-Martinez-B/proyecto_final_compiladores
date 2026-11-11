"""Analizador lexico de RPGScript (stub de la Fase 0, dueno: Juan Camilo)."""
from .errors import ErrorReporter
from .tokens import Token


def tokenize(source: str, reporter: ErrorReporter) -> list[Token]:
    raise NotImplementedError
