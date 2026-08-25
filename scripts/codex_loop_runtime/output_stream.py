from __future__ import annotations

from collections.abc import Iterable, Iterator

DEFAULT_FRAME_BYTES = 8192
DEFAULT_MAX_FRAMES = 10_000


def _utf8_boundary(data: bytes) -> int:
    """Behavioral port of Codex unified-exec utf8_boundary().

    Inspect only the last three bytes where an incomplete scalar can exist. Malformed bytes are
    treated as raw/complete; only a genuinely incomplete trailing UTF-8 scalar is retained.
    """
    boundary = max(0, len(data) - 3)
    while boundary < len(data):
        segment = data[boundary:]
        try:
            segment.decode("utf-8")
            return len(data)
        except UnicodeDecodeError as exc:
            boundary += exc.start
            if exc.reason == "unexpected end of data" and exc.end == len(segment):
                return boundary
            invalid_len = max(1, exc.end - exc.start)
            boundary += invalid_len
    return len(data)


def _complete_utf8_prefix(data: bytes) -> int:
    return _utf8_boundary(data)


def _safe_utf8_cut(data: bytes, limit: int) -> int:
    return _utf8_boundary(data[: min(len(data), limit)])


def frame_output(chunks: Iterable[bytes], max_frame_bytes: int = DEFAULT_FRAME_BYTES) -> Iterator[bytes]:
    """Frame a complete byte stream. Use OutputDeltaFramer for incremental process output."""
    framer = OutputDeltaFramer(max_frame_bytes=max_frame_bytes)
    for chunk in chunks:
        framer.push(chunk)
        frames, _ = framer.drain(final=False)
        yield from frames
    frames, _ = framer.drain(final=True)
    yield from frames


class OutputDeltaFramer:
    """Stateful Codex-style model-visible output framer.

    It preserves an incomplete UTF-8 suffix across polls, emits frames no larger than the
    configured byte cap, and bounds unpolled data. Full retained transcript/output is managed
    separately by the process layer, matching Codex's separation of streaming deltas from the
    aggregate transcript.
    """

    def __init__(
        self,
        *,
        max_frame_bytes: int = DEFAULT_FRAME_BYTES,
        max_pending_bytes: int = 512 * 1024,
        max_frames_total: int = DEFAULT_MAX_FRAMES,
    ) -> None:
        if max_frame_bytes < 4:
            raise ValueError("max_frame_bytes must be at least 4")
        if max_pending_bytes < max_frame_bytes:
            raise ValueError("max_pending_bytes must be at least max_frame_bytes")
        if max_frames_total <= 0:
            raise ValueError("max_frames_total must be positive")
        self.max_frame_bytes = int(max_frame_bytes)
        self.max_pending_bytes = int(max_pending_bytes)
        self.max_frames_total = int(max_frames_total)
        self._pending = bytearray()
        self._omitted_since_drain = 0
        self._remaining_frames = int(max_frames_total)

    @property
    def pending_bytes(self) -> int:
        return len(self._pending)

    def push(self, data: bytes) -> None:
        if not data:
            return
        available = self.max_pending_bytes - len(self._pending)
        if available <= 0:
            self._omitted_since_drain += len(data)
            return
        if len(data) <= available:
            self._pending.extend(data)
            return

        # Preserve the earliest not-yet-delivered delta bytes, matching Codex's eager-event
        # ordering. The local poll-driven adapter adds a bounded pending queue, so later bytes
        # are omitted rather than evicting earlier model-visible output.
        self._pending.extend(data[:available])
        omitted = len(data) - available
        complete = _complete_utf8_prefix(bytes(self._pending))
        if complete < len(self._pending):
            omitted += len(self._pending) - complete
            del self._pending[complete:]
        self._omitted_since_drain += omitted

    def drain(self, *, final: bool = False) -> tuple[list[bytes], int]:
        complete = len(self._pending) if final else _complete_utf8_prefix(bytes(self._pending))
        frames: list[bytes] = []
        cursor = 0
        while cursor < complete and self._remaining_frames > 0:
            remaining = bytes(self._pending[cursor:complete])
            if final and len(remaining) <= self.max_frame_bytes:
                # Upstream finish() emits the final incomplete suffix raw; the model-facing
                # string boundary may decode it lossily, but no byte is silently discarded.
                cut = len(remaining)
            else:
                cut = _safe_utf8_cut(remaining, self.max_frame_bytes)
            if cut <= 0:
                break
            frames.append(remaining[:cut])
            cursor += cut
            self._remaining_frames -= 1
        if cursor:
            del self._pending[:cursor]
        # Codex stops constructing delta events once the per-process quota is exhausted;
        # aggregate output/transcript collection continues independently. Do the same here.
        if self._remaining_frames <= 0 and self._pending:
            self._omitted_since_drain += len(self._pending)
            self._pending.clear()
        omitted = self._omitted_since_drain
        self._omitted_since_drain = 0
        return frames, omitted
