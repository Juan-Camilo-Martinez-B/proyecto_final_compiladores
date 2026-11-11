# Análisis semántico y modelo de memoria

Responsable: Rafael. Archivos: `backend/rpg_compiler/symbol_table.py`, `type_system.py`,
`semantic_analyzer.py`, `memory_model.py`, `backend/examples/estres_semantico.rpg`.

El analizador es el árbitro del compilador. Recibe el AST y decide si el programa tiene sentido:
un nombre debe existir en un ámbito visible, una operación solo acepta ciertas combinaciones de
tipos y una función solo puede llamarse con la firma que declaró. Si el programa es válido, además
calcula dónde viviría cada variable en memoria.

## 1. Tabla de símbolos (`symbol_table.py`)

### Fundamento teórico

Un **ámbito** es la región del programa donde un nombre es visible. RPGScript tiene ámbitos
anidados:

```
global  →  func:<nombre>  →  if@<línea> | else@<línea> | block@<línea>
```

La visibilidad es **unidireccional**: desde un ámbito se ven los nombres propios y los de los
padres, nunca los de un hermano ni los de un hijo ya cerrado. Por eso `temporal`, declarada dentro
de un `if`, desaparece al cerrar la llave aunque el objeto del ámbito siga existiendo para
mostrarlo en la web.

El modelo es una **pila de ámbitos** con un enlace al padre (sesión 5 del curso):

| Operación | Qué hace | Traza |
|-----------|----------|-------|
| `enter_scope(nombre, línea)` | Apila un ámbito nuevo. El nivel es el del padre más uno | `enter_scope` |
| `exit_scope(línea)` | Desapila. No borra el ámbito: queda en `all_scopes` | `exit_scope` |
| `define(símbolo)` | Inserta en el ámbito actual. Si el nombre ya estaba, no lo pisa y devuelve el anterior | `define` solo si entró |
| `lookup(nombre, línea)` | Sube por `parent` hasta encontrarlo o llegar a la raíz | `lookup` con `found_in` |
| `lookup_local(nombre)` | Mira solo el ámbito actual, sin traza. Sirve para la redeclaración | ninguna |

`global` es el nivel 0 y no se desapila. Cada ámbito guarda sus símbolos en un `dict`, así la
búsqueda es O(1) y el orden de inserción se conserva. Al serializar, los símbolos se ordenan por
línea y columna: la primera pasada inserta las funciones antes que las variables, pero la tabla que
se muestra sigue el orden del fuente.

Un símbolo recuerda la función dueña (`function`). Vale `None` en el ámbito global. El modelo de
memoria lo usa para reunir, en un solo frame, los parámetros y las variables de los `if` anidados.

La traza es la película de la pila. Cada evento tiene `step`, `action`, `scope`, `name`,
`found_in` y `line`. `action` es una de `enter_scope`, `exit_scope`, `define`, `lookup`.

## 2. Sistema de tipos (`type_system.py`)

Los nombres de tipo son las cadenas `"int"`, `"float"`, `"str"`, `"bool"` y `"void"`. Hay un tipo
interno extra, `"error"`, que no se escribe en el fuente.

Las reglas viven en `BINARY_RULES` y `UNARY_RULES`, diccionarios indexados por tuplas. Construirlos
con ciclos evita una cadena de `if` y deja la tabla lista para mostrarla en la sustentación.

| Operador | Operandos | Resultado |
|----------|-----------|-----------|
| `+` | int/float en cualquier mezcla, o `str + str` | `int` si ambos son int; `float` si alguno es float; `str` si ambos son str |
| `-` `*` `/` | mezclas de int y float | `int` si ambos son int (la división es entera); si no, `float` |
| `<` `>` `<=` `>=` | mezclas de int y float | `bool` |
| `==` `!=` | el mismo tipo, o una mezcla numérica | `bool` |
| `&&` y `\|\|` | `bool`, `bool` | `bool` |
| `-` unario | int o float | el mismo tipo |
| `!` | bool | `bool` |

`binary_result` y `unary_result` devuelven el tipo, `None` si la combinación no está en la tabla, o
`"error"` si algún operando ya es `"error"`. En ese último caso el analizador no emite otro
diagnóstico: es lo que evita la cascada de `int total = !vida`.

`is_assignable(destino, origen)` acepta tres casos: el origen ya es `"error"`, los dos tipos son
iguales, o el destino es `float` y el origen es `int`. La coerción implícita es solo en ese
sentido. `float` hacia `int` se rechaza porque se perdería precisión. La misma regla vale para
inicializar, asignar, pasar un argumento y retornar.

## 3. Analizador (`semantic_analyzer.py`)

`SemanticAnalyzer` es un `NodeVisitor`. `analyze(program)` devuelve un `SemanticResult` con los
símbolos, los ámbitos, la traza y las cadenas literales. Cada expresión del AST queda con
`inferred_type`; de eso depende el generador de código intermedio.

### Dos pasadas

1. Recorre solo los `FuncDecl` del nivel global y registra la firma (nombre, tipos de los
   parámetros y tipo de retorno). Una llamada puede aparecer antes de la declaración y una función
   puede llamarse a sí misma.
2. Recorre todo el programa en orden. Al entrar a una función abre `func:<nombre>`, define los
   parámetros con clase `parameter` y visita el cuerpo **sin** abrir otro ámbito para el bloque
   raíz. Un `if` abre `if@<línea>` y, si hay rama else, `else@<línea>`: el número es la línea del
   `if`. Un bloque suelto abre `block@<línea>`.

### Reglas

El número de línea y la columna salen del nodo del AST. Los errores usan `reporter.error` y los
dos avisos (S03 y S14) usan `reporter.warning`. El análisis no se detiene en el primero.

| Código | Cuándo | Mensaje |
|--------|--------|---------|
| S01 | El nombre no existe en ningún ámbito visible | La variable 'mana' no está declarada en el ámbito 'global'. |
| S02 | El mismo nombre se declara dos veces en el ámbito actual | La variable 'vida' ya fue declarada en el ámbito 'global' (línea 2). |
| S03 | Un nombre tapa a otro de un ámbito padre. Es legal | 'vida' oculta a la variable declarada en el ámbito 'global'. |
| S04 | No hay regla para el operador binario | El operador '-' no está definido entre 'int' y 'str'. |
| S05 | No hay regla para el operador unario | El operador '!' no se puede aplicar a 'int'. |
| S06 | La inicialización o la asignación no es compatible | No se puede asignar un valor 'float' a 'poder' de tipo 'int'. |
| S07 | Una variable se declara `void` | La variable 'nada' no puede ser de tipo 'void'. |
| S08 | La condición del `if` no es `bool` | La condición del 'if' debe ser 'bool', se obtuvo 'int'. |
| S09 | Se llama a algo que no existe o no es función | 'hechizo' no es una función. |
| S10 | Sobran o faltan argumentos | La función 'curar' espera 1 argumento(s) y recibió 2. |
| S11 | Un argumento no es compatible con el parámetro | El argumento 1 de 'curar' debe ser 'int', se recibió 'str'. |
| S12 | El `return` no coincide con la firma | 'curar' debe retornar 'int', pero retorna 'str'. |
| S13 | Hay un `return` fuera de una función | 'return' solo se permite dentro de una función. |
| S14 | Una función no void no tiene ningún `return` | La función 'calcular' declara 'int' pero no tiene 'return'. |
| S15 | Una llamada void se usa como valor (también en `print`) | La función 'saludar' es 'void' y no produce un valor. |
| S16 | El nombre de una función se usa como variable | 'curar' es una función y no se puede usar como variable. |
| S17 | La función está repetida, o un parámetro lo está | El parámetro 'dano' está repetido en 'atacar'. |

S17 también cubre la función repetida: `La función 'atacar' ya fue declarada en el ámbito 'global' (línea 1).`
Un parámetro `void` se rechaza con el mismo criterio que S07. Una llamada `void` escrita como
sentencia, por ejemplo `saludar();`, sí es válida: no se usa el valor.

Las cadenas literales se acumulan en `string_literals` sin duplicados y en orden de aparición. El
valor que se guarda es el texto, sin las comillas del fuente.

## 4. Memoria (`memory_model.py`)

`build_memory_layout(result)` solo corre si el semántico no reportó errores. Lee los símbolos y
las cadenas, y devuelve un `MemoryLayout` cuyo `to_dict()` tiene las claves `globals`, `frames` y
`heap`.

| Tipo | Bytes | Qué representa |
|------|-------|----------------|
| int | 4 | el valor |
| float | 8 | el valor |
| bool | 1 | el valor |
| str | 8 | un puntero al heap |

No se inserta relleno para alinear. El desplazamiento de un slot es la suma de los tamaños
anteriores.

**Segmento global.** Variables con `function is None`, en orden de definición, desde el
desplazamiento 0. En `batalla_ok.rpg` ocupa 29 bytes: `vida` en +0, `multiplicador` en +4,
`heroe` en +12, `vivo` en +20 y `golpe` en +21.

**Frame.** Uno por función, en el orden de las firmas. Abre con `return_address` y `saved_fp`
(4 bytes cada uno, clase `control`, tipo `null`). Después van los parámetros y luego todas las
variables locales de esa función, también las que nacieron dentro de un `if`. El frame de
`calcular_dano` mide 28 bytes: 8 de control, 4 de `base`, 8 de `factor` y 8 de `dano`. Si un
nombre se repite dentro de la misma función, el segundo slot se llama `nombre@ámbito`, por ejemplo
`x@if@2`.

**Heap.** Cada cadena de `string_literals` recibe una dirección desde `0x1000`. Su tamaño es la
cantidad de bytes UTF-8 más uno, por el terminador nulo. `Aria` mide 5 y la siguiente cadena
empieza en `0x1005`.

## 5. Pruebas

```bash
cd backend
python -m unittest tests.test_symbol_table tests.test_type_checker tests.test_memory_model -v
```

| Archivo | Qué cubre |
|---------|-----------|
| `test_symbol_table.py` | Lookup local, en el padre y en el abuelo; invisibilidad al salir; redeclaración; shadowing; traza |
| `test_type_checker.py` | Una prueba por regla S01–S17, coerción, concatenación, `inferred_type`, sin cascada, y los 13 errores más 1 aviso de `estres_semantico.rpg` |
| `test_memory_model.py` | Desplazamientos globales, frame de 28 bytes, sufijo de nombres repetidos y direcciones del heap |

`batalla_ok.rpg` no produce diagnósticos semánticos. `estres_semantico.rpg` produce exactamente 13
errores y 1 advertencia, en las líneas 5, 6, 7, 8, 10, 11, 13, 14, 15, 18, 19, 20, 21 y 22.
