"""Analizador semantico de RPGScript.

Dos pasadas sobre el AST:

1. Registra las firmas de las funciones del ambito global. Asi una llamada
   puede aparecer antes de la declaracion y una funcion puede llamarse a si
   misma.
2. Recorre el programa en orden. Cada expresion queda anotada con
   inferred_type. Si algo falla, el tipo es "error" y las operaciones que lo
   usan no reportan un segundo diagnostico.

Las reglas y el texto de cada diagnostico estan en la seccion 2.4 del plan.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ast_nodes import (
    BOOL, VOID, Block, Call, ExprStmt, Expression, FuncDecl, Node, NodeVisitor, Program, VarDecl,
)
from .errors import Phase
from .symbol_table import Scope, Symbol, SymbolTable
from .type_system import ERROR_TYPE, binary_result, is_assignable, unary_result


@dataclass
class SemanticResult:
    """Salida del analisis: simbolos para la memoria, ambitos y traza para la API."""

    symbols: list[Symbol]
    scopes: list[Scope]
    trace: list[dict]
    string_literals: list[str]

    def to_dict(self) -> dict:
        return {
            "scopes": [scope.to_dict() for scope in self.scopes],
            "trace": self.trace,
        }


class SemanticAnalyzer(NodeVisitor):
    def __init__(self, reporter) -> None:
        self._reporter = reporter
        self._table = SymbolTable()
        self._symbols: list[Symbol] = []
        self._strings: list[str] = []
        self._known_strings: set[str] = set()
        self._current_function: Symbol | None = None
        self._function_owner: str | None = None
        self._has_return = False
        self._expect_value = True
        self._functions: dict[int, Symbol] = {}
        self._owners: dict[int, str] = {}

    def analyze(self, program: Program) -> SemanticResult:
        self.visit(program)
        return SemanticResult(
            symbols=self._symbols,
            scopes=self._table.all_scopes,
            trace=self._table.trace,
            string_literals=self._strings,
        )

    # ------------------------------------------------------------------
    # Recorrido
    # ------------------------------------------------------------------
    def visit_Program(self, node: Program) -> None:
        for statement in node.statements:
            if isinstance(statement, FuncDecl):
                self._register_function(statement)
        for statement in node.statements:
            self.visit(statement)

    def visit_FuncDecl(self, node: FuncDecl) -> None:
        if id(node) not in self._functions:
            self._register_function(node)
        symbol = self._functions[id(node)]
        self._table.enter_scope(f"func:{node.name}", node.line)
        previous_function = self._current_function
        previous_owner = self._function_owner
        previous_return = self._has_return
        self._current_function = symbol
        self._function_owner = self._owners[id(node)]
        self._has_return = False
        seen: set[str] = set()
        for param in node.params:
            if param.name in seen:
                continue
            seen.add(param.name)
            if param.type_name == VOID:
                self._error(param, f"El parámetro '{param.name}' no puede ser de tipo 'void'.")
            self._define(param.name, param.type_name, "parameter", param.line, param.column)
            self._warn_if_shadows(param, param.name)
        for statement in node.body.statements:
            self.visit(statement)
        if symbol.return_type != VOID and not self._has_return:
            self._warning(
                node,
                f"La función '{node.name}' declara '{symbol.return_type}' pero no tiene 'return'.",
            )
        self._current_function = previous_function
        self._function_owner = previous_owner
        self._has_return = previous_return
        self._table.exit_scope(node.line)

    def visit_Block(self, node: Block) -> None:
        # El bloque raiz de una funcion no pasa por aqui: sus sentencias viven
        # en el ambito func:<nombre>. Un bloque suelto si abre el suyo.
        self._with_scope(f"block@{node.line}", node.line, node)

    def visit_VarDecl(self, node: VarDecl) -> None:
        init_type = self._as_value(node.initializer) if node.initializer is not None else None
        if node.type_name == VOID:
            self._error(node, f"La variable '{node.name}' no puede ser de tipo 'void'.")
        elif init_type is not None and not is_assignable(node.type_name, init_type):
            self._error(
                node,
                f"No se puede asignar un valor '{init_type}' a '{node.name}' de tipo '{node.type_name}'.",
            )
        _, previous = self._define(node.name, node.type_name, "variable", node.line, node.column)
        if previous is not None:
            self._error(
                node,
                f"La variable '{node.name}' ya fue declarada en el ámbito "
                f"'{self._table.current_scope.name}' (línea {previous.line}).",
            )
        else:
            self._warn_if_shadows(node, node.name)

    def visit_Assign(self, node: Assign) -> None:
        symbol = self._table.lookup(node.name, node.line)
        value_type = self._as_value(node.value)
        if symbol is None:
            self._error(
                node,
                f"La variable '{node.name}' no está declarada en el ámbito "
                f"'{self._table.current_scope.name}'.",
            )
            return
        if symbol.kind == "function":
            self._error(node, f"'{node.name}' es una función y no se puede usar como variable.")
            return
        if not is_assignable(symbol.type_name, value_type):
            self._error(
                node,
                f"No se puede asignar un valor '{value_type}' a '{node.name}' de tipo '{symbol.type_name}'.",
            )

    def visit_If(self, node: If) -> None:
        condition = self._as_value(node.condition)
        if condition not in (ERROR_TYPE, BOOL):
            self._error(node, f"La condición del 'if' debe ser 'bool', se obtuvo '{condition}'.")
        self._with_scope(f"if@{node.line}", node.line, node.then_block)
        if node.else_block is not None:
            self._with_scope(f"else@{node.line}", node.line, node.else_block)

    def visit_Return(self, node: Return) -> None:
        value_type = self._as_value(node.value) if node.value is not None else VOID
        if self._current_function is None:
            self._error(node, "'return' solo se permite dentro de una función.")
            return
        self._has_return = True
        expected = self._current_function.return_type
        if value_type == ERROR_TYPE:
            return
        if not is_assignable(expected, value_type):
            returned = value_type if node.value is not None else VOID
            self._error(
                node,
                f"'{self._current_function.name}' debe retornar '{expected}', pero retorna '{returned}'.",
            )

    def visit_Print(self, node) -> None:
        self._as_value(node.value)

    def visit_ExprStmt(self, node: ExprStmt) -> None:
        # Una llamada void como sentencia si es valida; no se usa como valor.
        previous = self._expect_value
        self._expect_value = False
        self.visit(node.expression)
        self._expect_value = previous

    def visit_Param(self, node) -> None:
        return None

    # ------------------------------------------------------------------
    # Expresiones: devuelven el tipo y anotan inferred_type
    # ------------------------------------------------------------------
    def visit_Literal(self, node: Literal) -> str:
        if node.type_name == "str" and node.value not in self._known_strings:
            self._known_strings.add(node.value)
            self._strings.append(node.value)
        return self._annotate(node, node.type_name)

    def visit_Identifier(self, node: Identifier) -> str:
        symbol = self._table.lookup(node.name, node.line)
        if symbol is None:
            self._error(
                node,
                f"La variable '{node.name}' no está declarada en el ámbito "
                f"'{self._table.current_scope.name}'.",
            )
            return self._annotate(node, ERROR_TYPE)
        if symbol.kind == "function":
            self._error(node, f"'{node.name}' es una función y no se puede usar como variable.")
            return self._annotate(node, ERROR_TYPE)
        return self._annotate(node, symbol.type_name)

    def visit_BinaryOp(self, node) -> str:
        left = self._as_value(node.left)
        right = self._as_value(node.right)
        result = binary_result(node.operator, left, right)
        if result is None:
            self._error(
                node,
                f"El operador '{node.operator}' no está definido entre '{left}' y '{right}'.",
            )
            result = ERROR_TYPE
        return self._annotate(node, result)

    def visit_UnaryOp(self, node) -> str:
        operand = self._as_value(node.operand)
        result = unary_result(node.operator, operand)
        if result is None:
            self._error(node, f"El operador '{node.operator}' no se puede aplicar a '{operand}'.")
            result = ERROR_TYPE
        return self._annotate(node, result)

    def visit_Call(self, node: Call) -> str:
        symbol = self._table.lookup(node.callee, node.line)
        arg_types = [self._as_value(argument) for argument in node.arguments]
        if symbol is None or symbol.kind != "function":
            self._error(node, f"'{node.callee}' no es una función.")
            return self._annotate(node, ERROR_TYPE)
        params = symbol.params or []
        if len(arg_types) != len(params):
            self._error(
                node,
                f"La función '{node.callee}' espera {len(params)} argumento(s) "
                f"y recibió {len(arg_types)}.",
            )
        for index, (expected, actual) in enumerate(zip(params, arg_types), start=1):
            if not is_assignable(expected, actual):
                self._error(
                    node.arguments[index - 1],
                    f"El argumento {index} de '{node.callee}' debe ser '{expected}', "
                    f"se recibió '{actual}'.",
                )
        if symbol.return_type == VOID and self._expect_value:
            self._error(node, f"La función '{node.callee}' es 'void' y no produce un valor.")
            return self._annotate(node, ERROR_TYPE)
        return self._annotate(node, symbol.return_type or VOID)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    def _register_function(self, node: FuncDecl) -> None:
        """Pasada 1: deja la firma visible antes de mirar el cuerpo."""
        param_types = [param.type_name for param in node.params]
        seen: set[str] = set()
        for param in node.params:
            if param.name in seen:
                self._error(param, f"El parámetro '{param.name}' está repetido en '{node.name}'.")
            else:
                seen.add(param.name)
        existing = self._table.lookup_local(node.name)
        if existing is not None:
            self._error(
                node,
                f"La función '{node.name}' ya fue declarada en el ámbito "
                f"'{self._table.current_scope.name}' (línea {existing.line}).",
            )
            symbol = Symbol(
                name=node.name, type_name=node.return_type, kind="function",
                scope_name=self._table.current_scope.name,
                level=self._table.current_scope.level,
                line=node.line, column=node.column, function=None,
                params=param_types, return_type=node.return_type,
            )
            self._functions[id(node)] = symbol
            # Un nombre distinto evita que sus locales se mezclen con la primera firma.
            self._owners[id(node)] = f"{node.name}#{node.line}:{node.column}"
            return
        symbol, _ = self._define(
            node.name, node.return_type, "function", node.line, node.column,
            params=param_types, return_type=node.return_type,
        )
        self._functions[id(node)] = symbol
        self._owners[id(node)] = node.name

    def _define(self, name: str, type_name: str, kind: str, line: int, column: int,
                params: list[str] | None = None, return_type: str | None = None,
                ) -> tuple[Symbol, Symbol | None]:
        """Inserta el simbolo. El segundo valor es el previo si ya existia en este ambito."""
        symbol = Symbol(
            name=name, type_name=type_name, kind=kind,
            scope_name=self._table.current_scope.name,
            level=self._table.current_scope.level,
            line=line, column=column,
            function=None if kind == "function" else self._function_owner,
            params=params, return_type=return_type,
        )
        previous = self._table.define(symbol)
        if previous is None:
            self._symbols.append(symbol)
        return symbol, previous

    def _warn_if_shadows(self, node: Node, name: str) -> None:
        scope = self._table.current_scope.parent
        while scope is not None:
            outer = scope.lookup_local(name)
            if outer is not None:
                self._warning(
                    node,
                    f"'{name}' oculta a la variable declarada en el ámbito '{outer.scope_name}'.",
                )
                return
            scope = scope.parent

    def _with_scope(self, name: str, line: int, block: Block) -> None:
        self._table.enter_scope(name, line)
        for statement in block.statements:
            self.visit(statement)
        self._table.exit_scope(line)

    def _as_value(self, expression: Expression) -> str:
        previous = self._expect_value
        self._expect_value = True
        try:
            return self.visit(expression)
        finally:
            self._expect_value = previous

    def _annotate(self, expression: Expression, type_name: str) -> str:
        expression.inferred_type = type_name
        return type_name

    def _error(self, node: Node, message: str) -> None:
        self._reporter.error(Phase.SEMANTIC, message, node.line, node.column)

    def _warning(self, node: Node, message: str) -> None:
        self._reporter.warning(Phase.SEMANTIC, message, node.line, node.column)
