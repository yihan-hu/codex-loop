from __future__ import annotations

import base64
import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TRANSPORT = "GUARDED_SINGLE_SHOT_RELAY"
FALLBACK_TRANSPORT = "VERIFIED_CHUNK_RELAY"
DEFAULT_GUARD_BYTES = 256
DEFAULT_LINE_WIDTH = 76
ASCII_WHITESPACE = frozenset(" \t\r\n")
_TRANSFER_BEGIN_RE = re.compile(r"<<<CODEX_LOOP_TRANSFER_BEGIN:v1:([0-9a-f]{32})>>>")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRANSFER_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class RelayError(RuntimeError):
    def __init__(self, failure_class: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.details = details

@dataclass(frozen=True)
class DecodedRelay:
    data: bytes
    telemetry: dict[str, Any]


def _validate_transfer_id(transfer_id: str) -> str:
    if not _TRANSFER_ID_RE.fullmatch(transfer_id):
        raise ValueError("transfer_id must be 32 lowercase hex characters")
    return transfer_id


def _guard(label: str, transfer_id: str, size: int) -> str:
    if size < 0 or size > 65536:
        raise ValueError("guard_bytes must be between 0 and 65536")
    chunks: list[str] = []
    counter = 0
    while sum(map(len, chunks)) < size:
        digest = hashlib.sha256(f"{label}:{transfer_id}:{counter}".encode("ascii")).hexdigest()
        chunks.append(f"{label[0]}{counter:04x}{digest}")
        counter += 1
    return "".join(chunks)[:size]


def _wrap_base64(encoded: str, line_width: int) -> str:
    if line_width < 4 or line_width > 4096 or line_width % 4:
        raise ValueError("line_width must be a multiple of 4 between 4 and 4096")
    return "\n".join(encoded[i:i + line_width] for i in range(0, len(encoded), line_width))


def build_guarded_envelope(
    data: bytes,
    *,
    transfer_id: str | None = None,
    guard_bytes: int = DEFAULT_GUARD_BYTES,
    line_width: int = DEFAULT_LINE_WIDTH,
) -> tuple[str, dict[str, Any]]:
    transfer_id = _validate_transfer_id(transfer_id or uuid.uuid4().hex)
    raw_sha256 = hashlib.sha256(data).hexdigest()
    encoded = base64.b64encode(data).decode("ascii")
    prefix_guard = _guard("PREFIX", transfer_id, guard_bytes)
    suffix_guard = _guard("SUFFIX", transfer_id, guard_bytes)
    lines = [
        f"<<<CODEX_LOOP_TRANSFER_BEGIN:v1:{transfer_id}>>>",
        f"RAW_SIZE={len(data)}",
        f"RAW_SHA256={raw_sha256}",
        "ENCODING=base64",
        f"GUARD_BYTES={guard_bytes}",
        f"PREFIX_GUARD={prefix_guard}",
        f"<<<PAYLOAD_BEGIN:{transfer_id}>>>",
        _wrap_base64(encoded, line_width),
        f"<<<PAYLOAD_END:{transfer_id}>>>",
        f"SUFFIX_GUARD={suffix_guard}",
        f"<<<CODEX_LOOP_TRANSFER_END:{transfer_id}>>>",
    ]
    envelope = "\n".join(lines) + "\n"
    return envelope, {
        "status": "FRAMED",
        "transport": TRANSPORT,
        "transfer_id": transfer_id,
        "raw_size": len(data),
        "raw_sha256": raw_sha256,
        "guard_bytes": guard_bytes,
        "line_width": line_width,
        "envelope_bytes": len(envelope.encode("utf-8")),
    }


def _parse_metadata(segment: str) -> tuple[int, str, int, str | None]:
    values: dict[str, str] = {}
    prefix_guard: str | None = None
    for raw_line in segment.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in values:
            raise RelayError("METADATA_INVALID", f"duplicate metadata key: {key}")
        values[key] = value
        if key == "PREFIX_GUARD":
            prefix_guard = value
    required = {"RAW_SIZE", "RAW_SHA256", "ENCODING", "GUARD_BYTES"}
    missing = sorted(required - values.keys())
    if missing:
        raise RelayError("METADATA_INVALID", f"missing metadata keys: {', '.join(missing)}")
    if values["ENCODING"] != "base64":
        raise RelayError("METADATA_INVALID", "unsupported relay encoding")
    try:
        raw_size = int(values["RAW_SIZE"])
        guard_bytes = int(values["GUARD_BYTES"])
    except ValueError as exc:
        raise RelayError("METADATA_INVALID", "size metadata must be integers") from exc
    if raw_size < 0 or guard_bytes < 0 or guard_bytes > 65536:
        raise RelayError("METADATA_INVALID", "size metadata is outside allowed bounds")
    raw_sha256 = values["RAW_SHA256"]
    if not _SHA256_RE.fullmatch(raw_sha256):
        raise RelayError("METADATA_INVALID", "RAW_SHA256 must be lowercase hex SHA-256")
    return raw_size, raw_sha256, guard_bytes, prefix_guard


def decode_guarded_envelope(text: str) -> DecodedRelay:
    begin_matches = list(_TRANSFER_BEGIN_RE.finditer(text))
    if not begin_matches:
        raise RelayError("MARKER_MISSING", "transfer begin marker is missing")
    if len(begin_matches) != 1:
        raise RelayError("MARKER_DUPLICATED", "transfer begin marker is not unique", count=len(begin_matches))
    begin_match = begin_matches[0]
    transfer_id = begin_match.group(1)
    payload_begin = f"<<<PAYLOAD_BEGIN:{transfer_id}>>>"
    payload_end = f"<<<PAYLOAD_END:{transfer_id}>>>"
    transfer_end = f"<<<CODEX_LOOP_TRANSFER_END:{transfer_id}>>>"
    begin_count = text.count(payload_begin)
    end_count = text.count(payload_end)
    if begin_count == 0:
        raise RelayError("TRUNCATED_BEFORE_PAYLOAD", "payload begin marker is missing", transfer_id=transfer_id)
    if end_count == 0:
        raise RelayError("TRUNCATED_AFTER_PAYLOAD", "payload end marker is missing", transfer_id=transfer_id)
    if begin_count != 1 or end_count != 1:
        raise RelayError(
            "MARKER_DUPLICATED",
            "payload markers are not unique",
            transfer_id=transfer_id,
            payload_begin_count=begin_count,
            payload_end_count=end_count,
        )
    payload_begin_at = text.index(payload_begin)
    payload_end_at = text.index(payload_end)
    if not (begin_match.end() <= payload_begin_at < payload_end_at):
        raise RelayError("MARKER_ORDER_INVALID", "relay markers are out of order", transfer_id=transfer_id)
    metadata_segment = text[begin_match.end():payload_begin_at]
    expected_size, expected_sha256, guard_bytes, prefix_guard = _parse_metadata(metadata_segment)
    payload_start = payload_begin_at + len(payload_begin)
    payload_text = text[payload_start:payload_end_at]
    normalized = "".join(ch for ch in payload_text if ch not in ASCII_WHITESPACE)
    try:
        encoded = normalized.encode("ascii")
        data = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise RelayError(
            "BASE64_INVALID",
            "payload is not strict Base64 after ASCII-whitespace normalization",
            transfer_id=transfer_id,
            normalized_payload_length=len(normalized),
        ) from exc
    actual_size = len(data)
    actual_sha256 = hashlib.sha256(data).hexdigest()
    suffix_segment = text[payload_end_at + len(payload_end):]
    expected_prefix = _guard("PREFIX", transfer_id, guard_bytes)
    expected_suffix = _guard("SUFFIX", transfer_id, guard_bytes)
    telemetry = {
        "status": "DECODED",
        "transport": TRANSPORT,
        "transfer_id": transfer_id,
        "expected_size": expected_size,
        "decoded_size": actual_size,
        "expected_sha256": expected_sha256,
        "actual_sha256": actual_sha256,
        "normalized_payload_length": len(normalized),
        "prefix_guard_match": prefix_guard == expected_prefix,
        "suffix_guard_match": f"SUFFIX_GUARD={expected_suffix}" in suffix_segment,
        "transfer_end_found": text.count(transfer_end) == 1,
        "outer_prefix_chars": begin_match.start(),
    }
    if actual_size != expected_size:
        raise RelayError(
            "SIZE_MISMATCH",
            "decoded payload size does not match RAW_SIZE",
            **telemetry,
        )
    if actual_sha256 != expected_sha256:
        raise RelayError(
            "SHA_MISMATCH",
            "decoded payload SHA-256 does not match RAW_SHA256",
            **telemetry,
        )
    telemetry["status"] = "VERIFIED"
    return DecodedRelay(data=data, telemetry=telemetry)


def failure_result(error: RelayError) -> dict[str, Any]:
    result: dict[str, Any] = dict(error.details)
    result.update(
        {
            "status": "FAILED",
            "transport": TRANSPORT,
            "failure_class": error.failure_class,
            "message": str(error),
            "fallback": FALLBACK_TRANSPORT,
        }
    )
    return result


def _atomic_write(path: Path, data: bytes, *, transfer_id: str, overwrite: bool) -> None:
    path = path.resolve()
    if path.exists() and not overwrite:
        raise RelayError("OUTPUT_EXISTS", "destination already exists", destination=str(path), transfer_id=transfer_id)
    if not path.parent.is_dir():
        raise RelayError("OUTPUT_PARENT_MISSING", "destination parent does not exist", destination=str(path))
    partial = path.with_name(f".{path.name}.partial.{transfer_id}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd: int | None = None
    try:
        fd = os.open(partial, flags, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
        if hasattr(os, "O_DIRECTORY"):
            try:
                dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                # File bytes were already fsynced and atomically published. Some
                # filesystems reject directory fsync; do not report a false
                # transfer failure after the destination has been replaced.
                pass
    except FileExistsError as exc:
        raise RelayError("PARTIAL_EXISTS", "relay partial file already exists", partial=str(partial)) from exc
    finally:
        if fd is not None:
            os.close(fd)
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass


def frame_file(
    input_path: Path,
    envelope_path: Path,
    *,
    transfer_id: str | None = None,
    guard_bytes: int = DEFAULT_GUARD_BYTES,
    line_width: int = DEFAULT_LINE_WIDTH,
    overwrite: bool = False,
) -> dict[str, Any]:
    data = input_path.read_bytes()
    envelope, result = build_guarded_envelope(
        data,
        transfer_id=transfer_id,
        guard_bytes=guard_bytes,
        line_width=line_width,
    )
    _atomic_write(
        envelope_path,
        envelope.encode("utf-8"),
        transfer_id=result["transfer_id"],
        overwrite=overwrite,
    )
    result["input"] = str(input_path.resolve())
    result["envelope"] = str(envelope_path.resolve())
    return result


def receive_file(
    envelope_path: Path,
    output_path: Path,
    *,
    overwrite: bool = False,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        text = envelope_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RelayError("ENVELOPE_UTF8_INVALID", "relay envelope is not UTF-8 text") from exc
    decoded = decode_guarded_envelope(text)
    if expected_size is not None and decoded.telemetry["expected_size"] != expected_size:
        raise RelayError(
            "MANIFEST_MISMATCH",
            "envelope RAW_SIZE does not match the external source manifest",
            transfer_id=decoded.telemetry["transfer_id"],
            external_expected_size=expected_size,
            envelope_expected_size=decoded.telemetry["expected_size"],
        )
    if expected_sha256 is not None:
        if not _SHA256_RE.fullmatch(expected_sha256):
            raise ValueError("expected_sha256 must be lowercase hex SHA-256")
        if decoded.telemetry["expected_sha256"] != expected_sha256:
            raise RelayError(
                "MANIFEST_MISMATCH",
                "envelope RAW_SHA256 does not match the external source manifest",
                transfer_id=decoded.telemetry["transfer_id"],
                external_expected_sha256=expected_sha256,
                envelope_expected_sha256=decoded.telemetry["expected_sha256"],
            )
    _atomic_write(
        output_path,
        decoded.data,
        transfer_id=decoded.telemetry["transfer_id"],
        overwrite=overwrite,
    )
    result = dict(decoded.telemetry)
    result.update(
        {
            "status": "COMPLETE",
            "envelope": str(envelope_path.resolve()),
            "destination": str(output_path.resolve()),
            "fallback": None,
        }
    )
    return result
