# FLASH verification lab

New AI-assisted, non-production repayment probe, not the earlier private v0.7.0
source archive or the separate Flint content sample. No earnings are claimed.

## Published core

- src/FlashLoanProbe.sol: repayment receiver limited to chain ID 31337.
- test/FlashLoanProbe.t.sol: 19 prepared mock Solidity tests.
- fork-tests/AaveArbitrumFork.t.sol: isolated Aave Arbitrum repayment test.
- scripts/anvil_smoke.py: starts and stops real loopback Anvil, no transactions.
- foundry.toml: Solidity 0.8.24, Paris EVM.

## Run

With official Foundry installed:

```sh
forge build
forge test --match-contract FlashLoanProbeTest -vv
python3 scripts/anvil_smoke.py
```

The fork test is separate from default tests. Do not treat default test success
as evidence of an actual fork, mainnet execution or profit. A local chain ID is
a guard, not node authentication. No production deployment path is included.

## Status at publication

The preparation container had no forge, solc or anvil. Solidity compilation,
EVM tests and CI success are not claimed without corresponding actual run logs.
A separate Python read-only evidence package passed 28 tests locally; those tests
are not part of this initial core publication and do not execute an EVM.
The complete new handoff archive is separate; this branch initially contains
only the published core listed above. No wallet or private keys are used.
