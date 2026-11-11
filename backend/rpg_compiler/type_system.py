"""Reglas de compatibilidad de tipos y coercion int -> float.

BINARY_RULES y UNARY_RULES son diccionarios indexados por tuplas: la busqueda
es O(1) y la tabla se puede mostrar tal cual en la sustentacion. Una
combinacion ausente no es un error todavia; el analizador decide el mensaje.
El tipo especial "error" corta la cascada: si un operando ya fallo, la
operacion tambien es "error" y no se reporta un segundo diagnostico.
"""
from __future__ import annotations

from .ast_nodes import BOOL, FLOAT, INT, STR

ERROR_TYPE = "error"

_NUMERIC = (INT, FLOAT)
_COMPARISONS = ("<", ">", "<=", ">=")
_EQUALITY = ("==", "!=")
_ARITHMETIC = ("+", "-", "*", "/")


def _numeric_result(left: str, right: str) -> str:
    """int si ambos son int (la division entera incluida); si no, float."""
    if left == INT and right == INT:
        return INT
    return FLOAT


def _build_binary_rules() -> dict[tuple[str, str, str], str]:
    rules: dict[tuple[str, str, str], str] = {}
    for left in _NUMERIC:
        for right in _NUMERIC:
            result = _numeric_result(left, right)
            for operator in _ARITHMETIC:
                rules[(operator, left, right)] = result
            for operator in _COMPARISONS:
                rules[(operator, left, right)] = BOOL
            for operator in _EQUALITY:
                rules[(operator, left, right)] = BOOL
    # La suma tambien concatena. == y != aceptan el mismo tipo no numerico.
    rules[("+", STR, STR)] = STR
    for type_name in (STR, BOOL):
        for operator in _EQUALITY:
            rules[(operator, type_name, type_name)] = BOOL
    for operator in ("&&", "||"):
        rules[(operator, BOOL, BOOL)] = BOOL
    return rules


BINARY_RULES = _build_binary_rules()

UNARY_RULES = {
    ("-", INT): INT,
    ("-", FLOAT): FLOAT,
    ("!", BOOL): BOOL,
}


def binary_result(op: str, left: str, right: str) -> str | None:
    """Tipo resultante, "error" si un operando ya fallo, o None si no hay regla."""
    if left == ERROR_TYPE or right == ERROR_TYPE:
        return ERROR_TYPE
    return BINARY_RULES.get((op, left, right))


def unary_result(op: str, operand: str) -> str | None:
    """Tipo resultante, "error" si el operando ya fallo, o None si no hay regla."""
    if operand == ERROR_TYPE:
        return ERROR_TYPE
    return UNARY_RULES.get((op, operand))


def is_assignable(target: str, source: str) -> bool:
    """True si source puede guardarse en target. error no dispara otro error."""
    if source == ERROR_TYPE:
        return True
    if target == source:
        return True
    return target == FLOAT and source == INT
