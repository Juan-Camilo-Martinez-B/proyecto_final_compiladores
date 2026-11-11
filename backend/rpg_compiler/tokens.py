"""Contrato de tokens compartido por todas las fases del compilador."""
from dataclasses import dataclass
from enum import Enum


class TokenType(str, Enum):
    INT_LITERAL = "INT_LITERAL"
    FLOAT_LITERAL = "FLOAT_LITERAL"
    STRING_LITERAL = "STRING_LITERAL"
    TRUE = "TRUE"
    FALSE = "FALSE"
    IDENTIFIER = "IDENTIFIER"
    TYPE = "TYPE"
    FUNC = "FUNC"
    RETURN = "RETURN"
    IF = "IF"
    ELSE = "ELSE"
    PRINT = "PRINT"
    PLUS = "PLUS"
    MINUS = "MINUS"
    STAR = "STAR"
    SLASH = "SLASH"
    EQ = "EQ"
    NEQ = "NEQ"
    LT = "LT"
    GT = "GT"
    LTE = "LTE"
    GTE = "GTE"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    ASSIGN = "ASSIGN"
    ARROW = "ARROW"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACE = "LBRACE"
    RBRACE = "RBRACE"
    COMMA = "COMMA"
    SEMICOLON = "SEMICOLON"
    EOF = "EOF"


# Palabras reservadas: el lexer las distingue de los identificadores.
KEYWORDS: dict[str, TokenType] = {
    "int": TokenType.TYPE, "float": TokenType.TYPE, "str": TokenType.TYPE,
    "bool": TokenType.TYPE, "void": TokenType.TYPE,
    "func": TokenType.FUNC, "return": TokenType.RETURN, "if": TokenType.IF,
    "else": TokenType.ELSE, "print": TokenType.PRINT,
    "true": TokenType.TRUE, "false": TokenType.FALSE,
}

# Operadores y delimitadores.
SYMBOLS: dict[str, TokenType] = {
    "+": TokenType.PLUS, "-": TokenType.MINUS, "*": TokenType.STAR, "/": TokenType.SLASH,
    "==": TokenType.EQ, "!=": TokenType.NEQ, "<": TokenType.LT, ">": TokenType.GT,
    "<=": TokenType.LTE, ">=": TokenType.GTE, "&&": TokenType.AND, "||": TokenType.OR,
    "!": TokenType.NOT, "=": TokenType.ASSIGN, "->": TokenType.ARROW,
    "(": TokenType.LPAREN, ")": TokenType.RPAREN, "{": TokenType.LBRACE,
    "}": TokenType.RBRACE, ",": TokenType.COMMA, ";": TokenType.SEMICOLON,
}


@dataclass(frozen=True)
class Token:
    type: TokenType
    lexeme: str
    line: int
    column: int

    def to_dict(self) -> dict:
        return {"type": self.type.value, "lexeme": self.lexeme,
                "line": self.line, "column": self.column}
