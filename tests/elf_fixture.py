"""Build a minimal 64-bit little-endian ELF file that exports one `u32` symbol, like a native Pumpkin plugin."""

from __future__ import annotations

import struct

_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
_SECTION = struct.Struct("<IIQQQQIIQQ")
_SYMBOL = struct.Struct("<IBBHQQ")
_RODATA_ADDR = 0x2000


def make_elf(symbol: str, value: int) -> bytes:
    rodata = struct.pack("<I", value)
    dynstr = b"\0" + symbol.encode() + b"\0"
    dynsym = _SYMBOL.pack(0, 0, 0, 0, 0, 0) + _SYMBOL.pack(1, 0x11, 0, 3, _RODATA_ADDR, 4)

    rodata_off = _HEADER.size
    dynstr_off = rodata_off + len(rodata)
    dynsym_off = dynstr_off + len(dynstr)
    shoff = dynsym_off + len(dynsym)
    sections = [
        _SECTION.pack(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        _SECTION.pack(0, 11, 0, 0, dynsym_off, len(dynsym), 2, 1, 8, _SYMBOL.size),  # .dynsym, linked to .dynstr
        _SECTION.pack(0, 3, 0, 0, dynstr_off, len(dynstr), 0, 0, 1, 0),  # .dynstr
        _SECTION.pack(0, 1, 0, _RODATA_ADDR, rodata_off, len(rodata), 0, 0, 4, 0),  # .rodata
    ]
    ident = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9)
    header = _HEADER.pack(ident, 3, 62, 1, 0, 0, shoff, 0, _HEADER.size, 0, 0, _SECTION.size, len(sections), 0)
    return header + rodata + dynstr + dynsym + b"".join(sections)
