"""Analizador sintactico descendente recursivo de RPGScript.

Cada regla de la gramatica EBNF (ver docs/lexer_parser.md) es un metodo. La
precedencia de operadores queda codificada en los niveles de la gramatica:
logicOr -> logicAnd -> equality -> comparison -> term -> factor -> unary -> call.

Recuperacion de errores en dos niveles:
1. Insercion de simbolo faltante: si falta ';', ')' o '}', se reporta y se
   continua como si estuviera (no se consume nada).
2. Modo panico: ante cualquier otro error se descartan tokens hasta un punto de
   sincronizacion (';', '}' o el inicio de una sentencia).
"""
from collections.abc import Callable

from .ast_nodes import (
    BOOL, FLOAT, INT, STR, Assign, BinaryOp, Block, Call, Expression, ExprStmt, FuncDecl,
    Identifier, If, Literal, Node, Param, Print, Program, Return, UnaryOp, VarDecl,
)
from .errors import ErrorReporter, Phase
from .tokens import Token, TokenType

T = TokenType

# Tokens con los que puede iniciar una sentencia; sirven para sincronizar.
_SYNC_STARTS = {T.FUNC, T.IF, T.RETURN, T.PRINT}

_CLOSING_SYMBOLS = {T.SEMICOLON: ";", T.RPAREN: ")", T.RBRACE: "}"}


class _ParseError(Exception):
    """Senal interna para activar el modo panico."""


class Parser:
    def __init__(self, tokens: list[Token], reporter: ErrorReporter) -> None:
        self._tokens = tokens or [Token(T.EOF, "", 1, 1)]
        self._reporter = reporter
        self._pos = 0

    # ------------------------------------------------------------------
    # Punto de entrada
    # ------------------------------------------------------------------
    def parse(self) -> Program:
        """Construye el AST completo; siempre devuelve un Program."""
        statements: list[Node] = []
        while not self._is_at_end():
            start = self._pos
            node = self._guarded(self._declaration)
            if node is not None:
                statements.append(node)
            self._ensure_progress(start)
        return Program(line=1, column=1, statements=statements)

    # ------------------------------------------------------------------
    # Declaraciones y sentencias
    # ------------------------------------------------------------------
    def _declaration(self) -> Node | None:
        if self._check(T.FUNC):
            return self._func_decl()
        if self._check(T.RBRACE):
            self._error_at(self._advance(), "Se encontró '}' sin un bloque abierto.")
            return None
        return self._statement()

    def _block_item(self) -> Node | None:
        if self._check(T.FUNC):
            token = self._peek()
            self._error_at(token, "Las funciones solo pueden declararse en el ámbito global.")
            self._func_decl()  # se consume completa para no generar errores en cascada
            return None
        return self._statement()

    def _func_decl(self) -> FuncDecl:
        func_token = self._advance()
        name = self._require(T.IDENTIFIER, "Se esperaba el nombre de la función después de 'func'.")
        self._require(T.LPAREN, f"Se esperaba '(' después de '{name.lexeme}'.")
        params: list[Param] = []
        if not self._check(T.RPAREN):
            params.append(self._param())
            while self._match(T.COMMA):
                params.append(self._param())
        self._close(T.RPAREN)
        self._require(T.ARROW, "Se esperaba '->' seguido del tipo de retorno de la función.")
        return_type = self._require(T.TYPE, "Se esperaba el tipo de retorno de la función después de '->'.")
        body = self._block()
        return FuncDecl(line=func_token.line, column=func_token.column, name=name.lexeme,
                        params=params, return_type=return_type.lexeme, body=body)

    def _param(self) -> Param:
        type_token = self._require(T.TYPE, "Se esperaba el tipo del parámetro.")
        name = self._require(T.IDENTIFIER, f"Se esperaba el nombre del parámetro después de '{type_token.lexeme}'.")
        return Param(line=type_token.line, column=type_token.column,
                     type_name=type_token.lexeme, name=name.lexeme)

    def _statement(self) -> Node:
        if self._check(T.TYPE):
            return self._var_decl()
        if self._check(T.IF):
            return self._if_stmt()
        if self._check(T.RETURN):
            return self._return_stmt()
        if self._check(T.PRINT):
            return self._print_stmt()
        if self._check(T.LBRACE):
            return self._block()
        if self._check(T.IDENTIFIER) and self._peek_next().type is T.ASSIGN:
            return self._assignment()
        return self._expr_stmt()

    def _var_decl(self) -> VarDecl:
        type_token = self._advance()
        name = self._require(T.IDENTIFIER, f"Se esperaba un nombre de variable después de '{type_token.lexeme}'.")
        initializer = self._expression() if self._match(T.ASSIGN) else None
        self._close(T.SEMICOLON)
        return VarDecl(line=type_token.line, column=type_token.column, type_name=type_token.lexeme,
                       name=name.lexeme, initializer=initializer)

    def _assignment(self) -> Assign:
        name = self._advance()
        self._advance()  # '='
        value = self._expression()
        self._close(T.SEMICOLON)
        return Assign(line=name.line, column=name.column, name=name.lexeme, value=value)

    def _if_stmt(self) -> If:
        if_token = self._advance()
        self._require(T.LPAREN, "Se esperaba '(' después de 'if'.")
        condition = self._expression()
        self._close(T.RPAREN)
        then_block = self._block()
        else_block = self._block() if self._match(T.ELSE) else None
        return If(line=if_token.line, column=if_token.column, condition=condition,
                  then_block=then_block, else_block=else_block)

    def _return_stmt(self) -> Return:
        return_token = self._advance()
        value = None if self._check(T.SEMICOLON) else self._expression()
        self._close(T.SEMICOLON)
        return Return(line=return_token.line, column=return_token.column, value=value)

    def _print_stmt(self) -> Print:
        print_token = self._advance()
        self._require(T.LPAREN, "Se esperaba '(' después de 'print'.")
        value = self._expression()
        self._close(T.RPAREN)
        self._close(T.SEMICOLON)
        return Print(line=print_token.line, column=print_token.column, value=value)

    def _expr_stmt(self) -> ExprStmt:
        expression = self._expression()
        self._close(T.SEMICOLON)
        return ExprStmt(line=expression.line, column=expression.column, expression=expression)

    def _block(self) -> Block:
        brace = self._require(T.LBRACE, "Se esperaba '{' para abrir el bloque.")
        statements: list[Node] = []
        while not self._check(T.RBRACE) and not self._is_at_end():
            start = self._pos
            node = self._guarded(self._block_item)
            if node is not None:
                statements.append(node)
            if not self._check(T.RBRACE):
                self._ensure_progress(start)
        self._close(T.RBRACE)
        return Block(line=brace.line, column=brace.column, statements=statements)

    # ------------------------------------------------------------------
    # Expresiones (de menor a mayor precedencia)
    # ------------------------------------------------------------------
    def _expression(self) -> Expression:
        return self._logic_or()

    def _logic_or(self) -> Expression:
        return self._binary(self._logic_and, T.OR)

    def _logic_and(self) -> Expression:
        return self._binary(self._equality, T.AND)

    def _equality(self) -> Expression:
        return self._binary(self._comparison, T.EQ, T.NEQ)

    def _comparison(self) -> Expression:
        return self._binary(self._term, T.LT, T.GT, T.LTE, T.GTE)

    def _term(self) -> Expression:
        return self._binary(self._factor, T.PLUS, T.MINUS)

    def _factor(self) -> Expression:
        return self._binary(self._unary, T.STAR, T.SLASH)

    def _binary(self, operand: Callable[[], Expression], *operators: TokenType) -> Expression:
        """Regla generica 'operand (op operand)*' con asociatividad por la izquierda."""
        left = operand()
        while self._match(*operators):
            operator = self._previous()
            right = operand()
            left = BinaryOp(line=operator.line, column=operator.column,
                            operator=operator.lexeme, left=left, right=right)
        return left

    def _unary(self) -> Expression:
        if self._match(T.MINUS, T.NOT):
            operator = self._previous()
            operand = self._unary()
            return UnaryOp(line=operator.line, column=operator.column,
                           operator=operator.lexeme, operand=operand)
        return self._call()

    def _call(self) -> Expression:
        if self._check(T.IDENTIFIER) and self._peek_next().type is T.LPAREN:
            name = self._advance()
            self._advance()  # '('
            arguments: list[Expression] = []
            if not self._check(T.RPAREN):
                arguments.append(self._expression())
                while self._match(T.COMMA):
                    arguments.append(self._expression())
            self._close(T.RPAREN)
            return Call(line=name.line, column=name.column, callee=name.lexeme, arguments=arguments)
        return self._primary()

    def _primary(self) -> Expression:
        token = self._peek()
        literal = self._literal(token)
        if literal is not None:
            self._advance()
            return literal
        if self._match(T.IDENTIFIER):
            return Identifier(line=token.line, column=token.column, name=token.lexeme)
        if self._match(T.LPAREN):
            expression = self._expression()
            self._close(T.RPAREN)
            return expression
        self._error_at(token, f"Se esperaba una expresión y se encontró {self._describe(token)}.")
        raise _ParseError

    @staticmethod
    def _literal(token: Token) -> Literal | None:
        position = {"line": token.line, "column": token.column}
        if token.type is T.INT_LITERAL:
            return Literal(**position, value=int(token.lexeme), type_name=INT)
        if token.type is T.FLOAT_LITERAL:
            return Literal(**position, value=float(token.lexeme), type_name=FLOAT)
        if token.type is T.STRING_LITERAL:
            return Literal(**position, value=token.lexeme[1:-1], type_name=STR)
        if token.type in (T.TRUE, T.FALSE):
            return Literal(**position, value=token.type is T.TRUE, type_name=BOOL)
        return None

    # ------------------------------------------------------------------
    # Recuperacion de errores
    # ------------------------------------------------------------------
    def _guarded(self, rule: Callable[[], Node | None]) -> Node | None:
        """Ejecuta una regla y, si falla, sincroniza en modo panico."""
        try:
            return rule()
        except _ParseError:
            self._synchronize()
            return None

    def _synchronize(self) -> None:
        while not self._is_at_end():
            if self._match(T.SEMICOLON):
                return
            current = self._peek()
            if current.type is T.RBRACE or current.type in _SYNC_STARTS:
                return
            if current.type is T.TYPE and self._peek_next().type is T.IDENTIFIER:
                return
            self._advance()

    def _ensure_progress(self, start: int) -> None:
        """Evita ciclos infinitos: si no se consumio ningun token, se avanza uno."""
        if self._pos == start and not self._is_at_end():
            self._advance()

    def _close(self, token_type: TokenType) -> None:
        """Consume un simbolo de cierre o reporta su ausencia y continua (insercion)."""
        if self._match(token_type):
            return
        symbol = _CLOSING_SYMBOLS[token_type]
        previous = self._previous()
        self._reporter.error(Phase.SYNTAX, f"Se esperaba '{symbol}' después de '{previous.lexeme}'.",
                             previous.line, previous.column + len(previous.lexeme))

    def _require(self, token_type: TokenType, message: str) -> Token:
        """Consume un token obligatorio o activa el modo panico."""
        if self._check(token_type):
            return self._advance()
        self._error_at(self._peek(), f"{message} Se encontró {self._describe(self._peek())}.")
        raise _ParseError

    def _error_at(self, token: Token, message: str) -> None:
        self._reporter.error(Phase.SYNTAX, message, token.line, token.column)

    @staticmethod
    def _describe(token: Token) -> str:
        return "el fin del archivo" if token.type is T.EOF else f"'{token.lexeme}'"

    # ------------------------------------------------------------------
    # Navegacion por los tokens
    # ------------------------------------------------------------------
    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _peek_next(self) -> Token:
        return self._tokens[min(self._pos + 1, len(self._tokens) - 1)]

    def _previous(self) -> Token:
        return self._tokens[max(self._pos - 1, 0)]

    def _is_at_end(self) -> bool:
        return self._peek().type is T.EOF

    def _advance(self) -> Token:
        token = self._peek()
        if not self._is_at_end():
            self._pos += 1
        return token

    def _check(self, token_type: TokenType) -> bool:
        return self._peek().type is token_type

    def _match(self, *token_types: TokenType) -> bool:
        if self._peek().type in token_types:
            self._advance()
            return True
        return False
