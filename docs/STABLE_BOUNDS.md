# Bounded upper-bound screening across three stable pairs

Builds on published 7abaae9902dc0b7d7579c66795885fada6e85a43 and integrates the explicit stable-pair discovery from 09f7ca9b140c3d6f22fcc9299f2ac8c24918f19d.

Scopes: USDC/USDC.e, USDC/DAI, USDC.e/DAI. Each uses WETH as the borrowed and returned asset, a fresh independently hash-pinned snapshot, all four supported V3 fee tiers and four WETH amounts. Maximum 512 bounds and 64 quote attempts per scope; three scopes only, not continuous monitoring. Native USDC and bridged USDC.e are different tokens. DAI has 18 decimals, both USDC contracts 6; discovery verifies this via eth_call. No runtime decimals are guessed or substituted.

The conservative rational bound works on raw token units and reads token0/token1 from each pool. Negative bounds are not called quotes. Every positive bound still needs an exact quote, matched atomic execution, complete transaction fees, and survival until actual inclusion. Unquoted survivors and explicit quote reverts remain unresolved. Provider transport or state errors cannot become votes. Conflicting complete responses still stop the capture. The existing 120-second process deadlines and checkpoints are retained.

The new session independently checks the complete bound grid, chosen quote budget, unavailable identities, every fee and return arithmetic, output below its bound, candidate seals, counts, the exact projection sent to the fork, and the fork result's source linkage. Scope substitution and omission fail closed. Checksums are not signatures and do not establish independent RPC operators or cryptographic state proofs.

Each scope's selected quote is tested in local Anvil: Aave flash loan -> three V3 swaps -> repayment/profit or rollback; repeated with local prefunding which cannot cover a loss. Test-frame gas and 1-wei thresholds are not an Arbitrum transaction fee estimate. The summary reports transaction_fee and net_after_fee as null, not zero. Historical liquidation regression includes its documented time adjustment and is not a live opportunity.

No public transaction, wallet, private key, mainnet deployment, paid API subscription or continuous task is included. Every Solidity execution path remains limited to chain 31337. A passing workflow is engineering evidence only, not an audit or earnings.

Run logs, not this document, determine whether a network experiment succeeded. Original state/quotes/checkpoints and per-scope results are retained as short-lived CI artifacts. Save them for longer-term reproducibility.

Sources: the existing docs/TRIANGLE_BOUNDS.md proof and linked Uniswap V3 SwapMath, SqrtPriceMath and pool swap implementation; Aave flash-loan documentation; Arbitrum gas-estimation documentation.
