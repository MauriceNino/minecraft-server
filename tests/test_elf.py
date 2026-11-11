from __future__ import annotations

from pathlib import Path

from orchestrator.elf import read_u32_symbol
from tests.elf_fixture import make_elf


def test_reads_the_exported_value(tmp_path: Path) -> None:
    lib = tmp_path / "lib.so"
    lib.write_bytes(make_elf("PUMPKIN_API_VERSION", 5))
    assert read_u32_symbol(lib, "PUMPKIN_API_VERSION") == 5
    assert read_u32_symbol(lib, "OTHER") is None


def test_non_elf_files_have_no_symbols(tmp_path: Path) -> None:
    lib = tmp_path / "lib.dylib"
    lib.write_bytes(b"\xcf\xfa\xed\xfe" + bytes(100))
    assert read_u32_symbol(lib, "PUMPKIN_API_VERSION") is None
    (tmp_path / "broken.so").write_bytes(b"\x7fELF\x02\x01" + bytes(10))
    assert read_u32_symbol(tmp_path / "broken.so", "PUMPKIN_API_VERSION") is None
    assert read_u32_symbol(tmp_path / "missing.so", "PUMPKIN_API_VERSION") is None
