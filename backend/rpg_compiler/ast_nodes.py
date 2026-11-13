"""Nodos del AST de RPGScript y visitante base (patrón Visitor)."""
# ======================================================================
# ast_nodes.py - Arbol de Sintaxis Abstracta (AST)
# ----------------------------------------------------------------------
# El parser convierte la lista de tokens en un arbol: cada nodo representa
# una construccion del lenguaje (una declaracion, un if, una suma...).
# Es un arbol ABSTRACTO porque descarta lo que solo sirve a la sintaxis
# (parentesis, punto y coma, llaves): (1 + 2) * 3 queda como
#   BinaryOp('*', BinaryOp('+', 1, 2), 3)
# y la agrupacion se refleja en la forma del arbol.
#
# Este archivo es un CONTRATO entre fases:
#   - parser.py construye los nodos.
#   - semantic_analyzer.py los recorre y llena inferred_type.
#   - ir_generator.py los recorre para generar codigo intermedio.
# Tambien define NodeVisitor, la base del patron Visitor que usan esas fases.
# ======================================================================
from __future__ import annotations

from dataclasses import dataclass, field, fields

# Nombres de los tipos de dato. Todo el compilador usa estas mismas cadenas.
INT = "int"
FLOAT = "float"
STR = "str"
BOOL = "bool"
VOID = "void"   # solo valido como tipo de retorno de una funcion
VALUE_TYPES = (INT, FLOAT, STR, BOOL)   # tipos que puede tener una variable


# ----------------------------------------------------------------------
# Node: base de todos los nodos. Guarda la posicion del token que origino el
# nodo, para que las fases posteriores reporten errores en la linea exacta.
# kw_only=True obliga a crear los nodos con argumentos por nombre:
#   VarDecl(type_name="int", name="vida", line=1, column=1)
# ----------------------------------------------------------------------
@dataclass(kw_only=True)
class Node:
    line: int
    column: int


# ----------------------------------------------------------------------
# Expression: base de todo lo que produce un valor.
# inferred_type empieza en None; el analizador semantico lo llena con el tipo
# calculado ("int", "float", ...) o con "error" si la expresion es invalida.
# ----------------------------------------------------------------------
@dataclass(kw_only=True)
class Expression(Node):
    # Lo asigna el analizador semántico y lo consume el generador de IR.
    inferred_type: str | None = None


# ---------- Expresiones ----------

# Valor escrito directamente: 100, 1.5, "Aria", true.
# value ya viene convertido al tipo de Python (int, float, str o bool);
# type_name es el tipo de RPGScript.
@dataclass(kw_only=True)
class Literal(Expression):
    value: int | float | str | bool
    type_name: str


# Uso de una variable por su nombre: vida.
@dataclass(kw_only=True)
class Identifier(Expression):
    name: str


# Operacion con dos operandos: left operator right (por ejemplo vida - dano).
@dataclass(kw_only=True)
class BinaryOp(Expression):
    operator: str          # + - * / == != < > <= >= && ||
    left: Expression
    right: Expression


# Operacion con un operando: -x o !vivo.
@dataclass(kw_only=True)
class UnaryOp(Expression):
    operator: str          # - !
    operand: Expression


# Llamada a funcion: curar(10). callee es el nombre de la funcion.
@dataclass(kw_only=True)
class Call(Expression):
    callee: str
    arguments: list[Expression] = field(default_factory=list)


# ---------- Sentencias ----------

# Raiz del arbol: todas las sentencias y funciones de nivel global, en orden.
@dataclass(kw_only=True)
class Program(Node):
    statements: list[Node] = field(default_factory=list)


# Bloque entre llaves { ... }. Lo usan las funciones y los if/else.
@dataclass(kw_only=True)
class Block(Node):
    statements: list[Node] = field(default_factory=list)


# Declaracion de variable: int vida = 100;  (initializer es None si no hay "= valor").
@dataclass(kw_only=True)
class VarDecl(Node):
    type_name: str
    name: str
    initializer: Expression | None = None


# Asignacion a una variable existente: vida = 50;
@dataclass(kw_only=True)
class Assign(Node):
    name: str
    value: Expression


# Parametro de una funcion: int cantidad.
@dataclass(kw_only=True)
class Param(Node):
    type_name: str
    name: str


# Declaracion de funcion: func curar(int cantidad) -> int { ... }
@dataclass(kw_only=True)
class FuncDecl(Node):
    name: str
    params: list[Param]
    return_type: str
    body: Block


# Condicional: if (condicion) { ... } else { ... }  (else_block es opcional).
@dataclass(kw_only=True)
class If(Node):
    condition: Expression
    then_block: Block
    else_block: Block | None = None


# Retorno de funcion: return valor;  (value es None en "return;").
@dataclass(kw_only=True)
class Return(Node):
    value: Expression | None = None


# Impresion: print(valor);
@dataclass(kw_only=True)
class Print(Node):
    value: Expression


# Expresion usada como sentencia, por ejemplo una llamada sola: curar(10);
@dataclass(kw_only=True)
class ExprStmt(Node):
    expression: Expression


# ----------------------------------------------------------------------
# node_to_dict(value): convierte un nodo (o una lista de nodos) en un dict
# listo para JSON. Recorre los campos de la dataclass de forma recursiva y
# agrega "node" con el nombre de la clase. Asi la web y la CLI dibujan el
# arbol sin conocer las clases de Python.
# Ejemplo: Literal(value=7, ...) -> {"node": "Literal", "value": 7, ...}
# ----------------------------------------------------------------------
def node_to_dict(value):
    """Serializa recursivamente un nodo (o lista de nodos) al formato JSON del contrato."""
    if isinstance(value, Node):
        data = {"node": type(value).__name__}
        for item in fields(value):
            data[item.name] = node_to_dict(getattr(value, item.name))
        return data
    if isinstance(value, list):
        return [node_to_dict(item) for item in value]
    return value   # valores simples (str, int, None...) se dejan tal cual


# ----------------------------------------------------------------------
# NodeVisitor: base del patron Visitor.
# Separa el recorrido del arbol de las clases de los nodos: cada fase hereda
# de NodeVisitor y define un metodo por tipo de nodo (visit_Literal,
# visit_If, ...). Agregar una fase nueva no obliga a modificar los nodos.
# ----------------------------------------------------------------------
class NodeVisitor:
    """Despacha visit_<NombreDelNodo>; cada fase hereda de esta clase."""

    # Despacho dinamico: arma el nombre "visit_" + nombre de la clase del nodo
    # y llama a ese metodo. Si la fase no lo define, usa generic_visit.
    def visit(self, node: Node):
        method = getattr(self, f"visit_{type(node).__name__}", self.generic_visit)
        return method(node)

    # Se ejecuta cuando una fase no sabe procesar un tipo de nodo.
    def generic_visit(self, node: Node):
        raise NotImplementedError(
            f"{type(self).__name__} no implementa visit_{type(node).__name__}")
