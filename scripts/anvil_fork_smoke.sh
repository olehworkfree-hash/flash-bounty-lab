#!/usr/bin/env bash
set -euo pipefail

RPC_URL="${ARBITRUM_RPC_URL:-https://arb1.arbitrum.io/rpc}"
FORK_BLOCK="${FORK_BLOCK:-501964988}"
LOCAL_RPC="http://127.0.0.1:8545"
AAVE_POOL="0x794a61358D6845594F94dc1DB02A252b5b4814aD"

cleanup() {
  if [[ -n "${ANVIL_PID:-}" ]]; then
    kill "$ANVIL_PID" 2>/dev/null || true
    wait "$ANVIL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

anvil --fork-url "$RPC_URL" --fork-block-number "$FORK_BLOCK" --chain-id 31337 --host 127.0.0.1 --port 8545 --silent >anvil-fork.log 2>&1 &
ANVIL_PID=$!

for _ in $(seq 1 60); do
  if cast chain-id --rpc-url "$LOCAL_RPC" >/dev/null 2>&1; then break; fi
  sleep 1
done

test "$(cast chain-id --rpc-url "$LOCAL_RPC")" = "31337"
test "$(cast block-number --rpc-url "$LOCAL_RPC")" = "$FORK_BLOCK"
test "$(cast call --rpc-url "$LOCAL_RPC" "$AAVE_POOL" 'FLASHLOAN_PREMIUM_TOTAL()(uint128)')" = "5"
test "$(cast code --rpc-url "$LOCAL_RPC" "$AAVE_POOL")" != "0x"

FOUNDRY_PROFILE=fork forge test --fork-url "$LOCAL_RPC" --match-contract AaveArbitrumForkTest -vvv

mkdir -p evidence/real/anvil
cat > evidence/real/anvil/pinned-arbitrum-fork.json <<EOF
{
  "schema": "flash.anvil_fork_result.v1",
  "status": "PASS",
  "source_rpc": "public_or_operator_supplied",
  "fork_block": $FORK_BLOCK,
  "local_chain_id": 31337,
  "aave_pool": "$AAVE_POOL",
  "flashloan_premium_total_bps": 5,
  "real_mainnet_broadcast": false,
  "real_funds": false
}
EOF
