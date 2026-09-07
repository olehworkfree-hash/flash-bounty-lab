#!/usr/bin/env python3
"""Bounded read-only Arbitrum observations. No keys, transaction signing or broadcast."""
import argparse\nfrom head_policy import select_heads\nfrom rpc_transport import fetch_body, SafeTransportError
import collections
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

PROVIDERS = {
    "arbitrum-official": "https://arb1.arbitrum.io/rpc",
    "alchemy-public": "https://arb-mainnet.g.alchemy.com/public",
    "nodeflare-public": "https://rpc.nodeflare.app/arb/public",
}
ALLOWED = {"eth_chainId", "eth_blockNumber", "eth_getBlockByNumber", "eth_getCode", "eth_call", "eth_getTransactionReceipt"}
POOL = "0x794a61358d6845594f94dc1db02a252b5b4814ad"
DAI = "0xda10009cbd5d07dd0cecc66161fc93d7c9000da1"
PAIR = "0x905dfcd5649217c42684f23958568e533c711aa3"
BORROWER = "a7c1ffdd40705b56785b31d48ff355e7b6f0336d"
PRE_BLOCK = 501873950
PRE_HASH = "0x2a85f58cbd2d67968a3fe04fe6b7af0f6c2d254c823ec6c0417743a8974315d7"
HISTORICAL_TX = "0x58b9a01462318048913c998f38a8f8d66a9ae8b5c2281e953f58c338f3bc1145"
LIMIT = 2 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def request(label, calls):
    if label not in PROVIDERS or any(method not in ALLOWED for method, _ in calls):
        raise ValueError("RPC_POLICY_REJECTED")
    payload = [{"jsonrpc": "2.0", "id": i, "method": method, "params": params}
               for i, (method, params) in enumerate(calls, 1)]
    req = urllib.request.Request(PROVIDERS[label], data=canonical(payload).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "FLASH-read-only-validation/1"})
    with urllib.request.urlopen(req, timeout=20) as reply:
        body = reply.read(LIMIT + 1)
    if len(body) > LIMIT:
        raise ValueError("RPC_RESPONSE_TOO_LARGE")
    replies = json.loads(body)
    if not isinstance(replies, list) or len(replies) != len(payload):
        raise ValueError("RPC_BATCH_SHAPE")
    indexed = {entry.get("id"): entry for entry in replies if isinstance(entry, dict)}
    if len(indexed) != len(payload) or set(indexed) != set(range(1, len(payload) + 1)):
        raise ValueError("RPC_RESPONSE_IDS")
    results = []
    for i in range(1, len(payload) + 1):
        entry = indexed[i]
        if entry.get("jsonrpc") != "2.0" or "error" in entry or "result" not in entry:
            # Never forward transport URLs or arbitrary error bodies into public reports.
            raise ValueError("RPC_CALL_FAILED_" + str(entry.get("error", {}).get("code", "INVALID")))
        results.append(entry["result"])
    return results


def parallel(fn, labels):
    results, errors = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fn, label): label for label in labels}
        for future in concurrent.futures.as_completed(futures):
            label = futures[future]
            try:
                results[label] = future.result()
            except Exception as exc:
                errors[label] = {"type": type(exc).__name__, "status": "READ_FAILED"}
    return results, errors


def agreement(observations):
    if len(observations) < 2:
        raise ValueError("INSUFFICIENT_PROVIDERS")
    groups = collections.defaultdict(list)
    for label, value in observations.items():
        groups[digest(value)].append(label)
    winners = [labels for labels in groups.values() if len(labels) >= 2]
    if len(winners) != 1:
        raise ValueError("NO_STATE_QUORUM")
    labels = sorted(winners[0])
    return observations[labels[0]], labels


def header(label, number):
    chain, h = request(label, [("eth_chainId", []), ("eth_getBlockByNumber", [hex(number), False])])
    if chain != "0xa4b1" or not h or int(h["number"], 16) != number:
        raise ValueError("CHAIN_OR_BLOCK_MISMATCH")
    keys = ("number", "hash", "parentHash", "stateRoot", "timestamp")
    result = {key: h[key].lower() for key in keys}
    if any(len(result[key]) != 66 for key in ("hash", "parentHash", "stateRoot")):
        raise ValueError("INVALID_BLOCK_HASH")
    return result


def state(label, number, h, historical):
    ref = {"blockHash": h["hash"], "requireCanonical": True}
    calls = [("eth_call", [{"to": POOL, "data": "0x074b2e43"}, ref]),
             ("eth_call", [{"to": POOL, "data": "0xbf92857c" + "0" * 24 + BORROWER}, ref]),
             ("eth_getCode", [POOL, ref]),
             ("eth_getCode", [DAI if historical else PAIR, ref])]
    if not historical:
        calls.append(("eth_call", [{"to": PAIR, "data": "0x0902f1ac"}, ref]))
    values = request(label, calls)
    if len(values[0]) != 66 or len(values[1]) != 386 or any(v == "0x" for v in values[2:4]):
        raise ValueError("EMPTY_CODE_OR_MALFORMED_ABI")
    if header(label, number) != h:
        raise ValueError("BLOCK_CHANGED_DURING_READ")
    if historical and int(values[1][-64:], 16) != 1000000000174597223:
        raise ValueError("HISTORICAL_PRESTATE_MISMATCH")
    return {"header": h, "premium_raw": values[0].lower(), "account_data_raw": values[1].lower(),
            "pool_runtime_sha256": hashlib.sha256(bytes.fromhex(values[2][2:])).hexdigest(),
            "asset_or_pair_runtime_sha256": hashlib.sha256(bytes.fromhex(values[3][2:])).hexdigest(),
            "reserves_raw": values[4].lower() if not historical else None}


def recorded_event(label, pre_header):
    h = header(label, PRE_BLOCK + 1)
    receipt = request(label, [("eth_getTransactionReceipt", [HISTORICAL_TX])])[0]
    if not receipt or receipt["status"] != "0x1" or receipt["blockHash"].lower() != h["hash"]:
        raise ValueError("HISTORICAL_RECEIPT_MISMATCH")
    if h["parentHash"] != pre_header["hash"] or int(receipt["blockNumber"], 16) != PRE_BLOCK + 1:
        raise ValueError("HISTORICAL_PARENT_MISMATCH")
    timestamp = int(h["timestamp"], 16)
    if not 0 < timestamp - int(pre_header["timestamp"], 16) <= 60:
        raise ValueError("UNEXPECTED_TIMESTAMP_DELTA")
    logs = [{"address": x["address"].lower(), "topics": [v.lower() for v in x["topics"]], "data": x["data"].lower()}
            for x in receipt["logs"] if x["address"].lower() == POOL]
    if not logs:
        raise ValueError("MISSING_POOL_EVENT")
    return {"header": h, "timestamp": timestamp, "transaction_hash": HISTORICAL_TX,
            "receipt_status": 1, "pool_logs": logs, "belongs_to_this_project": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical", action="store_true")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    evidence = {"schema": "flash.real_rpc_quorum.v1", "status": "FAILED", "historical": args.historical,
                "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "mainnet_broadcast": False,
                "actual_earnings": "0", "source_independence_cryptographically_proven": False,
                "commit": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID")}
    try:
        def head(label):
            chain, n = request(label, [("eth_chainId", []), ("eth_blockNumber", [])])
            if chain != "0xa4b1":
                raise ValueError("WRONG_CHAIN")
            return int(n, 16)
        heads, head_errors = parallel(head, PROVIDERS)
        if len(heads) < 2:
            raise ValueError("HEAD_QUORUM_UNAVAILABLE")
        selected = heads if args.historical else select_heads(heads); evidence['quarantined_head_labels'] = sorted(set(heads) - set(selected)); number = PRE_BLOCK if args.historical else min(selected.values()) - 32
        evidence.update(heads=heads, head_errors=head_errors, block_number=number, confirmation_policy="32 L2 blocks; not L1 finality")
        headers, errors = parallel(lambda label: header(label, number), selected)
        h, voters = agreement(headers)
        if args.historical and h["hash"] != PRE_HASH:
            raise ValueError("HISTORICAL_HASH_MISMATCH")
        if not args.historical and not -30 <= time.time() - int(h["timestamp"], 16) <= 600:
            raise ValueError("STALE_OR_FUTURE_LIVE_BLOCK")
        evidence.update(header=h, header_voters=voters, header_errors=errors)
        states, errors = parallel(lambda label: state(label, number, h, args.historical), voters)
        evidence.update(state_errors=errors, successful_state_readers=sorted(states))
        agreed, voters = agreement(states)
        evidence.update(state=agreed, state_voters=voters, state_fingerprint_sha256=digest(agreed))
        if args.historical:
            events, errors = parallel(lambda label: recorded_event(label, h), voters)
            event, event_voters = agreement(events)
            evidence.update(recorded_event=event, event_voters=event_voters, event_errors=errors)
        evidence["status"] = "PASS"
    except Exception as exc:
        evidence["failure_type"] = type(exc).__name__
        # Locally generated validation codes only; provider messages are omitted in parallel().
        evidence["failure_code"] = str(exc) if isinstance(exc, ValueError) else "VALIDATION_FAILED"
    evidence["evidence_sha256"] = digest(evidence)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(canonical({"status": evidence["status"], "block": evidence.get("block_number"),
                     "voters": evidence.get("state_voters", []), "failure": evidence.get("failure_code")}))
    if evidence["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
