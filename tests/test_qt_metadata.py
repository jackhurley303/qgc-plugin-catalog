import struct

import fixtures_qt as fx
import pytest
import qt_metadata
from qt_metadata import MetadataError


def _version(data: bytes) -> tuple[int, int]:
    return qt_metadata.qt_version(data)


# --- Mach-O -----------------------------------------------------------------------------


@pytest.mark.parametrize(("is64", "big"), [(True, False), (False, False), (True, True)])
def test_thin_macho_header_is_read(is64, big):
    assert _version(fx.macho(6, 12, is64=is64, big=big)) == (6, 12)


@pytest.mark.parametrize("wide", [False, True])
def test_universal_dylib_with_agreeing_slices_is_read(wide):
    data = fx.fat(fx.macho(6, 12), fx.macho(6, 12), wide=wide)
    headers = qt_metadata.qt_headers(data)
    assert len(headers) == 2
    assert _version(data) == (6, 12)


def test_universal_dylib_with_disagreeing_slices_is_refused():
    data = fx.fat(fx.macho(6, 12), fx.macho(6, 13))
    with pytest.raises(MetadataError, match=r"Qt 6\.12 but .* Qt 6\.13"):
        _version(data)


def test_universal_slice_without_a_header_is_refused():
    data = fx.fat(fx.macho(6, 12), fx.macho(6, 12, section=False))
    with pytest.raises(MetadataError, match="slice 1.*no __TEXT,qtmetadata"):
        _version(data)


def test_macho_without_a_header_is_refused():
    with pytest.raises(MetadataError, match="no __TEXT,qtmetadata"):
        _version(fx.macho(6, 12, section=False))


def test_macho_header_with_a_foreign_format_version_is_refused():
    with pytest.raises(MetadataError, match="format version 2"):
        _version(fx.macho(6, 12, version=2))


# --- ELF --------------------------------------------------------------------------------


@pytest.mark.parametrize(("is64", "big"), [(True, False), (False, False), (False, True)])
def test_elf_note_header_is_read(is64, big):
    assert _version(fx.elf(6, 12, is64=is64, big=big)) == (6, 12)


def test_elf_stray_magic_strings_are_ignored():
    data = fx.elf(6, 12, stray=True)
    assert data.count(fx.MAGIC) == 2
    assert _version(data) == (6, 12)


def test_elf_without_the_note_is_refused_even_with_the_magic_present():
    data = fx.elf(6, 12, stray=True, note=False)
    with pytest.raises(MetadataError, match="no .note.qt.metadata"):
        _version(data)


@pytest.mark.parametrize(
    "changes",
    [{"note_type": 0x74510002}, {"note_name": b"GNU\x00"}],
)
def test_elf_note_of_another_kind_is_refused(changes):
    with pytest.raises(MetadataError, match="no qt-project! note"):
        _version(fx.elf(6, 12, **changes))


def test_elf_with_two_matching_notes_is_refused():
    with pytest.raises(MetadataError, match="more than one qt-project! note"):
        _version(fx.elf(6, 12, note_count=2))


# --- PE ---------------------------------------------------------------------------------


@pytest.mark.parametrize("long_name", [False, True])
def test_pe_header_is_read(long_name):
    assert _version(fx.pe(6, 12, long_name=long_name)) == (6, 12)


def test_pe_without_the_section_is_refused():
    with pytest.raises(MetadataError, match="no .qtmetadata section"):
        _version(fx.pe(6, 12, section=False))


# --- Anything else ----------------------------------------------------------------------


@pytest.mark.parametrize("data", [b"", b"\x00\x01", b"plain text", fx.MAGIC + fx.header(6, 12)])
def test_unknown_or_bare_data_is_refused(data):
    with pytest.raises(MetadataError, match="not a Mach-O, ELF or PE binary"):
        _version(data)


@pytest.mark.parametrize(
    "make",
    [
        lambda: fx.macho(6, 12),
        lambda: fx.elf(6, 12),
        lambda: fx.pe(6, 12),
        lambda: fx.fat(fx.macho(6, 12)),
    ],
)
def test_truncated_binary_is_refused_and_never_crashes(make):
    data = make()
    for cut in range(0, len(data), 7):
        try:
            qt_metadata.qt_version(data[:cut])
        except MetadataError:
            pass


# --- Hostile structure: refused by size checks, not by running out of patience -----------


def _overlapping_thin(ncmds: int, nsects: int, sizeofcmds: int) -> bytes:
    """Many 72-byte segment commands that each claim `nsects` sections, so their section
    records would all overlap the same bytes."""
    head = struct.pack("<8I", 0xFEEDFACF, 0, 0, 6, ncmds, sizeofcmds, 0, 0)
    command = struct.pack("<II", 0x19, 72) + b"\0" * 56 + struct.pack("<II", nsects, 0)
    return head + command * ncmds + b"\0" * (nsects * 80 + 100)


def test_segment_claiming_more_sections_than_its_command_holds_is_refused():
    data = _overlapping_thin(4096, 4096, sizeofcmds=4096 * 72)
    with pytest.raises(MetadataError, match="claims 4096 sections"):
        _version(data)


def test_load_commands_past_sizeofcmds_are_refused():
    data = _overlapping_thin(4096, 0, sizeofcmds=72)
    with pytest.raises(MetadataError, match="overrun their area"):
        _version(data)


def test_load_command_past_the_end_of_the_slice_is_refused():
    data = _overlapping_thin(2, 0, sizeofcmds=144)[: 32 + 72 + 10]
    with pytest.raises(MetadataError, match="overrun their area"):
        _version(data)


def test_universal_binary_claiming_many_slices_is_refused():
    thin = fx.macho(6, 12)
    data = fx.fat(*([thin] * 17))
    with pytest.raises(MetadataError, match="claims 17 slices"):
        _version(data)


def test_universal_slice_that_is_not_macho_is_refused():
    data = struct.pack(">II", 0xCAFEBABE, 1) + struct.pack(">5I", 7, 3, 28, 8, 0) + b"XXXXXXXX"
    with pytest.raises(MetadataError, match="not a Mach-O image"):
        _version(data)


def test_segment_command_of_the_other_width_is_refused():
    data = bytearray(fx.macho(6, 12))
    struct.pack_into("<I", data, 32, 0x1)  # LC_SEGMENT where LC_SEGMENT_64 belongs
    with pytest.raises(MetadataError, match="64-bit Mach-O image holds a segment command 0x1"):
        _version(bytes(data))


# --- Hostile structure: many matching sections are refused, not each copied --------------


def test_macho_with_many_overlapping_qtmetadata_sections_is_refused():
    nsects = 8
    cmdsize = 72 + nsects * 80
    total = 32 + cmdsize
    head = struct.pack("<8I", 0xFEEDFACF, 0, 0, 6, 1, cmdsize, 0, 0)
    segment = struct.pack("<II", 0x19, cmdsize) + b"\0" * 56 + struct.pack("<II", nsects, 0)
    name = b"qtmetadata".ljust(16, b"\0") + b"__TEXT".ljust(16, b"\0")
    section = name + struct.pack("<QQII", 0, total - 1, 1, 0) + b"\0" * 24
    with pytest.raises(MetadataError, match="more than one __TEXT,qtmetadata section"):
        _version(head + segment + section * nsects)


def test_elf_with_many_overlapping_note_sections_is_refused():
    shnum, shoff = 8, 64
    names_off = shoff + shnum * 64
    names = b"\0.note.qt.metadata\0"
    total = names_off + len(names) + 64
    head = bytearray(64)
    head[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", head, 40, shoff)
    struct.pack_into("<HHH", head, 58, 64, shnum, 0)
    table = struct.pack("<IIQQQQ", 0, 3, 0, 0, names_off, len(names)) + b"\0" * 24
    for _ in range(1, shnum):
        table += struct.pack("<IIQQQQ", 1, 7, 0, 0, 1, total - 1) + b"\0" * 24
    data = bytes(head) + table + names + b"\0" * 64
    with pytest.raises(MetadataError, match="more than one .note.qt.metadata section"):
        _version(data)


def test_pe_with_two_qtmetadata_sections_is_refused():
    payload = fx.MAGIC + fx.header(6, 12) + fx.CBOR
    optional, pe_off = 16, 0x40
    raw_ptr = pe_off + 24 + optional + 2 * 40
    dos = b"MZ" + b"\x00" * 0x3A + struct.pack("<I", pe_off)
    coff = b"PE\x00\x00" + struct.pack("<HHIIIHH", 0x8664, 2, 0, 0, 0, optional, 0x2022)
    section = b".qtmetad" + struct.pack(
        "<IIIIIIHHI", len(payload), 0x1000, len(payload), raw_ptr, 0, 0, 0, 0, 0
    )
    data = dos + coff + b"\x00" * optional + section * 2 + payload
    with pytest.raises(MetadataError, match="more than one .qtmetadata section"):
        _version(data)


class _FindSpy(bytes):
    """Bytes that record the window of every find(), to show a name search stays short."""

    windows: list[int]

    def find(self, sub, start=None, end=None):
        self.windows.append(end - start)
        return super().find(sub, start, end)


@pytest.mark.parametrize(
    ("data", "old", "message"),
    [
        (fx.elf(6, 12), b".note.qt.metadata\x00", "no .note.qt.metadata section"),
        (fx.pe(6, 12, long_name=True), b".qtmetadata\x00", "no .qtmetadata section"),
    ],
    ids=["elf", "pe"],
)
def test_section_name_without_its_nul_is_searched_only_name_length(data, old, message):
    # The name runs into the next bytes, so an unbounded search would scan past it.
    assert old in data
    spy = _FindSpy(data.replace(old, old[:-1] + b"X") + b"Y" * 4096)
    spy.windows = []
    with pytest.raises(MetadataError, match=message):
        _version(spy)
    assert spy.windows
    assert max(spy.windows) <= len(old)
