#!/usr/bin/env python3
"""Exact-commit CI gate, three-provider quorum and isolated Aave fork.
No wallet keys, signing or mainnet broadcast. Forge funds are simulated."""
import concurrent.futures as cf
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess as sp
import time
import urllib.request as u
from anvil_smoke import free_port, local_rpc, wait_for_anvil

REPO = "olehworkfree-hash/flash-bounty-lab"
ENDPOINTS = {"drpc": "https://arbitrum.drpc.org/", "official": "https://arb1.arbitrum.io/rpc", "publicnode": "https://arbitrum-one-rpc.publicnode.com"}
FORK_SOURCE = "publicnode"
ADDRESSES = {"provider": "0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb", "pool": "0x794a61358D6845594F94dc1DB02A252b5b4814aD", "weth": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"}
METHODS = {"eth_chainId", "eth_blockNumber", "eth_getBlockByNumber", "eth_getCode", "eth_call"}
HASH = re.compile(r"0x[0-9a-fA-F]{64}\Z")

class NoRedirect(u.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("REDIRECT_REFUSED")

def get_json(url, payload=None):
    request = u.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers={"User-Agent": "FLASH-ReadOnly-Fork/1", "Content-Type": "application/json"})
    with u.build_opener(NoRedirect()).open(request, timeout=10) as r:
        raw = r.read(1000001)
        if r.status != 200 or len(raw) > 1000000: raise ValueError("BAD_HTTP_RESPONSE")
    return json.loads(raw)

def rpc(provider, method, params):
    if provider not in ENDPOINTS or method not in METHODS: raise ValueError("READ_ONLY_ALLOWLIST")
    result = get_json(ENDPOINTS[provider], {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if not isinstance(result, dict) or result.get("jsonrpc") != "2.0" or type(result.get("id")) is not int or result["id"] != 1 or "error" in result or "result" not in result: raise ValueError("BAD_RPC_RESPONSE")
    return result["result"]

def concurrent(function):
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        return dict(zip(ENDPOINTS, pool.map(function, ENDPOINTS)))

def sha256code(code):
    if not isinstance(code, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", code): raise ValueError("NO_CONTRACT_CODE")
    return hashlib.sha256(bytes.fromhex(code[2:])).hexdigest()

def main():
    if os.environ.get("GITHUB_ACTIONS") != "true": raise ValueError("CI_ONLY")
    sha = sp.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if sha != os.environ.get("GITHUB_SHA"): raise ValueError("WRONG_CHECKOUT")
    run_id = int(os.environ["GITHUB_RUN_ID"])
    run = get_json(f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}")
    jobs = get_json(f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100")
    if run.get("head_sha") != sha or run.get("path") != ".github/workflows/verify.yml" or run.get("repository", {}).get("full_name") != REPO: raise ValueError("CI_RUN_MISMATCH")
    if not any(j.get("name") == "verify" and j.get("head_sha") == sha and j.get("conclusion") == "success" for j in jobs.get("jobs", [])): raise ValueError("CI_GATE_NOT_PASSED")
    def head(p):
        if int(rpc(p, "eth_chainId", []), 16) != 42161: raise ValueError("WRONG_UPSTREAM_CHAIN")
        return int(rpc(p, "eth_blockNumber", []), 16)
    heads = concurrent(head)
    block = min(heads.values()) - 256
    if block < 1: raise ValueError("INVALID_BLOCK")
    tag = hex(block)
    headers = concurrent(lambda p: rpc(p, "eth_getBlockByNumber", [tag, False]))
    for h in headers.values():
        if not isinstance(h, dict) or int(h.get("number", "0x0"), 16) != block: raise ValueError("MISSING_OR_WRONG_HEADER")
        if any(not HASH.fullmatch(h.get(k, "")) for k in ("hash", "stateRoot", "parentHash")): raise ValueError("INVALID_HEADER_HASH")
        if not time.time() - 600 <= int(h["timestamp"], 16) <= time.time() + 30: raise ValueError("STALE_HEADER")
    keys = ("hash", "stateRoot", "parentHash", "timestamp")
    if len({tuple(h[k].lower() for k in keys) for h in headers.values()}) != 1: raise ValueError("QUORUM_CONFLICT")
    selectors = {s: sp.check_output(["cast", "sig", s], text=True).strip() for s in ("getPool()", "FLASHLOAN_PREMIUM_TOTAL()")}
    def state(p):
        codes = {name: sha256code(rpc(p, "eth_getCode", [address, tag])) for name, address in ADDRESSES.items()}
        pool_word = rpc(p, "eth_call", [{"to": ADDRESSES["provider"], "data": selectors["getPool()"]}, tag])
        fee_word = rpc(p, "eth_call", [{"to": ADDRESSES["pool"], "data": selectors["FLASHLOAN_PREMIUM_TOTAL()"]}, tag])
        if not HASH.fullmatch(pool_word) or not HASH.fullmatch(fee_word): raise ValueError("INVALID_ABI_WORD")
        if int(pool_word, 16) != int(ADDRESSES["pool"], 16): raise ValueError("POOL_CHANGED")
        return {"code_sha256": codes, "pool_word": pool_word.lower(), "premium_bps": int(fee_word, 16)}
    states = concurrent(state)
    if len({json.dumps(s, sort_keys=True) for s in states.values()}) != 1: raise ValueError("PROTOCOL_STATE_CONFLICT")
    agreed = headers[FORK_SOURCE]
    evidence = {"block_number": block, "headers": {p: {k: h[k] for k in ("number", *keys)} for p, h in headers.items()}, "protocol_state": states, "observed_unix": time.time(), "quorum": "3_OF_3", "independent_operators_verified": False, "finality_verified": False}
    Path("evidence").mkdir(exist_ok=True)
    Path("evidence/fork-quorum.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print("FORK_INPUT=" + json.dumps(evidence), flush=True)
    print("ANVIL_UPSTREAM=" + FORK_SOURCE, flush=True)
    port = free_port()
    proc = sp.Popen(["anvil", "--host", "127.0.0.1", "--port", str(port), "--chain-id", "31337", "--fork-url", ENDPOINTS[FORK_SOURCE], "--fork-block-number", str(block), "--silent"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    try:
        version = wait_for_anvil(proc, port)
        actual = local_rpc(port, "eth_getBlockByNumber", [tag, False])
        if not actual or any(actual.get(k, "").lower() != agreed[k].lower() for k in keys): raise ValueError("LOCAL_FORK_HEADER_MISMATCH")
        for name, address in ADDRESSES.items():
            if sha256code(local_rpc(port, "eth_getCode", [address, tag])) != states[FORK_SOURCE]["code_sha256"][name]: raise ValueError("LOCAL_FORK_CODE_MISMATCH")
        result = sp.run(["forge", "test", "--fork-url", f"http://127.0.0.1:{port}", "--chain-id", "31337", "--match-contract", "AaveArbitrumForkTest", "-vvvv"], env=dict(os.environ, FOUNDRY_PROFILE="fork"), text=True, stdout=sp.PIPE, stderr=sp.STDOUT, timeout=180)
        Path("evidence/aave-fork-test.txt").write_text(result.stdout)
        print(result.stdout, flush=True)
        passed = result.returncode == 0 and "[PASS] testActualAaveWethRepaymentOnIsolatedFork()" in result.stdout and "1 passed; 0 failed; 0 skipped" in result.stdout
        proof = {"status": "PASS_AAVE_FORK_ONLY" if passed else "FAIL_AAVE_FORK", "commit": sha, "run_id": run_id, "block": block, "block_hash": agreed["hash"], "anvil": version, "fork_source": FORK_SOURCE, "premium_bps": states[FORK_SOURCE]["premium_bps"], "quorum": "3_OF_3_HEADER_AND_PROTOCOL_READS", "mainnet_broadcast": False, "real_funds": False, "profit_verified": False}
        Path("evidence/aave-fork-result.json").write_text(json.dumps(proof, indent=2) + "\n")
        print("FORK_RESULT=" + json.dumps(proof), flush=True)
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary: summary.write("## Aave isolated fork result\n\n```json\n" + json.dumps(proof, indent=2) + "\n```\n")
        return 0 if passed else 1
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except sp.TimeoutExpired: proc.kill(); proc.wait()

if __name__ == "__main__":
    raise SystemExit(main())
