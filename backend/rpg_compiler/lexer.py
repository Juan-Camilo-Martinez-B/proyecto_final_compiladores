"""Analizador lexico de RPGScript.

Combina todos los patrones del lenguaje en una sola expresion regular con grupos
nombrados. El motor de expresiones regulares se comporta como el automata finito
(DFA) visto en clase: en cada posicion prueba las alternativas en orden y la
primera que coincide define el token. Los errores lexicos se reportan con linea y
columna y el escaneo continua, para encontrarlos todos en una sola pasada.
"""
# ======================================================================
# lexer.py - FASE 1: analisis lexico
# ----------------------------------------------------------------------
# Entrada : el codigo fuente como texto.
# Salida  : una lista de Token que siempre termina en EOF.
#
# Teoria (sesiones 1 y 2):
#   - Patron : regla que describe un tipo de token (una expresion regular).
#   - Lexema : el texto concreto del fuente que coincide con un patron.
#   - Token  : el par (tipo, lexema) que se entrega al parser.
# Cada patron describe un LENGUAJE REGULAR (el conjunto de cadenas que acepta),
# y todo lenguaje regular es reconocido por un automata finito.
#
# Errores que detecta: caracter no reconocido (@), cadena sin cerrar y
# identificador que empieza con digito (2poder). No se detiene en el primero.
# ======================================================================
import re

from .errors import ErrorReporter, Phase
from .tokens import KEYWORDS, SYMBOLS, Token, TokenType

# ----------------------------------------------------------------------
# TOKEN_SPEC: la especificacion lexica del lenguaje.
# Lista ordenada de pares (nombre del grupo, expresion regular).
# El orden importa: la alternancia "|" se queda con la PRIMERA opcion que
# coincide, no con la mas larga. Por eso se ordena de lo mas especifico a lo
# mas general, imitando la regla de la "coincidencia mas larga":
#   - FLOAT antes que INT       -> "1.5" no se parte en "1" y ".5".
#   - BAD_IDENT antes que INT   -> "2poder" se reporta completo como error.
#   - STRING antes que UNTERMINATED -> una cadena bien cerrada no es error.
#   - OP2 antes que OP1         -> "->" no se parte en "-" y ">".
#   - MISMATCH va al final      -> atrapa cualquier caracter que nadie reconocio.
# ----------------------------------------------------------------------
# El orden importa: los patrones mas especificos van primero.
TOKEN_SPEC: list[tuple[str, str]] = [
    ("COMMENT", r"//[^\n]*"),               # comentario hasta fin de linea (se descarta)
    ("NEWLINE", r"\n"),                     # salto de linea (solo actualiza el contador)
    ("SKIP", r"[ \t\r]+"),                  # espacios y tabulaciones (se descartan)
    ("FLOAT", r"\d+\.\d+"),                 # 1.5, 50.0
    ("BAD_IDENT", r"\d+[A-Za-z_]\w*"),      # ERROR: identificador que empieza con digito
    ("INT", r"\d+"),                        # 100
    ("STRING", r'"[^"\n]*"'),               # "Aria" (no puede cruzar lineas)
    ("UNTERMINATED", r'"[^"\n]*'),          # ERROR: cadena sin comilla de cierre
    ("IDENT", r"[A-Za-z_]\w*"),             # nombres y palabras reservadas
    ("OP2", r"->|==|!=|<=|>=|&&|\|\|"),     # operadores de dos caracteres
    ("OP1", r"[+\-*/<>=!(){},;]"),          # operadores y delimitadores de uno
    ("MISMATCH", r"."),                     # ERROR: cualquier otro caracter
]

# Une todos los patrones en UNA sola expresion regular:
#   (?P<COMMENT>//[^\n]*)|(?P<NEWLINE>\n)|...|(?P<MISMATCH>.)
# Cada patron va en un grupo nombrado (?P<NOMBRE>...). Al escanear,
# match.lastgroup dice que grupo coincidio, es decir, que tipo de token es.
# Se compila una sola vez al importar el modulo.
MASTER_PATTERN = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC))

# Grupos que coinciden pero no producen token.
_IGNORED = {"COMMENT", "SKIP"}


# ----------------------------------------------------------------------
# tokenize(source, reporter): punto de entrada de la fase.
#   source   : codigo fuente completo.
#   reporter : acumulador donde se registran los errores lexicos.
# Retorna la lista de tokens validos; siempre termina con un token EOF.
#
# Algoritmo: finditer recorre el texto de izquierda a derecha y, en cada
# posicion, aplica MASTER_PATTERN. Como MISMATCH acepta cualquier caracter,
# nunca queda texto sin revisar.
# ----------------------------------------------------------------------
def tokenize(source: str, reporter: ErrorReporter) -> list[Token]:
    """Convierte el codigo fuente en tokens; siempre termina con un token EOF."""
    tokens: list[Token] = []
    line = 1          # linea actual (empieza en 1)
    line_start = 0    # indice del texto donde empezo la linea actual

    for match in MASTER_PATTERN.finditer(source):
        kind = match.lastgroup                       # nombre del grupo que coincidio
        lexeme = match.group()                       # texto que coincidio
        column = match.start() - line_start + 1      # columna relativa a la linea

        # Un salto de linea solo actualiza la posicion; no es un token.
        if kind == "NEWLINE":
            line += 1
            line_start = match.end()
            continue
        # Comentarios y espacios se descartan.
        if kind in _IGNORED:
            continue

        # Clasifica el lexema. None significa que es un error lexico:
        # se reporta y se sigue escaneando (recuperacion de errores).
        token_type = _classify(kind, lexeme)
        if token_type is None:
            reporter.error(Phase.LEXICAL, _error_message(kind, lexeme), line, column)
            continue
        tokens.append(Token(token_type, lexeme, line, column))

    # EOF marca el final; su columna es la posicion despues del ultimo caracter.
    tokens.append(Token(TokenType.EOF, "", line, len(source) - line_start + 1))
    return tokens


# ----------------------------------------------------------------------
# _classify(kind, lexeme): traduce el grupo de la expresion regular a un
# TokenType. Retorna None para los grupos de error (BAD_IDENT, UNTERMINATED,
# MISMATCH).
# ----------------------------------------------------------------------
def _classify(kind: str, lexeme: str) -> TokenType | None:
    """Devuelve el tipo de token, o None si el lexema es un error lexico."""
    if kind == "INT":
        return TokenType.INT_LITERAL
    if kind == "FLOAT":
        return TokenType.FLOAT_LITERAL
    if kind == "STRING":
        return TokenType.STRING_LITERAL
    if kind == "IDENT":
        # Palabra reservada si esta en KEYWORDS; si no, es un nombre del usuario.
        return KEYWORDS.get(lexeme, TokenType.IDENTIFIER)
    if kind in ("OP1", "OP2"):
        return SYMBOLS[lexeme]
    return None


# ----------------------------------------------------------------------
# _error_message(kind, lexeme): mensaje en espanol para cada error lexico.
# ----------------------------------------------------------------------
def _error_message(kind: str, lexeme: str) -> str:
    if kind == "BAD_IDENT":
        return f"Identificador inválido '{lexeme}': no puede empezar con un dígito."
    if kind == "UNTERMINATED":
        return "Cadena sin cerrar: falta la comilla de cierre en esta línea."
    return f"Carácter no reconocido '{lexeme}'."
