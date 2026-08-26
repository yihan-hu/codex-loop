# Verified model relay

Use this reference only after the user explicitly authorizes a model-carried file transfer as an alternate data plane. It is a slow fallback for a file that otherwise cannot cross the ChatGPT/PiWork boundary. It is not a binary bridge, is never the repository publish transport, and must never be enabled silently.

## Goal

`GUARDED_SINGLE_SHOT_RELAY` optimizes for one-shot success when text boundaries add harmless material at the beginning or end of a relay, while preserving an exact byte-integrity gate. The transport does not assume the model is byte-perfect. It separates sacrificial framing from the Base64 payload and accepts success only when decoded size and full SHA-256 match the source manifest.

If the one-shot relay fails, surface the failure class and fall back to the separately verified chunk protocol (`VERIFIED_CHUNK_RELAY`) only when that fallback is also within the user's authorization.

## Deterministic commands

Frame a source file without putting file bytes in runtime state:

```bash
python scripts/codex_loop.py relay-frame \
  --cwd AUTHORIZED_ROOT \
  --input SOURCE --output ENVELOPE.txt \
  --transfer-id 0123456789abcdef0123456789abcdef
```

On the receiving host, verify and publish the destination atomically:

```bash
python scripts/codex_loop.py relay-receive \
  --cwd AUTHORIZED_ROOT \
  --envelope ENVELOPE.txt --output DESTINATION \
  --expected-size SOURCE_SIZE --expected-sha256 SOURCE_SHA256
```

`relay-frame` emits only metadata JSON. The envelope file contains the carrier payload. Preserve the returned source size/SHA outside the carrier when possible and pass them back with `--expected-size` / `--expected-sha256`; this catches a carrier whose payload and embedded manifest were both changed consistently. `relay-receive` returns exit code `0` only for a verified destination. Integrity failures return exit code `2` with a structured failure class and `fallback=VERIFIED_CHUNK_RELAY`; they do not create the destination.

## Envelope contract

Version 1 uses unique transfer-specific markers:

```text
<<<CODEX_LOOP_TRANSFER_BEGIN:v1:<transfer_id>>>
RAW_SIZE=<decimal bytes>
RAW_SHA256=<64 lowercase hex>
ENCODING=base64
GUARD_BYTES=<decimal chars>
PREFIX_GUARD=<sacrificial ASCII guard>
<<<PAYLOAD_BEGIN:<transfer_id>>>
<Base64 payload, optionally line wrapped>
<<<PAYLOAD_END:<transfer_id>>>
SUFFIX_GUARD=<sacrificial ASCII guard>
<<<CODEX_LOOP_TRANSFER_END:<transfer_id>>>
```

The receiver derives the exact payload interval only from the unique `PAYLOAD_BEGIN` and `PAYLOAD_END` markers for the transfer ID. Text outside that interval is not file content. Prefix/suffix guard damage or outer prose/Markdown may be tolerated when the payload and manifest remain intact.

Inside the payload interval, normalization is deliberately narrow: remove only ASCII space, tab, CR, and LF before strict Base64 decode. Never case-fold, Unicode-normalize, delete punctuation, guess missing padding, filter arbitrary non-Base64 characters, or heuristically repair decoded bytes.

## Integrity and publication

A relay is successful only when all of these are true:

1. Transfer and payload markers are unambiguous and ordered.
2. Manifest metadata is syntactically valid.
3. Payload is strict Base64 after ASCII-whitespace normalization.
4. Decoded byte count equals `RAW_SIZE`.
5. Decoded SHA-256 equals `RAW_SHA256`.
6. The verified bytes are fsynced to a sibling partial file and atomically renamed to the destination.

The destination is never published before the size/hash checks. An existing destination is not overwritten unless the caller explicitly passes `--overwrite`. A stale deterministic partial path fails closed instead of being appended to or silently reused.

## Failure classes

Expected integrity failures include:

- `MARKER_MISSING`
- `MARKER_DUPLICATED`
- `MARKER_ORDER_INVALID`
- `TRUNCATED_BEFORE_PAYLOAD`
- `TRUNCATED_AFTER_PAYLOAD`
- `METADATA_INVALID`
- `BASE64_INVALID`
- `SIZE_MISMATCH`
- `SHA_MISMATCH`
- `MANIFEST_MISMATCH`
- `OUTPUT_EXISTS`
- `PARTIAL_EXISTS`

These are transport observations, not permission to mutate or repair payload bytes. Do not convert an unknown interior corruption into success merely because it looks close to the expected file.

## Telemetry

Keep only bounded metadata needed to diagnose the transfer: transfer ID, expected/decoded size, expected/actual SHA-256, normalized payload length, marker outcome, guard-match booleans, and failure class. Do not persist the Base64 payload in Codex Loop durable task state.

The guard is diagnostic and sacrificial. A guard mismatch alone does not make a byte-exact payload fail. Conversely, intact guards never override a payload size/hash mismatch.

## Scope boundaries

This transport is allowed only for the specifically authorized file movement. It does not become standing permission for future model-carried transfers. It must not be used for normal Git publication, to replace native Git, to bypass a working binary bridge, or to promote a transferred artifact into a canonical source baseline without the normal workspace/lineage checks.

For every relay command, pass `--cwd` as the exact authorized filesystem root. The CLI resolves input/envelope/output paths and rejects any effective target outside that root, including a symlink escape. On Remote Desktop Commander use `--cwd /Users/yihanhu/PiWork` unless the user explicitly authorizes another narrow temporary root. The host remains responsible for actual tool dispatch, filesystem/network permissions, and carrying the envelope text between surfaces.
