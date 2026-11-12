"""Pruebas del generador de pseudo-ensamblador y la asignacion de registros."""
import unittest
from pathlib import Path

from rpg_compiler.codegen import CodeGenerator
from rpg_compiler.ir_generator import Quadruple as Q
from rpg_compiler.pipeline import compile_source

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def asm(quads, registers=4):
    return CodeGenerator(registers).generate(quads)


def mnemonics(result):
    return [line.split()[0] for line in result.instructions]


class CodeGeneratorTest(unittest.TestCase):
    def test_simple_sum(self):
        result = asm([Q("+", "a", "b", "t1"), Q("=", "t1", result="c")])
        self.assertEqual(mnemonics(result), ["LOAD", "LOAD", "ADD", "STORE"])
        self.assertIn("LOAD   R0, a", result.instructions[0])
        self.assertIn("ADD    R0, R1", result.instructions[2])
        self.assertIn("STORE  c, R0", result.instructions[3])
        self.assertEqual(result.spills, [])

    def test_constants_are_immediate(self):
        result = asm([Q("=", "5", result="x")])
        self.assertIn("LOAD   R0, #5", result.instructions[0])

    def test_comparison_uses_cmp_and_set(self):
        result = asm([Q("<", "a", "b", "t1"), Q("print", "t1")])
        self.assertEqual(mnemonics(result), ["LOAD", "LOAD", "CMP", "SETLT", "PRINT"])

    def test_if_false_produces_jz(self):
        result = asm([Q("if_false", "t", result="L1"), Q("label", result="L1")])
        self.assertIn("JZ     R0, L1", result.instructions[1])
        self.assertEqual(result.instructions[2], "L1:")

    def test_unary_and_coercion(self):
        result = asm([Q("int_to_float", "base", result="t1"), Q("neg", "t1", result="t2"),
                      Q("not", "v", result="t3"), Q("print", "t2"), Q("print", "t3")])
        self.assertEqual(mnemonics(result)[:5], ["LOAD", "ITOF", "NEG", "LOAD", "NOT"])

    def test_call_moves_return_value_from_rv(self):
        result = asm([Q("param", "x"), Q("call", "curar", "1", "t1"), Q("print", "t1")])
        self.assertEqual(mnemonics(result), ["LOAD", "PUSH", "CALL", "MOV", "PRINT"])
        self.assertIn("RV", result.instructions[3])

    def test_functions_and_main(self):
        result = asm([Q("func_begin", "f"), Q("return", "x"), Q("func_end", "f"),
                      Q("label", result="main"), Q("goto", result="L1")])
        self.assertEqual(result.instructions[0], "FUNC f")
        self.assertEqual(result.instructions[3], "ENDFUNC f")
        self.assertEqual(result.instructions[4], "main:")
        self.assertIn("JMP    L1", result.instructions[5])
        self.assertEqual(mnemonics(result)[-1], "HALT")

    def test_spill_and_reload_with_two_registers(self):
        # t1 = a + b ; t2 = c + d ; t3 = t1 * t2  -> t1 debe ir a la pila
        result = asm([Q("+", "a", "b", "t1"), Q("+", "c", "d", "t2"),
                      Q("*", "t1", "t2", "t3"), Q("print", "t3")], registers=2)
        self.assertEqual(len(result.spills), 1)
        spill = result.spills[0]
        self.assertEqual(spill["variable"], "t1")
        self.assertEqual(spill["slot"], "[SP+0]")
        self.assertTrue(result.instructions[spill["instruction"]].strip().startswith("STORE  [SP+0]"))
        self.assertTrue(any("LOAD" in line and "[SP+0]" in line for line in result.instructions))

    def test_live_temporary_is_saved_across_call(self):
        result = asm([Q("+", "a", "b", "t1"), Q("call", "f", "0", "t2"),
                      Q("*", "t1", "t2", "t3"), Q("print", "t3")])
        self.assertEqual([s["variable"] for s in result.spills], ["t1"])

    def test_register_trace_has_one_entry_per_instruction(self):
        result = asm([Q("+", "a", "b", "t1"), Q("=", "t1", result="c")], registers=3)
        self.assertEqual(len(result.register_trace), len(result.instructions))
        self.assertEqual([e["instruction"] for e in result.register_trace],
                         list(range(len(result.instructions))))
        self.assertEqual(result.register_trace[0]["registers"], {"R0": "a", "R1": None, "R2": None})
        self.assertEqual(result.register_trace[2]["registers"]["R0"], "t1")

    def test_to_dict_has_contract_keys(self):
        data = asm([Q("print", "1")], registers=4).to_dict()
        self.assertEqual(set(data), {"register_count", "instructions", "register_trace", "spills"})
        self.assertEqual(data["register_count"], 4)


class EndToEndTest(unittest.TestCase):
    def compile(self, name, registers=4):
        return compile_source((EXAMPLES / name).read_text(encoding="utf-8"), registers)

    def test_batalla_ok_completes_every_phase(self):
        result = self.compile("batalla_ok.rpg")
        self.assertTrue(result["success"])
        self.assertEqual(set(result["status"].values()), {"ok"})
        ir_text = [q["text"] for q in result["phases"]["ir"]]
        self.assertIn("t1 = int_to_float base", ir_text)
        self.assertEqual(result["phases"]["assembly"]["spills"], [])

    def test_spill_example_produces_spills(self):
        for registers in (4, 2):
            assembly = self.compile("spill_registros.rpg", registers)["phases"]["assembly"]
            self.assertGreaterEqual(len(assembly["spills"]), 1)
            self.assertEqual(assembly["register_count"], registers)


if __name__ == "__main__":
    unittest.main()
