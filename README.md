# FLASH - bounded triangle research

Isolated, AI-assisted research code. No wallet keys, mainnet broadcast, or realized earnings.

This branch combines deadline-supervised RPC capture from commit
`1b4fe906ef67b6e13053973faf550b7edccc46c5` and route-matched triangle tests from
`9734ef18054e40029b2e2dfb0db933910f940490` with the prepared optimistic-bound filter.

## Verification

```sh
python3 -m unittest discover -s scripts -p 'test_*.py' -v
forge build --sizes
FOUNDRY_PROFILE=fork forge build --sizes
forge test -vvv
```

The first command passed 180 tests locally before publication. Compilation and
network/fork outcomes for this commit must be read from its actual GitHub Actions
run; prepared source files alone are not proof of execution.

The workflow captures a fresh block, bounds every allowlisted triangle, obtains
at most 64 exact quotes (one diagnostic quote when all bounds lose), then tests
selected exact routes in local Anvil. Partial or conflicting full provider results
are not trading approvals. Historical evidence files retain their original dates.

Read `docs/TRIANGLE_BOUNDS.md` for the derivation and limits. A positive bound is
not an executable quote; a local fork surplus is not money received. Neither full
Arbitrum transaction fees nor survival on a later block are certified by this code.
