"""Generador de pseudo-ensamblador con asignacion de registros y spill.

Traduce cada cuadrupla a instrucciones de una CPU simulada con un banco
limitado de registros R0 ... R(n-1).

Modelo:
- Descriptor de registros: registro -> valor que contiene (o None si esta libre).
- Descriptor de direcciones: temporal -> registro donde vive.
- Una pre-pasada calcula el ultimo uso de cada temporal; despues de ese uso su
  registro queda libre. Las variables con nombre viven en memoria (se escriben
  con STORE al asignarse), por eso su registro se libera al terminar la cuadrupla.
- Spill (sesion 10): si no hay registros libres se elige el usado hace mas tiempo
  (LRU), se emite STORE [SP+k], Rx y, cuando el temporal se vuelve a necesitar,
  se recarga con LOAD Ry, [SP+k].
- Antes de un CALL se guardan en la pila los temporales vivos, porque la funcion
  llamada puede usar cualquier registro (convencion caller-saved). El valor de
  retorno llega en el registro especial RV.
"""
# ======================================================================
# codegen.py - FASE 6: generacion de codigo objetivo (sesion 10)
# ----------------------------------------------------------------------
# Entrada : la lista de cuadruplas (TAC).
# Salida  : un CodegenResult con el pseudo-ensamblador, una foto de los
#           registros despues de cada instruccion y la lista de spills.
#
# Los tres problemas del back-end:
#   1. Seleccion de instrucciones: que instrucciones implementan cada
#      cuadrupla (tablas ARITHMETIC, COMPARISON y UNARY + metodos _gen_*).
#   2. Asignacion de registros: los registros son pocos y mucho mas rapidos
#      que la RAM; hay que decidir que valor ocupa cada uno.
#   3. Spill: cuando no alcanzan, un valor se guarda en la pila y se recarga.
#
# Ejemplo:  t1 = a + b   ->   LOAD R0, a
#                             LOAD R1, b
#                             ADD  R0, R1     ; R0 = t1
#
# Glosario de la CPU simulada:
#   LOAD R, x   carga x (variable o constante #5) en R
#   STORE x, R  guarda R en la variable x (o en la pila: [SP+k])
#   ADD/SUB/MUL/DIV/AND/OR Rx, Ry   Rx = Rx op Ry
#   CMP Rx, Ry + SETxx Rx           compara y deja 1 o 0 en Rx
#   ITOF/NEG/NOT R                  conversion int->float, negativo, negacion
#   JMP L / JZ R, L                 salto incondicional / si R es cero
#   PUSH R / CALL f / RET R         parametro, llamada, retorno (resultado en RV)
# ======================================================================
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Seleccion de instrucciones: operador del TAC -> instruccion de la CPU.
ARITHMETIC = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "&&": "AND", "||": "OR"}
COMPARISON = {"==": "SETEQ", "!=": "SETNE", "<": "SETLT", ">": "SETGT", "<=": "SETLE", ">=": "SETGE"}
UNARY = {"neg": "NEG", "not": "NOT", "int_to_float": "ITOF"}
UNARY_COMMENTS = {"ITOF": "coerción int -> float"}
# Cuadruplas cuyo result no es un temporal.
_NON_VALUE_RESULTS = {"=", "label", "goto", "if_false"}
_SPILL_SLOT_SIZE = 8  # el tamano del tipo mas grande (float)
# Reconoce constantes (numeros, cadenas, true/false) para escribirlas como #valor.
_CONSTANT = re.compile(r'^(-?\d|"|true$|false$)')


# ----------------------------------------------------------------------
# CodegenResult: salida de la fase.
#   register_count : registros de la CPU simulada.
#   instructions   : lineas de pseudo-ensamblador.
#   register_trace : despues de cada instruccion, que valor tiene cada registro
#                    (la web lo muestra al pasar el cursor).
#   spills         : cada spill: valor expulsado, posicion en la pila e instruccion.
# ----------------------------------------------------------------------
@dataclass
class CodegenResult:
    register_count: int
    instructions: list[str] = field(default_factory=list)
    register_trace: list[dict] = field(default_factory=list)
    spills: list[dict] = field(default_factory=list)

    # Formato JSON del contrato.
    def to_dict(self) -> dict:
        return {"register_count": self.register_count, "instructions": self.instructions,
                "register_trace": self.register_trace, "spills": self.spills}


class CodeGenerator:
    # register_count: cuantos registros tiene la CPU (minimo 2: una operacion
    # binaria necesita dos operandos a la vez).
    def __init__(self, register_count: int = 4):
        if register_count < 2:
            raise ValueError("Se necesitan al menos 2 registros.")
        self.register_count = register_count
        self._registers = [f"R{i}" for i in range(register_count)]   # R0, R1, ...

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------

    # Traduce la lista de cuadruplas. Pasos:
    #   1. Identifica que nombres son temporales (resultados de operaciones).
    #   2. Pre-pasada: ultimo uso de cada valor (para liberar registros a tiempo).
    #   3. Recorre las cuadruplas y despacha cada una a su metodo _gen_*.
    #   4. Despues de cada cuadrupla libera los registros de valores muertos.
    #   5. Si hubo programa principal (main), termina con HALT.
    def generate(self, quads) -> CodegenResult:
        self._result = CodegenResult(self.register_count)
        self._temps = {q.result for q in quads
                       if q.result is not None and q.op not in _NON_VALUE_RESULTS}
        self._last_use = self._compute_last_use(quads)
        self._reset_state()

        # Operaciones que no son aritmeticas, comparaciones ni unarias.
        handlers = {
            "=": self._gen_assign, "label": self._gen_label, "goto": self._gen_goto,
            "if_false": self._gen_if_false, "param": self._gen_param, "call": self._gen_call,
            "return": self._gen_return, "print": self._gen_print,
            "func_begin": self._gen_func_begin, "func_end": self._gen_func_end,
        }
        main_started = False
        for index, quad in enumerate(quads):
            self._index = index                 # cuadrupla actual (para saber que esta vivo)
            if quad.op in ARITHMETIC:
                self._gen_arithmetic(quad)
            elif quad.op in COMPARISON:
                self._gen_comparison(quad)
            elif quad.op in UNARY:
                self._gen_unary(quad)
            elif quad.op in handlers:
                handlers[quad.op](quad)
            else:
                raise ValueError(f"Operación TAC desconocida: '{quad.op}'")
            if quad.op == "label" and quad.result == "main":
                main_started = True
            self._release_dead()
        if main_started:
            self._instr("HALT")
        return self._result

    # ------------------------------------------------------------------
    # Estado de registros
    # ------------------------------------------------------------------

    # Reinicia el banco de registros (al empezar, al entrar a cada funcion y en
    # main): todos libres, sin spills pendientes.
    #   _reg_desc   : descriptor de registros, registro -> valor (None = libre).
    #   _addr_desc  : descriptor de direcciones, temporal -> registro.
    #   _spilled    : temporal -> posicion en la pila donde se guardo.
    #   _last_touch : registro -> momento en que se uso por ultima vez (para LRU).
    def _reset_state(self) -> None:
        self._reg_desc: dict[str, str | None] = {reg: None for reg in self._registers}
        self._addr_desc: dict[str, str] = {}      # temporal -> registro
        self._spilled: dict[str, str] = {}        # temporal -> slot en la pila
        self._next_slot = 0
        self._last_touch = {reg: 0 for reg in self._registers}
        self._clock = 0

    # Pre-pasada de vida: para cada valor, el indice de la ultima cuadrupla que
    # lo usa como operando. Despues de ese indice el valor esta "muerto".
    @staticmethod
    def _compute_last_use(quads) -> dict[str, int]:
        last_use: dict[str, int] = {}
        for index, quad in enumerate(quads):
            for arg in (quad.arg1, quad.arg2):
                if arg is not None:
                    last_use[arg] = index
        return last_use

    # Un valor esta VIVO si es un temporal que todavia se usara despues de la
    # cuadrupla actual.
    def _is_live(self, value: str) -> bool:
        return value in self._temps and self._last_use.get(value, -1) > self._index

    # Marca un registro como recien usado (reloj logico para LRU).
    def _touch(self, reg: str) -> None:
        self._clock += 1
        self._last_touch[reg] = self._clock

    # Pone un valor en un registro y actualiza los dos descriptores.
    def _set(self, reg: str, value: str | None) -> None:
        old = self._reg_desc[reg]
        if old is not None and self._addr_desc.get(old) == reg:
            del self._addr_desc[old]           # el valor anterior ya no esta en este registro
        self._reg_desc[reg] = value
        if value is not None and value in self._temps:
            self._addr_desc[value] = reg
        self._touch(reg)

    # Deja un registro libre.
    def _free(self, reg: str) -> None:
        self._set(reg, None)

    # Libera los registros cuyo valor ya no se usara, y olvida los spills de
    # temporales muertos.
    def _release_dead(self) -> None:
        """Libera los registros de variables, constantes y temporales que ya no se usan."""
        for reg, value in self._reg_desc.items():
            if value is not None and not self._is_live(value):
                self._free(reg)
        for temp in [t for t in self._spilled if not self._is_live(t)]:
            del self._spilled[temp]

    # Consigue un registro:
    #   1. Si hay uno libre, lo usa.
    #   2. Si no, elige el usado hace mas tiempo (LRU) que no este fijado
    #      (pinned = los operandos de la instruccion actual).
    #   3. Si su valor sigue vivo, lo guarda en la pila (SPILL) antes de reusarlo.
    def _allocate(self, pinned: tuple[str, ...] = ()) -> str:
        for reg in self._registers:
            if self._reg_desc[reg] is None:
                return reg
        candidates = [reg for reg in self._registers if reg not in pinned]
        victim = min(candidates, key=lambda reg: self._last_touch[reg])
        value = self._reg_desc[victim]
        if value is not None and self._is_live(value):
            self._spill(victim, value, "spill (sin registros libres)")
        self._free(victim)
        return victim

    # SPILL: guarda el valor de un registro en la pila ([SP+k]) y lo anota en la
    # lista de spills. Cada spill usa una posicion nueva de 8 bytes.
    def _spill(self, reg: str, value: str, reason: str) -> None:
        slot = f"[SP+{self._next_slot * _SPILL_SLOT_SIZE}]"
        self._next_slot += 1
        self._spilled[value] = slot
        self._result.spills.append(
            {"variable": value, "slot": slot, "instruction": len(self._result.instructions)})
        self._free(reg)
        self._instr("STORE", f"{slot}, {reg}", f"{reason}: {value}")

    # Retorna un registro que contenga value:
    #   - si ya esta en un registro, lo reutiliza;
    #   - si fue expulsado a la pila, lo RECARGA (LOAD Rx, [SP+k]);
    #   - si es una variable o constante, la carga (LOAD Rx, nombre o #valor).
    def _ensure(self, value: str, pinned: tuple[str, ...] = ()) -> str:
        """Devuelve un registro que contiene value, cargandolo si hace falta."""
        if value in self._addr_desc:
            reg = self._addr_desc[value]
            self._touch(reg)
            return reg
        reg = self._allocate(pinned)
        if value in self._spilled:
            slot = self._spilled.pop(value)
            self._set(reg, value)
            self._instr("LOAD", f"{reg}, {slot}", f"recarga {value}")
        else:
            self._set(reg, self._operand(value))
            self._instr("LOAD", f"{reg}, {self._operand(value)}")
        return reg

    # Como _ensure, pero el registro se va a sobrescribir con el resultado
    # (ADD R0, R1 deja el resultado en R0). Si el valor sigue vivo despues, se
    # copia antes a otro registro (MOV) para no perderlo.
    def _ensure_writable(self, value: str, pinned: tuple[str, ...] = ()) -> str:
        """Como _ensure, pero copia el valor si un temporal sigue vivo despues de esta cuadrupla."""
        reg = self._ensure(value, pinned)
        if self._is_live(value):
            copy = self._allocate(pinned + (reg,))
            self._set(copy, value)
            self._instr("MOV", f"{copy}, {reg}")
            return copy
        return reg

    # Las constantes se escriben como operando inmediato: 50.0 -> #50.0.
    @staticmethod
    def _operand(value: str) -> str:
        return f"#{value}" if _CONSTANT.match(value) else value

    # ------------------------------------------------------------------
    # Emision
    # ------------------------------------------------------------------

    # Agrega una instruccion con formato alineado y un comentario opcional:
    #     ADD    R0, R1             ; R0 = t1
    def _instr(self, mnemonic: str, operands: str = "", comment: str | None = None) -> None:
        text = f"    {mnemonic:<7}{operands}".rstrip()
        if comment:
            text = f"{text:<30}; {comment}"
        self._emit_line(text)

    # Agrega una linea y guarda la foto de los registros en ese momento.
    def _emit_line(self, text: str) -> None:
        self._result.instructions.append(text)
        self._result.register_trace.append({
            "instruction": len(self._result.instructions) - 1,
            "registers": dict(self._reg_desc),
        })

    # ------------------------------------------------------------------
    # Seleccion de instrucciones por tipo de cuadrupla
    # ------------------------------------------------------------------

    # t = a op b  ->  carga a y b, ADD/SUB/... Rx, Ry. Rx queda con el resultado.
    def _gen_arithmetic(self, quad) -> None:
        left = self._ensure_writable(quad.arg1)
        right = self._ensure(quad.arg2, pinned=(left,))   # no expulsar el registro de left
        self._set(left, quad.result)
        if right != left:
            self._free(right)
        self._instr(ARITHMETIC[quad.op], f"{left}, {right}", f"{left} = {quad.result}")

    # t = a < b  ->  CMP Rx, Ry  y  SETLT Rx (Rx queda en 1 o 0).
    def _gen_comparison(self, quad) -> None:
        left = self._ensure_writable(quad.arg1)
        right = self._ensure(quad.arg2, pinned=(left,))
        self._instr("CMP", f"{left}, {right}")
        self._free(right)
        self._set(left, quad.result)
        self._instr(COMPARISON[quad.op], left, f"{left} = {quad.result}")

    # t = neg a / not a / int_to_float a  ->  NEG / NOT / ITOF Rx.
    def _gen_unary(self, quad) -> None:
        reg = self._ensure_writable(quad.arg1)
        self._set(reg, quad.result)
        mnemonic = UNARY[quad.op]
        self._instr(mnemonic, reg, UNARY_COMMENTS.get(mnemonic, f"{reg} = {quad.result}"))

    # x = valor  ->  carga el valor y STORE x, Rx (las variables viven en memoria).
    def _gen_assign(self, quad) -> None:
        reg = self._ensure(quad.arg1)
        self._instr("STORE", f"{quad.result}, {reg}")

    # Etiqueta. En main el banco de registros empieza limpio.
    def _gen_label(self, quad) -> None:
        if quad.result == "main":
            # Las sentencias globales empiezan con un banco de registros limpio.
            self._reset_state()
        self._emit_line(f"{quad.result}:")

    # goto L  ->  JMP L
    def _gen_goto(self, quad) -> None:
        self._instr("JMP", quad.result)

    # if_false t goto L  ->  JZ Rx, L (salta si la condicion vale 0)
    def _gen_if_false(self, quad) -> None:
        reg = self._ensure(quad.arg1)
        self._instr("JZ", f"{reg}, {quad.result}")

    # param v  ->  PUSH Rx (el argumento va a la pila).
    def _gen_param(self, quad) -> None:
        reg = self._ensure(quad.arg1)
        self._instr("PUSH", reg)
        if not self._is_live(quad.arg1):
            self._free(reg)

    # t = call f, n  ->  CALL f y MOV Rx, RV.
    # Convencion CALLER-SAVED: antes de llamar se guardan en la pila los
    # temporales vivos, porque la funcion llamada puede usar cualquier registro.
    def _gen_call(self, quad) -> None:
        for reg, value in list(self._reg_desc.items()):
            if value is not None and self._is_live(value):
                self._spill(reg, value, "guarda antes de CALL")
            elif value is not None:
                self._free(reg)
        self._instr("CALL", quad.arg1)
        if quad.result is not None:          # la funcion retorna un valor (no es void)
            reg = self._allocate()
            self._set(reg, quad.result)
            self._instr("MOV", f"{reg}, RV", f"{reg} = {quad.result}")

    # return v  ->  RET Rx  (o RET solo si no hay valor).
    def _gen_return(self, quad) -> None:
        if quad.arg1 is None:
            self._instr("RET")
            return
        reg = self._ensure(quad.arg1)
        self._instr("RET", reg)

    # print v  ->  PRINT Rx
    def _gen_print(self, quad) -> None:
        reg = self._ensure(quad.arg1)
        self._instr("PRINT", reg)

    # Inicio de funcion: banco de registros limpio y etiqueta FUNC.
    def _gen_func_begin(self, quad) -> None:
        self._reset_state()
        self._emit_line(f"FUNC {quad.arg1}")

    # Fin de funcion.
    def _gen_func_end(self, quad) -> None:
        self._reset_state()
        self._emit_line(f"ENDFUNC {quad.arg1}")
