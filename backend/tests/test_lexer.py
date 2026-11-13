# ======================================================================
# Pruebas de la FASE 1 (lexer.py).
# Verifican tipos de token, posiciones (linea y columna), palabras reservadas,
# la regla de la coincidencia mas larga (1.5 es FLOAT, -> es ARROW), que los
# comentarios se ignoran y los 3 errores lexicos de examples/error_lexico.rpg.
#
# Ejecutar (desde backend/): python -m unittest tests.test_lexer -v
# ======================================================================
import unittest
from pathlib import Path

from rpg_compiler.errors import ErrorReporter, Phase
from rpg_compiler.lexer import tokenize
from rpg_compiler.tokens import TokenType

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def scan(source: str):
    reporter = ErrorReporter()
    return tokenize(source, reporter), reporter


def types_of(tokens):
    return [token.type for token in tokens]


class LexerTest(unittest.TestCase):
    def test_simple_declaration_with_positions(self):
        tokens, reporter = scan("int vida = 100;")
        self.assertFalse(reporter.has_errors())
        self.assertEqual(types_of(tokens), [
            TokenType.TYPE, TokenType.IDENTIFIER, TokenType.ASSIGN,
            TokenType.INT_LITERAL, TokenType.SEMICOLON, TokenType.EOF,
        ])
        self.assertEqual([(t.line, t.column) for t in tokens[:5]],
                         [(1, 1), (1, 5), (1, 10), (1, 12), (1, 15)])

    def test_keywords_are_not_identifiers(self):
        tokens, _ = scan("func if else return print true false void funcion")
        self.assertEqual(types_of(tokens)[:-1], [
            TokenType.FUNC, TokenType.IF, TokenType.ELSE, TokenType.RETURN, TokenType.PRINT,
            TokenType.TRUE, TokenType.FALSE, TokenType.TYPE, TokenType.IDENTIFIER,
        ])

    def test_float_versus_int(self):
        tokens, _ = scan("1.5 15 0.25")
        self.assertEqual(types_of(tokens)[:-1], [
            TokenType.FLOAT_LITERAL, TokenType.INT_LITERAL, TokenType.FLOAT_LITERAL,
        ])

    def test_two_char_operators(self):
        tokens, _ = scan("-> <= >= == != && || < > = !")
        self.assertEqual(types_of(tokens)[:-1], [
            TokenType.ARROW, TokenType.LTE, TokenType.GTE, TokenType.EQ, TokenType.NEQ,
            TokenType.AND, TokenType.OR, TokenType.LT, TokenType.GT, TokenType.ASSIGN, TokenType.NOT,
        ])

    def test_string_keeps_quotes(self):
        tokens, _ = scan('str heroe = "Aria la valiente";')
        self.assertEqual(tokens[3].type, TokenType.STRING_LITERAL)
        self.assertEqual(tokens[3].lexeme, '"Aria la valiente"')

    def test_comments_are_ignored(self):
        tokens, reporter = scan("// comentario @ con basura\nint a; // otro")
        self.assertFalse(reporter.has_errors())
        self.assertEqual(types_of(tokens), [
            TokenType.TYPE, TokenType.IDENTIFIER, TokenType.SEMICOLON, TokenType.EOF,
        ])

    def test_columns_on_second_line(self):
        tokens, _ = scan("int a;\n  float b;")
        float_token = tokens[3]
        self.assertEqual((float_token.lexeme, float_token.line, float_token.column), ("float", 2, 3))

    def test_always_ends_with_eof(self):
        tokens, _ = scan("")
        self.assertEqual(types_of(tokens), [TokenType.EOF])

    def test_lexical_errors_example(self):
        source = (EXAMPLES / "error_lexico.rpg").read_text(encoding="utf-8")
        tokens, reporter = scan(source)
        errors = [d for d in reporter.diagnostics if d.phase is Phase.LEXICAL]
        self.assertEqual([(d.line, d.column) for d in errors], [(2, 15), (3, 14), (4, 5)])
        self.assertIn("'@'", errors[0].message)
        self.assertIn("Cadena sin cerrar", errors[1].message)
        self.assertIn("2poder", errors[2].message)
        self.assertEqual(tokens[-1].type, TokenType.EOF)

    def test_scanner_continues_after_error(self):
        tokens, reporter = scan("int # a = 1;")
        self.assertTrue(reporter.has_errors(Phase.LEXICAL))
        self.assertIn(TokenType.INT_LITERAL, types_of(tokens))


if __name__ == "__main__":
    unittest.main()
