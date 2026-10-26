"""Read the Qt version a plugin binary was built against, from the binary's own metadata.

Qt's qplugin.h puts a four-byte header in every plugin: the format version (1), the Qt major
version, the Qt minor version and an architecture byte. Where those bytes sit depends on the
binary format, so this reads each format's own section and nothing else:

- Mach-O: the `qtmetadata` section of the `__TEXT` segment, once per slice of a universal
  binary. The section starts with the 12-byte magic `QTMETADATA !`, then the header.
- ELF: the `.note.qt.metadata` section, whose note is named `qt-project!` and has type
  0x74510001. The header is the first four bytes of the note's descriptor. No magic precedes it.
- PE: the `.qtmetadata` section, which starts with the magic and then the header. The linker
  cuts an image section name to 8 characters, so MSVC writes `.qtmetad`; MinGW writes the long
  name through the string table.

A whole-file scan for the magic would be wrong: a real ELF plugin holds stray `QTMETADATA !`
strings outside its note. Standard library only.
"""

from __future__ import annotations

import struct
from typing import NamedTuple

# bytes, or a zero-copy view of one universal slice
Buffer = bytes | memoryview

MAGIC = b"QTMETADATA !"
HEADER_VERSION = 1
ELF_NOTE_NAME = b"qt-project!\x00"
ELF_NOTE_TYPE = 0x74510001

_MACHO_SECTION = b"qtmetadata"
_ELF_SECTION = b".note.qt.metadata"
_PE_SECTION = b".qtmetadata"
_PE_SECTION_SHORT = _PE_SECTION[:8]

_MAX_COUNT = 4096  # sections or load commands; a real binary has far fewer
# A real universal binary has two to four slices (arm64, x86_64, sometimes arm64e or i386).
# Every slice is parsed, so a larger claim is refused rather than multiplied by the work.
_MAX_SLICES = 16

# The input is untrusted, so every loop and copy is bounded by the file size n:
# - A universal slice is a zero-copy view; up to 16 slices, which may overlap, so at most 16n.
# - Load commands sit end to end inside the slice, and each segment's section records fit in
#   its own command, so one slice reads at most n / 68 section records of 32 bytes each.
# - ELF and PE section tables are capped at 4096 entries, each read in O(1).
# - A name lookup searches at most 18 bytes for its NUL.
# - A second matching section is refused. Mach-O and PE copy only the first 16 bytes of the
#   one section. The ELF walk reads that whole section in place, advancing at least 12 bytes
#   a step, and refuses a second matching note, so it keeps one header and copies 4 bytes.
_HEAD_BYTES = len(MAGIC) + 4


class QtHeader(NamedTuple):
    """One metadata header. `where` names the slice or format, for error messages."""

    where: str
    major: int
    minor: int


class MetadataError(Exception):
    """The binary has no readable Qt metadata header, or its headers disagree."""


def _check_range(data: Buffer, offset: int, size: int, what: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise MetadataError(f"{what} points outside the file")


def _slice(data: Buffer, offset: int, size: int, what: str) -> Buffer:
    """data[offset:offset + size]. Zero-copy when data is a memoryview."""
    _check_range(data, offset, size, what)
    return data[offset : offset + size]


def _head(data: Buffer, offset: int, size: int, what: str) -> bytes:
    """The first bytes of a section, enough for the magic and the header, as a small copy."""
    _check_range(data, offset, size, what)
    return bytes(data[offset : offset + min(size, _HEAD_BYTES)])


def _unpack(fmt: str, data: Buffer, offset: int, what: str) -> tuple[int, ...]:
    try:
        return struct.unpack_from(fmt, data, offset)
    except struct.error:
        raise MetadataError(f"{what} is cut off") from None


def _read_header(block: bytes, where: str, *, magic: bool) -> QtHeader:
    """Parse the four header bytes at the start of block, after the magic when there is one."""
    start = 0
    if magic:
        if not block.startswith(MAGIC):
            raise MetadataError(f"{where}: the Qt metadata section does not start with its magic")
        start = len(MAGIC)
    if len(block) < start + 4:
        raise MetadataError(f"{where}: the Qt metadata header is cut off")
    version, major, minor, _arch = block[start : start + 4]
    if version != HEADER_VERSION:
        raise MetadataError(f"{where}: the Qt metadata header has format version {version}")
    return QtHeader(where, major, minor)


# --- Mach-O ---------------------------------------------------------------------------

_FAT_MAGICS = {0xCAFEBABE: (False, "!5I"), 0xCAFEBABF: (True, "!IIQQII")}
_MACHO_MAGICS = {
    0xFEEDFACE: (False, "<"),
    0xFEEDFACF: (True, "<"),
    0xCEFAEDFE: (False, ">"),
    0xCFFAEDFE: (True, ">"),
}
_LC_SEGMENT = 0x1
_LC_SEGMENT_64 = 0x19


def _macho_header(data: Buffer, where: str) -> QtHeader:
    """The header in one thin Mach-O image (a universal binary's slice, cut out already)."""
    (magic,) = _unpack("<I", data, 0, f"{where}: the Mach-O header")
    if magic not in _MACHO_MAGICS:
        raise MetadataError(f"{where}: the slice is not a Mach-O image")
    is64, endian = _MACHO_MAGICS[magic]
    # mach_header: magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags (+ reserved)
    ncmds, sizeofcmds = _unpack(f"{endian}II", data, 16, f"{where}: the Mach-O header")
    if ncmds > _MAX_COUNT:
        raise MetadataError(f"{where}: the Mach-O header claims {ncmds} load commands")
    offset = 32 if is64 else 28
    segment_cmd, other_cmd = (
        (_LC_SEGMENT_64, _LC_SEGMENT) if is64 else (_LC_SEGMENT, _LC_SEGMENT_64)
    )
    segment_size, section_size = (72, 80) if is64 else (56, 68)
    # section: sectname, segname, addr, size, offset (size and addr are 64-bit in a 64-bit image)
    size_fmt, size_at = (f"{endian}QI", 40) if is64 else (f"{endian}II", 36)
    found: bytes | None = None
    used = 0
    for _ in range(ncmds):
        cmd, cmdsize = _unpack(f"{endian}II", data, offset, f"{where}: a Mach-O load command")
        if cmdsize < 8:
            raise MetadataError(f"{where}: a Mach-O load command has size {cmdsize}")
        # Each command stays inside the slice and the commands inside sizeofcmds, so the
        # records read below never overlap and the work is bounded by the input size.
        used += cmdsize
        if used > sizeofcmds or offset + cmdsize > len(data):
            raise MetadataError(f"{where}: the Mach-O load commands overrun their area")
        if cmd == other_cmd:
            bits = 64 if is64 else 32
            raise MetadataError(
                f"{where}: a {bits}-bit Mach-O image holds a segment command {cmd:#x}"
            )
        if cmd == segment_cmd:
            nsects = _unpack(
                f"{endian}I", data, offset + segment_size - 8, f"{where}: a Mach-O segment"
            )[0]
            if segment_size + nsects * section_size > cmdsize:
                raise MetadataError(f"{where}: a Mach-O segment claims {nsects} sections")
            for index in range(nsects):
                base = offset + segment_size + index * section_size
                name = bytes(_slice(data, base, 32, f"{where}: a Mach-O section"))
                sectname = name[:16].rstrip(b"\x00")
                segname = name[16:32].rstrip(b"\x00")
                if sectname != _MACHO_SECTION or segname != b"__TEXT":
                    continue
                if found is not None:
                    raise MetadataError(f"{where}: more than one __TEXT,qtmetadata section")
                size, file_offset = _unpack(size_fmt, data, base + size_at, f"{where}: a section")
                found = _head(data, file_offset, size, f"{where}: the qtmetadata section")
        offset += cmdsize
    if found is None:
        raise MetadataError(f"{where}: no __TEXT,qtmetadata section")
    return _read_header(found, where, magic=True)


def _macho_headers(data: bytes) -> list[QtHeader]:
    (magic,) = _unpack(">I", data, 0, "the file header")
    if magic not in _FAT_MAGICS:
        return [_macho_header(data, "Mach-O")]
    is64, fmt = _FAT_MAGICS[magic]
    count = _unpack(">I", data, 4, "the universal header")[0]
    if not 1 <= count <= _MAX_SLICES:
        raise MetadataError(f"the universal header claims {count} slices")
    view = memoryview(data)
    headers: list[QtHeader] = []
    for index in range(count):
        base = 8 + index * (32 if is64 else 20)
        fields = _unpack(fmt, data, base, "a universal slice entry")
        cputype, offset, size = fields[0], fields[2], fields[3]
        where = f"Mach-O slice {index} (cpu {cputype:#x})"
        headers.append(_macho_header(_slice(view, offset, size, where), where))
    return headers


# --- ELF ------------------------------------------------------------------------------


def _elf_headers(data: bytes) -> list[QtHeader]:
    if len(data) < 20 or data[4] not in (1, 2) or data[5] not in (1, 2):
        raise MetadataError("the ELF identification bytes are not valid")
    is64 = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    if is64:
        shoff = _unpack(f"{endian}Q", data, 40, "the ELF header")[0]
        shentsize, shnum, shstrndx = _unpack(f"{endian}HHH", data, 58, "the ELF header")
        section_fmt = f"{endian}IIQQQQ"
    else:
        shoff = _unpack(f"{endian}I", data, 32, "the ELF header")[0]
        shentsize, shnum, shstrndx = _unpack(f"{endian}HHH", data, 46, "the ELF header")
        section_fmt = f"{endian}IIIIII"
    if shnum == 0 or shnum > _MAX_COUNT:
        raise MetadataError(f"the ELF header claims {shnum} sections")

    def section(index: int) -> tuple[int, int, int]:
        """name offset, file offset and size of section `index`."""
        base = shoff + index * shentsize
        fields = _unpack(section_fmt, data, base, "an ELF section header")
        # sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size (the same order in both)
        return fields[0], fields[4], fields[5]

    if shstrndx >= shnum:
        raise MetadataError("the ELF section name table index is out of range")
    _, names_offset, names_size = section(shstrndx)
    _check_range(data, names_offset, names_size, "the ELF section name table")
    names_end = names_offset + names_size

    note: tuple[int, int] | None = None
    for index in range(shnum):
        name_offset, offset, size = section(index)
        start = names_offset + name_offset
        end = data.find(b"\x00", start, min(start + len(_ELF_SECTION) + 1, names_end))
        if end < 0 or data[start:end] != _ELF_SECTION:
            continue
        if note is not None:
            raise MetadataError("more than one .note.qt.metadata section")
        _check_range(data, offset, size, "the .note.qt.metadata section")
        note = offset, size
    if note is None:
        raise MetadataError("no .note.qt.metadata section")

    # Walk the notes in place; each step moves at least 12 bytes inside the one section.
    headers: list[QtHeader] = []
    position, block_end = note[0], note[0] + note[1]
    while position + 12 <= block_end:
        namesz, descsz, note_type = struct.unpack_from(f"{endian}III", data, position)
        name_start = position + 12
        desc_start = name_start + (namesz + 3) // 4 * 4
        if desc_start + descsz > block_end:
            raise MetadataError("an ELF note in .note.qt.metadata is cut off")
        if (
            note_type == ELF_NOTE_TYPE
            and namesz == len(ELF_NOTE_NAME)
            and data[name_start : name_start + namesz] == ELF_NOTE_NAME
        ):
            if headers:
                raise MetadataError("more than one qt-project! note in .note.qt.metadata")
            desc = data[desc_start : desc_start + min(descsz, 4)]
            headers.append(_read_header(desc, "ELF", magic=False))
        position = desc_start + (descsz + 3) // 4 * 4
    if not headers:
        raise MetadataError("no qt-project! note of type 0x74510001 in .note.qt.metadata")
    return headers


# --- PE -------------------------------------------------------------------------------


def _pe_headers(data: bytes) -> list[QtHeader]:
    (pe_offset,) = _unpack("<I", data, 0x3C, "the DOS header")
    if _unpack("<4s", data, pe_offset, "the PE signature")[0] != b"PE\x00\x00":
        raise MetadataError("the PE signature is missing")
    # COFF header: machine, nsections, timestamp, symtab, nsyms, optsize, characteristics
    nsections, _stamp, symtab, nsyms, optsize = _unpack(
        "<HIIIH", data, pe_offset + 6, "COFF header"
    )
    if nsections > _MAX_COUNT:
        raise MetadataError(f"the PE header claims {nsections} sections")
    table = pe_offset + 24 + optsize
    strings = symtab + nsyms * 18 if symtab else 0

    found: bytes | None = None
    for index in range(nsections):
        base = table + index * 40
        raw = _slice(data, base, 40, "a PE section header")
        name = raw[:8].rstrip(b"\x00")
        if name.startswith(b"/") and name[1:].isdigit() and strings:
            # A long name: the digits are an offset into the string table.
            start = strings + int(name[1:])
            end = data.find(b"\x00", start, start + len(_PE_SECTION) + 1)
            name = data[start:end] if end >= 0 else b""
        if name not in (_PE_SECTION, _PE_SECTION_SHORT):
            continue
        if found is not None:
            raise MetadataError("more than one .qtmetadata section")
        virtual_size, _addr, raw_size, raw_ptr = struct.unpack_from("<IIII", raw, 8)
        size = min(virtual_size, raw_size) if virtual_size else raw_size
        found = _head(data, raw_ptr, size, "the .qtmetadata section")
    if found is None:
        raise MetadataError("no .qtmetadata section")
    return [_read_header(found, "PE", magic=True)]


# --- Entry points ---------------------------------------------------------------------


def _agree(headers: list[QtHeader]) -> QtHeader:
    first = headers[0]
    for header in headers[1:]:
        if (header.major, header.minor) != (first.major, first.minor):
            raise MetadataError(
                f"{first.where} is built against Qt {first.major}.{first.minor} but "
                f"{header.where} against Qt {header.major}.{header.minor}"
            )
    return first


def qt_headers(data: bytes) -> list[QtHeader]:
    """Every Qt metadata header in the binary, one per Mach-O slice. Raises MetadataError."""
    head = data[:4]
    if head == b"\x7fELF":
        return _elf_headers(data)
    if head[:2] == b"MZ":
        return _pe_headers(data)
    if len(head) == 4 and struct.unpack(">I", head)[0] in _FAT_MAGICS:
        return _macho_headers(data)
    if len(head) == 4 and struct.unpack("<I", head)[0] in _MACHO_MAGICS:
        return _macho_headers(data)
    raise MetadataError("the file is not a Mach-O, ELF or PE binary")


def qt_version(data: bytes) -> tuple[int, int]:
    """The (major, minor) Qt version every header in the binary agrees on.

    Raises MetadataError when there is no header or two headers disagree.
    """
    first = _agree(qt_headers(data))
    return first.major, first.minor
