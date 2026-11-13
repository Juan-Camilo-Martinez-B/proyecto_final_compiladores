"""Pruebas de la maquina virtual que ejecuta el codigo de tres direcciones."""
# ======================================================================
# Pruebas de la maquina virtual (vm.py).
# Compilan programas pequenos y verifican lo que imprimen: aritmetica, division
# entera, llamadas, recursion y ambitos; y los errores de ejecucion (division
# entre cero, recursion infinita, variable sin valor, limite de pasos).
#
# Ejecutar (desde backend/): python -m unittest tests.test_vm -v
# ======================================================================
import unittest

from rpg_compiler.ir_generator import Quadruple
from rpg_compiler.pipeline import compile_source
from rpg_compiler.vm import TacVM, format_value, parse_literal


def run(source: str) -> dict:
    result = compile_source(source)
    assert result["success"], result["diagnostics"]
    return result["phases"]["execution"]


def output(source: str) -> list[str]:
    execution = run(source)
    assert execution["error"] is None, execution["error"]
    return execution["output"]


class ValuesTest(unittest.TestCase):
    def test_literals_are_parsed_by_type(self):
        self.assertEqual(parse_literal("7"), 7)
        self.assertEqual(parse_literal("2.5"), 2.5)
        self.assertEqual(parse_literal('"Aria"'), "Aria")
        self.assertIs(parse_literal("true"), True)
        self.assertIs(parse_literal("false"), False)

    def test_names_are_not_literals(self):
        self.assertIsNot(parse_literal("vida"), "vida")
        self.assertIsNot(parse_literal("t1"), "t1")

    def test_values_print_like_rpgscript(self):
        self.assertEqual(format_value(True), "true")
        self.assertEqual(format_value(50.0), "50.0")
        self.assertEqual(format_value("Aria"), "Aria")


class ArithmeticTest(unittest.TestCase):
    def test_precedence_is_respected_at_runtime(self):
        self.assertEqual(output("print(1 + 2 * 3);"), ["7"])

    def test_integer_division_truncates_toward_zero(self):
        self.assertEqual(output("print(7 / 2); print(-7 / 2);"), ["3", "-3"])

    def test_coercion_makes_float_results(self):
        self.assertEqual(output("int a = 3; float b = 1.5; print(a * b);"), ["4.5"])

    def test_integer_division_happens_before_coercion(self):
        self.assertEqual(output("float f = 3 / 2; print(f);"), ["1.0"])

    def test_string_concatenation_and_booleans(self):
        self.assertEqual(output('print("Aria" + " vive"); print(3 > 2 && !false);'),
                         ["Aria vive", "true"])


class ControlFlowTest(unittest.TestCase):
    def test_if_else_takes_one_branch(self):
        source = 'int vida = 0;\nif (vida > 0) { print("vivo"); } else { print("caido"); }'
        self.assertEqual(output(source), ["caido"])

    def test_function_call_and_return(self):
        source = "func doble(int n) -> int { return n * 2; }\nprint(doble(21));"
        self.assertEqual(output(source), ["42"])

    def test_recursion(self):
        source = ("func fact(int n) -> int { if (n <= 1) { return 1; } return n * fact(n - 1); }\n"
                  "print(fact(6));")
        self.assertEqual(output(source), ["720"])

    def test_function_modifies_global(self):
        source = "int vida = 10;\nfunc golpe(int d) -> void { vida = vida - d; }\ngolpe(3);\nprint(vida);"
        self.assertEqual(output(source), ["7"])

    def test_local_variable_shadows_global(self):
        source = ("int vida = 10;\nfunc f() -> int { int vida = 99; return vida; }\n"
                  "print(f());\nprint(vida);")
        self.assertEqual(output(source), ["99", "10"])

    def test_each_call_has_its_own_frame(self):
        source = ("func suma(int a, int b) -> int { int r = a + b; return r; }\n"
                  "print(suma(suma(1, 2), suma(3, 4)));")
        self.assertEqual(output(source), ["10"])


class RuntimeErrorsTest(unittest.TestCase):
    def test_division_by_zero(self):
        execution = run('print("antes");\nint x = 5 / 0;\nprint("despues");')
        self.assertEqual(execution["status"], "error")
        self.assertEqual(execution["output"], ["antes"])
        self.assertIn("División entre cero", execution["error"]["message"])
        self.assertEqual(execution["error"]["text"], "t1 = 5 / 0")

    def test_infinite_recursion_is_stopped(self):
        execution = run("func f(int n) -> int { return f(n - 1); }\nint r = f(3);")
        self.assertIn("recursión infinita", execution["error"]["message"])

    def test_step_limit(self):
        quads = [Quadruple("label", result="main"), Quadruple("goto", result="main")]
        result = TacVM(max_steps=50).run(quads)
        self.assertIn("límite de 50 instrucciones", result.error["message"])

    def test_variable_without_value(self):
        execution = run("int a;\nprint(a + 1);")
        self.assertIn("antes de tener un valor", execution["error"]["message"])

    def test_function_without_return_used_as_value(self):
        execution = run("func f() -> int { print(1); }\nint x = f();")
        self.assertIn("sin retornar un valor", execution["error"]["message"])

    def test_runtime_error_does_not_fail_compilation(self):
        result = compile_source("int x = 5 / 0;")
        self.assertTrue(result["success"])
        self.assertEqual(result["status"]["execution"], "error")


if __name__ == "__main__":
    unittest.main()
