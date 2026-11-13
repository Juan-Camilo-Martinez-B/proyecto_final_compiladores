# Ejecución: máquina virtual de TAC

Responsable: Juan Camilo. Archivo: `backend/rpg_compiler/vm.py`. Pruebas: `backend/tests/test_vm.py`.

El compilador traduce el programa, pero traducir no prueba que la traducción sea correcta. La máquina virtual (VM)
ejecuta el código de tres direcciones que produce el generador de IR y muestra lo que imprime el programa. Si
`recursion.rpg` imprime `120` y `55`, las cuádruplas calculan bien el factorial de 5 y el Fibonacci de 10.

## 1. Fundamento teórico

Un programa compilado se puede ejecutar de dos formas: en una CPU real, a partir de su código máquina, o en una
**máquina virtual**, un programa que simula una máquina abstracta. Java (JVM) y Python (CPython) ejecutan así su código
intermedio. Nuestra VM es la misma idea del `EmuladorVirtualIR` del laboratorio de la sesión 7: ejecuta las cuádruplas
una por una.

La VM trabaja sobre el TAC y no sobre el AST. Eso es importante: un intérprete del AST se saltaría la compilación,
mientras que la VM ejecuta exactamente lo que el compilador generó.

## 2. Modelo de ejecución

| Elemento | Implementación |
|----------|----------------|
| Contador de programa | Índice de la cuádrupla actual. Empieza en la etiqueta `main` y termina al pasar la última cuádrupla |
| Saltos | `goto` y `if_false` cambian el contador usando un diccionario etiqueta → índice |
| Registros de activación | Cada `call` apila un `_Frame` con sus variables locales, la dirección de retorno y el nombre donde se guarda el resultado; `return` y `func_end` lo desapilan |
| Parámetros | Los `param` se acumulan y el `call` toma los últimos `n` según su segundo argumento |
| Locales y globales | Una variable se escribe en el frame actual si es local de la función (según la tabla de símbolos) o un temporal; si no, en el segmento global |
| Recursión | Funciona sin usar la recursión de Python: la pila de frames es una lista |

La VM recibe la tabla de símbolos del análisis semántico (`TacVM.from_symbols`) para saber qué nombres son locales de
cada función y en qué orden van sus parámetros. Así, en una función que declara su propia `vida`, la variable global
`vida` no cambia.

### Semántica de los valores

- La división entre dos `int` es entera y se trunca hacia cero, como en C y Java: `7 / 2` da `3` y `-7 / 2` da `-3`.
- `float f = 3 / 2;` vale `1.0`: primero se divide como enteros y después se convierte (`int_to_float`).
- Los booleanos se imprimen como `true` y `false`, igual que en el código fuente.

## 3. Errores en tiempo de ejecución

Son distintos de los errores de compilación: el programa es válido, pero falla al ejecutarse. Por eso no cambian el
`success` de la respuesta, que se refiere a la compilación; la fase `execution` tiene su propio estado.

| Error | Ejemplo | Mensaje |
|-------|---------|---------|
| División entre cero | `int x = 5 / 0;` | División entre cero. |
| Recursión infinita | `func f(int n) -> int { return f(n - 1); }` | Se superaron 1000 llamadas anidadas: posible recursión infinita (desbordamiento de pila). |
| Programa que no termina | (límite de seguridad) | Se alcanzó el límite de 100000 instrucciones: el programa podría no terminar. |
| Variable sin valor | `int a; print(a + 1);` | La variable 'a' se usó antes de tener un valor. |
| Función sin `return` usada como valor | `func f() -> int { print(1); }` | La función 'f' terminó sin retornar un valor. |

Cada error indica la instrucción TAC donde ocurrió, por ejemplo `instrucción 2 (t1 = 5 / 0)`. La salida impresa
antes del error se conserva. El compilador no puede detectar estos errores porque dependen de los valores, no de los
tipos; detectar la recursión infinita en general es indecidible (problema de la parada).

## 4. Uso

```bash
cd backend
python main.py examples/recursion.rpg --run     # solo la salida del programa
python main.py examples/notas.rpg --phase run   # la fase de ejecución con su resumen
```

En la web, la pestaña **Consola** muestra la salida como una terminal simulada.

## 5. Contrato

La respuesta de `compile_source()` incluye la fase `execution`:

```json
"execution": {
  "status": "finished",
  "output": ["Resiste el golpe", "Aria sigue en pie", "65", "50.0"],
  "steps": 36,
  "error": null
}
```

Si hay un error de ejecución, `status` vale `"error"` y `error` trae `message`, `instruction` y `text`. La fase solo se
ejecuta si el programa compila sin errores; si no, vale `null` y su estado es `skipped`.

## 6. Límites conocidos

- RPGScript no tiene instrucciones de entrada: los programas no leen datos del usuario, solo imprimen.
- El TAC usa los nombres del código fuente. Si una función declara dentro de un `if` una variable con el mismo nombre
  que otra de esa misma función, ambas comparten el mismo espacio en el frame.
