"""Analizador semantico de RPGScript (stub de la Fase 0, dueno: Rafael)."""
from .ast_nodes import NodeVisitor


class SemanticAnalyzer(NodeVisitor):
    def __init__(self, reporter):
        self._reporter = reporter

    def analyze(self, program):
        raise NotImplementedError
