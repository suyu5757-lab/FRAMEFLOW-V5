"""T48's intentionally narrow, dependency-free video smoke check."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping


@dataclass(frozen=True, slots=True)
class SmokeResult:
    passed: bool
    artifact_id: str
    path: str
    exists: bool
    decodable: bool
    duration: float | None
    code: str

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "artifact_id": self.artifact_id, "path": self.path, "exists": self.exists, "decodable": self.decodable, "duration": self.duration, "code": self.code}


def _chunks(raw: bytes, start: int, end: int) -> Iterator[tuple[bytes, bytes]]:
    index = start
    while index + 8 <= end:
        name, size = raw[index:index + 4], struct.unpack_from("<I", raw, index + 4)[0]
        data_start, data_end = index + 8, index + 8 + size
        if data_end > end:
            return
        payload = raw[data_start:data_end]
        if name == b"LIST" and len(payload) >= 4:
            yield from _chunks(payload, 4, len(payload))
        else:
            yield name, payload
        index = data_end + (size % 2)


def _decode_uncompressed_avi(raw: bytes) -> float | None:
    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"AVI ":
        return None
    avih = strf = frame = None
    for name, payload in _chunks(raw, 12, len(raw)):
        if name == b"avih" and len(payload) >= 40:
            avih = payload
        elif name == b"strf" and len(payload) >= 40:
            strf = payload
        elif name.endswith(b"db") and frame is None:
            frame = payload
    if avih is None or strf is None or frame is None:
        return None
    microseconds, _max_bytes, _padding, _flags, frames = struct.unpack_from("<IIIII", avih)
    header_size, width, height, planes, bits, compression, image_size = struct.unpack_from("<IiiHHII", strf)
    if header_size != 40 or width <= 0 or height == 0 or planes != 1 or bits != 24 or compression != 0 or frames <= 0 or microseconds <= 0:
        return None
    row_bytes = ((width * 3 + 3) // 4) * 4
    if image_size < row_bytes * abs(height) or len(frame) < row_bytes * abs(height):
        return None
    # Reading BGR bytes is the decode boundary: the fixture is an uncompressed
    # AVI, so successful frame extraction proves it is not merely a renamed file.
    _blue, _green, _red = frame[:3]
    return (microseconds * frames) / 1_000_000


def smoke_video(artifact: Mapping[str, Any]) -> SmokeResult:
    artifact_id = str(artifact.get("id") or artifact.get("artifact_id") or "")
    path = Path(str(artifact.get("path") or "")).expanduser()
    if not artifact_id or not path.is_file():
        return SmokeResult(False, artifact_id, str(path), False, False, None, "MISSING_MEDIA")
    try:
        duration = _decode_uncompressed_avi(path.read_bytes())
    except OSError:
        duration = None
    if duration is None:
        return SmokeResult(False, artifact_id, str(path), True, False, None, "UNDECODABLE_MEDIA")
    return SmokeResult(True, artifact_id, str(path), True, True, duration, "PASS")


__all__ = ["SmokeResult", "smoke_video"]
