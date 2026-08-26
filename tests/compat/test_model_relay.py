import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from codex_loop_runtime.model_relay import (
    FALLBACK_TRANSPORT,
    RelayError,
    build_guarded_envelope,
    decode_guarded_envelope,
    receive_file,
)

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"
TRANSFER_ID = "0123456789abcdef0123456789abcdef"


def payload() -> bytes:
    return bytes((i * 73 + 19) % 256 for i in range(8193))


def replace_payload_char(envelope: str) -> str:
    begin = f"<<<PAYLOAD_BEGIN:{TRANSFER_ID}>>>"
    end = f"<<<PAYLOAD_END:{TRANSFER_ID}>>>"
    start = envelope.index(begin) + len(begin)
    stop = envelope.index(end)
    segment = envelope[start:stop]
    chars = list(segment)
    for index, char in enumerate(chars):
        if char in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/":
            chars[index] = "A" if char != "A" else "B"
            break
    return envelope[:start] + "".join(chars) + envelope[stop:]


class ModelRelayTests(unittest.TestCase):
    def test_round_trip_is_byte_exact(self):
        data = payload()
        envelope, framed = build_guarded_envelope(data, transfer_id=TRANSFER_ID)
        decoded = decode_guarded_envelope(envelope)
        self.assertEqual(decoded.data, data)
        self.assertEqual(decoded.telemetry["actual_sha256"], framed["raw_sha256"])
        self.assertEqual(decoded.telemetry["status"], "VERIFIED")

    def test_outer_edge_contamination_and_payload_whitespace_are_tolerated(self):
        data = payload()
        envelope, _ = build_guarded_envelope(data, transfer_id=TRANSFER_ID, line_width=64)
        begin = f"<<<PAYLOAD_BEGIN:{TRANSFER_ID}>>>"
        end = f"<<<PAYLOAD_END:{TRANSFER_ID}>>>"
        start = envelope.index(begin) + len(begin)
        stop = envelope.index(end)
        interior = envelope[start:stop].replace("\n", " \r\n\t")
        contaminated = "Here is the file:\n```text\n" + envelope[:start] + interior + envelope[stop:] + "```\nDone.\n"
        self.assertEqual(decode_guarded_envelope(contaminated).data, data)

    def test_sacrificial_guards_may_be_corrupted_without_changing_payload_success(self):
        data = payload()
        envelope, _ = build_guarded_envelope(data, transfer_id=TRANSFER_ID)
        envelope = envelope.replace("PREFIX_GUARD=P", "PREFIX_GUARD=X", 1)
        envelope = envelope.replace("SUFFIX_GUARD=S", "SUFFIX_GUARD=Y", 1)
        decoded = decode_guarded_envelope(envelope)
        self.assertEqual(decoded.data, data)
        self.assertFalse(decoded.telemetry["prefix_guard_match"])
        self.assertFalse(decoded.telemetry["suffix_guard_match"])

    def test_valid_base64_interior_substitution_fails_full_hash(self):
        envelope, _ = build_guarded_envelope(payload(), transfer_id=TRANSFER_ID)
        corrupted = replace_payload_char(envelope)
        with self.assertRaises(RelayError) as caught:
            decode_guarded_envelope(corrupted)
        self.assertEqual(caught.exception.failure_class, "SHA_MISMATCH")

    def test_non_whitespace_invalid_payload_character_fails_strict_base64(self):
        envelope, _ = build_guarded_envelope(payload(), transfer_id=TRANSFER_ID)
        begin = f"<<<PAYLOAD_BEGIN:{TRANSFER_ID}>>>"
        start = envelope.index(begin) + len(begin)
        mutated = envelope[:start] + "!" + envelope[start:]
        with self.assertRaises(RelayError) as caught:
            decode_guarded_envelope(mutated)
        self.assertEqual(caught.exception.failure_class, "BASE64_INVALID")

    def test_missing_end_marker_is_classified_as_payload_truncation(self):
        envelope, _ = build_guarded_envelope(payload(), transfer_id=TRANSFER_ID)
        marker = f"<<<PAYLOAD_END:{TRANSFER_ID}>>>"
        truncated = envelope[: envelope.index(marker)]
        with self.assertRaises(RelayError) as caught:
            decode_guarded_envelope(truncated)
        self.assertEqual(caught.exception.failure_class, "TRUNCATED_AFTER_PAYLOAD")

    def test_duplicate_payload_marker_fails_closed(self):
        envelope, _ = build_guarded_envelope(payload(), transfer_id=TRANSFER_ID)
        marker = f"<<<PAYLOAD_BEGIN:{TRANSFER_ID}>>>"
        duplicate = marker + "\n" + envelope
        with self.assertRaises(RelayError) as caught:
            decode_guarded_envelope(duplicate)
        self.assertEqual(caught.exception.failure_class, "MARKER_DUPLICATED")

    def test_size_metadata_mismatch_fails_before_publish(self):
        data = payload()
        envelope, _ = build_guarded_envelope(data, transfer_id=TRANSFER_ID)
        envelope = envelope.replace(f"RAW_SIZE={len(data)}", f"RAW_SIZE={len(data) + 1}", 1)
        with self.assertRaises(RelayError) as caught:
            decode_guarded_envelope(envelope)
        self.assertEqual(caught.exception.failure_class, "SIZE_MISMATCH")

    def test_receive_writes_only_verified_destination(self):
        data = payload()
        envelope, _ = build_guarded_envelope(data, transfer_id=TRANSFER_ID)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            envelope_path = root / "relay.txt"
            output_path = root / "result.bin"
            envelope_path.write_text(envelope, encoding="utf-8")
            result = receive_file(envelope_path, output_path)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(output_path.read_bytes(), data)
            self.assertEqual(list(root.glob("*.partial.*")), [])

    def test_receive_does_not_publish_corrupt_destination(self):
        envelope, _ = build_guarded_envelope(payload(), transfer_id=TRANSFER_ID)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            envelope_path = root / "relay.txt"
            output_path = root / "result.bin"
            envelope_path.write_text(replace_payload_char(envelope), encoding="utf-8")
            with self.assertRaises(RelayError) as caught:
                receive_file(envelope_path, output_path)
            self.assertEqual(caught.exception.failure_class, "SHA_MISMATCH")
            self.assertFalse(output_path.exists())

    def test_external_manifest_mismatch_fails_before_publish(self):
        data = payload()
        envelope, framed = build_guarded_envelope(data, transfer_id=TRANSFER_ID)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            envelope_path = root / "relay.txt"
            output_path = root / "result.bin"
            envelope_path.write_text(envelope, encoding="utf-8")
            with self.assertRaises(RelayError) as caught:
                receive_file(
                    envelope_path,
                    output_path,
                    expected_size=framed["raw_size"],
                    expected_sha256="0" * 64,
                )
            self.assertEqual(caught.exception.failure_class, "MANIFEST_MISMATCH")
            self.assertFalse(output_path.exists())

    def test_cli_round_trip_and_failure_fallback_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.bin"
            envelope = root / "relay.txt"
            output = root / "output.bin"
            source.write_bytes(payload())
            frame = subprocess.run(
                [sys.executable, str(CLI), "relay-frame", "--input", str(source), "--output", str(envelope), "--transfer-id", TRANSFER_ID],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            framed = json.loads(frame.stdout)
            self.assertEqual(framed["data"]["status"], "FRAMED")
            receive = subprocess.run(
                [
                    sys.executable, str(CLI), "relay-receive",
                    "--envelope", str(envelope), "--output", str(output),
                    "--expected-size", str(framed["data"]["raw_size"]),
                    "--expected-sha256", framed["data"]["raw_sha256"],
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            received = json.loads(receive.stdout)
            self.assertEqual(received["data"]["status"], "COMPLETE")
            self.assertEqual(output.read_bytes(), source.read_bytes())

            bad = root / "bad.txt"
            bad_output = root / "bad.bin"
            bad.write_text(replace_payload_char(envelope.read_text()), encoding="utf-8")
            failed = subprocess.run(
                [sys.executable, str(CLI), "relay-receive", "--envelope", str(bad), "--output", str(bad_output)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(failed.returncode, 2)
            result = json.loads(failed.stdout)["data"]
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["failure_class"], "SHA_MISMATCH")
            self.assertEqual(result["fallback"], FALLBACK_TRANSPORT)
            self.assertFalse(bad_output.exists())


if __name__ == "__main__":
    unittest.main()
