# Three stable pairs, one bounded research workflow

Base: 1b4fe906ef67b6e13053973faf550b7edccc46c5 (deadline and accounting fixes).
Integrated earlier triangle branch: 9734ef18054e40029b2e2dfb0db933910f940490.
No live wallet, signing, public broadcast, deployment, or earnings.

## New coverage
WETH -> A -> B -> WETH, and reverse, for USDC/USDC.e, USDC/DAI,
and USDC.e/DAI. Each scope receives its own fresh hash-pinned RPC quorum.
DAI uses 18 decimals; USDC and USDC.e use 6. These are distinct tokens.
Three fee tiers 100, 500, 3000 and four WETH inputs 0.001, 0.01, 0.1, 1.
The 10000 tier is intentionally outside this bounded run.
At most 216 quotes per scope (648 overall), depending on actual active pools.
This is not the whole market, consecutive-block survival, or a continuous service.

## Safety and integration
Reuse the deadline worker and checkpoint journal from the validated parent.
Every source has a 120-second window. Partial captures cannot vote. All full
observations must agree; conflicts fail even if a majority agrees.
The exact expected route grid, arithmetic, candidate seals, pool mapping and
selection are verified. Omitting a losing route and updating the checksum fails.
The best three positive quotes, or the best negative when none are positive,
receive an exact-route local Aave flash loan + 3 swaps + repayment/profit-or-revert
check. Each selected route is tested without and with local prefunding.
Only chain 31337 is permitted. No mainnet-ready executor is provided.

## Economics
The report separates gross before transaction fees from net after fees.
A negative gross is rejected without inventing a fee estimate. A positive gross
with no full transaction estimate remains FULL_TRANSACTION_FEE_REQUIRED.
The break-even total fee is only an arithmetic ceiling, NOT an observed gas cost.
Quoter gas and test-frame gas are not a complete Arbitrum transaction estimate.
The two existing 1-wei thresholds exercise integration only.

## Verification
python3 -m unittest discover -s scripts -p 'test_*.py' -v
forge test -vvv
python3 scripts/stable_route_session.py --out-dir evidence/new-unique-session

Inspect actual CI and archives before claiming a passing experiment.
Public references:
https://github.com/Uniswap/v3-periphery/blob/main/contracts/lens/QuoterV2.sol
https://docs.arbitrum.io/arbitrum-essentials/how-to-estimate-gas
