"""Small synthetic binaries that carry a Qt metadata header, one builder per format.

Each builder writes only the structures the reader walks: a header, the section table and the
section itself. They are not loadable programs. Used by test_qt_metadata.py and
test_validate_entry.py.
"""

from __future__ import annotations

import struct

MAGIC = b"QTMETADATA !"
CBOR = b"\xa1\x61a\x01"  # stand-in payload after the four header bytes


def header(major: int, minor: int, *, version: int = 1, arch: int = 0x80) -> bytes:
    return bytes([version, major, minor, arch])


def _pad(data: bytes, align: int) -> bytes:
    return data + b"\x00" * (-len(data) % align)


def macho(
    major: int,
    minor: int,
    *,
    is64: bool = True,
    big: bool = False,
    section: bool = True,
    version: int = 1,
) -> bytes:
    """A thin Mach-O image with one __TEXT segment holding a qtmetadata section."""
    e = ">" if big else "<"
    nsects = 1 if section else 0
    seg_size = (72 if is64 else 56) + nsects * (80 if is64 else 68)
    base = (32 if is64 else 28) + seg_size
    payload = MAGIC + header(major, minor, version=version) + CBOR
    name = b"qtmetadata".ljust(16, b"\x00") + b"__TEXT".ljust(16, b"\x00")
    if is64:
        sect = name + struct.pack(f"{e}QQIIIIIIII", 0, len(payload), base, 0, 0, 0, 0, 0, 0, 0)
        seg = struct.pack(f"{e}II", 0x19, seg_size) + b"__TEXT".ljust(16, b"\x00")
        seg += struct.pack(f"{e}QQQQIIII", 0, 0x1000, 0, 0x1000, 5, 5, nsects, 0)
        head = struct.pack(f"{e}IIIIIIII", 0xFEEDFACF, 0, 0, 6, 1, seg_size, 0, 0)
    else:
        sect = name + struct.pack(f"{e}IIIIIIIII", 0, len(payload), base, 0, 0, 0, 0, 0, 0)
        seg = struct.pack(f"{e}II", 0x1, seg_size) + b"__TEXT".ljust(16, b"\x00")
        seg += struct.pack(f"{e}IIIIIIII", 0, 0x1000, 0, 0x1000, 5, 5, nsects, 0)
        head = struct.pack(f"{e}IIIIIII", 0xFEEDFACE, 0, 0, 6, 1, seg_size, 0)
    body = seg + (sect if section else b"")
    return head + body + (payload if section else b"")


def fat(*slices: bytes, wide: bool = False) -> bytes:
    """A universal binary holding the given thin images, each 16-byte aligned."""
    entry = 32 if wide else 20
    offset = 8 + entry * len(slices)
    table, body = b"", b""
    for index, blob in enumerate(slices):
        pad = -offset % 16
        offset += pad
        body += b"\x00" * pad + blob
        cpu = 0x01000007 + index
        if wide:
            table += struct.pack(">IIQQII", cpu, 3, offset, len(blob), 4, 0)
        else:
            table += struct.pack(">IIIII", cpu, 3, offset, len(blob), 4)
        offset += len(blob)
    magic = 0xCAFEBABF if wide else 0xCAFEBABE
    return struct.pack(">II", magic, len(slices)) + table + body


def elf(
    major: int,
    minor: int,
    *,
    is64: bool = True,
    big: bool = False,
    stray: bool = False,
    note: bool = True,
    note_type: int = 0x74510001,
    note_name: bytes = b"qt-project!\x00",
    note_count: int = 1,
) -> bytes:
    """An ELF image with a .note.qt.metadata section.

    With `stray`, the image also holds `QTMETADATA !` strings outside the note, carrying a
    different (wrong) Qt version, as a real x86-64 plugin does.
    """
    e = ">" if big else "<"
    desc = _pad(header(major, minor) + CBOR, 4)
    # Qt aligns the descriptor to the pointer size; the name pads to 4 and the note is 24 bytes
    # of preamble in both widths, so no extra padding is needed.
    note_bytes = struct.pack(f"{e}III", len(note_name), len(desc), note_type)
    note_bytes += _pad(note_name, 4) + desc
    note_bytes *= note_count
    strtab = b"\x00.note.qt.metadata\x00.shstrtab\x00.rodata\x00"
    note_name_off, shstr_name_off, rodata_name_off = 1, 1 + len(b".note.qt.metadata\x00"), 0
    rodata_name_off = shstr_name_off + len(b".shstrtab\x00")
    rodata = b""
    if stray:
        rodata = MAGIC + header(5, 99) + b"\x00" + MAGIC + header(4, 1) + b"\x00"
    ehsize = 64 if is64 else 52
    shentsize = 64 if is64 else 40
    note_off = ehsize
    str_off = note_off + (len(note_bytes) if note else 0)
    rodata_off = str_off + len(strtab)
    shoff = rodata_off + len(rodata)

    def sh(name: int, offset: int, size: int) -> bytes:
        if is64:
            return struct.pack(f"{e}IIQQQQIIQQ", name, 1, 0, 0, offset, size, 0, 0, 1, 0)
        return struct.pack(f"{e}IIIIIIIIII", name, 1, 0, 0, offset, size, 0, 0, 1, 0)

    sections = [sh(0, 0, 0)]
    if note:
        sections.append(sh(note_name_off, note_off, len(note_bytes)))
    sections.append(sh(shstr_name_off, str_off, len(strtab)))
    sections.append(sh(rodata_name_off, rodata_off, len(rodata)))
    shstrndx = len(sections) - 2
    ident = b"\x7fELF" + bytes([2 if is64 else 1, 2 if big else 1, 1]) + b"\x00" * 9
    if is64:
        ehdr = ident + struct.pack(
            f"{e}HHIQQQIHHHHHH",
            3,
            62,
            1,
            0,
            0,
            shoff,
            0,
            64,
            0,
            0,
            shentsize,
            len(sections),
            shstrndx,
        )
    else:
        ehdr = ident + struct.pack(
            f"{e}HHIIIIIHHHHHH",
            3,
            3,
            1,
            0,
            0,
            shoff,
            0,
            52,
            0,
            0,
            shentsize,
            len(sections),
            shstrndx,
        )
    assert len(ehdr) == ehsize
    return ehdr + (note_bytes if note else b"") + strtab + rodata + b"".join(sections)


def pe(major: int, minor: int, *, long_name: bool = False, section: bool = True) -> bytes:
    """A PE image with a .qtmetadata section (short MSVC name, or MinGW's string-table name)."""
    payload = MAGIC + header(major, minor) + CBOR
    optional = 16
    pe_off = 0x40
    table = pe_off + 24 + optional
    raw_ptr = table + 40
    if long_name:
        symtab = raw_ptr + len(payload)
        name = b"/4".ljust(8, b"\x00")
        strings = struct.pack("<I", 4 + len(b".qtmetadata\x00")) + b".qtmetadata\x00"
    else:
        symtab = 0
        name = b".qtmetad"
        strings = b""
    nsects = 1 if section else 0
    dos = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", pe_off)
    coff = b"PE\x00\x00" + struct.pack("<HHIIIHH", 0x8664, nsects, 0, symtab, 0, optional, 0x2022)
    sect = name + struct.pack(
        "<IIIIIIHHI", len(payload), 0x1000, len(payload), raw_ptr, 0, 0, 0, 0, 0x40000040
    )
    return dos + coff + b"\x00" * optional + (sect + payload if section else b"") + strings
