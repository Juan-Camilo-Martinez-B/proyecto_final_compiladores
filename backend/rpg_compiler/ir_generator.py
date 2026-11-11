"""Generador de codigo de tres direcciones en cuadruplas (stub de la Fase 0, duena: Saray)."""
from .ast_nodes import NodeVisitor


class IRGenerator(NodeVisitor):
    def generate(self, program):
        raise NotImplementedError
