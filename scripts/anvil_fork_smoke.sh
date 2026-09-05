#!/usr/bin/env bash
set -euo pipefail

FORK_BLOCK="${FORK_BLOCK:-501964988}"
LOCAL_RPC="http://127.0.0.1:8545"
AAVE_POOL="0x794a61358D6845594F94dc1DB02A252b5b4814aD"

ANVIL_PID=""
cleanup() {
  if [[ -n "${ANVIL_PID:-}" ]]; then
    kill "$ANVIL_PID" 2>/dev/null || true
    wait "$ANVIL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

providers=(
  "alchemy-public|https://arb-mainnet.g.alchemy.com/public"
  "nodeflare-public|https://rpc.nodeflare.app/arb/public"
  "arbitrum-official|https://arb1.arbitrum.io/rpc"
)
if [[ -n "${ARBITRUM_RPC_URL:-}" ]]; then
  providers=("operator-supplied|${ARBITRUM_RPC_URL}" "${providers[@]}")
fi

ready=0
selected=""
for candidate in "${providers[@]}"; do
  label="${candidate%%|*}"
  url="${candidate#*|}"
  log="anvil-fork-${label}.log"
  rm -f "$log"
  echo "Starting pinned Arbitrum fork using provider label: $label"
  anvil \
    --fork-url "$url" \
    --fork-block-number "$FORK_BLOCK" \
    --chain-id 31337 \
    --host 127.0.0.1 \
    --port 8545 \
    --silent >"$log" 2>&1 &
  ANVIL_PID=$!

  for _ in $(seq 1 90); do
    if ! kill -0 "$ANVIL_PID" 2>/dev/null; then
      echo "Anvil exited before readiness for $label"
      tail -200 "$log" || true
      break
    fi
    if cast chain-id --rpc-url "$LOCAL_RPC" >/dev/null 2>&1; then
      ready=1
      selected="$label"
      break
    fi
    sleep 1
  done

  if [[ "$ready" == "1" ]]; then
    break
  fi
  kill "$ANVIL_PID" 2>/dev/null || true
  wait "$ANVIL_PID" 2>/dev/null || true
  ANVIL_PID=""
done

if [[ "$ready" != "1" ]]; then
  echo "No configured provider produced a usable pinned Anvil fork" >&2
  for log in anvil-fork-*.log; do echo "--- $log ---"; tail -200 "$log" || true; done
  exit 1
fi

echo "Pinned Anvil fork is ready through provider label: $selected"
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
  "provider_label": "$selected",
  "fork_block": $FORK_BLOCK,
  "local_chain_id": 31337,
  "aave_pool": "$AAVE_POOL",
  "flashloan_premium_total_bps": 5,
  "real_mainnet_broadcast": false,
  "real_funds": false
}
EOF
