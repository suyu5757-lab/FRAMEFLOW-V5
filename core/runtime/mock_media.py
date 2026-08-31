"""Deterministic, dependency-free media bytes for the local T48 mock only."""

from __future__ import annotations

import struct


def _chunk(name: bytes, payload: bytes) -> bytes:
    value = name + struct.pack("<I", len(payload)) + payload
    return value + (b"\0" if len(payload) % 2 else b"")


def _list(kind: bytes, payload: bytes) -> bytes:
    return _chunk(b"LIST", kind + payload)


def tiny_uncompressed_avi() -> bytes:
    """Return a valid one-frame, one-second 1x1 BGR AVI.

    The sample is deliberately raw/uncompressed so T48 can decode its frame
    without installing a codec, ffmpeg, a model, or a network dependency.
    """

    avih = struct.pack("<14I", 1_000_000, 4, 0, 0x10, 1, 0, 1, 4, 1, 1, 0, 0, 0, 0)
    strh = b"vids" + b"DIB " + struct.pack("<IHHIIIIIIIIhhhh", 0, 0, 0, 0, 1, 1, 0, 1, 4, 0xFFFFFFFF, 0, 0, 0, 1, 1)
    strf = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0)
    hdrl = _list(b"hdrl", _chunk(b"avih", avih) + _list(b"strl", _chunk(b"strh", strh) + _chunk(b"strf", strf)))
    frame = b"\x00\x00\xff\x00"  # one opaque red BGR pixel plus row padding
    movi = _list(b"movi", _chunk(b"00db", frame))
    idx1 = _chunk(b"idx1", b"00db" + struct.pack("<III", 0x10, 4, len(frame)))
    body = b"AVI " + hdrl + movi + idx1
    return b"RIFF" + struct.pack("<I", len(body)) + body


__all__ = ["tiny_uncompressed_avi"]
