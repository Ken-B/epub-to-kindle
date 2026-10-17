"""
Shared helpers for reading the text of a MOBI/AZW3 file in tests.

  text_bytes(data)  -> decompressed text with every record's trailing entries removed
  fdst_flows(data)  -> list[bytes], one per FDST flow (KF8: flow 0 = HTML, 1..N = CSS)

Text records end with "trailing entries" selected by extra_data_flags (MOBI header
offset 0xF0): bits 1.. are TBS-style entries (backward varint size), bit 0 is the
multibyte entry (overlap bytes + one byte = len(overlap)). The overlap bytes are
repeated at the start of the next record, so after stripping nothing is re-added.
Our writer uses flags = 1 and always emits the multibyte entry (0x00 when no overlap).
"""
import struct


def palmdoc_decompress(data: bytes) -> bytes:
    out = bytearray(); i = 0
    while i < len(data):
        b = data[i]; i += 1
        if b == 0:
            out.append(0)
        elif b <= 8:
            for _ in range(b):
                if i < len(data): out.append(data[i]); i += 1
        elif b <= 0x7F:
            out.append(b)
        elif b <= 0xBF:
            if i >= len(data): break
            b2 = data[i]; i += 1
            dist = ((b & 0x3F) << 5) | (b2 >> 3)
            ln = (b2 & 7) + 3
            for _ in range(ln):
                out.append(out[-dist] if dist <= len(out) else 0)
        else:
            out.append(0x20); out.append(b & 0x7F)
    return bytes(out)


def _rec_offsets(data: bytes) -> list[int]:
    nrec = struct.unpack_from('>H', data, 76)[0]
    return [struct.unpack_from('>I', data, 78 + i * 8)[0] for i in range(nrec)]


def _extra_data_flags(data: bytes, r0: int) -> int:
    mobi_len = struct.unpack_from('>I', data, r0 + 20)[0]
    return struct.unpack_from('>I', data, r0 + 0xF0)[0] if mobi_len >= 0xE4 else 0


def strip_trailing_entries(rec: bytes, flags: int) -> bytes:
    """Drop the trailing entries of one text record (before decompression)."""
    size = len(rec)
    f = flags >> 1
    while f:
        if f & 1:  # TBS-style entry: backward varint holding its own size
            val = shift = 0; p = size
            while p > 0:
                v = rec[p - 1]; val |= (v & 0x7F) << shift; shift += 7; p -= 1
                if (v & 0x80) or shift >= 28: break
            size -= val
        f >>= 1
    if flags & 1:  # multibyte: n overlap bytes + count byte
        n = rec[size - 1] & 0x3
        size -= n + 1
    return rec[:size]


def text_bytes(data: bytes) -> bytes:
    offs = _rec_offsets(data)
    r0 = offs[0]
    compression = struct.unpack_from('>H', data, r0)[0]
    num_text = struct.unpack_from('>H', data, r0 + 8)[0]
    flags = _extra_data_flags(data, r0)
    out = b''
    for i in range(1, num_text + 1):
        s = offs[i]; e = offs[i + 1] if i + 1 < len(offs) else len(data)
        rec = strip_trailing_entries(data[s:e], flags)
        out += palmdoc_decompress(rec) if compression == 2 else rec
    return out


def fdst_flows(data: bytes) -> list[bytes]:
    """FDST flows of a KF8 file; [] when there is no FDST (MOBI v6)."""
    offs = _rec_offsets(data)
    r0 = offs[0]
    fdst_rec = struct.unpack_from('>I', data, r0 + 0xC0)[0]
    if struct.unpack_from('>I', data, r0 + 36)[0] != 8 or fdst_rec >= len(offs):
        return []
    fo = offs[fdst_rec]
    if data[fo:fo + 4] != b'FDST':
        return []
    count = struct.unpack_from('>I', data, fo + 8)[0]
    text = text_bytes(data)
    return [text[a:b] for a, b in
            (struct.unpack_from('>II', data, fo + 12 + j * 8) for j in range(count))]
