"""Pruebas del generador de codigo de tres direcciones (cuadruplas)."""
import unittest

from rpg_compiler.ast_nodes import (
    BOOL, FLOAT, INT, STR, VOID, Assign, BinaryOp, Block, Call, ExprStmt, FuncDecl, Identifier,
    If, Literal, Param, Print, Program, Return, UnaryOp, VarDecl,
)
from rpg_compiler.ir_generator import IRGenerator, Quadruple


def lit(value, type_name):
    return Literal(line=1, column=1, value=value, type_name=type_name, inferred_type=type_name)


def ident(name, type_name):
    return Identifier(line=1, column=1, name=name, inferred_type=type_name)


def binop(op, left, right, type_name):
    return BinaryOp(line=1, column=1, operator=op, left=left, right=right, inferred_type=type_name)


def texts(quads):
    return [str(q) for q in quads]


def generate(*statements):
    return IRGenerator().generate(Program(line=1, column=1, statements=list(statements)))


class QuadrupleTest(unittest.TestCase):
    def test_to_dict_has_contract_keys(self):
        quad = Quadruple("+", "a", "b", "t1")
        self.assertEqual(quad.to_dict(3), {"index": 3, "op": "+", "arg1": "a", "arg2": "b",
                                           "result": "t1", "text": "t1 = a + b"})

    def test_text_of_each_operation(self):
        cases = [
            (Quadruple("neg", "x", result="t1"), "t1 = - x"),
            (Quadruple("not", "v", result="t2"), "t2 = ! v"),
            (Quadruple("int_to_float", "base", result="t1"), "t1 = int_to_float base"),
            (Quadruple("=", "t2", result="vida"), "vida = t2"),
            (Quadruple("label", result="L1"), "L1:"),
            (Quadruple("goto", result="L2"), "goto L2"),
            (Quadruple("if_false", "t3", result="L1"), "if_false t3 goto L1"),
            (Quadruple("param", "t1"), "param t1"),
            (Quadruple("call", "curar", "1", "t4"), "t4 = call curar, 1"),
            (Quadruple("call", "saludar", "0"), "call saludar, 0"),
            (Quadruple("return", "t1"), "return t1"),
            (Quadruple("return"), "return"),
            (Quadruple("print", "t2"), "print t2"),
            (Quadruple("func_begin", "curar"), "func_begin curar"),
        ]
        for quad, expected in cases:
            self.assertEqual(str(quad), expected)


class IRGeneratorTest(unittest.TestCase):
    def test_sum_with_int_to_float_coercion(self):
        quads = generate(
            VarDecl(line=1, column=1, type_name=INT, name="a", initializer=lit(2, INT)),
            VarDecl(line=2, column=1, type_name=FLOAT, name="b",
                    initializer=binop("+", ident("a", INT), lit(1.5, FLOAT), FLOAT)),
        )
        self.assertEqual(texts(quads), [
            "main:", "a = 2", "t1 = int_to_float a", "t2 = t1 + 1.5", "b = t2",
        ])

    def test_assignment_of_int_to_float_variable_is_coerced(self):
        quads = generate(
            VarDecl(line=1, column=1, type_name=FLOAT, name="x"),
            Assign(line=2, column=1, name="x", value=lit(5, INT)),
        )
        self.assertEqual(texts(quads), ["main:", "t1 = int_to_float 5", "x = t1"])

    def test_var_decl_without_initializer_emits_nothing(self):
        self.assertEqual(texts(generate(VarDecl(line=1, column=1, type_name=INT, name="x"))),
                         ["main:"])

    def test_literals_as_text(self):
        quads = generate(
            Print(line=1, column=1, value=lit("Aria", STR)),
            Print(line=2, column=1, value=lit(True, BOOL)),
            Print(line=3, column=1, value=lit(50.0, FLOAT)),
        )
        self.assertEqual(texts(quads), ["main:", 'print "Aria"', "print true", "print 50.0"])

    def test_precedence_produces_temporaries_in_order(self):
        # a + b * c
        expr = binop("+", ident("a", INT), binop("*", ident("b", INT), ident("c", INT), INT), INT)
        quads = generate(Print(line=1, column=1, value=expr))
        self.assertEqual(texts(quads), ["main:", "t1 = b * c", "t2 = a + t1", "print t2"])

    def test_unary_operators(self):
        quads = generate(
            Print(line=1, column=1, value=UnaryOp(line=1, column=1, operator="-",
                                                  operand=ident("x", INT), inferred_type=INT)),
            Print(line=2, column=1, value=UnaryOp(line=2, column=1, operator="!",
                                                  operand=ident("v", BOOL), inferred_type=BOOL)),
        )
        self.assertEqual(texts(quads), ["main:", "t1 = - x", "print t1", "t2 = ! v", "print t2"])

    def test_if_without_else(self):
        quads = generate(If(
            line=1, column=1, condition=binop(">", ident("vida", INT), lit(0, INT), BOOL),
            then_block=Block(line=1, column=1, statements=[Print(line=2, column=1, value=ident("vida", INT))]),
        ))
        self.assertEqual(texts(quads), [
            "main:", "t1 = vida > 0", "if_false t1 goto L1", "print vida", "L1:",
        ])

    def test_if_with_else(self):
        quads = generate(If(
            line=1, column=1, condition=ident("vivo", BOOL),
            then_block=Block(line=1, column=1, statements=[Print(line=2, column=1, value=lit(1, INT))]),
            else_block=Block(line=3, column=1, statements=[Print(line=4, column=1, value=lit(2, INT))]),
        ))
        self.assertEqual(texts(quads), [
            "main:", "if_false vivo goto L1", "print 1", "goto L2", "L1:", "print 2", "L2:",
        ])

    def test_functions_first_then_main(self):
        func = FuncDecl(line=2, column=1, name="curar", return_type=INT,
                        params=[Param(line=2, column=12, type_name=INT, name="cantidad")],
                        body=Block(line=2, column=30, statements=[
                            Return(line=3, column=5, value=ident("cantidad", INT))]))
        quads = generate(
            VarDecl(line=1, column=1, type_name=INT, name="vida", initializer=lit(10, INT)),
            func,
            Print(line=4, column=1, value=ident("vida", INT)),
        )
        self.assertEqual(texts(quads), [
            "func_begin curar", "return cantidad", "func_end curar",
            "main:", "vida = 10", "print vida",
        ])

    def test_call_with_params_and_coerced_argument(self):
        func = FuncDecl(line=1, column=1, name="escalar", return_type=FLOAT,
                        params=[Param(line=1, column=1, type_name=FLOAT, name="f"),
                                Param(line=1, column=1, type_name=INT, name="n")],
                        body=Block(line=1, column=1, statements=[
                            Return(line=2, column=1, value=ident("f", FLOAT))]))
        call = Call(line=3, column=1, callee="escalar", inferred_type=FLOAT,
                    arguments=[lit(2, INT), ident("x", INT)])
        quads = generate(func, VarDecl(line=3, column=1, type_name=FLOAT, name="r", initializer=call))
        self.assertEqual(texts(quads)[3:], [
            "main:", "t1 = int_to_float 2", "param t1", "param x", "t2 = call escalar, 2", "r = t2",
        ])

    def test_void_call_has_no_result(self):
        func = FuncDecl(line=1, column=1, name="saludar", return_type=VOID, params=[],
                        body=Block(line=1, column=1, statements=[]))
        quads = generate(func, ExprStmt(line=2, column=1, expression=Call(
            line=2, column=1, callee="saludar", inferred_type=VOID)))
        self.assertEqual(texts(quads), ["func_begin saludar", "func_end saludar", "main:",
                                        "call saludar, 0"])
        self.assertIsNone(quads[-1].result)

    def test_return_is_coerced_to_function_type(self):
        func = FuncDecl(line=1, column=1, name="f", return_type=FLOAT, params=[],
                        body=Block(line=1, column=1, statements=[Return(line=1, column=1, value=lit(1, INT))]))
        self.assertEqual(texts(generate(func))[:3],
                         ["func_begin f", "t1 = int_to_float 1", "return t1"])

    def test_temporaries_skip_user_names(self):
        quads = generate(
            VarDecl(line=1, column=1, type_name=INT, name="t1", initializer=lit(1, INT)),
            Print(line=2, column=1, value=binop("+", ident("t1", INT), lit(2, INT), INT)),
        )
        self.assertEqual(texts(quads), ["main:", "t1 = 1", "t2 = t1 + 2", "print t2"])

    def test_counters_restart_on_each_generate(self):
        program = Program(line=1, column=1, statements=[
            Print(line=1, column=1, value=binop("+", lit(1, INT), lit(2, INT), INT))])
        generator = IRGenerator()
        self.assertEqual(texts(generator.generate(program)), texts(generator.generate(program)))


if __name__ == "__main__":
    unittest.main()
