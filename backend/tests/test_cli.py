import contextlib
import io
import json
import unittest
from pathlib import Path

import main

BACKEND = Path(__file__).resolve().parent.parent
CONTRACT = BACKEND.parent / "docs" / "contract" / "api_response_example.json"


def run_cli(*args: str) -> tuple[int, str]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        code = main.main(list(args))
    return code, output.getvalue()


class CliTest(unittest.TestCase):
    def test_prints_tokens_and_ast_of_reference_program(self):
        _, output = run_cli(str(BACKEND / "examples" / "batalla_ok.rpg"))
        self.assertIn("FASE 1: TOKENS", output)
        self.assertIn("FuncDecl calcular_dano(int base, float factor) -> float", output)

    def test_reports_lexical_errors_with_lines(self):
        code, output = run_cli(str(BACKEND / "examples" / "error_lexico.rpg"))
        self.assertEqual(code, 1)
        self.assertIn("línea 2, columna 15", output)
        self.assertIn("3 error(es)", output)

    def test_json_output_follows_contract(self):
        _, output = run_cli(str(BACKEND / "examples" / "batalla_ok.rpg"), "--json")
        data = json.loads(output)
        self.assertEqual(set(data), {"success", "status", "diagnostics", "phases"})

    def test_missing_file_and_wrong_extension(self):
        self.assertEqual(run_cli("no_existe.rpg")[0], 1)
        self.assertEqual(run_cli(str(BACKEND / "main.py"))[0], 1)

    def test_printers_accept_every_phase_of_the_contract(self):
        # Garantiza que la CLI ya sabe imprimir las fases de Rafael y Saray.
        result = json.loads(CONTRACT.read_text(encoding="utf-8"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            for phase in main.PHASES:
                key, title = main.PHASE_TITLES[phase]
                main._print_phase(title, key, result)
        text = output.getvalue()
        self.assertIn("func:calcular_dano", text)
        self.assertIn("Frame de 'calcular_dano' · 28 bytes", text)
        self.assertIn("t1 = int_to_float base", text)
        self.assertIn("LOAD   R0, base", text)
        self.assertIn("Programa terminado: 36 instrucciones TAC ejecutadas.", text)

    def test_run_mode_prints_only_program_output(self):
        code, output = run_cli(str(BACKEND / "examples" / "recursion.rpg"), "--run")
        self.assertEqual(code, 0)
        self.assertEqual(output.splitlines(), ["120", "55"])

    def test_run_mode_refuses_programs_with_errors(self):
        code, output = run_cli(str(BACKEND / "examples" / "error_lexico.rpg"), "--run")
        self.assertEqual(code, 1)
        self.assertIn("no compila", output)


if __name__ == "__main__":
    unittest.main()
