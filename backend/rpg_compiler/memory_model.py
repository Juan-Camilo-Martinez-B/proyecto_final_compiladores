"""Modelo de memoria: segmento global, stack frames y heap de cadenas.

No hay relleno de alineacion: el desplazamiento de cada slot es la suma de los
tamanos anteriores. Por eso un bool de 1 byte puede ir seguido de un float en
el byte siguiente (vivo en +20 y golpe en +21 en batalla_ok.rpg).

Tamanos: int 4, float 8, bool 1, str 8 (el slot guarda un puntero; el texto
vive en el heap). Cada frame abre con return_address y saved_fp, de 4 bytes.
"""
from __future__ import annotations

from dataclasses import dataclass

TYPE_SIZES = {"int": 4, "float": 8, "bool": 1, "str": 8}
_CONTROL_SIZE = 4
_HEAP_BASE = 0x1000


@dataclass
class MemorySlot:
    name: str
    type_name: str | None
    kind: str
    offset: int
    size: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type_name,
            "kind": self.kind,
            "offset": self.offset,
            "size": self.size,
        }


@dataclass
class MemorySegment:
    size: int
    slots: list[MemorySlot]

    def to_dict(self) -> dict:
        return {"size": self.size, "slots": [slot.to_dict() for slot in self.slots]}


@dataclass
class StackFrame:
    function: str
    size: int
    slots: list[MemorySlot]

    def to_dict(self) -> dict:
        return {
            "function": self.function,
            "size": self.size,
            "slots": [slot.to_dict() for slot in self.slots],
        }


@dataclass
class HeapString:
    address: str
    value: str
    size: int

    def to_dict(self) -> dict:
        return {"address": self.address, "value": self.value, "size": self.size}


@dataclass
class MemoryLayout:
    global_segment: MemorySegment
    frames: list[StackFrame]
    heap: list[HeapString]

    def to_dict(self) -> dict:
        return {
            "globals": self.global_segment.to_dict(),
            "frames": [frame.to_dict() for frame in self.frames],
            "heap": [item.to_dict() for item in self.heap],
        }


def build_memory_layout(result) -> MemoryLayout:
    """Calcula desplazamientos a partir de SemanticResult."""
    return MemoryLayout(
        global_segment=_global_segment(result.symbols),
        frames=_frames(result.symbols),
        heap=_heap(result.string_literals),
    )


def _global_segment(symbols) -> MemorySegment:
    variables = [symbol for symbol in symbols if symbol.function is None and symbol.kind == "variable"]
    return _pack(variables)


def _frames(symbols) -> list[StackFrame]:
    frames = []
    for function in symbols:
        if function.kind != "function":
            continue
        owned = [
            symbol for symbol in symbols
            if symbol.function == function.name and symbol.kind in ("variable", "parameter")
        ]
        control = [
            MemorySlot("return_address", None, "control", 0, _CONTROL_SIZE),
            MemorySlot("saved_fp", None, "control", _CONTROL_SIZE, _CONTROL_SIZE),
        ]
        body = _pack(owned, offset=_CONTROL_SIZE * 2)
        frames.append(StackFrame(function.name, body.size, control + body.slots))
    return frames


def _pack(symbols, offset: int = 0) -> MemorySegment:
    slots: list[MemorySlot] = []
    used: set[str] = set()
    for symbol in symbols:
        size = TYPE_SIZES.get(symbol.type_name)
        if size is None:
            continue
        name = symbol.name if symbol.name not in used else f"{symbol.name}@{symbol.scope_name}"
        used.add(symbol.name)
        slots.append(MemorySlot(name, symbol.type_name, symbol.kind, offset, size))
        offset += size
    return MemorySegment(offset, slots)


def _heap(literals: list[str]) -> list[HeapString]:
    address = _HEAP_BASE
    objects = []
    for value in literals:
        size = len(value.encode("utf-8")) + 1  # terminador nulo
        objects.append(HeapString(f"0x{address:04x}", value, size))
        address += size
    return objects
