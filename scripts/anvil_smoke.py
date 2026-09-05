#!/usr/bin/env python3
"""Start and stop a real loopback Anvil node. Never broadcasts transactions."""
import json
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

def local_rpc(port, method, params):
    req = urllib.request.Request(f"http://127.0.0.1:{port}", method="POST",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json"})
    # Explicitly ignore environment proxy settings for loopback.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3) as response:
        body = json.loads(response.read(1_000_000))
    if body.get("id") != 1 or "error" in body or "result" not in body:
        raise RuntimeError("INVALID_LOCAL_RPC")
    return body["result"]

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); return s.getsockname()[1]

def wait_for_anvil(proc, port):
    for _ in range(60):
        if proc.poll() is not None: raise RuntimeError("ANVIL_EXITED")
        try:
            version = local_rpc(port, "web3_clientVersion", [])
            if "anvil" not in str(version).lower(): raise RuntimeError("NOT_ANVIL")
            if int(local_rpc(port, "eth_chainId", []), 16) != 31337: raise RuntimeError("WRONG_LOCAL_CHAIN")
            return version
        except (OSError, ValueError): time.sleep(0.25)
    raise RuntimeError("ANVIL_START_TIMEOUT")

def main():
    if not shutil.which("anvil"): raise SystemExit("BLOCKED: anvil is not installed; no EVM execution claimed")
    port = free_port()
    proc = subprocess.Popen(["anvil", "--host", "127.0.0.1", "--port", str(port), "--chain-id", "31337", "--silent"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        version = wait_for_anvil(proc, port)
        evidence = {"status": "PASS_LOCAL_ANVIL_NOT_A_FORK", "client": version,
            "chain_id": 31337, "block_number": local_rpc(port, "eth_blockNumber", []),
            "broadcast": False, "real_funds": False}
        Path("evidence").mkdir(exist_ok=True)
        Path("evidence/anvil-local.json").write_text(json.dumps(evidence, indent=2)+"\n")
        print(json.dumps(evidence))
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()

if __name__ == "__main__": main()
