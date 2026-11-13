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
# ======================================================================
# semantic_analyzer.py - FASE 3: analisis semantico (sesiones 5 y 6)
# ----------------------------------------------------------------------
# Entrada : el AST que produjo el parser.
# Salida  : un SemanticResult (simbolos, ambitos, traza y cadenas) y el
#           mismo AST con inferred_type en cada expresion.
#
# La sintaxis solo dice si el programa esta bien escrito; esta fase decide si
# TIENE SENTIDO. Combina dos herramientas:
#   - La tabla de simbolos (symbol_table.py): que nombres existen y donde.
#   - El sistema de tipos (type_system.py): que operaciones son validas.
#
# Es un VISITANTE (patron Visitor): hay un metodo visit_<Nodo> para cada
# tipo de nodo. Los visit_ de expresiones retornan el tipo calculado, que se
# propaga de las hojas a la raiz (atributo sintetizado).
#
# Reglas que verifica (codigos del plan):
#   S01 variable no declarada          S10 numero de argumentos
#   S02 redeclaracion en el ambito     S11 tipo de argumento
#   S03 shadowing (advertencia)        S12 tipo de return
#   S04 operador binario incompatible  S13 return fuera de funcion
#   S05 operador unario incompatible   S14 funcion sin return (advertencia)
#   S06 asignacion incompatible        S15 funcion void usada como valor
#   S07 variable void                  S16 funcion usada como variable
#   S08 condicion del if no booleana   S17 funcion o parametro repetido
#   S09 llamar algo que no es funcion
# ======================================================================
from __future__ import annotations

from dataclasses import dataclass

from .ast_nodes import (
    BOOL, VOID, Block, Call, ExprStmt, Expression, FuncDecl, Node, NodeVisitor, Program, VarDecl,
)
from .errors import Phase
from .symbol_table import Scope, Symbol, SymbolTable
from .type_system import ERROR_TYPE, binary_result, is_assignable, unary_result


# ----------------------------------------------------------------------
# SemanticResult: lo que entrega esta fase a las siguientes.
#   symbols         : todos los simbolos definidos, en orden (memoria y VM).
#   scopes          : todos los ambitos creados, incluidos los cerrados (web).
#   trace           : traza de enter/exit/define/lookup (web).
#   string_literals : cadenas del programa sin repetir (heap del modelo de memoria).
# ----------------------------------------------------------------------
@dataclass
class SemanticResult:
    """Salida del analisis: simbolos para la memoria, ambitos y traza para la API."""

    symbols: list[Symbol]
    scopes: list[Scope]
    trace: list[dict]
    string_literals: list[str]

    # Formato JSON del contrato: los ambitos con sus simbolos y la traza.
    def to_dict(self) -> dict:
        return {
            "scopes": [scope.to_dict() for scope in self.scopes],
            "trace": self.trace,
        }


class SemanticAnalyzer(NodeVisitor):
    # Estado del recorrido:
    #   _table            : la tabla de simbolos con su pila de ambitos.
    #   _symbols          : simbolos definidos, en orden (para SemanticResult).
    #   _strings          : cadenas literales en orden de aparicion, sin repetir.
    #   _known_strings    : set para saber en O(1) si una cadena ya se guardo.
    #   _current_function : simbolo de la funcion que se esta analizando
    #                       (None en el nivel global); valida los return.
    #   _function_owner   : nombre de la funcion duena de las variables locales.
    #   _has_return       : si la funcion actual tiene algun return (regla S14).
    #   _expect_value     : False cuando una llamada es una sentencia sola; asi
    #                       una funcion void se puede llamar sin usar su valor.
    #   _functions/_owners: simbolo y nombre dueno de cada FuncDecl, por id del nodo.
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

    # Punto de entrada: recorre el programa y empaqueta el resultado.
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

    # Las DOS PASADAS:
    #   1. Registra solo las firmas de las funciones globales.
    #   2. Visita todas las sentencias en orden.
    # Gracias a la pasada 1, una funcion se puede llamar antes de declararse y
    # puede ser recursiva.
    def visit_Program(self, node: Program) -> None:
        for statement in node.statements:
            if isinstance(statement, FuncDecl):
                self._register_function(statement)
        for statement in node.statements:
            self.visit(statement)

    # Analiza el cuerpo de una funcion:
    #   1. Abre el ambito func:<nombre>.
    #   2. Guarda el contexto anterior y marca esta funcion como la actual.
    #   3. Define los parametros (sin repetir) en el nuevo ambito.
    #   4. Visita las sentencias del cuerpo SIN abrir otro ambito para el bloque
    #      raiz: las locales de la funcion viven en func:<nombre>.
    #   5. Si no es void y no tuvo return, emite la advertencia S14.
    #   6. Restaura el contexto y cierra el ambito.
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
            if param.name in seen:      # el repetido ya se reporto en la pasada 1 (S17)
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

    # Un bloque { } suelto abre su propio ambito block@<linea>.
    def visit_Block(self, node: Block) -> None:
        # El bloque raiz de una funcion no pasa por aqui: sus sentencias viven
        # en el ambito func:<nombre>. Un bloque suelto si abre el suyo.
        self._with_scope(f"block@{node.line}", node.line, node)

    # Declaracion de variable (int vida = 100;):
    #   - Primero evalua el inicializador: en "int x = x;" la x de la derecha
    #     todavia no existe en este ambito.
    #   - Rechaza el tipo void (S07) y valores incompatibles (S06).
    #   - La define; si ya existia en este ambito es redeclaracion (S02); si
    #     existe en un ambito padre es shadowing (S03).
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

    # Asignacion (vida = 50;): la variable debe existir y ser visible (S01), no
    # puede ser una funcion (S16) y el valor debe ser compatible (S06).
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

    # Condicional: la condicion debe ser bool (S08). La rama then abre el
    # ambito if@<linea> y la rama else, else@<linea>.
    def visit_If(self, node: If) -> None:
        condition = self._as_value(node.condition)
        if condition not in (ERROR_TYPE, BOOL):
            self._error(node, f"La condición del 'if' debe ser 'bool', se obtuvo '{condition}'.")
        self._with_scope(f"if@{node.line}", node.line, node.then_block)
        if node.else_block is not None:
            self._with_scope(f"else@{node.line}", node.line, node.else_block)

    # Retorno: solo dentro de una funcion (S13) y con un valor compatible con el
    # tipo de retorno declarado (S12). "return;" equivale a retornar void.
    def visit_Return(self, node: Return) -> None:
        value_type = self._as_value(node.value) if node.value is not None else VOID
        if self._current_function is None:
            self._error(node, "'return' solo se permite dentro de una función.")
            return
        self._has_return = True
        expected = self._current_function.return_type
        if value_type == ERROR_TYPE:      # el error ya se reporto en la expresion
            return
        if not is_assignable(expected, value_type):
            returned = value_type if node.value is not None else VOID
            self._error(
                node,
                f"'{self._current_function.name}' debe retornar '{expected}', pero retorna '{returned}'.",
            )

    # print acepta cualquier tipo de valor; solo se valida la expresion.
    def visit_Print(self, node) -> None:
        self._as_value(node.value)

    # Una expresion usada como sentencia (por ejemplo, saludar();). Desactiva
    # _expect_value: aqui una funcion void es valida porque no se usa su valor.
    def visit_ExprStmt(self, node: ExprStmt) -> None:
        # Una llamada void como sentencia si es valida; no se usa como valor.
        previous = self._expect_value
        self._expect_value = False
        self.visit(node.expression)
        self._expect_value = previous

    # Los parametros se procesan en visit_FuncDecl; este metodo existe para
    # que el visitante no falle si llega a recibir un Param.
    def visit_Param(self, node) -> None:
        return None

    # ------------------------------------------------------------------
    # Expresiones: devuelven el tipo y anotan inferred_type
    # ------------------------------------------------------------------

    # Un literal tiene su tipo fijo. Las cadenas se guardan (sin repetir) para
    # el heap del modelo de memoria.
    def visit_Literal(self, node: Literal) -> str:
        if node.type_name == "str" and node.value not in self._known_strings:
            self._known_strings.add(node.value)
            self._strings.append(node.value)
        return self._annotate(node, node.type_name)

    # Uso de una variable: lookup en la pila de ambitos. Si no existe es S01;
    # si es el nombre de una funcion, S16. En ambos casos el tipo es "error".
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

    # Operacion binaria: primero el tipo de cada lado y luego la tabla de reglas.
    # Sin regla es S04 y el resultado queda "error" para cortar la cascada.
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

    # Operacion unaria (-x, !x): igual que la binaria, con UNARY_RULES (S05).
    def visit_UnaryOp(self, node) -> str:
        operand = self._as_value(node.operand)
        result = unary_result(node.operator, operand)
        if result is None:
            self._error(node, f"El operador '{node.operator}' no se puede aplicar a '{operand}'.")
            result = ERROR_TYPE
        return self._annotate(node, result)

    # Llamada a funcion. Verifica, en orden:
    #   - que el nombre exista y sea una funcion (S09),
    #   - que la cantidad de argumentos coincida (S10),
    #   - que cada argumento sea compatible con su parametro (S11),
    #   - que una funcion void no se use como valor (S15).
    # El tipo de la llamada es el tipo de retorno de la funcion.
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

    # Pasada 1: registra la firma de una funcion en el ambito global.
    # Detecta parametros repetidos y funciones repetidas (S17). Una funcion
    # repetida recibe un nombre interno distinto (nombre#linea:columna) para que
    # sus variables locales no se mezclen con las de la primera declaracion.
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

    # Crea un Symbol y lo define en el ambito actual de la tabla.
    # Retorna (simbolo, previo): previo no es None si hubo redeclaracion.
    # Las variables y parametros guardan su funcion duena (None en el global).
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

    # Regla S03: si un ambito PADRE ya declara este nombre, el nuevo lo oculta.
    # Es legal, por eso es una advertencia y no un error.
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

    # Abre un ambito, visita las sentencias del bloque y lo cierra.
    def _with_scope(self, name: str, line: int, block: Block) -> None:
        self._table.enter_scope(name, line)
        for statement in block.statements:
            self.visit(statement)
        self._table.exit_scope(line)

    # Visita una expresion cuyo valor SI se va a usar (_expect_value = True) y
    # retorna su tipo. try/finally restaura el valor anterior aunque falle.
    def _as_value(self, expression: Expression) -> str:
        previous = self._expect_value
        self._expect_value = True
        try:
            return self.visit(expression)
        finally:
            self._expect_value = previous

    # Guarda el tipo calculado en el nodo (lo usa el generador de IR) y lo retorna.
    def _annotate(self, expression: Expression, type_name: str) -> str:
        expression.inferred_type = type_name
        return type_name

    # Registra un error semantico en la posicion del nodo.
    def _error(self, node: Node, message: str) -> None:
        self._reporter.error(Phase.SEMANTIC, message, node.line, node.column)

    # Registra una advertencia semantica en la posicion del nodo.
    def _warning(self, node: Node, message: str) -> None:
        self._reporter.warning(Phase.SEMANTIC, message, node.line, node.column)
