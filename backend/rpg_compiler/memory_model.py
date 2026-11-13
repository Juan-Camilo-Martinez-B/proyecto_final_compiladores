"""Modelo de memoria: segmento global, stack frames y heap de cadenas.

No hay relleno de alineacion: el desplazamiento de cada slot es la suma de los
tamanos anteriores. Por eso un bool de 1 byte puede ir seguido de un float en
el byte siguiente (vivo en +20 y golpe en +21 en batalla_ok.rpg).

Tamanos: int 4, float 8, bool 1, str 8 (el slot guarda un puntero; el texto
vive en el heap). Cada frame abre con return_address y saved_fp, de 4 bytes.
"""
# ======================================================================
# memory_model.py - FASE 4: modelo de memoria (sesiones 8 y 9)
# ----------------------------------------------------------------------
# Entrada : el SemanticResult (simbolos y cadenas literales).
# Salida  : un MemoryLayout con tres zonas:
#   - Segmento global (data): las variables globales.
#   - Stack frames: un registro de activacion por funcion, con la direccion
#     de retorno, el frame pointer guardado, los parametros y las locales.
#   - Heap: las cadenas literales del programa.
#
# Teoria:
#   - STACK: memoria automatica, LIFO; cada llamada apila un frame y lo
#     libera al retornar. Rapida, pero de tamano limitado.
#   - HEAP: memoria dinamica para datos de tamano o vida variables.
#
# Es una simulacion ESTATICA: calcula tamanos y desplazamientos (offsets) sin
# ejecutar nada. Ejemplo, frame de calcular_dano (28 bytes):
#     +0  return_address 4 | +4 saved_fp 4 | +8 base int 4
#     +12 factor float 8   | +20 dano float 8
# ======================================================================
from __future__ import annotations

from dataclasses import dataclass

# Bytes que ocupa cada tipo. str ocupa 8 porque guarda un puntero al heap.
TYPE_SIZES = {"int": 4, "float": 8, "bool": 1, "str": 8}
_CONTROL_SIZE = 4         # tamano de return_address y de saved_fp
_HEAP_BASE = 0x1000       # direccion donde empieza el heap


# ----------------------------------------------------------------------
# MemorySlot: un espacio en memoria.
#   name      : nombre de la variable (o return_address / saved_fp).
#   type_name : tipo de dato (None en los slots de control).
#   kind      : "variable", "parameter" o "control".
#   offset    : desplazamiento desde el inicio del segmento o frame.
#   size      : bytes que ocupa.
# ----------------------------------------------------------------------
@dataclass
class MemorySlot:
    name: str
    type_name: str | None
    kind: str
    offset: int
    size: int

    # Formato JSON del contrato (la clave del tipo es "type").
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type_name,
            "kind": self.kind,
            "offset": self.offset,
            "size": self.size,
        }


# Un bloque contiguo de slots (el segmento global o el cuerpo de un frame).
# size es el total de bytes.
@dataclass
class MemorySegment:
    size: int
    slots: list[MemorySlot]

    def to_dict(self) -> dict:
        return {"size": self.size, "slots": [slot.to_dict() for slot in self.slots]}


# Registro de activacion de una funcion: su nombre, tamano total y slots.
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


# Una cadena guardada en el heap: direccion (en hexadecimal), texto y tamano.
@dataclass
class HeapString:
    address: str
    value: str
    size: int

    def to_dict(self) -> dict:
        return {"address": self.address, "value": self.value, "size": self.size}


# Resultado completo de la fase: segmento global, frames y heap.
@dataclass
class MemoryLayout:
    global_segment: MemorySegment
    frames: list[StackFrame]
    heap: list[HeapString]

    # Formato JSON del contrato: {"globals", "frames", "heap"}.
    def to_dict(self) -> dict:
        return {
            "globals": self.global_segment.to_dict(),
            "frames": [frame.to_dict() for frame in self.frames],
            "heap": [item.to_dict() for item in self.heap],
        }


# ----------------------------------------------------------------------
# build_memory_layout(result): punto de entrada de la fase.
#   result : SemanticResult del analizador semantico.
# Retorna el MemoryLayout con las tres zonas.
# ----------------------------------------------------------------------
def build_memory_layout(result) -> MemoryLayout:
    """Calcula desplazamientos a partir de SemanticResult."""
    return MemoryLayout(
        global_segment=_global_segment(result.symbols),
        frames=_frames(result.symbols),
        heap=_heap(result.string_literals),
    )


# Segmento global: variables que no pertenecen a ninguna funcion, en orden de
# declaracion, empezando en el desplazamiento 0.
def _global_segment(symbols) -> MemorySegment:
    variables = [symbol for symbol in symbols if symbol.function is None and symbol.kind == "variable"]
    return _pack(variables)


# Un frame por cada funcion. Cada frame:
#   1. Empieza con dos slots de control: return_address (+0) y saved_fp (+4).
#   2. Sigue con los parametros y las variables locales de esa funcion,
#      incluidas las declaradas dentro de sus bloques if (por eso se usa
#      symbol.function y no el ambito).
def _frames(symbols) -> list[StackFrame]:
    frames = []
    for function in symbols:
        if function.kind != "function":
            continue
        # Simbolos que pertenecen a esta funcion.
        owned = [
            symbol for symbol in symbols
            if symbol.function == function.name and symbol.kind in ("variable", "parameter")
        ]
        control = [
            MemorySlot("return_address", None, "control", 0, _CONTROL_SIZE),
            MemorySlot("saved_fp", None, "control", _CONTROL_SIZE, _CONTROL_SIZE),
        ]
        # Los datos empiezan despues de los 8 bytes de control.
        body = _pack(owned, offset=_CONTROL_SIZE * 2)
        frames.append(StackFrame(function.name, body.size, control + body.slots))
    return frames


# Coloca los simbolos uno tras otro a partir de offset, sin relleno: cada slot
# empieza donde termino el anterior. Si un nombre se repite (por ejemplo una
# variable de un if con el mismo nombre que otra de la funcion), el segundo
# slot se llama nombre@ambito para distinguirlos.
# Retorna el segmento; su size es el desplazamiento final (bytes totales).
def _pack(symbols, offset: int = 0) -> MemorySegment:
    slots: list[MemorySlot] = []
    used: set[str] = set()
    for symbol in symbols:
        size = TYPE_SIZES.get(symbol.type_name)
        if size is None:          # tipo sin tamano (void): no ocupa memoria
            continue
        name = symbol.name if symbol.name not in used else f"{symbol.name}@{symbol.scope_name}"
        used.add(symbol.name)
        slots.append(MemorySlot(name, symbol.type_name, symbol.kind, offset, size))
        offset += size
    return MemorySegment(offset, slots)


# Heap de cadenas: cada literal recibe una direccion a partir de 0x1000. Su
# tamano son sus bytes UTF-8 mas 1 del terminador nulo, como en C.
def _heap(literals: list[str]) -> list[HeapString]:
    address = _HEAP_BASE
    objects = []
    for value in literals:
        size = len(value.encode("utf-8")) + 1  # terminador nulo
        objects.append(HeapString(f"0x{address:04x}", value, size))
        address += size                        # la siguiente cadena va justo despues
    return objects
