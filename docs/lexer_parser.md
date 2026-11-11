# Front-end del compilador: análisis léxico y sintáctico

Responsable: Juan Camilo. Archivos: `backend/rpg_compiler/lexer.py`, `backend/rpg_compiler/parser.py`,
`backend/main.py`, `backend/server.py`.

## 1. Análisis léxico (`lexer.py`)

### Fundamento teórico

El analizador léxico convierte el flujo de caracteres en una secuencia de **tokens**. Tres conceptos lo definen:

| Concepto | Definición                                       | Ejemplo en RPGScript             |
|----------|--------------------------------------------------|----------------------------------|
| Lexema   | Secuencia concreta de caracteres del fuente      | `vida`, `100`, `->`              |
| Patrón   | Regla que describe a todos los lexemas válidos   | `[A-Za-z_][A-Za-z0-9_]*`         |
| Token    | Par (tipo, lexema) más su posición               | `IDENTIFIER vida (línea 2, col 5)` |

Toda expresión regular equivale a un **autómata finito determinista (DFA)**. El lexer une todos los patrones en
una sola expresión regular con **grupos nombrados** (`(?P<NOMBRE>patrón)`). En cada posición, el motor prueba las
alternativas en orden y la primera que coincide define el token. Por eso el orden es parte del diseño:

```
COMMENT      //[^\n]*            se descarta
NEWLINE      \n                  actualiza la línea
SKIP         [ \t\r]+            se descarta
FLOAT        \d+\.\d+            antes que INT, para no partir 1.5 en 1 y .5
BAD_IDENT    \d+[A-Za-z_]\w*     error: 2poder
INT          \d+
STRING       "[^"\n]*"
UNTERMINATED "[^"\n]*            error: cadena sin cerrar
IDENT        [A-Za-z_]\w*        luego se busca en KEYWORDS
OP2          -> == != <= >= && ||  antes que OP1, para no partir -> en - y >
OP1          + - * / < > = ! ( ) { } , ;
MISMATCH     .                   error: carácter no reconocido
```

### Decisiones

- **Posición exacta:** se lleva la línea actual y el índice donde empezó (`line_start`); la columna es
  `match.start() - line_start + 1`.
- **Palabras reservadas:** se reconocen como identificadores y luego se buscan en el diccionario `KEYWORDS`
  (búsqueda O(1)). Esto mantiene la expresión regular simple.
- **Recuperación:** un error léxico se reporta en el `ErrorReporter` y el escaneo continúa. Así, un archivo con tres
  errores muestra los tres en una sola ejecución.
- El lexema de un `STRING_LITERAL` conserva las comillas; el parser las quita al crear el `Literal`.
- La lista de tokens **siempre** termina en `EOF`, lo que simplifica el parser.

## 2. Análisis sintáctico (`parser.py`)

### Fundamento teórico

El parser verifica que la secuencia de tokens cumpla la **gramática libre de contexto** del lenguaje y construye el
**Árbol de Sintaxis Abstracta (AST)**. Se usa un **parser descendente recursivo** (top-down): cada regla de la
gramática es un método, y la recursión entre métodos refleja la estructura de la gramática.

```
program      → declaration* EOF
declaration  → funcDecl | statement
funcDecl     → "func" IDENTIFIER "(" params? ")" "->" TYPE block
params       → param ( "," param )*
param        → TYPE IDENTIFIER
statement    → varDecl | assignment | ifStmt | returnStmt | printStmt | exprStmt | block
varDecl      → TYPE IDENTIFIER ( "=" expression )? ";"
assignment   → IDENTIFIER "=" expression ";"
ifStmt       → "if" "(" expression ")" block ( "else" block )?
returnStmt   → "return" expression? ";"
printStmt    → "print" "(" expression ")" ";"
exprStmt     → expression ";"
block        → "{" statement* "}"

expression   → logicOr
logicOr      → logicAnd ( "||" logicAnd )*
logicAnd     → equality ( "&&" equality )*
equality     → comparison ( ( "==" | "!=" ) comparison )*
comparison   → term ( ( "<" | ">" | "<=" | ">=" ) term )*
term         → factor ( ( "+" | "-" ) factor )*
factor       → unary ( ( "*" | "/" ) unary )*
unary        → ( "-" | "!" ) unary | call
call         → IDENTIFIER "(" arguments? ")" | primary
arguments    → expression ( "," expression )*
primary      → INT_LITERAL | FLOAT_LITERAL | STRING_LITERAL | "true" | "false"
             | IDENTIFIER | "(" expression ")"
```

### Precedencia y asociatividad

La gramática es **no ambigua** porque cada nivel de precedencia es una regla distinta: cuanto más abajo está la regla,
más fuerte liga su operador. En `1 + 2 * 3`, `term` llama a `factor`, que consume `2 * 3` antes de que `term` vea el
`+`, y por eso la raíz del árbol es `+`.

Las reglas con forma `a ( op a )*` se implementan con un ciclo que va acumulando el árbol hacia la izquierda
(`_binary`). Eso da **asociatividad por la izquierda**: `10 - 3 - 2` es `(10 - 3) - 2`. Los unarios son recursivos por
la derecha (`--5` es `-(-5)`).

La gramática es LL(1) salvo en dos puntos, que se resuelven mirando un token más (LL(2)):
`IDENTIFIER "="` es una asignación, e `IDENTIFIER "("` es una llamada.

### Árbol concreto frente al AST

El AST descarta los tokens que solo sirven a la sintaxis (paréntesis, `;`, llaves) y conserva el significado. Por
ejemplo, `(1 + 2) * 3` produce `BinaryOp('*', BinaryOp('+', 1, 2), 3)`, sin nodo para los paréntesis. Cada nodo guarda
la línea y la columna de su token de origen, que luego usa el analizador semántico para reportar errores.

### Recuperación de errores

El parser **nunca se detiene en el primer error**. Usa dos estrategias:

1. **Inserción de símbolo faltante (nivel de frase).** Si falta un `;`, un `)` o una `}`, se reporta
   `Se esperaba ';' después de '100'.` en la posición donde debería estar, y el análisis continúa como si el
   símbolo existiera. Es la causa más común de error y así no se pierde nada del resto del programa.
2. **Modo pánico.** Ante cualquier otro error (por ejemplo, una expresión incompleta), se lanza una excepción interna
   que se captura al nivel de sentencia. Luego `_synchronize()` descarta tokens hasta un punto seguro: después de un
   `;`, o antes de `}`, `func`, `if`, `return`, `print` o de una declaración (`TYPE IDENTIFIER`).

Además, una protección evita ciclos infinitos: si una iteración no consumió ningún token, se avanza uno a la fuerza.
Con esto, `error_sintactico.rpg` produce exactamente 3 errores (líneas 1, 2 y 5) y ningún error en cascada.

## 3. CLI (`main.py`)

```bash
cd backend
python main.py examples/batalla_ok.rpg                  # todas las fases
python main.py examples/batalla_ok.rpg --phase ast      # tokens | ast | symbols | memory | ir | asm | all
python main.py examples/batalla_ok.rpg --json           # respuesta completa del contrato
python main.py examples/spill_registros.rpg --registers 2
```

La CLI solo depende de `pipeline.compile_source()` e imprime a partir del diccionario del contrato de la API, el
mismo que consume la web. El código de salida es 0 si la compilación fue exitosa y 1 si hubo errores o el archivo no
es válido.

## 4. Servidor (`server.py`)

```bash
cd backend
python server.py            # http://127.0.0.1:8000
```

| Ruta                 | Descripción                                                    |
|----------------------|----------------------------------------------------------------|
| `POST /api/compile`  | Cuerpo `{"source": "...", "register_count": 4}`; responde el contrato |
| `GET /api/examples`  | Programas `.rpg` de `backend/examples` con su contenido        |
| `GET /...`           | Archivos estáticos de `frontend/`                              |

Medidas de seguridad: escucha solo en `127.0.0.1`; limita el cuerpo a 64 KB (413); valida el JSON y los tipos de
`source` y `register_count` (400); sirve archivos solo dentro de `frontend/`, resolviendo la ruta para bloquear el
*path traversal*; agrega `X-Content-Type-Options: nosniff`. El código del usuario nunca se ejecuta: solo se analiza.

## 5. Pruebas

```bash
cd backend
python -m unittest discover -s tests -v
```

| Archivo          | Qué cubre                                                                    |
|------------------|------------------------------------------------------------------------------|
| `test_lexer.py`  | Tipos y posiciones, palabras clave, números, operadores, comentarios y los 3 errores léxicos |
| `test_parser.py` | Precedencia, asociatividad, sentencias, funciones, `batalla_ok.rpg` y recuperación de errores |
| `test_cli.py`    | Salida por fases, errores con línea, JSON y que la CLI ya imprime las fases del contrato |
| `test_server.py` | Contrato de `/api/compile`, validaciones, límite de tamaño, ejemplos y path traversal |
