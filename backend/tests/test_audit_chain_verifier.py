import copy
import hashlib
import json

from backend.verify_audit_chain import main, verify_export


def make_export(events):
    rows = []
    previous_hash = ""
    for sequence, event in enumerate(events, start=1):
        canonical = json.dumps(
            event, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        event_hash = hashlib.sha256(
            previous_hash.encode("ascii") + b"\0" + canonical
        ).hexdigest()
        rows.append({
            "sequence": sequence,
            "event": event,
            "previous_hash": previous_hash,
            "event_hash": event_hash,
        })
        previous_hash = event_hash
    return {
        "format": "cloudops-audit-chain-v1",
        "algorithm": "sha256",
        "genesis_hash": "",
        "events": rows,
        "final_hash": previous_hash,
    }


def test_verifier_accepts_valid_and_empty_exports():
    valid, message = verify_export(make_export([{"event": "approved", "actor": "λ"}]))
    assert valid
    assert "1 events" in message

    empty, message = verify_export(make_export([]))
    assert empty
    assert "0 events" in message


def test_verifier_rejects_tampering_and_chain_boundary_errors():
    original = make_export([{"event": "created"}, {"event": "approved"}])
    cases = []

    changed_event = copy.deepcopy(original)
    changed_event["events"][0]["event"]["event"] = "tampered"
    cases.append(changed_event)

    wrong_previous = copy.deepcopy(original)
    wrong_previous["events"][1]["previous_hash"] = "0" * 64
    cases.append(wrong_previous)

    wrong_sequence = copy.deepcopy(original)
    wrong_sequence["events"][1]["sequence"] = 3
    cases.append(wrong_sequence)

    wrong_final = copy.deepcopy(original)
    wrong_final["final_hash"] = "0" * 64
    cases.append(wrong_final)

    malformed_hash = copy.deepcopy(original)
    malformed_hash["events"][0]["event_hash"] = "z" * 64
    cases.append(malformed_hash)

    for payload in cases:
        valid, _ = verify_export(payload)
        assert not valid


def test_verifier_rejects_non_finite_event_values():
    payload = make_export([])
    payload["events"] = [{
        "sequence": 1,
        "event": {"number": float("nan")},
        "previous_hash": "",
        "event_hash": "0" * 64,
    }]
    payload["final_hash"] = "0" * 64
    valid, message = verify_export(payload)
    assert not valid
    assert "canonical JSON" in message


def test_cli_reports_valid_and_invalid_exports(tmp_path, capsys):
    path = tmp_path / "chain.json"
    path.write_text(json.dumps(make_export([{"event": "created"}])), encoding="utf-8")
    assert main([str(path)]) == 0
    assert "valid audit chain" in capsys.readouterr().out

    path.write_text("{}", encoding="utf-8")
    assert main([str(path)]) == 1
    assert "unsupported audit export format" in capsys.readouterr().err

    assert main([str(tmp_path / "missing.json")]) == 1
    assert "cannot read audit export" in capsys.readouterr().err
