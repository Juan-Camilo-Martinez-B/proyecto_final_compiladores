"""Reglas de compatibilidad de tipos y coercion int -> float.

BINARY_RULES y UNARY_RULES son diccionarios indexados por tuplas: la busqueda
es O(1) y la tabla se puede mostrar tal cual en la sustentacion. Una
combinacion ausente no es un error todavia; el analizador decide el mensaje.
El tipo especial "error" corta la cascada: si un operando ya fallo, la
operacion tambien es "error" y no se reporta un segundo diagnostico.
"""
# ======================================================================
# type_system.py - Sistema de tipos (sesion 6)
# ----------------------------------------------------------------------
# Define que operaciones son validas y que tipo producen:
#   - Equivalencia  : dos tipos son iguales si tienen el mismo nombre.
#   - Compatibilidad: que combinaciones de tipos acepta cada operador.
#   - Coercion      : conversion implicita segura; solo int -> float.
#
# Se usa una TABLA (diccionario) en lugar de una cadena de if:
#   BINARY_RULES[("+", "int", "float")] -> "float"
#   BINARY_RULES[("-", "int", "str")]   -> no existe -> error S04
#
# Las funciones de este modulo no reportan errores: solo responden. El
# analizador semantico decide el mensaje.
# ======================================================================
from __future__ import annotations

from .ast_nodes import BOOL, FLOAT, INT, STR

# Tipo interno para expresiones que ya fallaron. Nunca aparece en el fuente.
ERROR_TYPE = "error"

# Grupos de tipos y operadores para construir la tabla con ciclos.
_NUMERIC = (INT, FLOAT)
_COMPARISONS = ("<", ">", "<=", ">=")
_EQUALITY = ("==", "!=")
_ARITHMETIC = ("+", "-", "*", "/")


# Tipo resultante de una operacion aritmetica entre dos numeros:
#   int con int -> int (por eso int / int es division entera).
#   si alguno es float -> float.
def _numeric_result(left: str, right: str) -> str:
    """int si ambos son int (la division entera incluida); si no, float."""
    if left == INT and right == INT:
        return INT
    return FLOAT


# Construye la tabla de reglas binarias: (operador, tipo_izq, tipo_der) -> tipo.
# Toda combinacion que no quede en la tabla es invalida.
def _build_binary_rules() -> dict[tuple[str, str, str], str]:
    rules: dict[tuple[str, str, str], str] = {}
    # Las 4 combinaciones numericas (int/float con int/float):
    for left in _NUMERIC:
        for right in _NUMERIC:
            result = _numeric_result(left, right)
            for operator in _ARITHMETIC:        # + - * / dan un numero
                rules[(operator, left, right)] = result
            for operator in _COMPARISONS:       # < > <= >= dan bool
                rules[(operator, left, right)] = BOOL
            for operator in _EQUALITY:          # == != dan bool
                rules[(operator, left, right)] = BOOL
    # La suma tambien concatena. == y != aceptan el mismo tipo no numerico.
    rules[("+", STR, STR)] = STR
    for type_name in (STR, BOOL):
        for operator in _EQUALITY:
            rules[(operator, type_name, type_name)] = BOOL
    # Los operadores logicos solo aceptan bool.
    for operator in ("&&", "||"):
        rules[(operator, BOOL, BOOL)] = BOOL
    return rules


# La tabla se construye una sola vez, al importar el modulo.
BINARY_RULES = _build_binary_rules()

# Reglas de los operadores unarios: (operador, tipo) -> tipo.
UNARY_RULES = {
    ("-", INT): INT,       # negativo de un entero
    ("-", FLOAT): FLOAT,   # negativo de un real
    ("!", BOOL): BOOL,     # negacion logica
}


# Tipo de "left op right".
# Retorna el tipo resultante, ERROR_TYPE si un operando ya era un error (asi
# no se reporta dos veces el mismo problema), o None si no hay regla.
def binary_result(op: str, left: str, right: str) -> str | None:
    """Tipo resultante, "error" si un operando ya fallo, o None si no hay regla."""
    if left == ERROR_TYPE or right == ERROR_TYPE:
        return ERROR_TYPE
    return BINARY_RULES.get((op, left, right))


# Tipo de "op operand", con la misma logica que binary_result.
def unary_result(op: str, operand: str) -> str | None:
    """Tipo resultante, "error" si el operando ya fallo, o None si no hay regla."""
    if operand == ERROR_TYPE:
        return ERROR_TYPE
    return UNARY_RULES.get((op, operand))


# Indica si un valor de tipo source se puede guardar en un destino de tipo
# target. Se usa en inicializaciones, asignaciones, argumentos y return.
#   - mismo tipo           -> si (equivalencia por nombre)
#   - target float, int    -> si (coercion implicita segura)
#   - float a int          -> no (perderia los decimales)
#   - source "error"       -> si, para no reportar un error en cascada
def is_assignable(target: str, source: str) -> bool:
    """True si source puede guardarse en target. error no dispara otro error."""
    if source == ERROR_TYPE:
        return True
    if target == source:
        return True
    return target == FLOAT and source == INT
