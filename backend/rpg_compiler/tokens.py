"""Contrato de tokens compartido por todas las fases del compilador."""
# ======================================================================
# tokens.py - Vocabulario del lenguaje RPGScript
# ----------------------------------------------------------------------
# Un TOKEN es la unidad minima con significado que produce el analizador
# lexico: el par (tipo, lexema) mas su posicion en el codigo fuente.
#   - Tipo   : la categoria (IDENTIFIER, PLUS, INT_LITERAL...).
#   - Lexema : el texto exacto que aparecio en el fuente ("vida", "+", "100").
#
# Este archivo es un CONTRATO: el lexer lo produce y el parser lo consume.
# Define tres cosas:
#   1. TokenType : el conjunto de todos los tipos de token que existen.
#   2. KEYWORDS  : las palabras reservadas (el lexer las separa de los nombres).
#   3. SYMBOLS   : los operadores y delimitadores, del texto a su tipo.
# ======================================================================
from dataclasses import dataclass
from enum import Enum


# ----------------------------------------------------------------------
# TokenType: enumeracion con todos los tipos de token del lenguaje.
# Hereda de str para que cada valor se pueda escribir directo en JSON
# (TokenType.PLUS.value == "PLUS").
# ----------------------------------------------------------------------
class TokenType(str, Enum):
    # --- Literales: valores escritos directamente en el codigo ---
    INT_LITERAL = "INT_LITERAL"        # 100
    FLOAT_LITERAL = "FLOAT_LITERAL"    # 1.5
    STRING_LITERAL = "STRING_LITERAL"  # "Aria"
    TRUE = "TRUE"                      # true
    FALSE = "FALSE"                    # false

    # --- Nombres y palabras reservadas ---
    IDENTIFIER = "IDENTIFIER"  # nombres de variables y funciones: vida, curar
    TYPE = "TYPE"              # int, float, str, bool, void (el lexema dice cual)
    FUNC = "FUNC"              # func
    RETURN = "RETURN"          # return
    IF = "IF"                  # if
    ELSE = "ELSE"              # else
    PRINT = "PRINT"            # print

    # --- Operadores aritmeticos ---
    PLUS = "PLUS"    # +
    MINUS = "MINUS"  # -
    STAR = "STAR"    # *
    SLASH = "SLASH"  # /

    # --- Operadores relacionales ---
    EQ = "EQ"    # ==
    NEQ = "NEQ"  # !=
    LT = "LT"    # <
    GT = "GT"    # >
    LTE = "LTE"  # <=
    GTE = "GTE"  # >=

    # --- Operadores logicos ---
    AND = "AND"  # &&
    OR = "OR"    # ||
    NOT = "NOT"  # !

    # --- Delimitadores ---
    ASSIGN = "ASSIGN"        # =
    ARROW = "ARROW"          # -> (separa la firma del tipo de retorno)
    LPAREN = "LPAREN"        # (
    RPAREN = "RPAREN"        # )
    LBRACE = "LBRACE"        # {
    RBRACE = "RBRACE"        # }
    COMMA = "COMMA"          # ,
    SEMICOLON = "SEMICOLON"  # ;

    # --- Fin de archivo: el lexer siempre lo agrega al final ---
    EOF = "EOF"


# Palabras reservadas: el lexer las distingue de los identificadores.
# Funcionamiento: el lexer reconoce "return" con el mismo patron de un
# identificador y luego busca el lexema en este diccionario. Si esta, el token
# es el tipo indicado; si no, es IDENTIFIER. La busqueda en un dict es O(1).
# Los cinco tipos de dato comparten el token TYPE; el parser lee el lexema
# para saber cual es.
KEYWORDS: dict[str, TokenType] = {
    "int": TokenType.TYPE, "float": TokenType.TYPE, "str": TokenType.TYPE,
    "bool": TokenType.TYPE, "void": TokenType.TYPE,
    "func": TokenType.FUNC, "return": TokenType.RETURN, "if": TokenType.IF,
    "else": TokenType.ELSE, "print": TokenType.PRINT,
    "true": TokenType.TRUE, "false": TokenType.FALSE,
}

# Operadores y delimitadores.
# Traduce el texto de un simbolo a su tipo de token. El lexer lo usa despues de
# que la expresion regular reconoce un operador de uno o dos caracteres.
SYMBOLS: dict[str, TokenType] = {
    "+": TokenType.PLUS, "-": TokenType.MINUS, "*": TokenType.STAR, "/": TokenType.SLASH,
    "==": TokenType.EQ, "!=": TokenType.NEQ, "<": TokenType.LT, ">": TokenType.GT,
    "<=": TokenType.LTE, ">=": TokenType.GTE, "&&": TokenType.AND, "||": TokenType.OR,
    "!": TokenType.NOT, "=": TokenType.ASSIGN, "->": TokenType.ARROW,
    "(": TokenType.LPAREN, ")": TokenType.RPAREN, "{": TokenType.LBRACE,
    "}": TokenType.RBRACE, ",": TokenType.COMMA, ";": TokenType.SEMICOLON,
}


# ----------------------------------------------------------------------
# Token: una unidad lexica con su posicion.
#   type   : el TokenType del token.
#   lexeme : el texto original. En las cadenas incluye las comillas ("Aria").
#   line   : linea donde empieza (la primera linea es 1).
#   column : columna donde empieza (la primera columna es 1).
# frozen=True la hace inmutable: ninguna fase puede alterar un token.
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Token:
    type: TokenType
    lexeme: str
    line: int
    column: int

    # Convierte el token al formato JSON que consumen la CLI y la web.
    def to_dict(self) -> dict:
        return {"type": self.type.value, "lexeme": self.lexeme,
                "line": self.line, "column": self.column}
