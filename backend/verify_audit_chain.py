"""Offline verifier for CloudOps AI verifiable audit-chain exports."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from pathlib import Path
from typing import Any


def verify_export(payload: Any) -> tuple[bool, str]:
    """Return whether a decoded export verifies and a useful diagnostic."""
    if not isinstance(payload, dict):
        return False, "export must be a JSON object"
    if payload.get("format") != "cloudops-audit-chain-v1":
        return False, "unsupported audit export format"
    if payload.get("algorithm") != "sha256" or payload.get("genesis_hash") != "":
        return False, "unsupported audit chain parameters"
    events = payload.get("events")
    if not isinstance(events, list):
        return False, "events must be a list"

    previous_hash = ""
    previous_sequence = 0
    for index, row in enumerate(events):
        if not isinstance(row, dict):
            return False, f"event at index {index} must be an object"
        sequence = row.get("sequence")
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence != previous_sequence + 1
        ):
            return False, f"event sequence is invalid at index {index}"
        if row.get("previous_hash") != previous_hash:
            return False, f"previous hash mismatch at index {index}"
        event = row.get("event")
        if not isinstance(event, dict):
            return False, f"event payload is invalid at index {index}"
        stored_hash = row.get("event_hash")
        if (
            not isinstance(stored_hash, str)
            or len(stored_hash) != 64
            or any(character not in "0123456789abcdef" for character in stored_hash)
        ):
            return False, f"event hash is malformed at index {index}"
        try:
            canonical = json.dumps(
                event,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            return False, f"event payload is not canonical JSON at index {index}"
        expected_hash = hashlib.sha256(
            previous_hash.encode("ascii") + b"\0" + canonical
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, stored_hash):
            return False, f"event hash mismatch at index {index}"
        previous_hash = stored_hash
        previous_sequence = sequence

    final_hash = payload.get("final_hash")
    if final_hash != previous_hash:
        return False, "final hash does not match the verified chain"
    return True, f"valid audit chain: {len(events)} events; final hash {final_hash or '(empty)'}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="path to the downloaded JSON export")
    args = parser.parse_args(argv)
    try:
        with args.export.open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"cannot read audit export: {exc}", file=sys.stderr)
        return 1
    valid, message = verify_export(payload)
    print(message, file=sys.stdout if valid else sys.stderr)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
