"""Tabla de simbolos con pila de ambitos y busqueda lexical.

El ambito actual es la cima de una pila. Cada ambito apunta a su padre, asi que
lookup sube de lo local hacia lo global (visibilidad unidireccional). Al salir
de un ambito se desapila, pero el objeto queda en all_scopes para poder
mostrarlo: una variable local sigue viendose en la tabla aunque ya no sea
visible para el codigo que viene despues.
"""
from __future__ import annotations

from dataclasses import dataclass, field


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


class Scope:
    """Un nivel de la pila. symbols conserva el orden de insercion."""

    def __init__(self, name: str, level: int, parent: Scope | None) -> None:
        self.name = name
        self.level = level
        self.parent = parent
        self.symbols: dict[str, Symbol] = {}

    def define(self, symbol: Symbol) -> bool:
        """Inserta el simbolo. False si ese nombre ya existe en ESTE ambito."""
        if symbol.name in self.symbols:
            return False
        self.symbols[symbol.name] = symbol
        return True

    def lookup_local(self, name: str) -> Symbol | None:
        return self.symbols.get(name)

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


class SymbolTable:
    """Pila de ambitos. global (nivel 0) existe desde el constructor y no se desapila."""

    def __init__(self) -> None:
        global_scope = Scope("global", 0, None)
        self._stack: list[Scope] = [global_scope]
        self.all_scopes: list[Scope] = [global_scope]
        self.trace: list[dict] = []
        self._step = 0

    @property
    def current_scope(self) -> Scope:
        return self._stack[-1]

    def enter_scope(self, name: str, line: int) -> Scope:
        parent = self.current_scope
        scope = Scope(name, parent.level + 1, parent)
        self._stack.append(scope)
        self.all_scopes.append(scope)
        self._record("enter_scope", scope.name, None, None, line)
        return scope

    def exit_scope(self, line: int) -> None:
        if len(self._stack) == 1:
            return
        scope = self._stack.pop()
        self._record("exit_scope", scope.name, None, None, line)

    def define(self, symbol: Symbol) -> Symbol | None:
        """None si quedo definido. El simbolo previo si ya habia redeclaracion."""
        current = self.current_scope
        existing = current.lookup_local(symbol.name)
        if existing is not None:
            return existing
        symbol.scope_name = current.name
        symbol.level = current.level
        current.define(symbol)
        self._record("define", current.name, symbol.name, None, symbol.line)
        return None

    def lookup(self, name: str, line: int) -> Symbol | None:
        """Busca desde el ambito actual hacia el global y deja constancia en la traza."""
        here = self.current_scope.name
        scope: Scope | None = self.current_scope
        while scope is not None:
            found = scope.lookup_local(name)
            if found is not None:
                self._record("lookup", here, name, scope.name, line)
                return found
            scope = scope.parent
        self._record("lookup", here, name, None, line)
        return None

    def lookup_local(self, name: str) -> Symbol | None:
        """Busca solo en el ambito actual, sin traza. Sirve para detectar redeclaraciones."""
        return self.current_scope.lookup_local(name)

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
