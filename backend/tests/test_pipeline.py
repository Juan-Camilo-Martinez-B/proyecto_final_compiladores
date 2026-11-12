"""Pruebas de integracion de punta a punta: archivo .rpg -> respuesta completa del contrato."""
import json
import unittest
from pathlib import Path

from rpg_compiler.pipeline import PHASE_KEYS, compile_source

BACKEND = Path(__file__).resolve().parent.parent
EXAMPLES = BACKEND / "examples"
MOCKS = BACKEND.parent / "frontend" / "mock"

CONTRACT_KEYS = {"success", "status", "diagnostics", "phases"}
VALID_STATUS = {"ok", "error", "skipped", "not_implemented"}


def compile_example(name: str, register_count: int = 4) -> dict:
    return compile_source((EXAMPLES / name).read_text(encoding="utf-8"), register_count)


def by_severity(result: dict, phase: str, severity: str) -> list[dict]:
    return [d for d in result["diagnostics"] if d["phase"] == phase and d["severity"] == severity]


class ReferenceProgramTest(unittest.TestCase):
    """batalla_ok.rpg: el flujo correcto completo de la sustentacion."""

    @classmethod
    def setUpClass(cls):
        cls.result = compile_example("batalla_ok.rpg")

    def test_all_phases_succeed_without_diagnostics(self):
        self.assertTrue(self.result["success"])
        self.assertEqual(self.result["status"], {key: "ok" for key in PHASE_KEYS})
        self.assertEqual(self.result["diagnostics"], [])

    def test_ast_includes_types_inferred_by_semantic_phase(self):
        declaration = self.result["phases"]["ast"]["statements"][0]
        self.assertEqual(declaration["initializer"]["inferred_type"], "int")

    def test_scopes_follow_the_source_structure(self):
        names = [scope["name"] for scope in self.result["phases"]["symbols"]["scopes"]]
        self.assertEqual(names, ["global", "func:calcular_dano", "if@9",
                                 "func:recibir_golpe", "if@17", "else@17"])

    def test_memory_layout(self):
        memory = self.result["phases"]["memory"]
        self.assertEqual(memory["globals"]["size"], 29)
        frames = {frame["function"]: frame["size"] for frame in memory["frames"]}
        self.assertEqual(frames["calcular_dano"], 28)
        self.assertEqual([h["address"] for h in memory["heap"]], ["0x1000", "0x1005", "0x1016"])

    def test_ir_makes_coercion_explicit(self):
        texts = [quad["text"] for quad in self.result["phases"]["ir"]]
        self.assertIn("t1 = int_to_float base", texts)
        self.assertEqual([q["index"] for q in self.result["phases"]["ir"]], list(range(len(texts))))

    def test_assembly_uses_registers_without_spills(self):
        assembly = self.result["phases"]["assembly"]
        self.assertEqual(assembly["register_count"], 4)
        self.assertEqual(assembly["spills"], [])
        self.assertEqual(assembly["instructions"][-1].strip(), "HALT")
        self.assertEqual(len(assembly["register_trace"]), len(assembly["instructions"]))


class ErrorProgramsTest(unittest.TestCase):
    def test_lexical_errors_stop_after_tokens(self):
        result = compile_example("error_lexico.rpg")
        errors = by_severity(result, "lexico", "error")
        self.assertFalse(result["success"])
        self.assertEqual([(d["line"], d["column"]) for d in errors], [(2, 15), (3, 14), (4, 5)])
        self.assertEqual(result["status"]["tokens"], "error")
        self.assertIsNotNone(result["phases"]["tokens"])
        for key in PHASE_KEYS[1:]:
            self.assertEqual(result["status"][key], "skipped")
            self.assertIsNone(result["phases"][key])

    def test_syntax_errors_stop_after_ast(self):
        result = compile_example("error_sintactico.rpg")
        errors = by_severity(result, "sintactico", "error")
        self.assertEqual([d["line"] for d in errors], [1, 2, 5])
        self.assertEqual(len(result["diagnostics"]), 3)
        self.assertEqual(result["status"]["ast"], "error")
        self.assertIsNone(result["phases"]["symbols"])

    def test_semantic_stress_program(self):
        result = compile_example("estres_semantico.rpg")
        errors = by_severity(result, "semantico", "error")
        warnings = by_severity(result, "semantico", "warning")
        self.assertEqual(len(errors), 13)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(sorted(d["line"] for d in errors + warnings),
                         [5, 6, 7, 8, 10, 11, 13, 14, 15, 18, 19, 20, 21, 22])
        self.assertEqual(warnings[0]["line"], 10)
        self.assertEqual(result["status"]["symbols"], "error")
        self.assertIsNotNone(result["phases"]["symbols"])
        for key in ("memory", "ir", "assembly"):
            self.assertIsNone(result["phases"][key])


class RegisterPressureTest(unittest.TestCase):
    def test_spill_with_four_registers(self):
        result = compile_example("spill_registros.rpg")
        self.assertTrue(result["success"])
        self.assertGreaterEqual(len(result["phases"]["assembly"]["spills"]), 1)

    def test_fewer_registers_mean_more_spills(self):
        four = compile_example("spill_registros.rpg", 4)["phases"]["assembly"]["spills"]
        two = compile_example("spill_registros.rpg", 2)["phases"]["assembly"]["spills"]
        self.assertGreater(len(two), len(four))


class RobustnessTest(unittest.TestCase):
    """El pipeline nunca lanza excepciones y siempre responde con el contrato."""

    def test_every_example_follows_the_contract(self):
        for path in sorted(EXAMPLES.glob("*.rpg")):
            with self.subTest(example=path.name):
                result = compile_source(path.read_text(encoding="utf-8"))
                self.assertEqual(set(result), CONTRACT_KEYS)
                self.assertEqual(set(result["phases"]), set(PHASE_KEYS))
                self.assertTrue(set(result["status"].values()) <= VALID_STATUS)
                self.assertNotIn("not_implemented", result["status"].values())
                self.assertEqual([d for d in result["diagnostics"] if d["phase"] == "interno"], [])
                json.dumps(result)  # debe ser serializable para la API

    def test_unusual_inputs_never_crash(self):
        sources = [
            "", "   \n\n", "}}}}", "func", "int x = ;", "((((((((1))))))))", "if (true) {",
            "func f() -> int { return f(); } print(f());", 'print("<script>alert(1)</script>");',
            "int a = 1 + 2 * 3 - 4 / 5 && true;", "x" * 5000, "print(" * 200,
        ]
        for source in sources:
            with self.subTest(source=source[:30]):
                result = compile_source(source)
                self.assertEqual(set(result), CONTRACT_KEYS)
                self.assertEqual([d for d in result["diagnostics"] if d["phase"] == "interno"], [])


class FrontendMocksTest(unittest.TestCase):
    """Los mocks de la web deben ser respuestas reales y actuales del compilador."""

    def test_mocks_match_current_compiler_output(self):
        cases = {"response_ok.json": "batalla_ok.rpg", "response_errors.json": "estres_semantico.rpg"}
        for mock_name, example in cases.items():
            with self.subTest(mock=mock_name):
                mock = json.loads((MOCKS / mock_name).read_text(encoding="utf-8"))
                self.assertEqual(mock, compile_example(example))


if __name__ == "__main__":
    unittest.main()
