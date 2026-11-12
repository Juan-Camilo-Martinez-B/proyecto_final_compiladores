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
from __future__ import annotations

import re
from dataclasses import dataclass, field

ARITHMETIC = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "&&": "AND", "||": "OR"}
COMPARISON = {"==": "SETEQ", "!=": "SETNE", "<": "SETLT", ">": "SETGT", "<=": "SETLE", ">=": "SETGE"}
UNARY = {"neg": "NEG", "not": "NOT", "int_to_float": "ITOF"}
UNARY_COMMENTS = {"ITOF": "coerción int -> float"}
# Cuadruplas cuyo result no es un temporal.
_NON_VALUE_RESULTS = {"=", "label", "goto", "if_false"}
_SPILL_SLOT_SIZE = 8  # el tamano del tipo mas grande (float)
_CONSTANT = re.compile(r'^(-?\d|"|true$|false$)')


@dataclass
class CodegenResult:
    register_count: int
    instructions: list[str] = field(default_factory=list)
    register_trace: list[dict] = field(default_factory=list)
    spills: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"register_count": self.register_count, "instructions": self.instructions,
                "register_trace": self.register_trace, "spills": self.spills}


class CodeGenerator:
    def __init__(self, register_count: int = 4):
        if register_count < 2:
            raise ValueError("Se necesitan al menos 2 registros.")
        self.register_count = register_count
        self._registers = [f"R{i}" for i in range(register_count)]

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
    def generate(self, quads) -> CodegenResult:
        self._result = CodegenResult(self.register_count)
        self._temps = {q.result for q in quads
                       if q.result is not None and q.op not in _NON_VALUE_RESULTS}
        self._last_use = self._compute_last_use(quads)
        self._reset_state()

        handlers = {
            "=": self._gen_assign, "label": self._gen_label, "goto": self._gen_goto,
            "if_false": self._gen_if_false, "param": self._gen_param, "call": self._gen_call,
            "return": self._gen_return, "print": self._gen_print,
            "func_begin": self._gen_func_begin, "func_end": self._gen_func_end,
        }
        main_started = False
        for index, quad in enumerate(quads):
            self._index = index
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
    def _reset_state(self) -> None:
        self._reg_desc: dict[str, str | None] = {reg: None for reg in self._registers}
        self._addr_desc: dict[str, str] = {}      # temporal -> registro
        self._spilled: dict[str, str] = {}        # temporal -> slot en la pila
        self._next_slot = 0
        self._last_touch = {reg: 0 for reg in self._registers}
        self._clock = 0

    @staticmethod
    def _compute_last_use(quads) -> dict[str, int]:
        last_use: dict[str, int] = {}
        for index, quad in enumerate(quads):
            for arg in (quad.arg1, quad.arg2):
                if arg is not None:
                    last_use[arg] = index
        return last_use

    def _is_live(self, value: str) -> bool:
        return value in self._temps and self._last_use.get(value, -1) > self._index

    def _touch(self, reg: str) -> None:
        self._clock += 1
        self._last_touch[reg] = self._clock

    def _set(self, reg: str, value: str | None) -> None:
        old = self._reg_desc[reg]
        if old is not None and self._addr_desc.get(old) == reg:
            del self._addr_desc[old]
        self._reg_desc[reg] = value
        if value is not None and value in self._temps:
            self._addr_desc[value] = reg
        self._touch(reg)

    def _free(self, reg: str) -> None:
        self._set(reg, None)

    def _release_dead(self) -> None:
        """Libera los registros de variables, constantes y temporales que ya no se usan."""
        for reg, value in self._reg_desc.items():
            if value is not None and not self._is_live(value):
                self._free(reg)
        for temp in [t for t in self._spilled if not self._is_live(t)]:
            del self._spilled[temp]

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

    def _spill(self, reg: str, value: str, reason: str) -> None:
        slot = f"[SP+{self._next_slot * _SPILL_SLOT_SIZE}]"
        self._next_slot += 1
        self._spilled[value] = slot
        self._result.spills.append(
            {"variable": value, "slot": slot, "instruction": len(self._result.instructions)})
        self._free(reg)
        self._instr("STORE", f"{slot}, {reg}", f"{reason}: {value}")

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

    def _ensure_writable(self, value: str, pinned: tuple[str, ...] = ()) -> str:
        """Como _ensure, pero copia el valor si un temporal sigue vivo despues de esta cuadrupla."""
        reg = self._ensure(value, pinned)
        if self._is_live(value):
            copy = self._allocate(pinned + (reg,))
            self._set(copy, value)
            self._instr("MOV", f"{copy}, {reg}")
            return copy
        return reg

    @staticmethod
    def _operand(value: str) -> str:
        return f"#{value}" if _CONSTANT.match(value) else value

    # ------------------------------------------------------------------
    # Emision
    # ------------------------------------------------------------------
    def _instr(self, mnemonic: str, operands: str = "", comment: str | None = None) -> None:
        text = f"    {mnemonic:<7}{operands}".rstrip()
        if comment:
            text = f"{text:<30}; {comment}"
        self._emit_line(text)

    def _emit_line(self, text: str) -> None:
        self._result.instructions.append(text)
        self._result.register_trace.append({
            "instruction": len(self._result.instructions) - 1,
            "registers": dict(self._reg_desc),
        })

    # ------------------------------------------------------------------
    # Seleccion de instrucciones por tipo de cuadrupla
    # ------------------------------------------------------------------
    def _gen_arithmetic(self, quad) -> None:
        left = self._ensure_writable(quad.arg1)
        right = self._ensure(quad.arg2, pinned=(left,))
        self._set(left, quad.result)
        if right != left:
            self._free(right)
        self._instr(ARITHMETIC[quad.op], f"{left}, {right}", f"{left} = {quad.result}")

    def _gen_comparison(self, quad) -> None:
        left = self._ensure_writable(quad.arg1)
        right = self._ensure(quad.arg2, pinned=(left,))
        self._instr("CMP", f"{left}, {right}")
        self._free(right)
        self._set(left, quad.result)
        self._instr(COMPARISON[quad.op], left, f"{left} = {quad.result}")

    def _gen_unary(self, quad) -> None:
        reg = self._ensure_writable(quad.arg1)
        self._set(reg, quad.result)
        mnemonic = UNARY[quad.op]
        self._instr(mnemonic, reg, UNARY_COMMENTS.get(mnemonic, f"{reg} = {quad.result}"))

    def _gen_assign(self, quad) -> None:
        reg = self._ensure(quad.arg1)
        self._instr("STORE", f"{quad.result}, {reg}")

    def _gen_label(self, quad) -> None:
        if quad.result == "main":
            # Las sentencias globales empiezan con un banco de registros limpio.
            self._reset_state()
        self._emit_line(f"{quad.result}:")

    def _gen_goto(self, quad) -> None:
        self._instr("JMP", quad.result)

    def _gen_if_false(self, quad) -> None:
        reg = self._ensure(quad.arg1)
        self._instr("JZ", f"{reg}, {quad.result}")

    def _gen_param(self, quad) -> None:
        reg = self._ensure(quad.arg1)
        self._instr("PUSH", reg)
        if not self._is_live(quad.arg1):
            self._free(reg)

    def _gen_call(self, quad) -> None:
        for reg, value in list(self._reg_desc.items()):
            if value is not None and self._is_live(value):
                self._spill(reg, value, "guarda antes de CALL")
            elif value is not None:
                self._free(reg)
        self._instr("CALL", quad.arg1)
        if quad.result is not None:
            reg = self._allocate()
            self._set(reg, quad.result)
            self._instr("MOV", f"{reg}, RV", f"{reg} = {quad.result}")

    def _gen_return(self, quad) -> None:
        if quad.arg1 is None:
            self._instr("RET")
            return
        reg = self._ensure(quad.arg1)
        self._instr("RET", reg)

    def _gen_print(self, quad) -> None:
        reg = self._ensure(quad.arg1)
        self._instr("PRINT", reg)

    def _gen_func_begin(self, quad) -> None:
        self._reset_state()
        self._emit_line(f"FUNC {quad.arg1}")

    def _gen_func_end(self, quad) -> None:
        self._reset_state()
        self._emit_line(f"ENDFUNC {quad.arg1}")
