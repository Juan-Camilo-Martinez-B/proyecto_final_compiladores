"""Maquina virtual que ejecuta el codigo de tres direcciones (TAC).

Es la ultima etapa del pipeline: toma las cuadruplas que produjo el generador de
IR y las ejecuta una por una, como la CPU virtual del laboratorio de la sesion 7.
Si el programa imprime los resultados esperados, la traduccion es correcta.

Modelo de ejecucion:
- Un contador de programa (pc) recorre la lista de cuadruplas. La ejecucion
  empieza en la etiqueta main y termina al pasar la ultima cuadrupla.
- Cada llamada apila un registro de activacion (_Frame) con sus variables
  locales, la direccion de retorno y el nombre donde se guarda el resultado.
  Asi funciona la recursion sin usar la recursion de Python.
- Una variable se escribe en el frame actual si es local de la funcion (segun
  la tabla de simbolos) o si es un temporal; si no, es una global.
- Los errores en tiempo de ejecucion (division entre cero, recursion infinita)
  no detienen el servidor: se devuelven en ExecutionResult.error.

El codigo del usuario nunca se pasa a eval ni a exec: solo se interpretan las
operaciones TAC conocidas.
"""
# ======================================================================
# vm.py - Ejecucion: maquina virtual de TAC
# ----------------------------------------------------------------------
# Entrada : las cuadruplas del generador de IR y la tabla de simbolos.
# Salida  : un ExecutionResult con lo que imprimio el programa, cuantas
#           instrucciones ejecuto y el error de ejecucion, si lo hubo.
#
# Diferencia clave:
#   - Errores de COMPILACION: el programa esta mal escrito (tipos, sintaxis).
#   - Errores de EJECUCION  : el programa es valido, pero falla segun los
#     valores (por ejemplo, dividir entre cero). Solo se ven al ejecutar.
#
# Ciclo de ejecucion (fetch-execute):
#     pc = indice de "main:"
#     mientras pc no llegue al final:
#         ejecutar la cuadrupla quads[pc]
#         pc = siguiente instruccion (o el destino de un salto o llamada)
# ======================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Limites de seguridad: evitan que un programa sin fin bloquee el servidor.
MAX_STEPS = 100_000          # instrucciones ejecutadas como maximo
MAX_CALL_DEPTH = 1_000       # llamadas anidadas como maximo (recursion)
MAX_OUTPUT_LINES = 1_000     # lineas impresas como maximo

_INT_LITERAL = re.compile(r"\d+")
_FLOAT_LITERAL = re.compile(r"\d+\.\d+")
_NOT_A_LITERAL = object()    # marcador unico: "este operando es un nombre, no un literal"


# Excepcion para un error en tiempo de ejecucion. La captura run() y la
# guarda en el resultado; nunca sale de la maquina virtual.
class RuntimeFault(Exception):
    """Error en tiempo de ejecucion del programa RPGScript."""


# ----------------------------------------------------------------------
# ExecutionResult: resultado de ejecutar el programa.
#   output : lineas que imprimio el programa, en orden.
#   steps  : cuantas cuadruplas se ejecutaron.
#   error  : None si termino bien; si no, {"message", "instruction", "text"}.
# ----------------------------------------------------------------------
@dataclass
class ExecutionResult:
    output: list[str] = field(default_factory=list)
    steps: int = 0
    error: dict | None = None

    # Formato JSON del contrato; status es "finished" o "error".
    def to_dict(self) -> dict:
        return {
            "status": "error" if self.error else "finished",
            "output": self.output,
            "steps": self.steps,
            "error": self.error,
        }


# ----------------------------------------------------------------------
# _Frame: registro de activacion de una llamada EN EJECUCION.
#   function      : funcion a la que pertenece (None para el programa principal).
#   variables     : variables locales y temporales de esta llamada.
#   return_pc     : instruccion donde se continua al retornar.
#   result_target : nombre del temporal donde se guarda el valor retornado.
# ----------------------------------------------------------------------
@dataclass
class _Frame:
    """Registro de activacion de una llamada en ejecucion."""

    function: str | None
    variables: dict[str, object]
    return_pc: int = -1
    result_target: str | None = None


class TacVM:
    #   function_locals : funcion -> nombres de sus variables locales y parametros.
    #   function_params : funcion -> nombres de sus parametros, en orden.
    #   global_names    : nombres de las variables globales.
    #   max_steps / max_call_depth : limites de seguridad (configurables en pruebas).
    def __init__(self, function_locals: dict[str, set[str]] | None = None,
                 function_params: dict[str, list[str]] | None = None,
                 global_names: set[str] | None = None,
                 max_steps: int = MAX_STEPS, max_call_depth: int = MAX_CALL_DEPTH) -> None:
        self._function_locals = function_locals or {}
        self._function_params = function_params or {}
        self._global_names = global_names or set()
        self._max_steps = max_steps
        self._max_call_depth = max_call_depth

    # Construye la VM a partir de los simbolos del analizador semantico: asi
    # sabe que nombres son locales de cada funcion, en que orden van sus
    # parametros y cuales son globales.
    @classmethod
    def from_symbols(cls, symbols, **limits) -> TacVM:
        """Construye la VM con los ambitos que calculo el analizador semantico."""
        function_locals: dict[str, set[str]] = {}
        function_params: dict[str, list[str]] = {}
        global_names: set[str] = set()
        for symbol in symbols:
            if symbol.kind == "function":
                continue
            if symbol.function is None:           # declarada fuera de toda funcion
                global_names.add(symbol.name)
                continue
            function_locals.setdefault(symbol.function, set()).add(symbol.name)
            if symbol.kind == "parameter":
                function_params.setdefault(symbol.function, []).append(symbol.name)
        return cls(function_locals, function_params, global_names, **limits)

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------

    # Ejecuta las cuadruplas y retorna el ExecutionResult.
    #   1. Indexa las etiquetas (para los saltos) y el inicio de cada funcion.
    #   2. Crea el frame del programa principal, que usa el segmento global.
    #   3. Empieza en "main:" y ejecuta hasta el final, contando los pasos.
    #   4. Si ocurre un RuntimeFault, guarda el mensaje y la instruccion.
    def run(self, quads) -> ExecutionResult:
        result = ExecutionResult()
        self._quads = list(quads)
        self._labels = {q.result: i for i, q in enumerate(self._quads) if q.op == "label"}
        self._entries = {q.arg1: i for i, q in enumerate(self._quads) if q.op == "func_begin"}
        self._globals: dict[str, object] = {}
        self._frames = [_Frame(None, self._globals)]   # pila de llamadas
        self._pending_args: list[object] = []          # valores de los "param" aun sin usar
        self._output = result.output

        # Las funciones van antes de main, asi que se empieza directamente en main.
        pc = self._labels.get("main", len(self._quads))
        try:
            while pc < len(self._quads):
                result.steps += 1
                if result.steps > self._max_steps:
                    raise RuntimeFault(
                        f"Se alcanzó el límite de {self._max_steps} instrucciones: "
                        "el programa podría no terminar.")
                pc = self._execute(pc)
        except RuntimeFault as fault:
            result.error = {"message": str(fault), "instruction": pc, "text": str(self._quads[pc])}
        return result

    # ------------------------------------------------------------------
    # Ejecucion de una cuadrupla: devuelve el siguiente pc
    # ------------------------------------------------------------------

    # Ejecuta la cuadrupla en la posicion pc y retorna la posicion de la
    # siguiente. Normalmente es pc + 1; los saltos, llamadas y retornos la cambian.
    def _execute(self, pc: int) -> int:
        quad = self._quads[pc]
        op = quad.op
        if op in _BINARY:                     # t = a op b
            self._write(quad.result, _BINARY[op](self._read(quad.arg1), self._read(quad.arg2)))
        elif op in _UNARY:                    # t = neg a | not a | int_to_float a
            self._write(quad.result, _UNARY[op](self._read(quad.arg1)))
        elif op == "=":                       # x = valor
            self._write(quad.result, self._read(quad.arg1))
        elif op == "label":                   # una etiqueta no hace nada al ejecutarse
            pass
        elif op == "goto":                    # salto incondicional
            return self._labels[quad.result]
        elif op == "if_false":                # salta si la condicion es falsa
            if not self._read(quad.arg1):
                return self._labels[quad.result]
        elif op == "param":                   # guarda un argumento para la proxima llamada
            self._pending_args.append(self._read(quad.arg1))
        elif op == "call":
            return self._call(quad, pc)
        elif op == "return":
            return self._return(self._read(quad.arg1) if quad.arg1 is not None else None)
        elif op == "func_end":                # llego al final sin return: retorna sin valor
            return self._return(None)
        elif op == "print":
            self._print(self._read(quad.arg1))
        else:
            raise RuntimeFault(f"Operación TAC desconocida: '{op}'.")
        return pc + 1

    # LLAMADA: toma los ultimos n argumentos pendientes, apila un frame nuevo
    # con los parametros ya asignados y salta a la primera instruccion de la
    # funcion. Si se superan las llamadas anidadas, es recursion infinita.
    def _call(self, quad, pc: int) -> int:
        name = quad.arg1
        if name not in self._entries:
            raise RuntimeFault(f"La función '{name}' no existe en el código intermedio.")
        if len(self._frames) > self._max_call_depth:
            raise RuntimeFault(
                f"Se superaron {self._max_call_depth} llamadas anidadas: "
                "posible recursión infinita (desbordamiento de pila).")
        count = int(quad.arg2)                              # numero de argumentos
        args = self._pending_args[len(self._pending_args) - count:] if count else []
        del self._pending_args[len(self._pending_args) - count:]
        params = self._function_params.get(name, [])
        # Asigna cada argumento a su parametro: zip(["a", "b"], [8, 3]).
        self._frames.append(_Frame(name, dict(zip(params, args)), pc + 1, quad.result))
        return self._entries[name] + 1                      # la instruccion siguiente a func_begin

    # RETORNO: desapila el frame actual, guarda el valor en el temporal del
    # llamador y continua en la instruccion siguiente a la llamada.
    def _return(self, value) -> int:
        frame = self._frames.pop()
        if frame.result_target is not None:
            if value is None:
                raise RuntimeFault(f"La función '{frame.function}' terminó sin retornar un valor.")
            self._write(frame.result_target, value)      # se escribe en el frame del llamador
        return frame.return_pc

    # Agrega una linea a la salida del programa.
    def _print(self, value) -> None:
        if len(self._output) >= MAX_OUTPUT_LINES:
            raise RuntimeFault(f"El programa imprimió más de {MAX_OUTPUT_LINES} líneas.")
        self._output.append(format_value(value))

    # ------------------------------------------------------------------
    # Lectura y escritura de operandos
    # ------------------------------------------------------------------

    # Obtiene el valor de un operando: si es un literal lo convierte; si es un
    # nombre lo busca en el frame actual y luego en las globales.
    def _read(self, operand: str):
        literal = parse_literal(operand)
        if literal is not _NOT_A_LITERAL:
            return literal
        frame = self._frames[-1]
        if operand in frame.variables:
            return frame.variables[operand]
        if operand in self._globals:
            return self._globals[operand]
        raise RuntimeFault(f"La variable '{operand}' se usó antes de tener un valor.")

    # Guarda un valor. Se escribe en el frame actual si:
    #   - se esta en el programa principal (su frame ES el segmento global),
    #   - el nombre es local de la funcion actual (oculta a una global), o
    #   - no es una variable global (es un temporal).
    # En otro caso es una global modificada desde una funcion.
    def _write(self, name: str, value) -> None:
        frame = self._frames[-1]
        is_local = (frame.function is None
                    or name in self._function_locals.get(frame.function, ())
                    or name not in self._global_names)
        (frame.variables if is_local else self._globals)[name] = value


# ----------------------------------------------------------------------
# Valores y operaciones
# ----------------------------------------------------------------------

# Convierte un operando literal del TAC a su valor de Python:
#   '"Aria"' -> "Aria" | "true" -> True | "2.5" -> 2.5 | "7" -> 7
# Si es un nombre (vida, t1) retorna el marcador _NOT_A_LITERAL. Los nombres
# nunca empiezan con digito, asi que no se confunden con numeros.
def parse_literal(operand: str):
    """Convierte un operando literal del TAC a su valor; los nombres no son literales."""
    if operand.startswith('"'):
        return operand[1:-1]
    if operand == "true":
        return True
    if operand == "false":
        return False
    if _FLOAT_LITERAL.fullmatch(operand):
        return float(operand)
    if _INT_LITERAL.fullmatch(operand):
        return int(operand)
    return _NOT_A_LITERAL


# Texto que imprime print: los booleanos como true/false (como en RPGScript).
def format_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# Division con la semantica de RPGScript: error si el divisor es cero; entre
# dos int es division entera truncada hacia cero (7 / 2 = 3, -7 / 2 = -3).
def _divide(left, right):
    if right == 0:
        raise RuntimeFault("División entre cero.")
    if isinstance(left, int) and isinstance(right, int):
        # Division entera truncada hacia cero, como en C y Java.
        quotient = abs(left) // abs(right)
        return quotient if (left >= 0) == (right >= 0) else -quotient
    return left / right


# Operaciones binarias del TAC -> funcion que la calcula. Los tipos ya fueron
# validados por el analizador semantico, asi que aqui no se revisan.
_BINARY = {
    "+": lambda a, b: a + b,       # suma de numeros o concatenacion de cadenas
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": _divide,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "&&": lambda a, b: a and b,
    "||": lambda a, b: a or b,
}

# Operaciones unarias del TAC.
_UNARY = {
    "neg": lambda a: -a,
    "not": lambda a: not a,
    "int_to_float": float,         # la coercion explicita: 3 -> 3.0
}
