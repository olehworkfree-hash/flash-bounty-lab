# Bounded three-hop screen and exact-candidate fork check

Parent: f569ab58bc4fc36fb9cdfca3f0a2085ae25d61b6. Experimental, not audited.
No signer, no public transaction, no realized earnings, no daemon.

## Coverage
WETH -> native USDC -> USDC.e -> WETH and reverse; Uniswap V3 pools only.
Four fee tiers (100,500,3000,10000), four WETH inputs (0.001,0.01,0.1,1).
At most 12 pools and 512 evaluations per snapshot. Not the entire market.
QuoterV2 quoteExactInput is used, with distinct pools, correct packed paths and
strict dynamic ABI decoding. Local native USDC and bridged USDC.e are not confused.
Code, decimals, factory, router, token and pool identities are checked at one
canonical hash; at least two providers must agree. Hashes are observed, not audited.
Quoter gasEstimate is not a complete Arbitrum transaction fee and is not used as one.

## Exact matching
The best three positive quotes (or the best negative if none is positive) go to
Anvil at that exact block. The selector validates original evidence hashes,
quorum, full route/pool/fee linkage, arithmetic and deterministic selection.
Tests receive the selected tokens, fees, pool addresses, amount and expected return.
They re-quote in EVM, perform Aave flashLoanSimple -> three swaps -> repayment/profit
OR UNPROFITABLE_ROUTE, then check nonce, allowances and baseline preservation.
A separate test repeats with local prefunding; it must never cover a loss.
The synthetic 1-wei gas/profit thresholds are integration checks only. Reported
executor frame gas is not a transaction receipt fee: no L1 posting/intrinsic/full
transaction estimate is claimed. Mainnet trading and fee estimation remain absent.
The fixed two-hop return adapter implements the existing executor's transport
interface but uses V3 exactInput internally. No V2 formula is used for V3.

## Limits
Only the selected subset receives a route-matched atomic check. Equal states are
not a proof of independent provider ownership. One snapshot is not survival or
latency validation. Sending a losing trade to a public chain still costs gas.
All new contracts reject chain IDs other than 31337.

## Sources
https://github.com/Uniswap/v3-periphery/blob/main/contracts/lens/QuoterV2.sol
https://developers.uniswap.org/docs/protocols/v3/deployments/v3-arbitrum-deployments
https://aave.com/docs/aave-v3/guides/flash-loans
https://docs.arbitrum.io/arbitrum-essentials/how-to-estimate-gas
