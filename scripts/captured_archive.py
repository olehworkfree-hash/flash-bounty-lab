#!/usr/bin/env python3
"""Validate two historical RPC captures, not live state or earned money.

Capture transport is Make HTTPS, with two configured endpoints. This is an
ordinary reproducibility record, not a signed attestation or an Ethereum proof.
The unchanged real_quorum.py remains available for live two-reader validation.
"""
import argparse
import json
from pathlib import Path
import real_quorum as q

LABELS = {'alchemy-public', 'nodeflare-public'}
CAPTURE = Path('evidence/real/2026-09-07/archive-capture.json')

def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('DUPLICATE_JSON_KEY')
        obj[key] = value
    return obj

def parse_batch(raw):
    if isinstance(raw, list):
        if len(q.canonical(raw).encode()) > q.LIMIT:
            raise ValueError('INVALID_CAPTURE_BODY')
        items = raw
    elif isinstance(raw, str) and len(raw.encode()) <= q.LIMIT:
        items = json.loads(raw, object_pairs_hook=unique_object)
    else:
        raise ValueError('INVALID_CAPTURE_BODY')
    if not isinstance(items, list) or len(items) != 8:
        raise ValueError('CAPTURE_BATCH_SHAPE')
    indexed = {}
    for row in items:
        if not isinstance(row, dict) or type(row.get('id')) is not int:
            raise ValueError('CAPTURE_RESPONSE_ID')
        if row['id'] in indexed:
            raise ValueError('CAPTURE_DUPLICATE_ID')
        if row.get('jsonrpc') != '2.0' or 'error' in row or 'result' not in row:
            raise ValueError('CAPTURE_RPC_ERROR')
        indexed[row['id']] = row['result']
    if set(indexed) != set(range(1, 9)):
        raise ValueError('CAPTURE_MISSING_ID')
    return indexed

def validate(capture):
    if capture.get('schema') != 'flash.make_archive_capture.v1':
        raise ValueError('CAPTURE_SCHEMA')
    bodies = capture.get('responses', {})
    if set(bodies) != LABELS:
        raise ValueError('TWO_DISTINCT_CAPTURE_LABELS_REQUIRED')
    rows = {label: parse_batch(body) for label, body in bodies.items()}
    ref = {'blockHash': q.PRE_HASH, 'requireCanonical': True}
    calls = [
        ('eth_chainId', []),
        ('eth_getBlockByNumber', [hex(q.PRE_BLOCK), False]),
        ('eth_call', [{'to': q.POOL, 'data': '0x074b2e43'}, ref]),
        ('eth_call', [{'to': q.POOL, 'data': '0xbf92857c' + '0' * 24 + q.BORROWER}, ref]),
        ('eth_getCode', [q.POOL, ref]),
        ('eth_getCode', [q.DAI, ref]),
        ('eth_getBlockByNumber', [hex(q.PRE_BLOCK + 1), False]),
        ('eth_getTransactionReceipt', [q.HISTORICAL_TX]),
    ]
    lookup = {q.canonical(call): i for i, call in enumerate(calls, 1)}
    def captured_request(label, requested):
        if label not in LABELS:
            raise ValueError('UNKNOWN_CAPTURE_PROVIDER')
        return [rows[label][lookup[q.canonical(call)]] for call in requested]
    old = q.request
    q.request = captured_request
    try:
        headers = {label: q.header(label, q.PRE_BLOCK) for label in sorted(LABELS)}
        h, voters = q.agreement(headers)
        if h['hash'] != q.PRE_HASH:
            raise ValueError('HISTORICAL_HASH_MISMATCH')
        states = {label: q.state(label, q.PRE_BLOCK, h, True) for label in voters}
        agreed, state_voters = q.agreement(states)
        events = {label: q.recorded_event(label, h) for label in state_voters}
        event, event_voters = q.agreement(events)
        for label in event_voters:
            if rows[label][8].get('transactionHash', '').lower() != q.HISTORICAL_TX:
                raise ValueError('WRONG_CAPTURE_TRANSACTION')
    finally:
        q.request = old
    result = dict(schema='flash.captured_historical_quorum.v1', status='PASS',
                  historical=True, block_number=q.PRE_BLOCK, header=h, state=agreed,
                  state_voters=state_voters, recorded_event=event, event_voters=event_voters,
                  capture_sha256=q.digest(capture), capture_environment='Make HTTPS',
                  capture_scenario_id=capture.get('scenario_id'),
                  observed_at=capture.get('observed_at'), network_reads_in_this_validator=False,
                  independent_source_ownership_proven=False, signed_attestation=False,
                  current_trade_signal=False, live_execution_allowed=False,
                  actual_earnings='0', mainnet_broadcast=False,
                  state_fingerprint_sha256=q.digest(agreed))
    result['evidence_sha256'] = q.digest(result)
    return result

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    if CAPTURE.stat().st_size > 4 * q.LIMIT:
        raise ValueError('CAPTURE_FILE_TOO_LARGE')
    report = validate(json.loads(CAPTURE.read_text(), object_pairs_hook=unique_object))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(q.canonical({'status': report['status'], 'source': 'CAPTURED_NOT_LIVE',
                       'block': q.PRE_BLOCK, 'voters': report['state_voters']}))
if __name__ == '__main__':
    main()
