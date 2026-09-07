#!/usr/bin/env bash
set -euo pipefail
mode="${1:?Choose swaps or liquidation}"
mkdir -p evidence/real/2026-09-07
case "$mode" in
  swaps)
    block=501964988
    match='AaveArbitrum(Fork|SwapFork)Test'
    ;;
  liquidation)
    python3 scripts/captured_archive.py --out evidence/real/2026-09-07/historical-quorum.json
    export LIQUIDATION_TIMESTAMP
    LIQUIDATION_TIMESTAMP="$(python3 -c 'import json; print(json.load(open("evidence/real/2026-09-07/historical-quorum.json"))["recorded_event"]["timestamp"])')"
    block=501873950
    match=HistoricalLiquidationForkTest
    ;;
  *) echo "Unsupported validation mode" >&2; exit 2;;
esac
local_rpc=http://127.0.0.1:8545
pid=''
cleanup() { if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi; }
trap cleanup EXIT
ready=0
for candidate in 'alchemy-public|https://arb-mainnet.g.alchemy.com/public' 'nodeflare-public|https://rpc.nodeflare.app/arb/public'; do
  label="${candidate%%|*}"
  url="${candidate#*|}"
  log="evidence/real/2026-09-07/anvil-${mode}-${label}.log"
  anvil --fork-url "$url" --fork-block-number "$block" --hardfork shanghai --chain-id 31337 --host 127.0.0.1 --port 8545 --silent >"$log" 2>&1 &
  pid=$!
  for _ in $(seq 1 40); do
    kill -0 "$pid" 2>/dev/null || break
    if cast chain-id --rpc-url "$local_rpc" >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
  done
  [[ "$ready" == 1 ]] && break
  cleanup; pid=''
done
[[ "$ready" == 1 ]] || { echo "ARCHIVE_FORK_UNAVAILABLE" >&2; exit 1; }
[[ "$(cast chain-id --rpc-url "$local_rpc")" == 31337 ]]
[[ "$(cast block-number --rpc-url "$local_rpc")" == "$block" ]]
if [[ "$mode" == liquidation ]]; then
  cast block "$block" --rpc-url "$local_rpc" --json > evidence/real/2026-09-07/local-pinned-header.json
  python3 -c 'import json; a=json.load(open("evidence/real/2026-09-07/local-pinned-header.json")); b=json.load(open("evidence/real/2026-09-07/historical-quorum.json")); assert a["hash"].lower()==b["header"]["hash"]'
fi
FOUNDRY_PROFILE=fork forge test --fork-url "$local_rpc" --match-contract "$match" -vvvv | tee "evidence/real/2026-09-07/${mode}-tests.log"
# This file is written only after Forge exits successfully, with pipefail enabled.
python3 - "$mode" "$block" "$label" <<'PY'
import json, os, sys
from pathlib import Path
mode, block, provider = sys.argv[1:]
report = dict(schema='flash.executed_fork_gate.v1', status='PASS', mode=mode, source_block=int(block), provider_label=provider,
              local_chain_id=31337, anvil_hardfork='shanghai', forge_evm_profile='cancun',
              source_commit=os.getenv('GITHUB_SHA'), source_run=os.getenv('GITHUB_RUN_ID'),
              actual_earnings='0', mainnet_broadcast=False, user_funds_used=False,
              exact_arbitrum_fee_model=False, full_historical_transaction_replay=False)
Path('evidence/real/2026-09-07/'+mode+'-gate.json').write_text(json.dumps(report, indent=2)+'\n')
PY
