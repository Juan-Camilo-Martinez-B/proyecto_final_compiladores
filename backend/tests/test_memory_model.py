"""Pruebas del modelo de memoria: global, frames y heap."""
# ======================================================================
# Pruebas de la FASE 4 (memory_model.py).
# Verifican los desplazamientos del segmento global, el tamano de los frames
# (calcular_dano mide 28 bytes), los nombres repetidos y las direcciones del heap.
#
# Ejecutar (desde backend/): python -m unittest tests.test_memory_model -v
# ======================================================================
import unittest
from pathlib import Path

from rpg_compiler.ast_nodes import (
    FLOAT, INT, STR, BinaryOp, Block, FuncDecl, Identifier, Literal, Param, Print, Program,
    Return, VarDecl,
)
from rpg_compiler.errors import ErrorReporter
from rpg_compiler.lexer import tokenize
from rpg_compiler.memory_model import build_memory_layout
from rpg_compiler.parser import Parser
from rpg_compiler.semantic_analyzer import SemanticAnalyzer, SemanticResult
from rpg_compiler.symbol_table import Symbol

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def sym(name, type_name, kind, line, function=None, scope_name="global"):
    return Symbol(
        name=name, type_name=type_name, kind=kind, scope_name=scope_name,
        level=0 if function is None else 1, line=line, column=1, function=function,
        params=["int", "float"] if kind == "function" else None,
        return_type=type_name if kind == "function" else None,
    )


class MemoryLayoutTest(unittest.TestCase):
    def test_global_offsets_have_no_padding(self):
        result = SemanticResult(
            symbols=[
                sym("vida", "int", "variable", 2),
                sym("multiplicador", "float", "variable", 3),
                sym("heroe", "str", "variable", 4),
                sym("vivo", "bool", "variable", 5),
                sym("golpe", "float", "variable", 25),
            ],
            scopes=[], trace=[], string_literals=[],
        )
        data = build_memory_layout(result).to_dict()["globals"]
        self.assertEqual(data["size"], 29)
        self.assertEqual(
            [(slot["name"], slot["offset"], slot["size"]) for slot in data["slots"]],
            [("vida", 0, 4), ("multiplicador", 4, 8), ("heroe", 12, 8), ("vivo", 20, 1), ("golpe", 21, 8)],
        )

    def test_calcular_dano_frame_is_28_bytes(self):
        result = SemanticResult(
            symbols=[
                sym("calcular_dano", "float", "function", 7),
                sym("base", "int", "parameter", 7, function="calcular_dano", scope_name="func:calcular_dano"),
                sym("factor", "float", "parameter", 7, function="calcular_dano", scope_name="func:calcular_dano"),
                sym("dano", "float", "variable", 8, function="calcular_dano", scope_name="func:calcular_dano"),
            ],
            scopes=[], trace=[], string_literals=[],
        )
        frame = build_memory_layout(result).to_dict()["frames"][0]
        self.assertEqual(frame["function"], "calcular_dano")
        self.assertEqual(frame["size"], 28)
        self.assertEqual(
            [(slot["name"], slot["kind"], slot["type"], slot["offset"], slot["size"]) for slot in frame["slots"]],
            [
                ("return_address", "control", None, 0, 4),
                ("saved_fp", "control", None, 4, 4),
                ("base", "parameter", "int", 8, 4),
                ("factor", "parameter", "float", 12, 8),
                ("dano", "variable", "float", 20, 8),
            ],
        )

    def test_repeated_name_in_a_frame_uses_the_scope_suffix(self):
        result = SemanticResult(
            symbols=[
                sym("f", "int", "function", 1),
                sym("x", "int", "parameter", 1, function="f", scope_name="func:f"),
                sym("x", "int", "variable", 3, function="f", scope_name="if@2"),
            ],
            scopes=[], trace=[], string_literals=[],
        )
        names = [slot["name"] for slot in build_memory_layout(result).to_dict()["frames"][0]["slots"]]
        self.assertEqual(names, ["return_address", "saved_fp", "x", "x@if@2"])

    def test_heap_addresses_advance_by_utf8_size_plus_null(self):
        result = SemanticResult(
            symbols=[], scopes=[], trace=[],
            string_literals=["Aria", "Resiste el golpe", " sigue en pie"],
        )
        heap = build_memory_layout(result).to_dict()["heap"]
        self.assertEqual(heap, [
            {"address": "0x1000", "value": "Aria", "size": 5},
            {"address": "0x1005", "value": "Resiste el golpe", "size": 17},
            {"address": "0x1016", "value": " sigue en pie", "size": 14},
        ])

    def test_analyzer_lays_out_a_function_built_by_hand(self):
        product = BinaryOp(
            line=2, column=20, operator="*",
            left=Identifier(line=2, column=16, name="base"),
            right=Identifier(line=2, column=23, name="factor"),
        )
        function = FuncDecl(
            line=1, column=1, name="calcular_dano",
            params=[
                Param(line=1, column=20, type_name=INT, name="base"),
                Param(line=1, column=30, type_name=FLOAT, name="factor"),
            ],
            return_type=FLOAT,
            body=Block(line=1, column=40, statements=[
                VarDecl(line=2, column=5, type_name=FLOAT, name="dano", initializer=product),
                Return(line=3, column=5, value=Identifier(line=3, column=12, name="dano")),
            ]),
        )
        text = BinaryOp(
            line=4, column=16, operator="+",
            left=Identifier(line=4, column=10, name="heroe"),
            right=Literal(line=4, column=18, value=" sigue en pie", type_name=STR),
        )
        tree = Program(line=1, column=1, statements=[
            VarDecl(line=1, column=1, type_name=INT, name="vida",
                    initializer=Literal(line=1, column=12, value=100, type_name=INT)),
            function,
            VarDecl(line=4, column=1, type_name=STR, name="heroe",
                    initializer=Literal(line=4, column=12, value="Aria", type_name=STR)),
            Print(line=5, column=1, value=text),
        ])
        reporter = ErrorReporter()
        result = SemanticAnalyzer(reporter).analyze(tree)
        self.assertEqual(reporter.diagnostics, [])
        layout = build_memory_layout(result).to_dict()
        self.assertEqual(layout["frames"][0]["size"], 28)
        self.assertEqual(layout["globals"]["slots"][0]["name"], "vida")
        self.assertEqual(layout["heap"], [
            {"address": "0x1000", "value": "Aria", "size": 5},
            {"address": "0x1005", "value": " sigue en pie", "size": 14},
        ])

    def test_reference_program_matches_the_spec_layout(self):
        source = (EXAMPLES / "batalla_ok.rpg").read_text(encoding="utf-8")
        reporter = ErrorReporter()
        tree = Parser(tokenize(source, reporter), reporter).parse()
        result = SemanticAnalyzer(reporter).analyze(tree)
        self.assertFalse(reporter.has_errors())
        layout = build_memory_layout(result).to_dict()
        self.assertEqual(layout["globals"]["size"], 29)
        self.assertEqual(layout["frames"][0]["function"], "calcular_dano")
        self.assertEqual(layout["frames"][0]["size"], 28)
        self.assertEqual(layout["frames"][1]["function"], "recibir_golpe")
        self.assertEqual(layout["frames"][1]["size"], 20)
        self.assertEqual(layout["heap"], [
            {"address": "0x1000", "value": "Aria", "size": 5},
            {"address": "0x1005", "value": "Resiste el golpe", "size": 17},
            {"address": "0x1016", "value": " sigue en pie", "size": 14},
        ])


if __name__ == "__main__":
    unittest.main()
