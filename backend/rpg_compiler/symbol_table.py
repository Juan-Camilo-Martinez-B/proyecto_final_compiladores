"""Tabla de simbolos con pila de ambitos y busqueda lexical.

El ambito actual es la cima de una pila. Cada ambito apunta a su padre, asi que
lookup sube de lo local hacia lo global (visibilidad unidireccional). Al salir
de un ambito se desapila, pero el objeto queda en all_scopes para poder
mostrarlo: una variable local sigue viendose en la tabla aunque ya no sea
visible para el codigo que viene despues.
"""
# ======================================================================
# symbol_table.py - Tabla de simbolos (sesion 5)
# ----------------------------------------------------------------------
# La tabla de simbolos es la "base de datos" del compilador: responde que
# nombres existen, de que tipo son y donde son visibles.
#
# Reglas de los ambitos:
#   1. Global : lo declarado fuera de toda funcion se ve en todo el programa.
#   2. Local  : lo declarado en una funcion o bloque solo existe dentro de el.
#   3. Visibilidad unidireccional: desde adentro se ve hacia afuera, pero
#      desde afuera no se ve hacia adentro.
#
# Implementacion: una PILA de ambitos. Cada ambito tiene un diccionario de
# simbolos y un enlace a su padre:
#
#     cima  ->  if@15          (ambito actual)
#                 |  parent
#               func:curar
#                 |  parent
#               global         (base; nunca se desapila)
#
# Hay dos listas importantes:
#   _stack     : la pila ACTIVA; lookup solo busca aqui.
#   all_scopes : el HISTORIAL de todos los ambitos creados, para mostrarlos.
# ======================================================================
from __future__ import annotations

from dataclasses import dataclass, field


# ----------------------------------------------------------------------
# Symbol: un nombre declarado en el programa.
#   name        : el nombre (vida, curar...).
#   type_name   : su tipo; en una funcion, el tipo de retorno.
#   kind        : "variable", "parameter" o "function".
#   scope_name  : ambito donde se declaro (global, func:curar, if@15...).
#   level       : profundidad del ambito (global = 0).
#   line/column : posicion de la declaracion.
#   function    : funcion duena (None si es global); la usan la memoria y la VM.
#   params      : solo funciones; tipos de los parametros en orden.
#   return_type : solo funciones; tipo de retorno.
# ----------------------------------------------------------------------
@dataclass
class Symbol:
    """Un nombre declarado: variable, parametro o funcion."""

    name: str
    type_name: str
    kind: str                       # "variable" | "parameter" | "function"
    scope_name: str
    level: int
    line: int
    column: int
    function: str | None = None     # funcion duena; None si es global
    params: list[str] | None = None
    return_type: str | None = None

    # Formato JSON del contrato. Ojo: las claves son "type" y "scope".
    def to_dict(self) -> dict:
        """Claves exactas del contrato: type (no type_name) y scope (no scope_name)."""
        return {
            "name": self.name,
            "type": self.type_name,
            "kind": self.kind,
            "scope": self.scope_name,
            "level": self.level,
            "line": self.line,
            "params": self.params,
            "return_type": self.return_type,
        }


# ----------------------------------------------------------------------
# Scope: un nivel de la pila (global, una funcion o un bloque).
# symbols es un dict: busqueda O(1) por nombre y conserva el orden de insercion.
# ----------------------------------------------------------------------
class Scope:
    """Un nivel de la pila. symbols conserva el orden de insercion."""

    #   name   : nombre del ambito (global, func:curar, if@15, else@15, block@3).
    #   level  : profundidad (el padre mas uno).
    #   parent : ambito que lo contiene (None solo para global).
    def __init__(self, name: str, level: int, parent: Scope | None) -> None:
        self.name = name
        self.level = level
        self.parent = parent
        self.symbols: dict[str, Symbol] = {}

    # Inserta un simbolo en ESTE ambito. Retorna False si el nombre ya existe
    # aqui (redeclaracion); no revisa los ambitos padres.
    def define(self, symbol: Symbol) -> bool:
        """Inserta el simbolo. False si ese nombre ya existe en ESTE ambito."""
        if symbol.name in self.symbols:
            return False
        self.symbols[symbol.name] = symbol
        return True

    # Busca un nombre solo en este ambito (sin subir a los padres).
    def lookup_local(self, name: str) -> Symbol | None:
        return self.symbols.get(name)

    # Formato JSON para la web: nombre, nivel, nombre del padre y sus simbolos.
    def to_dict(self) -> dict:
        # Por linea y columna: la primera pasada registra las funciones antes
        # que las variables, pero la tabla se muestra en el orden del fuente.
        ordered = sorted(self.symbols.values(), key=lambda symbol: (symbol.line, symbol.column))
        return {
            "name": self.name,
            "level": self.level,
            "parent": None if self.parent is None else self.parent.name,
            "symbols": [symbol.to_dict() for symbol in ordered],
        }


# ----------------------------------------------------------------------
# SymbolTable: la pila de ambitos con sus operaciones (enter_scope,
# exit_scope, define, lookup). Ademas registra una TRAZA de cada operacion,
# que la web reproduce paso a paso en la pestana Simbolos.
# ----------------------------------------------------------------------
class SymbolTable:
    """Pila de ambitos. global (nivel 0) existe desde el constructor y no se desapila."""

    # Empieza con el ambito global como unico elemento de la pila.
    def __init__(self) -> None:
        global_scope = Scope("global", 0, None)
        self._stack: list[Scope] = [global_scope]       # pila activa
        self.all_scopes: list[Scope] = [global_scope]   # historial completo
        self.trace: list[dict] = []                     # traza para la web
        self._step = 0                                  # contador de pasos de la traza

    # El ambito actual es siempre la cima de la pila.
    @property
    def current_scope(self) -> Scope:
        return self._stack[-1]

    # Entra a un ambito nuevo (al abrir una funcion o un bloque): lo crea como
    # hijo del actual, lo apila y lo guarda en el historial.
    def enter_scope(self, name: str, line: int) -> Scope:
        parent = self.current_scope
        scope = Scope(name, parent.level + 1, parent)
        self._stack.append(scope)        # pasa a ser el ambito actual
        self.all_scopes.append(scope)    # queda guardado para mostrarlo
        self._record("enter_scope", scope.name, None, None, line)
        return scope

    # Sale del ambito actual (al cerrar la llave): lo DESAPILA, asi sus
    # simbolos dejan de ser visibles. No lo borra de all_scopes.
    # El ambito global nunca se desapila.
    def exit_scope(self, line: int) -> None:
        if len(self._stack) == 1:
            return
        scope = self._stack.pop()
        self._record("exit_scope", scope.name, None, None, line)

    # Declara un simbolo en el ambito actual.
    # Retorna None si quedo definido, o el simbolo previo si ese nombre ya
    # existia EN ESTE AMBITO (redeclaracion, error S02). Un mismo nombre en un
    # ambito padre no es redeclaracion: es shadowing (advertencia S03).
    def define(self, symbol: Symbol) -> Symbol | None:
        """None si quedo definido. El simbolo previo si ya habia redeclaracion."""
        current = self.current_scope
        existing = current.lookup_local(symbol.name)
        if existing is not None:
            return existing
        symbol.scope_name = current.name     # el simbolo recuerda donde nacio
        symbol.level = current.level
        current.define(symbol)
        self._record("define", current.name, symbol.name, None, symbol.line)
        return None

    # BUSQUEDA LEXICAL: busca el nombre en el ambito actual y, si no esta, sube
    # por la cadena de padres hasta el global. Asi se cumple la visibilidad
    # unidireccional: se ve hacia afuera, nunca hacia adentro.
    # Retorna el simbolo encontrado o None (variable no declarada, error S01).
    def lookup(self, name: str, line: int) -> Symbol | None:
        """Busca desde el ambito actual hacia el global y deja constancia en la traza."""
        here = self.current_scope.name
        scope: Scope | None = self.current_scope
        while scope is not None:
            found = scope.lookup_local(name)
            if found is not None:
                self._record("lookup", here, name, scope.name, line)   # encontrado
                return found
            scope = scope.parent                                     # sube un nivel
        self._record("lookup", here, name, None, line)                # no encontrado
        return None

    # Busca solo en el ambito actual y sin dejar traza.
    def lookup_local(self, name: str) -> Symbol | None:
        """Busca solo en el ambito actual, sin traza. Sirve para detectar redeclaraciones."""
        return self.current_scope.lookup_local(name)

    # Agrega un evento a la traza:
    #   action   : "enter_scope", "exit_scope", "define" o "lookup".
    #   scope    : ambito actual en ese momento.
    #   name     : nombre involucrado (None al entrar o salir de un ambito).
    #   found_in : en un lookup, ambito donde se encontro (None si no se encontro).
    def _record(self, action: str, scope: str, name: str | None,
                found_in: str | None, line: int) -> None:
        self._step += 1
        self.trace.append({
            "step": self._step,
            "action": action,
            "scope": scope,
            "name": name,
            "found_in": found_in,
            "line": line,
        })
