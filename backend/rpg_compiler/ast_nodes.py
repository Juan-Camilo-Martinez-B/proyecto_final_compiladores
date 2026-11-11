"""Nodos del AST de RPGScript y visitante base (patrón Visitor)."""
from __future__ import annotations

from dataclasses import dataclass, field, fields

INT = "int"
FLOAT = "float"
STR = "str"
BOOL = "bool"
VOID = "void"
VALUE_TYPES = (INT, FLOAT, STR, BOOL)


@dataclass(kw_only=True)
class Node:
    line: int
    column: int


@dataclass(kw_only=True)
class Expression(Node):
    # Lo asigna el analizador semántico y lo consume el generador de IR.
    inferred_type: str | None = None


# ---------- Expresiones ----------
@dataclass(kw_only=True)
class Literal(Expression):
    value: int | float | str | bool
    type_name: str


@dataclass(kw_only=True)
class Identifier(Expression):
    name: str


@dataclass(kw_only=True)
class BinaryOp(Expression):
    operator: str          # + - * / == != < > <= >= && ||
    left: Expression
    right: Expression


@dataclass(kw_only=True)
class UnaryOp(Expression):
    operator: str          # - !
    operand: Expression


@dataclass(kw_only=True)
class Call(Expression):
    callee: str
    arguments: list[Expression] = field(default_factory=list)


# ---------- Sentencias ----------
@dataclass(kw_only=True)
class Program(Node):
    statements: list[Node] = field(default_factory=list)


@dataclass(kw_only=True)
class Block(Node):
    statements: list[Node] = field(default_factory=list)


@dataclass(kw_only=True)
class VarDecl(Node):
    type_name: str
    name: str
    initializer: Expression | None = None


@dataclass(kw_only=True)
class Assign(Node):
    name: str
    value: Expression


@dataclass(kw_only=True)
class Param(Node):
    type_name: str
    name: str


@dataclass(kw_only=True)
class FuncDecl(Node):
    name: str
    params: list[Param]
    return_type: str
    body: Block


@dataclass(kw_only=True)
class If(Node):
    condition: Expression
    then_block: Block
    else_block: Block | None = None


@dataclass(kw_only=True)
class Return(Node):
    value: Expression | None = None


@dataclass(kw_only=True)
class Print(Node):
    value: Expression


@dataclass(kw_only=True)
class ExprStmt(Node):
    expression: Expression


def node_to_dict(value):
    """Serializa recursivamente un nodo (o lista de nodos) al formato JSON del contrato."""
    if isinstance(value, Node):
        data = {"node": type(value).__name__}
        for item in fields(value):
            data[item.name] = node_to_dict(getattr(value, item.name))
        return data
    if isinstance(value, list):
        return [node_to_dict(item) for item in value]
    return value


class NodeVisitor:
    """Despacha visit_<NombreDelNodo>; cada fase hereda de esta clase."""

    def visit(self, node: Node):
        method = getattr(self, f"visit_{type(node).__name__}", self.generic_visit)
        return method(node)

    def generic_visit(self, node: Node):
        raise NotImplementedError(
            f"{type(self).__name__} no implementa visit_{type(node).__name__}")
