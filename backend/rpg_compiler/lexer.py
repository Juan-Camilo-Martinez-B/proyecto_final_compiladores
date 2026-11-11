"""Analizador lexico de RPGScript.

Combina todos los patrones del lenguaje en una sola expresion regular con grupos
nombrados. El motor de expresiones regulares se comporta como el automata finito
(DFA) visto en clase: en cada posicion prueba las alternativas en orden y la
primera que coincide define el token. Los errores lexicos se reportan con linea y
columna y el escaneo continua, para encontrarlos todos en una sola pasada.
"""
import re

from .errors import ErrorReporter, Phase
from .tokens import KEYWORDS, SYMBOLS, Token, TokenType

# El orden importa: los patrones mas especificos van primero.
TOKEN_SPEC: list[tuple[str, str]] = [
    ("COMMENT", r"//[^\n]*"),
    ("NEWLINE", r"\n"),
    ("SKIP", r"[ \t\r]+"),
    ("FLOAT", r"\d+\.\d+"),
    ("BAD_IDENT", r"\d+[A-Za-z_]\w*"),
    ("INT", r"\d+"),
    ("STRING", r'"[^"\n]*"'),
    ("UNTERMINATED", r'"[^"\n]*'),
    ("IDENT", r"[A-Za-z_]\w*"),
    ("OP2", r"->|==|!=|<=|>=|&&|\|\|"),
    ("OP1", r"[+\-*/<>=!(){},;]"),
    ("MISMATCH", r"."),
]

MASTER_PATTERN = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC))

_IGNORED = {"COMMENT", "SKIP"}


def tokenize(source: str, reporter: ErrorReporter) -> list[Token]:
    """Convierte el codigo fuente en tokens; siempre termina con un token EOF."""
    tokens: list[Token] = []
    line = 1
    line_start = 0

    for match in MASTER_PATTERN.finditer(source):
        kind = match.lastgroup
        lexeme = match.group()
        column = match.start() - line_start + 1

        if kind == "NEWLINE":
            line += 1
            line_start = match.end()
            continue
        if kind in _IGNORED:
            continue

        token_type = _classify(kind, lexeme)
        if token_type is None:
            reporter.error(Phase.LEXICAL, _error_message(kind, lexeme), line, column)
            continue
        tokens.append(Token(token_type, lexeme, line, column))

    tokens.append(Token(TokenType.EOF, "", line, len(source) - line_start + 1))
    return tokens


def _classify(kind: str, lexeme: str) -> TokenType | None:
    """Devuelve el tipo de token, o None si el lexema es un error lexico."""
    if kind == "INT":
        return TokenType.INT_LITERAL
    if kind == "FLOAT":
        return TokenType.FLOAT_LITERAL
    if kind == "STRING":
        return TokenType.STRING_LITERAL
    if kind == "IDENT":
        return KEYWORDS.get(lexeme, TokenType.IDENTIFIER)
    if kind in ("OP1", "OP2"):
        return SYMBOLS[lexeme]
    return None


def _error_message(kind: str, lexeme: str) -> str:
    if kind == "BAD_IDENT":
        return f"Identificador inválido '{lexeme}': no puede empezar con un dígito."
    if kind == "UNTERMINATED":
        return "Cadena sin cerrar: falta la comilla de cierre en esta línea."
    return f"Carácter no reconocido '{lexeme}'."
