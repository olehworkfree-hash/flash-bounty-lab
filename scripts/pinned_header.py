"""Validate both supported Cast block JSON formats without relaxing block identity."""
import json
from pathlib import Path
import sys


def checked_header(document: dict, evidence: dict) -> dict:
    if not isinstance(document, dict) or evidence.get('status') != 'PASS':
        raise ValueError('INVALID_HEADER_EVIDENCE')
    if 'schema_version' in document:
        if document.get('schema_version') != 1 or document.get('success') is not True or document.get('errors'):
            raise ValueError('CAST_HEADER_FAILED')
        document = document.get('data')
    if not isinstance(document, dict):
        raise ValueError('MISSING_CAST_HEADER_DATA')
    for key in ('hash', 'parentHash', 'stateRoot', 'number', 'timestamp'):
        seen, expected = document.get(key), evidence['header'].get(key)
        if not isinstance(seen, str) or not isinstance(expected, str) or seen.lower() != expected.lower():
            raise ValueError('LOCAL_FORK_HEADER_MISMATCH_' + key)
    return document


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: pinned_header.py LOCAL_CAST_JSON QUORUM_JSON')
    checked_header(json.loads(Path(sys.argv[1]).read_text()), json.loads(Path(sys.argv[2]).read_text()))
    print('LOCAL_FORK_HEADER_VERIFIED')
