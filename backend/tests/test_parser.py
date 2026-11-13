# ======================================================================
# Pruebas de la FASE 2 (parser.py).
# Verifican la forma del AST: precedencia (1 + 2 * 3), asociatividad por la
# izquierda (10 - 3 - 2), sentencias y funciones; y la recuperacion de errores:
# examples/error_sintactico.rpg debe dar exactamente 3 errores.
#
# Ejecutar (desde backend/): python -m unittest tests.test_parser -v
# ======================================================================
import unittest
from pathlib import Path

from rpg_compiler.ast_nodes import (
    BOOL, FLOAT, INT, STR, Assign, BinaryOp, Block, Call, ExprStmt, FuncDecl, Identifier, If,
    Literal, Print, Program, Return, UnaryOp, VarDecl,
)
from rpg_compiler.errors import ErrorReporter, Phase
from rpg_compiler.lexer import tokenize
from rpg_compiler.parser import Parser

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def parse(source: str):
    reporter = ErrorReporter()
    program = Parser(tokenize(source, reporter), reporter).parse()
    return program, reporter


def parse_expression(source: str):
    program, reporter = parse(f"int x = {source};")
    return program.statements[0].initializer, reporter


class ExpressionTest(unittest.TestCase):
    def test_multiplication_binds_tighter_than_addition(self):
        expr, _ = parse_expression("1 + 2 * 3")
        self.assertIsInstance(expr, BinaryOp)
        self.assertEqual(expr.operator, "+")
        self.assertEqual(expr.right.operator, "*")

    def test_left_associativity(self):
        expr, _ = parse_expression("10 - 3 - 2")
        self.assertEqual(expr.operator, "-")
        self.assertEqual(expr.left.operator, "-")
        self.assertEqual(expr.right.value, 2)

    def test_parentheses_override_precedence(self):
        expr, _ = parse_expression("(1 + 2) * 3")
        self.assertEqual(expr.operator, "*")
        self.assertEqual(expr.left.operator, "+")

    def test_logical_and_comparison_precedence(self):
        expr, _ = parse_expression("a > 0 && b || !c")
        self.assertEqual(expr.operator, "||")
        self.assertEqual(expr.left.operator, "&&")
        self.assertEqual(expr.left.left.operator, ">")
        self.assertIsInstance(expr.right, UnaryOp)

    def test_unary_minus_is_nested(self):
        expr, _ = parse_expression("--5")
        self.assertIsInstance(expr, UnaryOp)
        self.assertIsInstance(expr.operand, UnaryOp)

    def test_literal_values_and_types(self):
        program, _ = parse('int a = 7; float b = 2.5; str c = "Aria"; bool d = false;')
        literals = [statement.initializer for statement in program.statements]
        self.assertEqual([(lit.value, lit.type_name) for lit in literals],
                         [(7, INT), (2.5, FLOAT), ("Aria", STR), (False, BOOL)])

    def test_call_with_arguments(self):
        expr, _ = parse_expression("atacar(vida, 2 + 3)")
        self.assertIsInstance(expr, Call)
        self.assertEqual(expr.callee, "atacar")
        self.assertIsInstance(expr.arguments[0], Identifier)
        self.assertIsInstance(expr.arguments[1], BinaryOp)

    def test_binary_node_uses_operator_position(self):
        expr, _ = parse_expression("1 + 2")
        self.assertEqual((expr.line, expr.column), (1, 11))


class StatementTest(unittest.TestCase):
    def test_if_without_else(self):
        program, reporter = parse("if (vivo) { print(1); }")
        statement = program.statements[0]
        self.assertFalse(reporter.has_errors())
        self.assertIsInstance(statement, If)
        self.assertIsNone(statement.else_block)
        self.assertIsInstance(statement.then_block.statements[0], Print)

    def test_if_with_else(self):
        program, _ = parse("if (vivo) { vida = 1; } else { vida = 0; }")
        statement = program.statements[0]
        self.assertIsInstance(statement.else_block, Block)
        self.assertIsInstance(statement.else_block.statements[0], Assign)

    def test_function_declaration(self):
        program, reporter = parse("func curar(int base, float factor) -> float { return base * factor; }")
        function = program.statements[0]
        self.assertFalse(reporter.has_errors())
        self.assertIsInstance(function, FuncDecl)
        self.assertEqual([(p.type_name, p.name) for p in function.params], [(INT, "base"), (FLOAT, "factor")])
        self.assertEqual(function.return_type, FLOAT)
        self.assertIsInstance(function.body.statements[0], Return)

    def test_assignment_versus_expression_statement(self):
        program, _ = parse("vida = 5; curar(3);")
        self.assertIsInstance(program.statements[0], Assign)
        self.assertIsInstance(program.statements[1], ExprStmt)

    def test_empty_return_and_declaration_without_initializer(self):
        program, reporter = parse("int a; func f() -> void { return; }")
        self.assertFalse(reporter.has_errors())
        self.assertIsNone(program.statements[0].initializer)
        self.assertIsNone(program.statements[1].body.statements[0].value)

    def test_reference_program_has_no_errors(self):
        source = (EXAMPLES / "batalla_ok.rpg").read_text(encoding="utf-8")
        program, reporter = parse(source)
        self.assertEqual(reporter.diagnostics, [])
        self.assertIsInstance(program, Program)
        self.assertEqual(len(program.statements), 12)
        self.assertEqual(sum(isinstance(s, FuncDecl) for s in program.statements), 2)


class SyntaxErrorTest(unittest.TestCase):
    def syntax_errors(self, reporter):
        return [d for d in reporter.diagnostics if d.phase is Phase.SYNTAX]

    def test_syntax_error_example_reports_exactly_three_errors(self):
        source = (EXAMPLES / "error_sintactico.rpg").read_text(encoding="utf-8")
        _, reporter = parse(source)
        errors = self.syntax_errors(reporter)
        self.assertEqual([d.line for d in errors], [1, 2, 5])
        self.assertIn("';'", errors[0].message)
        self.assertIn("')'", errors[1].message)
        self.assertIn("')'", errors[2].message)

    def test_function_inside_block_is_an_error(self):
        _, reporter = parse("if (x) { func f() -> int { return 1; } }")
        errors = self.syntax_errors(reporter)
        self.assertEqual(len(errors), 1)
        self.assertIn("ámbito global", errors[0].message)

    def test_panic_mode_recovers_on_next_statement(self):
        program, reporter = parse("int = 3; print(1);")
        self.assertEqual(len(self.syntax_errors(reporter)), 1)
        self.assertIsInstance(program.statements[-1], Print)

    def test_stray_closing_brace(self):
        _, reporter = parse("int a = 1; } int b = 2;")
        errors = self.syntax_errors(reporter)
        self.assertEqual(len(errors), 1)
        self.assertIn("'}'", errors[0].message)

    def test_unclosed_block_reaches_end_without_hanging(self):
        program, reporter = parse("{ int a = 1;")
        self.assertEqual(len(self.syntax_errors(reporter)), 1)
        self.assertIsInstance(program.statements[0], Block)

    def test_always_returns_program(self):
        program, reporter = parse("@@ ;;; ) ( }")
        self.assertIsInstance(program, Program)
        self.assertTrue(reporter.has_errors())


if __name__ == "__main__":
    unittest.main()
