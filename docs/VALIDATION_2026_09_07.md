# Validation work, 2026-09-07

Repository: `olehworkfree-hash/flash-bounty-lab`. The older `flashloan-safe-lab` archive is a separate codebase and is not implicitly audited by these tests.

This change builds on commit d161127f8f469d1b40b437a464fabe3a8001d47f, whose GitHub Actions run 33994207169 passed on 2026-09-05. That existing run compiled Solidity 0.8.24 with Foundry 1.8.1 and executed actual Aave/Sushi deployed code in an isolated Anvil fork. The round trip was lossy, not income.

## New evidence gates

1. Compile all probe contracts and pass mock EVM plus read-only policy tests.
2. Read one fresh canonical Arbitrum block from three endpoints; require two matching complete state observations. Different labels are not a cryptographic proof of independent infrastructure.
3. Re-run flash loan, two swaps, exact repayment, slippage rejection and atomic loss rejection on the original pinned snapshot.
4. Independently verify historical block 501873950 and the next block's public transaction receipt. Recreate the previous-block position with the **recorded** next-block timestamp. No token balances, prices, oracle responses, or storage values are mocked in the liquidation test.
5. Attempt a 5 DAI flash loan and same-asset liquidation using the actual deployed Aave Pool. Require surplus after repayment without starting token capital.

The historical test is deliberately NOT advertised as full transaction replay: it does not reproduce every intervening transaction or every Arbitrum system rule. Timestamp and block height changes are explicit test inputs. Anvil and Forge gas are NOT exact Arbitrum L1+L2 fees. Even a positive fork surplus is not a current opportunity, a paid bounty or realized profit.

`ForkLiquidationProbe` refuses execution and deployment outside local chain 31337. It is a narrow experiment, not a production liquidation bot. Its approval amounts are bounded, callbacks are authenticated, and pre-existing token balances cannot subsidize a losing result. There is no live signer or mainnet broadcast.

## Commands in a network-enabled environment

```
forge build --sizes
python3 scripts/test_real_quorum.py
forge test --match-contract FlashLoanProbeTest -vvv
python3 scripts/anvil_smoke.py
python3 scripts/real_quorum.py --out evidence/real/2026-09-07/fresh-quorum.json
bash scripts/run_real_validation.sh swaps
bash scripts/run_real_validation.sh liquidation
```

A failure leaves the gate failed and preserves diagnostic artifacts. No automatic transition to live financial execution exists.
