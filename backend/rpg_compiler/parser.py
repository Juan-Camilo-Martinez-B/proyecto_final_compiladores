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
# ======================================================================
# parser.py - FASE 2: analisis sintactico
# ----------------------------------------------------------------------
# Entrada : la lista de tokens del lexer.
# Salida  : el AST, cuya raiz siempre es un Program (aunque haya errores).
#
# Teoria (sesiones 3 y 4):
#   - Una gramatica libre de contexto define la estructura valida.
#   - Este es un parser DESCENDENTE RECURSIVO (top-down): cada regla de la
#     gramatica es un metodo y los metodos se llaman entre si siguiendo la
#     gramatica. Es LL(1) salvo en dos puntos que miran un token mas:
#     IDENTIFIER "=" es asignacion e IDENTIFIER "(" es llamada.
#   - La PRECEDENCIA sale de los niveles de la gramatica: cuanto mas profunda
#     la regla, mas fuerte liga su operador (* liga mas que +).
#   - La ASOCIATIVIDAD por la izquierda sale del ciclo while de _binary.
#
# Gramatica resumida (EBNF):
#   program    -> declaration* EOF
#   declaration-> funcDecl | statement
#   statement  -> varDecl | assignment | ifStmt | returnStmt | printStmt
#                 | exprStmt | block
#   expression -> logicOr
#   logicOr    -> logicAnd ( "||" logicAnd )*
#   ...        -> (un nivel por precedencia)
#   primary    -> literal | IDENTIFIER | "(" expression ")"
# ======================================================================
from collections.abc import Callable

from .ast_nodes import (
    BOOL, FLOAT, INT, STR, Assign, BinaryOp, Block, Call, Expression, ExprStmt, FuncDecl,
    Identifier, If, Literal, Node, Param, Print, Program, Return, UnaryOp, VarDecl,
)
from .errors import ErrorReporter, Phase
from .tokens import Token, TokenType

T = TokenType   # alias corto para que las reglas se lean mejor

# Tokens con los que puede iniciar una sentencia; sirven para sincronizar.
# En modo panico, el parser descarta tokens hasta encontrar uno de estos.
_SYNC_STARTS = {T.FUNC, T.IF, T.RETURN, T.PRINT}

# Simbolos de cierre que el parser puede "insertar" si faltan.
_CLOSING_SYMBOLS = {T.SEMICOLON: ";", T.RPAREN: ")", T.RBRACE: "}"}


# Excepcion interna: no sale del parser. Se lanza al encontrar un error grave
# y la captura _guarded, que activa el modo panico.
class _ParseError(Exception):
    """Senal interna para activar el modo panico."""


class Parser:
    # tokens   : lista que produjo el lexer (si viene vacia se usa solo un EOF).
    # reporter : acumulador donde se registran los errores sintacticos.
    # _pos     : indice del token actual (el "cursor" del parser).
    def __init__(self, tokens: list[Token], reporter: ErrorReporter) -> None:
        self._tokens = tokens or [Token(T.EOF, "", 1, 1)]
        self._reporter = reporter
        self._pos = 0

    # ------------------------------------------------------------------
    # Punto de entrada
    # ------------------------------------------------------------------

    # Regla: program -> declaration* EOF
    # Lee declaraciones hasta el fin del archivo. Cada una se ejecuta protegida
    # por _guarded: si falla, se sincroniza y se sigue con la siguiente, asi se
    # reportan todos los errores sintacticos en una sola pasada.
    def parse(self) -> Program:
        """Construye el AST completo; siempre devuelve un Program."""
        statements: list[Node] = []
        while not self._is_at_end():
            start = self._pos
            node = self._guarded(self._declaration)
            if node is not None:
                statements.append(node)
            self._ensure_progress(start)   # proteccion contra ciclos infinitos
        return Program(line=1, column=1, statements=statements)

    # ------------------------------------------------------------------
    # Declaraciones y sentencias
    # ------------------------------------------------------------------

    # Regla: declaration -> funcDecl | statement   (solo en el nivel global)
    # Ademas atrapa una '}' sobrante, que no tiene bloque que cerrar.
    def _declaration(self) -> Node | None:
        if self._check(T.FUNC):
            return self._func_decl()
        if self._check(T.RBRACE):
            self._error_at(self._advance(), "Se encontró '}' sin un bloque abierto.")
            return None
        return self._statement()

    # Una sentencia dentro de un bloque { }. Las funciones solo se permiten en
    # el nivel global: si aparece "func" aqui se reporta el error, pero se
    # analiza la funcion completa para que sus tokens no causen mas errores.
    def _block_item(self) -> Node | None:
        if self._check(T.FUNC):
            token = self._peek()
            self._error_at(token, "Las funciones solo pueden declararse en el ámbito global.")
            self._func_decl()  # se consume completa para no generar errores en cascada
            return None
        return self._statement()

    # Regla: funcDecl -> "func" IDENTIFIER "(" params? ")" "->" TYPE block
    #        params   -> param ( "," param )*
    def _func_decl(self) -> FuncDecl:
        func_token = self._advance()                       # consume "func"
        name = self._require(T.IDENTIFIER, "Se esperaba el nombre de la función después de 'func'.")
        self._require(T.LPAREN, f"Se esperaba '(' después de '{name.lexeme}'.")
        params: list[Param] = []
        if not self._check(T.RPAREN):                      # hay al menos un parametro
            params.append(self._param())
            while self._match(T.COMMA):                    # mas parametros separados por coma
                params.append(self._param())
        self._close(T.RPAREN)
        self._require(T.ARROW, "Se esperaba '->' seguido del tipo de retorno de la función.")
        return_type = self._require(T.TYPE, "Se esperaba el tipo de retorno de la función después de '->'.")
        body = self._block()
        return FuncDecl(line=func_token.line, column=func_token.column, name=name.lexeme,
                        params=params, return_type=return_type.lexeme, body=body)

    # Regla: param -> TYPE IDENTIFIER
    def _param(self) -> Param:
        type_token = self._require(T.TYPE, "Se esperaba el tipo del parámetro.")
        name = self._require(T.IDENTIFIER, f"Se esperaba el nombre del parámetro después de '{type_token.lexeme}'.")
        return Param(line=type_token.line, column=type_token.column,
                     type_name=type_token.lexeme, name=name.lexeme)

    # Regla: statement -> varDecl | ifStmt | returnStmt | printStmt | block
    #                     | assignment | exprStmt
    # Decide la regla mirando el token actual (prediccion LL(1)). El unico caso
    # que necesita mirar dos tokens es IDENTIFIER seguido de "=" (asignacion).
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

    # Regla: varDecl -> TYPE IDENTIFIER ( "=" expression )? ";"
    def _var_decl(self) -> VarDecl:
        type_token = self._advance()                       # consume el tipo (int, float...)
        name = self._require(T.IDENTIFIER, f"Se esperaba un nombre de variable después de '{type_token.lexeme}'.")
        initializer = self._expression() if self._match(T.ASSIGN) else None
        self._close(T.SEMICOLON)
        return VarDecl(line=type_token.line, column=type_token.column, type_name=type_token.lexeme,
                       name=name.lexeme, initializer=initializer)

    # Regla: assignment -> IDENTIFIER "=" expression ";"
    def _assignment(self) -> Assign:
        name = self._advance()
        self._advance()  # '='
        value = self._expression()
        self._close(T.SEMICOLON)
        return Assign(line=name.line, column=name.column, name=name.lexeme, value=value)

    # Regla: ifStmt -> "if" "(" expression ")" block ( "else" block )?
    # Los bloques exigen llaves, asi que no existe el problema del "else colgante".
    def _if_stmt(self) -> If:
        if_token = self._advance()
        self._require(T.LPAREN, "Se esperaba '(' después de 'if'.")
        condition = self._expression()
        self._close(T.RPAREN)
        then_block = self._block()
        else_block = self._block() if self._match(T.ELSE) else None
        return If(line=if_token.line, column=if_token.column, condition=condition,
                  then_block=then_block, else_block=else_block)

    # Regla: returnStmt -> "return" expression? ";"
    def _return_stmt(self) -> Return:
        return_token = self._advance()
        value = None if self._check(T.SEMICOLON) else self._expression()
        self._close(T.SEMICOLON)
        return Return(line=return_token.line, column=return_token.column, value=value)

    # Regla: printStmt -> "print" "(" expression ")" ";"
    def _print_stmt(self) -> Print:
        print_token = self._advance()
        self._require(T.LPAREN, "Se esperaba '(' después de 'print'.")
        value = self._expression()
        self._close(T.RPAREN)
        self._close(T.SEMICOLON)
        return Print(line=print_token.line, column=print_token.column, value=value)

    # Regla: exprStmt -> expression ";"   (por ejemplo, una llamada sola: curar(10);)
    def _expr_stmt(self) -> ExprStmt:
        expression = self._expression()
        self._close(T.SEMICOLON)
        return ExprStmt(line=expression.line, column=expression.column, expression=expression)

    # Regla: block -> "{" statement* "}"
    # Igual que parse(), cada sentencia va protegida para recuperarse de errores
    # sin salir del bloque.
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
    # Cada nivel llama al siguiente: asi un operador de menor precedencia
    # queda mas arriba en el arbol y se evalua despues.
    # ------------------------------------------------------------------

    # Regla: expression -> logicOr
    def _expression(self) -> Expression:
        return self._logic_or()

    # Regla: logicOr -> logicAnd ( "||" logicAnd )*        (menor precedencia)
    def _logic_or(self) -> Expression:
        return self._binary(self._logic_and, T.OR)

    # Regla: logicAnd -> equality ( "&&" equality )*
    def _logic_and(self) -> Expression:
        return self._binary(self._equality, T.AND)

    # Regla: equality -> comparison ( ("==" | "!=") comparison )*
    def _equality(self) -> Expression:
        return self._binary(self._comparison, T.EQ, T.NEQ)

    # Regla: comparison -> term ( ("<" | ">" | "<=" | ">=") term )*
    def _comparison(self) -> Expression:
        return self._binary(self._term, T.LT, T.GT, T.LTE, T.GTE)

    # Regla: term -> factor ( ("+" | "-") factor )*
    def _term(self) -> Expression:
        return self._binary(self._factor, T.PLUS, T.MINUS)

    # Regla: factor -> unary ( ("*" | "/") unary )*
    def _factor(self) -> Expression:
        return self._binary(self._unary, T.STAR, T.SLASH)

    # Regla generica para todos los niveles binarios: operand ( op operand )*
    #   operand   : el metodo del nivel siguiente (mas precedencia).
    #   operators : los tokens de operador de este nivel.
    # La gramatica de libro E -> E + T tiene recursion por la izquierda, que en
    # un parser descendente seria un ciclo infinito. Se reescribe como
    # E -> T ( + T )*, y el while la implementa. Como "left" acumula el arbol
    # construido hasta ahora, a - b - c queda (a - b) - c: asociatividad por la
    # izquierda.
    def _binary(self, operand: Callable[[], Expression], *operators: TokenType) -> Expression:
        """Regla generica 'operand (op operand)*' con asociatividad por la izquierda."""
        left = operand()
        while self._match(*operators):
            operator = self._previous()             # el operador que se acaba de consumir
            right = operand()
            left = BinaryOp(line=operator.line, column=operator.column,
                            operator=operator.lexeme, left=left, right=right)
        return left

    # Regla: unary -> ("-" | "!") unary | call
    # Es recursiva por la derecha: --5 se lee como -(-5).
    def _unary(self) -> Expression:
        if self._match(T.MINUS, T.NOT):
            operator = self._previous()
            operand = self._unary()
            return UnaryOp(line=operator.line, column=operator.column,
                           operator=operator.lexeme, operand=operand)
        return self._call()

    # Regla: call -> IDENTIFIER "(" arguments? ")" | primary
    # Necesita mirar dos tokens: un nombre seguido de "(" es una llamada.
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

    # Regla: primary -> literal | IDENTIFIER | "(" expression ")"   (mayor precedencia)
    # Los parentesis no generan nodo: se devuelve la expresion interior, porque
    # la agrupacion ya quedo expresada en la forma del arbol.
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
        # Ningun caso aplica: error grave, se activa el modo panico.
        self._error_at(token, f"Se esperaba una expresión y se encontró {self._describe(token)}.")
        raise _ParseError

    # Convierte un token literal en un nodo Literal con su valor de Python.
    # A las cadenas se les quitan las comillas. Retorna None si no es literal.
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

    # Ejecuta una regla; si lanza _ParseError (error grave), sincroniza en modo
    # panico y retorna None para que el llamador siga con la siguiente sentencia.
    def _guarded(self, rule: Callable[[], Node | None]) -> Node | None:
        """Ejecuta una regla y, si falla, sincroniza en modo panico."""
        try:
            return rule()
        except _ParseError:
            self._synchronize()
            return None

    # Modo panico: descarta tokens hasta un punto seguro desde donde retomar:
    #   - despues de un ";" (lo consume),
    #   - antes de "}" o de una palabra que inicia sentencia (func, if, return, print),
    #   - antes de una declaracion (TYPE seguido de IDENTIFIER).
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

    # Si una iteracion no consumio ningun token (el cursor sigue en start), se
    # avanza uno a la fuerza. Sin esto, un token inesperado podria hacer que el
    # parser se quede en un ciclo infinito.
    def _ensure_progress(self, start: int) -> None:
        """Evita ciclos infinitos: si no se consumio ningun token, se avanza uno."""
        if self._pos == start and not self._is_at_end():
            self._advance()

    # Recuperacion por INSERCION: si el simbolo de cierre esta, lo consume; si
    # falta, reporta el error justo despues del token anterior y continua como
    # si estuviera (no consume nada). Es el error mas comun y asi no se pierde
    # el resto del programa.
    def _close(self, token_type: TokenType) -> None:
        """Consume un simbolo de cierre o reporta su ausencia y continua (insercion)."""
        if self._match(token_type):
            return
        symbol = _CLOSING_SYMBOLS[token_type]
        previous = self._previous()
        self._reporter.error(Phase.SYNTAX, f"Se esperaba '{symbol}' después de '{previous.lexeme}'.",
                             previous.line, previous.column + len(previous.lexeme))

    # Exige un token. Si no esta, reporta el error y lanza _ParseError (modo
    # panico), porque sin ese token (un nombre, un tipo) no se puede seguir.
    def _require(self, token_type: TokenType, message: str) -> Token:
        """Consume un token obligatorio o activa el modo panico."""
        if self._check(token_type):
            return self._advance()
        self._error_at(self._peek(), f"{message} Se encontró {self._describe(self._peek())}.")
        raise _ParseError

    # Registra un error sintactico en la posicion de un token.
    def _error_at(self, token: Token, message: str) -> None:
        self._reporter.error(Phase.SYNTAX, message, token.line, token.column)

    # Describe un token para los mensajes de error.
    @staticmethod
    def _describe(token: Token) -> str:
        return "el fin del archivo" if token.type is T.EOF else f"'{token.lexeme}'"

    # ------------------------------------------------------------------
    # Navegacion por los tokens (el cursor del parser)
    # ------------------------------------------------------------------

    # Token actual, sin consumirlo.
    def _peek(self) -> Token:
        return self._tokens[self._pos]

    # Token siguiente al actual (lookahead de dos), sin pasar del EOF.
    def _peek_next(self) -> Token:
        return self._tokens[min(self._pos + 1, len(self._tokens) - 1)]

    # Ultimo token consumido.
    def _previous(self) -> Token:
        return self._tokens[max(self._pos - 1, 0)]

    # True si el token actual es EOF.
    def _is_at_end(self) -> bool:
        return self._peek().type is T.EOF

    # Consume el token actual y lo retorna. Nunca avanza mas alla del EOF.
    def _advance(self) -> Token:
        token = self._peek()
        if not self._is_at_end():
            self._pos += 1
        return token

    # True si el token actual es del tipo indicado (no consume).
    def _check(self, token_type: TokenType) -> bool:
        return self._peek().type is token_type

    # Si el token actual es de alguno de los tipos indicados, lo consume y
    # retorna True; si no, no hace nada y retorna False.
    def _match(self, *token_types: TokenType) -> bool:
        if self._peek().type in token_types:
            self._advance()
            return True
        return False
