"""Generador de codigo de tres direcciones (TAC) almacenado en cuadruplas.

Recorre el AST ya anotado por el analizador semantico (cada expresion trae su
inferred_type) y produce una lista de cuadruplas (op, arg1, arg2, result).

Decisiones:
- Orden de emision: primero todas las funciones (func_begin ... func_end),
  despues la etiqueta main y las sentencias globales en orden.
- Temporales t1, t2, ... y etiquetas L1, L2, ...; cada generate() reinicia los
  contadores. Si el programa usa un identificador con forma de temporal (t1),
  ese nombre se salta para no confundir variables con temporales.
- Las coerciones int -> float quedan explicitas (int_to_float) en operaciones
  mixtas, asignaciones, argumentos y return. Para conocer los tipos destino se
  hace una pre-pasada propia sobre el Program: este modulo no depende de la
  tabla de simbolos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .ast_nodes import (
    FLOAT, INT, STR, VOID, Assign, BinaryOp, Block, Call, ExprStmt, Expression, FuncDecl,
    Identifier, If, Literal, Node, NodeVisitor, Print, Program, Return, UnaryOp, VarDecl,
)

BINARY_OPS = ("+", "-", "*", "/", "==", "!=", "<", ">", "<=", ">=", "&&", "||")
UNARY_OPS = {"-": "neg", "!": "not"}
UNARY_SYMBOLS = {"neg": "-", "not": "!"}
MAIN_LABEL = "main"
_TEMP_PATTERN = re.compile(r"t\d+")


@dataclass
class Quadruple:
    """Una instruccion TAC: (op, arg1, arg2, result)."""

    op: str
    arg1: str | None = None
    arg2: str | None = None
    result: str | None = None

    def to_dict(self, index: int) -> dict:
        return {"index": index, "op": self.op, "arg1": self.arg1, "arg2": self.arg2,
                "result": self.result, "text": str(self)}

    def __str__(self) -> str:
        op, a1, a2, res = self.op, self.arg1, self.arg2, self.result
        if op in BINARY_OPS:
            return f"{res} = {a1} {op} {a2}"
        if op in UNARY_SYMBOLS:
            return f"{res} = {UNARY_SYMBOLS[op]} {a1}"
        if op == "int_to_float":
            return f"{res} = int_to_float {a1}"
        if op == "=":
            return f"{res} = {a1}"
        if op == "label":
            return f"{res}:"
        if op == "goto":
            return f"goto {res}"
        if op == "if_false":
            return f"if_false {a1} goto {res}"
        if op == "call":
            call = f"call {a1}, {a2}"
            return f"{res} = {call}" if res else call
        if op == "return":
            return f"return {a1}" if a1 is not None else "return"
        # param, print, func_begin, func_end
        return f"{op} {a1}"


class IRGenerator(NodeVisitor):
    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._quads: list[Quadruple] = []
        self._temp_count = 0
        self._label_count = 0
        self._reserved: set[str] = set()
        # nombre -> (tipos de parametros, tipo de retorno)
        self._functions: dict[str, tuple[list[str], str]] = {}
        self._scopes: list[dict[str, str]] = [{}]
        self._return_type: str | None = None

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
    def generate(self, program: Program) -> list[Quadruple]:
        self._reset()
        self._prepass(program)

        functions = [s for s in program.statements if isinstance(s, FuncDecl)]
        others = [s for s in program.statements if not isinstance(s, FuncDecl)]
        for function in functions:
            self.visit(function)
        self._emit("label", result=MAIN_LABEL)
        for statement in others:
            self.visit(statement)
        return self._quads

    # ------------------------------------------------------------------
    # Pre-pasada: firmas, tipos de globales y nombres reservados
    # ------------------------------------------------------------------
    def _prepass(self, program: Program) -> None:
        for statement in program.statements:
            if isinstance(statement, FuncDecl):
                self._functions[statement.name] = (
                    [param.type_name for param in statement.params], statement.return_type)
            elif isinstance(statement, VarDecl):
                self._scopes[0][statement.name] = statement.type_name
        self._collect_names(program)

    def _collect_names(self, node) -> None:
        """Guarda los identificadores del programa para no reutilizarlos como temporales."""
        if isinstance(node, list):
            for item in node:
                self._collect_names(item)
            return
        if not isinstance(node, Node):
            return
        for attr in ("name", "callee"):
            value = getattr(node, attr, None)
            if isinstance(value, str):
                self._reserved.add(value)
        for value in vars(node).values():
            if isinstance(value, (Node, list)):
                self._collect_names(value)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _emit(self, op: str, arg1: str | None = None, arg2: str | None = None,
              result: str | None = None) -> Quadruple:
        quad = Quadruple(op, arg1, arg2, result)
        self._quads.append(quad)
        return quad

    def _new_temp(self) -> str:
        while True:
            self._temp_count += 1
            name = f"t{self._temp_count}"
            if name not in self._reserved:
                return name

    def _new_label(self) -> str:
        self._label_count += 1
        return f"L{self._label_count}"

    def _lookup_type(self, name: str) -> str | None:
        for scope in reversed(self._scopes):
            if name in scope:
                return scope[name]
        return None

    def _coerce(self, operand: str, source_type: str | None, target_type: str | None) -> str:
        """Emite int_to_float cuando un valor int llega a un destino float."""
        if source_type == INT and target_type == FLOAT:
            temp = self._new_temp()
            self._emit("int_to_float", operand, result=temp)
            return temp
        return operand

    def _expression(self, node: Expression, target_type: str | None = None) -> str:
        operand = self.visit(node)
        return self._coerce(operand, node.inferred_type, target_type)

    def _block(self, block: Block) -> None:
        self._scopes.append({})
        for statement in block.statements:
            self.visit(statement)
        self._scopes.pop()

    # ------------------------------------------------------------------
    # Sentencias
    # ------------------------------------------------------------------
    def visit_Program(self, node: Program) -> None:
        for statement in node.statements:
            self.visit(statement)

    def visit_FuncDecl(self, node: FuncDecl) -> None:
        self._emit("func_begin", node.name)
        self._scopes.append({param.name: param.type_name for param in node.params})
        self._return_type = node.return_type
        for statement in node.body.statements:
            self.visit(statement)
        self._return_type = None
        self._scopes.pop()
        self._emit("func_end", node.name)

    def visit_Block(self, node: Block) -> None:
        self._block(node)

    def visit_VarDecl(self, node: VarDecl) -> None:
        self._scopes[-1][node.name] = node.type_name
        if node.initializer is None:
            return  # una declaracion sin valor no genera codigo
        value = self._expression(node.initializer, node.type_name)
        self._emit("=", value, result=node.name)

    def visit_Assign(self, node: Assign) -> None:
        value = self._expression(node.value, self._lookup_type(node.name))
        self._emit("=", value, result=node.name)

    def visit_If(self, node: If) -> None:
        condition = self._expression(node.condition)
        end_label = self._new_label()
        if node.else_block is None:
            self._emit("if_false", condition, result=end_label)
            self._block(node.then_block)
            self._emit("label", result=end_label)
            return
        else_label = end_label
        end_label = self._new_label()
        self._emit("if_false", condition, result=else_label)
        self._block(node.then_block)
        self._emit("goto", result=end_label)
        self._emit("label", result=else_label)
        self._block(node.else_block)
        self._emit("label", result=end_label)

    def visit_Return(self, node: Return) -> None:
        if node.value is None:
            self._emit("return")
            return
        value = self._expression(node.value, self._return_type)
        self._emit("return", value)

    def visit_Print(self, node: Print) -> None:
        self._emit("print", self._expression(node.value))

    def visit_ExprStmt(self, node: ExprStmt) -> None:
        self.visit(node.expression)

    # ------------------------------------------------------------------
    # Expresiones: cada visit_ devuelve el operando que contiene el valor
    # ------------------------------------------------------------------
    def visit_Literal(self, node: Literal) -> str:
        value = node.value
        if isinstance(value, bool):
            return "true" if value else "false"
        if node.type_name == STR or isinstance(value, str):
            return f'"{value}"'
        return str(value)

    def visit_Identifier(self, node: Identifier) -> str:
        return node.name

    def visit_BinaryOp(self, node: BinaryOp) -> str:
        left_type, right_type = node.left.inferred_type, node.right.inferred_type
        # Si un lado es float y el otro int, el int se convierte antes de operar.
        target = FLOAT if FLOAT in (left_type, right_type) else None
        left = self._expression(node.left, target)
        right = self._expression(node.right, target)
        temp = self._new_temp()
        self._emit(node.operator, left, right, temp)
        return temp

    def visit_UnaryOp(self, node: UnaryOp) -> str:
        operand = self._expression(node.operand)
        temp = self._new_temp()
        self._emit(UNARY_OPS[node.operator], operand, result=temp)
        return temp

    def visit_Call(self, node: Call) -> str | None:
        param_types, return_type = self._functions.get(node.callee, ([], node.inferred_type))
        # Primero se evaluan todos los argumentos y luego se emiten los param:
        # asi una llamada anidada no se mezcla con los param de la exterior.
        values = []
        for index, argument in enumerate(node.arguments):
            target = param_types[index] if index < len(param_types) else None
            values.append(self._expression(argument, target))
        for value in values:
            self._emit("param", value)
        result = None if return_type == VOID else self._new_temp()
        self._emit("call", node.callee, str(len(values)), result)
        return result
