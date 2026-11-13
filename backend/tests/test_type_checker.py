"""Pruebas del sistema de tipos y de las reglas semanticas S01-S17."""
# ======================================================================
# Pruebas del analisis semantico (semantic_analyzer.py y type_system.py).
# Construyen el AST a mano (sin depender del parser) y verifican cada regla
# S01-S17, la coercion int -> float, la anotacion inferred_type y que no haya
# errores en cascada. Incluyen los 13 errores y 1 advertencia del programa de estres.
#
# Ejecutar (desde backend/): python -m unittest tests.test_type_checker -v
# ======================================================================
import unittest
from pathlib import Path

from rpg_compiler.ast_nodes import (
    BOOL, FLOAT, INT, STR, VOID, Assign, BinaryOp, Block, Call, ExprStmt, FuncDecl, Identifier,
    If, Literal, Param, Print, Program, Return, UnaryOp, VarDecl,
)
from rpg_compiler.errors import ErrorReporter
from rpg_compiler.lexer import tokenize
from rpg_compiler.parser import Parser
from rpg_compiler.pipeline import compile_source
from rpg_compiler.semantic_analyzer import SemanticAnalyzer
from rpg_compiler.type_system import ERROR_TYPE, binary_result, is_assignable, unary_result

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def analyze(program):
    reporter = ErrorReporter()
    result = SemanticAnalyzer(reporter).analyze(program)
    return result, reporter


def messages(reporter):
    return [item.message for item in reporter.diagnostics]


def program(*statements):
    return Program(line=1, column=1, statements=list(statements))


def literal(value, type_name, line=1, column=1):
    return Literal(line=line, column=column, value=value, type_name=type_name)


def name(identifier, line=1, column=1):
    return Identifier(line=line, column=column, name=identifier)


class TypeRulesTest(unittest.TestCase):
    def test_arithmetic_coerces_to_float_and_keeps_int_division(self):
        self.assertEqual(binary_result("+", INT, FLOAT), FLOAT)
        self.assertEqual(binary_result("+", FLOAT, INT), FLOAT)
        self.assertEqual(binary_result("*", INT, INT), INT)
        self.assertEqual(binary_result("/", INT, INT), INT)
        self.assertEqual(binary_result("/", INT, FLOAT), FLOAT)

    def test_addition_concatenates_strings_and_rejects_mixed_text(self):
        self.assertEqual(binary_result("+", STR, STR), STR)
        self.assertIsNone(binary_result("-", INT, STR))
        self.assertIsNone(binary_result("+", STR, INT))

    def test_comparisons_and_equality(self):
        self.assertEqual(binary_result("<", INT, FLOAT), BOOL)
        self.assertEqual(binary_result("==", INT, FLOAT), BOOL)
        self.assertEqual(binary_result("==", STR, STR), BOOL)
        self.assertEqual(binary_result("!=", BOOL, BOOL), BOOL)
        self.assertIsNone(binary_result("==", STR, INT))
        self.assertEqual(binary_result("&&", BOOL, BOOL), BOOL)
        self.assertIsNone(binary_result("||", INT, BOOL))

    def test_unary_operators_and_error_short_circuit(self):
        self.assertEqual(unary_result("-", INT), INT)
        self.assertEqual(unary_result("-", FLOAT), FLOAT)
        self.assertEqual(unary_result("!", BOOL), BOOL)
        self.assertIsNone(unary_result("!", INT))
        self.assertEqual(binary_result("+", ERROR_TYPE, INT), ERROR_TYPE)
        self.assertEqual(unary_result("!", ERROR_TYPE), ERROR_TYPE)

    def test_assignment_accepts_int_to_float_and_rejects_the_opposite(self):
        self.assertTrue(is_assignable(FLOAT, INT))
        self.assertFalse(is_assignable(INT, FLOAT))
        self.assertTrue(is_assignable(INT, INT))
        self.assertTrue(is_assignable(INT, ERROR_TYPE))
        self.assertFalse(is_assignable(BOOL, INT))


class SemanticRulesTest(unittest.TestCase):
    def test_s01_undeclared_variable(self):
        _, reporter = analyze(program(
            Print(line=1, column=1, value=name("mana", line=1, column=7)),
        ))
        self.assertEqual(messages(reporter), [
            "La variable 'mana' no está declarada en el ámbito 'global'.",
        ])

    def test_s02_redeclaration_in_the_same_scope(self):
        _, reporter = analyze(program(
            VarDecl(line=2, column=1, type_name=INT, name="vida", initializer=literal(100, INT)),
            VarDecl(line=5, column=1, type_name=INT, name="vida", initializer=literal(50, INT, line=5)),
        ))
        self.assertEqual(messages(reporter), [
            "La variable 'vida' ya fue declarada en el ámbito 'global' (línea 2).",
        ])

    def test_s03_shadowing_is_a_warning(self):
        body = Block(line=2, column=1, statements=[
            VarDecl(line=3, column=5, type_name=INT, name="vida", initializer=literal(1, INT, line=3)),
            Return(line=4, column=5, value=name("vida", line=4, column=12)),
        ])
        function = FuncDecl(
            line=2, column=1, name="curar", params=[Param(line=2, column=12, type_name=INT, name="cantidad")],
            return_type=INT, body=body,
        )
        _, reporter = analyze(program(
            VarDecl(line=1, column=1, type_name=INT, name="vida", initializer=literal(100, INT)),
            function,
        ))
        self.assertEqual(messages(reporter), [
            "'vida' oculta a la variable declarada en el ámbito 'global'.",
        ])
        self.assertEqual(reporter.diagnostics[0].severity.value, "warning")

    def test_s04_incompatible_binary_operator(self):
        # El mismo arbol que construye el plan a mano: int - str no dispara otro error.
        _, reporter = analyze(program(
            VarDecl(line=1, column=1, type_name=INT, name="vida",
                    initializer=literal(100, INT, column=12)),
            Assign(line=2, column=1, name="vida", value=BinaryOp(
                line=2, column=13, operator="-",
                left=name("vida", line=2, column=8),
                right=literal("Fuego", STR, line=2, column=15),
            )),
        ))
        self.assertEqual(messages(reporter), [
            "El operador '-' no está definido entre 'int' y 'str'.",
        ])

    def test_s05_incompatible_unary_operator_does_not_cascade(self):
        _, reporter = analyze(program(
            VarDecl(line=1, column=1, type_name=INT, name="vida", initializer=literal(100, INT)),
            VarDecl(line=2, column=1, type_name=INT, name="total",
                    initializer=UnaryOp(line=2, column=16, operator="!", operand=name("vida", line=2, column=17))),
        ))
        self.assertEqual(messages(reporter), [
            "El operador '!' no se puede aplicar a 'int'.",
        ])

    def test_s06_rejects_float_to_int_and_accepts_int_to_float(self):
        _, reporter = analyze(program(
            VarDecl(line=1, column=1, type_name=FLOAT, name="escudo", initializer=literal(2.5, FLOAT)),
            VarDecl(line=2, column=1, type_name=INT, name="poder",
                    initializer=name("escudo", line=2, column=13)),
        ))
        self.assertEqual(messages(reporter), [
            "No se puede asignar un valor 'float' a 'poder' de tipo 'int'.",
        ])
        accepted, reporter = analyze(program(
            VarDecl(line=1, column=1, type_name=INT, name="base", initializer=literal(40, INT)),
            VarDecl(line=2, column=1, type_name=FLOAT, name="factor",
                    initializer=name("base", line=2, column=16)),
        ))
        self.assertEqual(messages(reporter), [])
        self.assertEqual(accepted.symbols[-1].type_name, FLOAT)

    def test_s07_void_variable(self):
        _, reporter = analyze(program(
            VarDecl(line=1, column=1, type_name=VOID, name="nada"),
        ))
        self.assertEqual(messages(reporter), [
            "La variable 'nada' no puede ser de tipo 'void'.",
        ])

    def test_s08_if_condition_must_be_bool(self):
        _, reporter = analyze(program(
            VarDecl(line=1, column=1, type_name=INT, name="vida", initializer=literal(100, INT)),
            If(line=2, column=1, condition=name("vida", line=2, column=5),
               then_block=Block(line=2, column=10, statements=[]), else_block=None),
        ))
        self.assertEqual(messages(reporter), [
            "La condición del 'if' debe ser 'bool', se obtuvo 'int'.",
        ])

    def test_s09_call_target_must_be_a_function(self):
        _, reporter = analyze(program(
            VarDecl(line=1, column=1, type_name=STR, name="hechizo", initializer=literal("Fuego", STR)),
            ExprStmt(line=2, column=1, expression=Call(line=2, column=1, callee="hechizo")),
            ExprStmt(line=3, column=1, expression=Call(line=3, column=1, callee="ausente")),
        ))
        self.assertEqual(messages(reporter), [
            "'hechizo' no es una función.",
            "'ausente' no es una función.",
        ])

    def test_s10_wrong_arity(self):
        function = FuncDecl(
            line=1, column=1, name="curar",
            params=[Param(line=1, column=12, type_name=INT, name="cantidad")],
            return_type=INT,
            body=Block(line=1, column=30, statements=[
                Return(line=2, column=5, value=name("cantidad", line=2, column=12)),
            ]),
        )
        _, reporter = analyze(program(
            function,
            ExprStmt(line=3, column=1, expression=Call(
                line=3, column=1, callee="curar",
                arguments=[literal(10, INT, line=3), literal(20, INT, line=3, column=10)],
            )),
        ))
        self.assertEqual(messages(reporter), [
            "La función 'curar' espera 1 argumento(s) y recibió 2.",
        ])

    def test_s11_incompatible_argument(self):
        function = FuncDecl(
            line=1, column=1, name="curar",
            params=[Param(line=1, column=12, type_name=INT, name="cantidad")],
            return_type=INT,
            body=Block(line=1, column=30, statements=[
                Return(line=2, column=5, value=name("cantidad", line=2, column=12)),
            ]),
        )
        _, reporter = analyze(program(
            function,
            ExprStmt(line=3, column=1, expression=Call(
                line=3, column=1, callee="curar",
                arguments=[literal("Fuego", STR, line=3, column=7)],
            )),
        ))
        self.assertEqual(messages(reporter), [
            "El argumento 1 de 'curar' debe ser 'int', se recibió 'str'.",
        ])

    def test_s12_return_type_must_match_and_int_coerces_to_float(self):
        wrong = FuncDecl(
            line=1, column=1, name="curar", params=[], return_type=INT,
            body=Block(line=1, column=20, statements=[
                Return(line=2, column=5, value=literal("mucho", STR, line=2, column=12)),
            ]),
        )
        _, reporter = analyze(program(wrong))
        self.assertEqual(messages(reporter), [
            "'curar' debe retornar 'int', pero retorna 'str'.",
        ])
        coerced = FuncDecl(
            line=1, column=1, name="dano", params=[], return_type=FLOAT,
            body=Block(line=1, column=20, statements=[
                Return(line=2, column=5, value=literal(1, INT, line=2, column=12)),
            ]),
        )
        _, reporter = analyze(program(coerced))
        self.assertEqual(messages(reporter), [])

    def test_s13_return_outside_a_function(self):
        _, reporter = analyze(program(
            Return(line=4, column=1, value=literal(5, INT, line=4, column=8)),
        ))
        self.assertEqual(messages(reporter), [
            "'return' solo se permite dentro de una función.",
        ])

    def test_s14_missing_return_is_a_warning(self):
        function = FuncDecl(
            line=1, column=1, name="calcular", params=[], return_type=INT,
            body=Block(line=1, column=20, statements=[
                VarDecl(line=2, column=5, type_name=INT, name="x", initializer=literal(1, INT, line=2)),
            ]),
        )
        _, reporter = analyze(program(function))
        self.assertEqual(messages(reporter), [
            "La función 'calcular' declara 'int' pero no tiene 'return'.",
        ])
        void_function = FuncDecl(
            line=1, column=1, name="saludar", params=[], return_type=VOID,
            body=Block(line=1, column=20, statements=[]),
        )
        _, reporter = analyze(program(void_function))
        self.assertEqual(messages(reporter), [])

    def test_s15_void_call_used_as_a_value(self):
        function = FuncDecl(
            line=1, column=1, name="saludar", params=[], return_type=VOID,
            body=Block(line=1, column=20, statements=[
                Print(line=2, column=5, value=literal("hola", STR, line=2)),
            ]),
        )
        _, reporter = analyze(program(
            function,
            ExprStmt(line=3, column=1, expression=Call(line=3, column=1, callee="saludar")),
            Print(line=4, column=1, value=Call(line=4, column=7, callee="saludar")),
        ))
        self.assertEqual(messages(reporter), [
            "La función 'saludar' es 'void' y no produce un valor.",
        ])

    def test_s16_function_name_used_as_a_variable(self):
        function = FuncDecl(
            line=1, column=1, name="curar",
            params=[Param(line=1, column=12, type_name=INT, name="cantidad")],
            return_type=INT,
            body=Block(line=1, column=30, statements=[
                Return(line=2, column=5, value=name("cantidad", line=2)),
            ]),
        )
        _, reporter = analyze(program(
            function,
            VarDecl(line=3, column=1, type_name=INT, name="x", initializer=name("curar", line=3, column=9)),
        ))
        self.assertEqual(messages(reporter), [
            "'curar' es una función y no se puede usar como variable.",
        ])

    def test_s17_repeated_parameter_and_redeclared_function(self):
        repeated = FuncDecl(
            line=1, column=1, name="atacar",
            params=[
                Param(line=1, column=14, type_name=INT, name="dano"),
                Param(line=1, column=24, type_name=INT, name="dano"),
            ],
            return_type=INT,
            body=Block(line=1, column=40, statements=[
                Return(line=2, column=5, value=name("dano", line=2)),
            ]),
        )
        _, reporter = analyze(program(repeated))
        self.assertEqual(messages(reporter), [
            "El parámetro 'dano' está repetido en 'atacar'.",
        ])
        first = FuncDecl(
            line=1, column=1, name="atacar", params=[], return_type=VOID,
            body=Block(line=1, column=20, statements=[]),
        )
        second = FuncDecl(
            line=3, column=1, name="atacar", params=[], return_type=VOID,
            body=Block(line=3, column=20, statements=[]),
        )
        _, reporter = analyze(program(first, second))
        self.assertEqual(messages(reporter), [
            "La función 'atacar' ya fue declarada en el ámbito 'global' (línea 1).",
        ])

    def test_forward_call_and_recursion_are_visible(self):
        recursive = FuncDecl(
            line=2, column=1, name="fact",
            params=[Param(line=2, column=11, type_name=INT, name="n")],
            return_type=INT,
            body=Block(line=2, column=20, statements=[
                Return(line=3, column=5, value=Call(
                    line=3, column=12, callee="fact",
                    arguments=[name("n", line=3, column=17)],
                )),
            ]),
        )
        result, reporter = analyze(program(
            VarDecl(line=1, column=1, type_name=INT, name="x",
                    initializer=Call(line=1, column=9, callee="fact", arguments=[literal(3, INT, line=1)])),
            recursive,
        ))
        self.assertEqual(messages(reporter), [])
        self.assertEqual(result.symbols[0].kind, "function")

    def test_every_expression_receives_an_inferred_type(self):
        product = BinaryOp(
            line=2, column=18, operator="*",
            left=name("base", line=2, column=13),
            right=name("factor", line=2, column=20),
        )
        function = FuncDecl(
            line=1, column=1, name="calcular_dano",
            params=[
                Param(line=1, column=20, type_name=INT, name="base"),
                Param(line=1, column=30, type_name=FLOAT, name="factor"),
            ],
            return_type=FLOAT,
            body=Block(line=1, column=50, statements=[
                VarDecl(line=2, column=5, type_name=FLOAT, name="dano", initializer=product),
                Return(line=3, column=5, value=name("dano", line=3, column=12)),
            ]),
        )
        _, reporter = analyze(program(function))
        self.assertEqual(messages(reporter), [])
        self.assertEqual(product.inferred_type, FLOAT)
        self.assertEqual(product.left.inferred_type, INT)
        self.assertEqual(product.right.inferred_type, FLOAT)

    def test_string_literals_keep_first_seen_order_without_duplicates(self):
        result, reporter = analyze(program(
            VarDecl(line=1, column=1, type_name=STR, name="heroe", initializer=literal("Aria", STR)),
            VarDecl(line=2, column=1, type_name=STR, name="copia", initializer=literal("Aria", STR, line=2)),
            Print(line=3, column=1, value=literal(" sigue en pie", STR, line=3)),
        ))
        self.assertEqual(messages(reporter), [])
        self.assertEqual(result.string_literals, ["Aria", " sigue en pie"])


class ExampleProgramsTest(unittest.TestCase):
    def test_reference_program_has_no_semantic_diagnostics(self):
        source = (EXAMPLES / "batalla_ok.rpg").read_text(encoding="utf-8")
        reporter = ErrorReporter()
        tree = Parser(tokenize(source, reporter), reporter).parse()
        self.assertFalse(reporter.has_errors())
        result, semantic = analyze(tree)
        self.assertEqual(semantic.diagnostics, [])
        scopes = {scope.name: scope for scope in result.scopes}
        self.assertEqual(
            [item.name for item in scopes["global"].symbols.values()],
            ["calcular_dano", "recibir_golpe", "vida", "multiplicador", "heroe", "vivo", "golpe"],
        )
        shown = [item["name"] for item in scopes["global"].to_dict()["symbols"]]
        self.assertEqual(shown, ["vida", "multiplicador", "heroe", "vivo", "calcular_dano", "recibir_golpe", "golpe"])
        self.assertEqual([item.name for item in scopes["func:calcular_dano"].symbols.values()], ["base", "factor", "dano"])
        self.assertEqual(scopes["if@9"].level, 2)
        self.assertEqual(scopes["if@9"].parent.name, "func:calcular_dano")
        self.assertEqual(scopes["if@9"].symbols, {})
        self.assertEqual(scopes["else@17"].parent.name, "func:recibir_golpe")
        product = tree.statements[4].body.statements[0].initializer
        self.assertEqual(product.inferred_type, FLOAT)
        self.assertEqual(product.left.inferred_type, INT)

    def test_stress_program_reports_13_errors_and_1_warning(self):
        source = (EXAMPLES / "estres_semantico.rpg").read_text(encoding="utf-8")
        result = compile_source(source)
        semantic = [item for item in result["diagnostics"] if item["phase"] == "semantico"]
        errors = [item for item in semantic if item["severity"] == "error"]
        warnings = [item for item in semantic if item["severity"] == "warning"]
        self.assertEqual([(item["line"], item["message"]) for item in errors], [
            (5, "La variable 'vida' ya fue declarada en el ámbito 'global' (línea 2)."),
            (6, "El operador '-' no está definido entre 'int' y 'str'."),
            (7, "No se puede asignar un valor 'float' a 'poder' de tipo 'int'."),
            (8, "No se puede asignar un valor 'int' a 'vivo' de tipo 'bool'."),
            (11, "'curar' debe retornar 'int', pero retorna 'str'."),
            (13, "La función 'curar' espera 1 argumento(s) y recibió 2."),
            (14, "El argumento 1 de 'curar' debe ser 'int', se recibió 'str'."),
            (15, "La condición del 'if' debe ser 'bool', se obtuvo 'int'."),
            (18, "La variable 'temporal' no está declarada en el ámbito 'global'."),
            (19, "La variable 'mana' no está declarada en el ámbito 'global'."),
            (20, "'return' solo se permite dentro de una función."),
            (21, "'hechizo' no es una función."),
            (22, "El operador '!' no se puede aplicar a 'int'."),
        ])
        self.assertEqual([(item["line"], item["message"]) for item in warnings], [
            (10, "'vida' oculta a la variable declarada en el ámbito 'global'."),
        ])
        self.assertEqual(result["status"]["symbols"], "error")
        self.assertEqual(result["status"]["memory"], "skipped")


if __name__ == "__main__":
    unittest.main()
