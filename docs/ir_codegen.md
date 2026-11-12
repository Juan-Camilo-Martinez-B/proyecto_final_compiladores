# Código intermedio (TAC) y generación de código objetivo

Responsable: Saray. Archivos: `backend/rpg_compiler/ir_generator.py`, `codegen.py`,
`backend/examples/spill_registros.rpg`, `backend/tests/test_ir_generator.py`, `test_codegen.py`.

Estas son las dos últimas fases del pipeline. El generador de IR traduce el AST, ya validado y
anotado por el analizador semántico, a **código de tres direcciones** independiente de la máquina.
El generador de código traduce ese TAC a un **pseudo-ensamblador** para una CPU con pocos
registros, y decide qué valor vive en cada registro y qué valor se manda a la pila cuando no alcanzan.

```
AST anotado ──► IRGenerator ──► list[Quadruple] ──► CodeGenerator(n) ──► CodegenResult
                (sesión 7)                          (sesión 10)
```

## 1. Código de tres direcciones (`ir_generator.py`)

### Fundamento teórico

Una representación intermedia separa el *front-end* (léxico, sintaxis, semántica) del *back-end*
(máquina destino). Con M lenguajes y N máquinas basta escribir M + N traductores en lugar de M × N.

En el **código de tres direcciones** cada instrucción tiene como máximo un operador y tres
"direcciones": dos operandos y un resultado. Las expresiones anidadas se aplanan con
**temporales** (`t1`, `t2`, ...) y el control de flujo se expresa con **etiquetas** (`L1`, `L2`, ...)
y saltos. Se almacena en **cuádruplas** `(op, arg1, arg2, result)`.

### Interfaz

```python
@dataclass
class Quadruple:
    op: str
    arg1: str | None = None
    arg2: str | None = None
    result: str | None = None
    def to_dict(self, index) -> dict   # {"index","op","arg1","arg2","result","text"}
    def __str__(self) -> str           # texto TAC

IRGenerator().generate(program) -> list[Quadruple]
```

### Traducción por nodo

| Nodo | Cuádruplas | Ejemplo TAC |
|------|------------|-------------|
| `BinaryOp` | evalúa los dos lados y emite el operador | `t3 = a + b` |
| `UnaryOp` | `neg` (`-`) o `not` (`!`) | `t1 = - x` · `t2 = ! v` |
| `VarDecl` con valor / `Assign` | `=` | `vida = t2` |
| `VarDecl` sin valor | nada (la memoria la reserva el modelo de memoria) | |
| `If` sin `else` | `if_false c goto Lfin`, bloque, `Lfin:` | |
| `If` con `else` | `if_false c goto Lelse`, then, `goto Lfin`, `Lelse:`, else, `Lfin:` | |
| `Call` | primero evalúa **todos** los argumentos, luego un `param` por cada uno y `call` | `param t1` · `t4 = call curar, 1` |
| `Call` a función `void` | `call` sin resultado | `call saludar, 0` |
| `Return` / `Print` | `return` / `print` | `return t1` · `print t2` |
| `FuncDecl` | `func_begin`, cuerpo, `func_end` | `func_begin curar` |

Literales como texto: números tal cual (`50.0`), cadenas con comillas (`"Aria"`) y booleanos
`true` / `false`.

### Decisiones de diseño

- **Orden de emisión**: primero todas las funciones y luego `main:` con las sentencias globales en
  el orden del fuente. Así el código ejecutable empieza en un único punto de entrada.
- **Coerciones explícitas**: cuando un valor `int` llega a un destino `float` se emite
  `int_to_float`. Esto pasa en operaciones mixtas (`base * factor`), asignaciones, inicializaciones,
  argumentos y `return`. El tipo de cada expresión viene de `inferred_type` (lo pone el semántico).
  Los tipos destino (parámetros, retorno, variables) los calcula el propio generador con una
  pre-pasada y una pila de ámbitos pequeña, así que no depende de la tabla de símbolos.
- **Los argumentos se evalúan antes de los `param`**: en `f(g(x), y)` primero se resuelve `g(x)`
  completo y solo después se emiten los `param` de `f`. Así no se mezclan los parámetros de las dos
  llamadas.
- **Temporales sin choques**: si el programa declara una variable llamada `t1`, el contador se la
  salta y el primer temporal será `t2`.
- `&&` y `||` se traducen como operadores binarios normales, sin cortocircuito. Como RPGScript no
  tiene efectos secundarios en las expresiones, el resultado es el mismo.

### Ejemplo (`batalla_ok.rpg`, función `calcular_dano`)

```
0   func_begin calcular_dano
1   t1 = int_to_float base        ← coerción: base es int, factor es float
2   t2 = t1 * factor
3   dano = t2
4   t3 = dano > 50.0
5   if_false t3 goto L1
6   dano = 50.0
7   L1:
8   return dano
9   func_end calcular_dano
```

## 2. Generación de código objetivo (`codegen.py`)

### Fundamento teórico

La generación de código tiene tres problemas (sesión 10):

1. **Selección de instrucciones**: qué instrucciones de la máquina implementan cada cuádrupla.
2. **Asignación de registros**: los registros son pocos y mucho más rápidos que la RAM. Hay que
   decidir qué valor vive en cada uno en cada momento.
3. **Spill**: si se necesita un registro y todos están ocupados con valores que todavía se van a
   usar, uno de esos valores se guarda temporalmente en la pila y luego se recarga.

### Interfaz

```python
CodeGenerator(register_count: int = 4).generate(quads) -> CodegenResult
CodegenResult.to_dict() -> {"register_count", "instructions", "register_trace", "spills"}
```

### Selección de instrucciones

| Cuádrupla | Pseudo-ensamblador |
|-----------|--------------------|
| `t = a + b` (también `-`, `*`, `/`, `&&`, `\|\|`) | `LOAD Rx, a` · `LOAD Ry, b` · `ADD Rx, Ry` (Rx queda con `t`). Igual `SUB`, `MUL`, `DIV`, `AND`, `OR` |
| `t = a < b` (y `==`, `!=`, `>`, `<=`, `>=`) | `CMP Rx, Ry` · `SETLT Rx` (`SETEQ`, `SETNE`, `SETGT`, `SETLE`, `SETGE`) |
| `int_to_float`, `neg`, `not` | `ITOF Rx` · `NEG Rx` · `NOT Rx` |
| `x = t` / `x = 5` | `STORE x, Rx` / `LOAD Rx, #5` + `STORE x, Rx` |
| `label`, `goto`, `if_false` | `L1:` · `JMP L1` · `JZ Rx, L1` |
| `param`, `call`, `return`, `print` | `PUSH Rx` · `CALL f` + `MOV Rx, RV` · `RET Rx` · `PRINT Rx` |
| `func_begin`, `func_end` | `FUNC f` · `ENDFUNC f` |

Las constantes son operandos inmediatos (`#50.0`, `#"Aria"`). El programa principal termina con
`HALT`. El valor de retorno de una función llega en el registro especial `RV`.

### Asignación de registros

- **Descriptor de registros** (`registro → valor`) y **descriptor de direcciones**
  (`temporal → registro`).
- Una **pre-pasada** calcula el último uso de cada temporal. Después de esa cuádrupla su registro
  queda libre.
- Las variables con nombre viven en memoria y se escriben con `STORE` en cada asignación. Por eso
  su registro se libera al terminar la cuádrupla y no hay que sincronizar valores en los saltos.
- **Spill por LRU**: si no hay registros libres, se elige el usado hace más tiempo (sin tocar los
  operandos de la instrucción actual), se emite `STORE [SP+k], Rx` y se anota en `spills`. Cuando
  el temporal vuelve a necesitarse se recarga con `LOAD Ry, [SP+k]`.
- **Guardado antes de `CALL`** (*caller-saved*): la función llamada puede usar cualquier registro,
  así que los temporales vivos se guardan en la pila antes del `CALL`. Por ejemplo, en
  `(a + 1) * doble(a)` el temporal de `a + 1` se guarda y luego se recarga.
- `register_trace` guarda, después de **cada** instrucción, una foto del banco de registros. La
  web la usa para mostrar el estado al pasar el cursor por una instrucción.

### Ejemplo de spill (`spill_registros.rpg`)

```
int resultado = (a + b) * ((c + d) * ((e + f) * ((g + h) * (i + j))));
```

Con 4 registros, los resultados de `a+b`, `c+d` y `e+f` ocupan R0, R1 y R2, y `g` entra en R3.
Para cargar `h` ya no queda ningún registro libre, así que se hace spill del más antiguo (`t1`):

```
LOAD   R3, g
STORE  [SP+0], R0     ; spill (sin registros libres): t1
LOAD   R0, h
ADD    R3, R0         ; R3 = t4
...
LOAD   R1, [SP+0]     ; recarga t1
MUL    R1, R0         ; R1 = t9
```

| Registros | Spills |
|-----------|--------|
| 4 | 2 (`t1`, `t2`) |
| 2 | 4 |

`batalla_ok.rpg` no produce ningún spill con 4 registros.

## 3. Pruebas

```bash
cd backend
python -m unittest tests.test_ir_generator tests.test_codegen -v
```

- **IR** (AST construidos a mano con `inferred_type`): texto de cada operación, suma con coerción,
  asignación a `float`, precedencia, unarios, `if` con y sin `else` (etiquetas), orden funciones →
  `main`, llamada con `param`/`call` y argumento convertido, llamada `void`, `return` convertido,
  temporales que no chocan con variables y contadores que se reinician en cada `generate()`.
- **Codegen** (cuádruplas a mano): suma simple, constantes inmediatas, `CMP` + `SET`, `if_false` →
  `JZ`, unarios y `ITOF`, `CALL` + `MOV Rx, RV`, `FUNC`/`ENDFUNC`/`HALT`, spill y recarga con 2
  registros, temporal guardado antes de `CALL`, `register_trace` con una entrada por instrucción y
  claves del contrato.
- **De punta a punta**: `batalla_ok.rpg` completa las 6 fases con `int_to_float` y sin spills;
  `spill_registros.rpg` produce al menos un spill con 4 y con 2 registros.

## 4. Guion para la sustentación

1. `batalla_ok.rpg`, pestaña **TAC**: mostrar las cuádruplas, `int_to_float base` y las etiquetas
   del `if`/`else` de `recibir_golpe`.
2. Pestaña **ASM**: recorrer `calcular_dano` con el cursor y ver cómo cambian R0..R3. Spills: 0.
3. `spill_registros.rpg` con 4 registros: las líneas rojas son spills y las ámbar son recargas.
4. Cambiar a **2 registros**: el número de spills sube de 2 a 4. Es el mismo programa con menos
   hardware.
