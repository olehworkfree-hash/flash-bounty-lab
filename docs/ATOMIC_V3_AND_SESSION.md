# Local atomic V3 integration and bounded observation session

This branch builds on commit eec589dca6340181c28f5c8db3dd6d8ff40f75ac.
It does not claim live execution, realized profit, a production audit, or continuous monitoring.

## New executor integration
`ForkV3Adapter` implements the fixed V2-shaped transport interface already consumed by
`ForkProfitExecutor`, but calls Uniswap V3 `exactInputSingle`. This is an interface adapter,
**not V2 pricing for V3**. Factory, pool, token, fee and router identities are checked.
Recipients must be the caller; only one immutable WETH/intermediate pair is allowed.
Actual received amounts, exact input consumption, unchanged adapter baselines and zero
remaining approval are checked. Everything is restricted to local chain 31337.

`V3AtomicForkTest` runs a real Aave flashLoanSimple callback through two different V3 pools
for native USDC and bridged USDC.e, with and without local prefunding. Negative economics
must revert with UNPROFITABLE_ROUTE; positive cases must repay then transfer the surplus.
The fixed test amount is 0.01 WETH; these four tests do **not** cover every screened route.
The 1-wei gas budget in this integration test only exercises arithmetic: it is not a real
Arbitrum gas estimate. Quoter gas estimates are not executor gas or a parent-data fee.
Synthetic mock profits and local prefunds are never real earnings. A public reverted
transaction would still consume gas; no public transactions are sent here.

## Bounded session
The session driver makes at most three fresh quorum and V2/V3 screen observations,
checking hashes, voters, counts, source linkage and strictly increasing block numbers.
It counts quote evaluations, not unique opportunities. Blocks need not be consecutive.
This is not N+1 survival testing, not a continuous watcher and not an execution scheduler.
A positive pre-gas quote requires a route-matched atomic simulation, full transaction
fee estimation and controls before any live consideration.

All runs have contents:read only and no wallet credentials. Workflow is push/manual only;
no scheduled billable runtime is installed. Compiler 0.8.24 now uses viaIR, so both full
unit suite and fork regression are required, not just the new tests.

## Sources
- https://developers.uniswap.org/docs/protocols/v3/deployments/v3-arbitrum-deployments
- https://aave.com/docs/aave-v3/guides/flash-loans
- https://docs.arbitrum.io/arbitrum-essentials/how-to-estimate-gas

## Run
```sh
python3 -m unittest discover -s scripts -p 'test_*.py' -v
forge build --sizes
FOUNDRY_PROFILE=fork forge build --sizes
forge test -vvv
python3 scripts/session_screen.py --out-dir evidence/session --rounds 3
python3 scripts/run_v3_atomic.py --quorum evidence/session/round-3/quorum.json --out-dir evidence/atomic
```

Observe the actual CI outcome and artifacts. Prepared files alone are not a passed test.
