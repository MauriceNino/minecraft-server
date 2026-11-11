"""Read an exported constant from an ELF shared library without loading it."""

from __future__ import annotations

import struct
from pathlib import Path

_SHT_DYNSYM = 11
_SHT_NOBITS = 8
_SECTION = struct.Struct("<IIQQQQIIQQ")  # name, type, flags, addr, offset, size, link, info, addralign, entsize
_SYMBOL = struct.Struct("<IBBHQQ")  # name, info, other, shndx, value, size


def read_u32_symbol(path: Path, name: str) -> int | None:
    """The `u32` an exported symbol of a 64-bit little-endian ELF file points to, or None if there is none."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        return None

    try:
        shoff, shentsize, shnum = struct.unpack_from("<Q", data, 0x28)[0], *struct.unpack_from("<HH", data, 0x3A)
        sections = [_SECTION.unpack_from(data, shoff + i * shentsize) for i in range(shnum)]
        dynsym = next((s for s in sections if s[1] == _SHT_DYNSYM), None)
        if dynsym is None:
            return None
        strtab = sections[dynsym[6]]

        for offset in range(dynsym[4], dynsym[4] + dynsym[5], _SYMBOL.size):
            st_name, _, _, st_shndx, st_value, _ = _SYMBOL.unpack_from(data, offset)
            start = strtab[4] + st_name
            if data[start : data.index(b"\0", start)].decode() != name:
                continue
            if not 0 < st_shndx < len(sections) or sections[st_shndx][1] == _SHT_NOBITS:
                return None
            section = sections[st_shndx]
            return struct.unpack_from("<I", data, section[4] + st_value - section[3])[0]
    except (struct.error, ValueError, IndexError, UnicodeDecodeError):
        return None
    return None
