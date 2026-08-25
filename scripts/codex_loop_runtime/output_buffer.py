from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BufferSnapshot:
    retained: bytes
    omitted_bytes: int
    total_bytes: int


class HeadTailBuffer:
    """Behavioral port of Codex unified-exec HeadTailBuffer."""

    def __init__(self, max_bytes: int = 1024 * 1024):
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        self.max_bytes = int(max_bytes)
        self._head_budget = self.max_bytes // 2
        self._tail_budget = self.max_bytes - self._head_budget
        self._head = bytearray()
        self._tail = bytearray()
        self._omitted = 0

    @property
    def omitted_bytes(self) -> int:
        return self._omitted

    @property
    def total_bytes(self) -> int:
        return self.retained_bytes() + self._omitted

    def retained_bytes(self) -> int:
        return len(self._head) + len(self._tail)

    def _fill_head(self, data: bytes) -> bytes:
        remaining = max(0, self._head_budget - len(self._head))
        take = min(remaining, len(data))
        self._head.extend(data[:take])
        return data[take:]

    def _push_tail(self, data: bytes) -> None:
        if not data:
            return
        remaining_tail = max(0, self._tail_budget - len(self._tail))
        excess = max(0, len(data) - remaining_tail)
        self._omitted += excess
        if excess <= len(self._tail):
            if excess:
                del self._tail[:excess]
            incoming = data
        else:
            skip = excess - len(self._tail)
            self._tail.clear()
            incoming = data[skip:]
        self._tail.extend(incoming)

    def push_chunk(self, chunk: bytes | bytearray | memoryview) -> None:
        data = self._fill_head(bytes(chunk))
        self._push_tail(data)

    def push_buffer(self, other: "HeadTailBuffer") -> None:
        """Append a later summarized buffer using the same composition semantics as upstream."""
        if self.max_bytes != other.max_bytes:
            raise ValueError("buffers must use the same max_bytes budget")
        self._omitted += other._omitted
        source_head = bytes(other._head)
        source_tail = bytearray(other._tail)

        if not self._head:
            self._head = bytearray(source_head)
            overflow = b""
        else:
            overflow = self._fill_head(source_head)

        if len(source_tail) == self._tail_budget:
            self._omitted += len(self._tail) + len(overflow)
            self._tail = source_tail
        else:
            self._push_tail(overflow)
            if not self._tail:
                self._tail = source_tail
            else:
                self._push_tail(bytes(source_tail))

    def to_bytes(self) -> bytes:
        return bytes(self._head) + bytes(self._tail)

    def to_bytes_with_omission_marker(self) -> bytes:
        if self._omitted == 0:
            return self.to_bytes()
        marker = f"... {self._omitted} bytes omitted ...".encode("ascii")
        return bytes(self._head) + b"\n" + marker + b"\n" + bytes(self._tail)

    def snapshot(self) -> BufferSnapshot:
        return BufferSnapshot(self.to_bytes(), self._omitted, self.total_bytes)
