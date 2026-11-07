from __future__ import annotations

import struct

from .types import ParseError


class BinaryReader:
    """Read little-endian values, and raise ParseError instead of reading past the end."""

    def __init__(self, buffer: bytes | bytearray | memoryview, base_offset: int = 0):
        self._buffer = memoryview(buffer)
        self._cursor = 0
        self._base_offset = base_offset

    @property
    def offset(self) -> int:
        return self._cursor

    @property
    def remaining(self) -> int:
        return len(self._buffer) - self._cursor

    def read_bytes(self, length: int) -> bytes:
        self._require(length)
        start = self._cursor
        self._cursor += length
        return bytes(self._buffer[start:self._cursor])

    def read_string(self) -> str:
        start = self._base_offset + self._cursor
        length = self.read_u16le()
        data = self.read_bytes(length * 2)
        try:
            return data.decode("utf-16le", errors="strict")
        except UnicodeDecodeError as error:
            raise ParseError(f"Invalid string: {error}", start) from error

    def read_u8(self) -> int:
        return self.read_bytes(1)[0]

    def read_u16le(self) -> int:
        return struct.unpack("<H", self.read_bytes(2))[0]

    def read_u32le(self) -> int:
        return struct.unpack("<I", self.read_bytes(4))[0]

    def seek(self, offset: int) -> None:
        self._cursor = offset

    def _require(self, length: int) -> None:
        if length > self.remaining:
            raise ParseError(f"Unexpected end of data: need {length} bytes, {self.remaining} remain",
                             self._base_offset + self._cursor)
