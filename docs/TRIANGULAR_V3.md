# Bounded V3 triangle experiment

Extends the verified provider-deadline branch, without replacing the existing two-leg screen or profit executor.

Allowed token paths: WETH -> native USDC -> USDC.e -> WETH, and the reverse stable-token order. Native USDC and USDC.e are separate assets, never treated as a 1:1 peg. Three distinct Uniswap V3 pools; fee tiers 100/500/3000; amounts 0.001/0.01/0.1 WETH. Maximum 54 paths and 162 quote evaluations. No bridge or centralised-exchange leg.

`triangle_screen.py` calls the deployed QuoterV2's quoteExactInput(bytes,uint256). It validates strict ABI lengths, offsets and integer bounds; ignores its gas estimate for both consensus and profitability; reads Aave premium in the same block; and saves intermediate-price/tick data. One bounded child process per provider, with per-batch journals, a 120-second shared deadline, at least two complete matching observations, and rejection on any completed-provider conflict. Unsupported pools and unavailable quotes are not counted as losses or zero-priced trades.

The independent arithmetic check regenerates the route and amount sets and recalculates flash fees and gross-before-gas outcomes. SHA-256 provides artifact integrity, not authenticity or proof of a fully independent provider infrastructure. Observed code hashes are not automatically preapproved. All outputs remain non-executable research evidence; no wallet or signer exists here.

`run_triangle_fork.py` selects one successful quote with the largest gross-before-gas delta. It verifies the source snapshot, quotes, and pinned Anvil header. `TriangularV3ForkTest` confirms the Python selector in Solidity, executes the exact selected three-swap path, and attempts the same route with an Aave flash loan. The receiver starts empty: a net-negative cycle must revert specifically with UNPROFITABLE_TRIANGLE; a positive cycle may retain only the local post-repayment surplus. This is a local-chain-only test harness, not a production executor or audit. The mechanically funded swap test seeds only local ETH; it is not profitable-trade evidence.

Only one selected route is EVM-verified; no claim that every candidate is tested. Costs of a public Arbitrum transaction, inclusion delay, competition, and deployment remain unverified. No gas is paid in mainnet; paper and fork outcomes are not revenue. An unknown fee is unknown, not zero.

Run order: offline Python and Solidity checks, fresh quorum, triangle quotes, selected-route fork, same-block two-leg comparison, previous fork regressions. The workflow is finite and manually/push triggered; no 24/7 monitor is activated and no credentials or repository secrets are needed.
