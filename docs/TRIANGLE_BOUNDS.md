# Optimistic return bounds for three distinct Uniswap V3 pools

## Status
This is research code. Read the actual workflow outcome for the published commit.
It builds on 1b4fe906ef67b6e13053973faf550b7edccc46c5 plus the triangle adapters/tests
from 9734ef18054e40029b2e2dfb0db933910f940490. Solidity was not recompiled locally.
No mainnet transaction, account connection, gas expenditure, or earnings is claimed.
Historical verification is a replay of captured data, not a fresh market. New RPC
capture and fork execution are separate workflow gates, not guaranteed by publication.

## Scope and invariants
Only exact-input WETH -> USDC -> USDC.e -> WETH, and the reverse stable-token order,
on standard Uniswap V3 pools are covered. Tokens use raw integer units; no decimal or
floating-point price conversion is performed. All three pool addresses must be distinct.
The factory, periphery, pool token ordering, fees, runtime presence, slot0 and active
liquidity are read at one block hash. Quorum is not a proof of RPC honesty, approved
implementation hashes, or finality. This is not V4 or an arbitrary-token filter.

## Derivation (model reasoning, not a third-party audit)
Let Q = 2^96, s = sqrtPriceX96 at the start of a pool swap, F the fee in millionths.
The fee-adjusted spot price upper bound is:
- token0 -> token1: (s^2 / Q^2) * (1 - F/1,000,000)
- token1 -> token0: (Q^2 / s^2) * (1 - F/1,000,000)

For one constant-liquidity step from s0 to s1 <= s0 in token0 -> token1 direction:
  output <= L*(s0-s1)/Q
  net input >= L*Q*(s0-s1)/(s0*s1)
so output/net input <= s0*s1/Q^2 <= s0^2/Q^2.
In the opposite direction s1 >= s0, the ratio is <= Q^2/(s0*s1) <= Q^2/s0^2.
Input rounding up and output rounding down in SqrtPriceMath preserve these inequalities.
SwapMath's fee rounding means net input <= gross input*(1-F/1,000,000).
Across initialized ticks, spot moves monotonically against the trade, so every later
step has no better spot ratio than the initial one. Changes in L do not change this
inequality. Zero-liquidity traversal produces no output. Pool reuse is prohibited so
another leg of this route cannot first change the starting price of a later leg.

Therefore, for three distinct pools with ratios R0,R1,R2:
  actual return <= floor(input * R0 * R1 * R2).
The implementation multiplies integer numerators and denominators and rounds down
only once at the end. If this optimistic return <= principal + current flash premium,
then that route cannot be profitable even before nonnegative execution costs under
these assumptions. A positive bound proves nothing about executable profit.

## Implementation and validation
`triangle_bounds.py` implements the rational bound and structural checks.
`triangle_fast_screen.py` reuses the process deadline/checkpoint supervisor. Every
complete provider independently discovers pools and recalculates the full route grid.
Any mismatch among complete providers aborts; incomplete providers do not vote.
At most 64 surviving routes are quoted. Extra survivors remain explicitly unquoted,
not negative. If all bounds lose, one diagnostic route is still quoted for the exact
route-matched local fork regression. `matched-selection.json` contains ONLY actual
eth_call quotes; upper bounds are never passed off as prices.

There are 20 new mathematical/structural tests, including 400 deterministic randomized
three-pool constant-liquidity comparisons against a Fraction-based reference. These
are not 400 actual on-chain swaps and do not replace fork or mainnet fee checks.
Eight further integration tests exercise captured mock responses, exact-quote projection, failure before network, and reorg rejection. The parent deadline and triangle unit tests are retained. Fresh runtime validation of
this integration remains a required next gate, not a completed task.

## Primary sources consulted
https://github.com/Uniswap/v3-core/blob/v1.0.0/contracts/libraries/SwapMath.sol
https://github.com/Uniswap/v3-core/blob/v1.0.0/contracts/libraries/SqrtPriceMath.sol
https://docs.arbitrum.io/arbitrum-essentials/how-to-estimate-gas
The bound proof above is our derivation from the standard swap mechanics. Exact
Arbitrum fees are not inferred from a Quoter gas counter or ordinary Anvil execution.
