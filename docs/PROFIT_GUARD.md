# Experimental profit-only guard

The new executor is local-fork-only (31337), paused at deployment, with immutable operator, treasury, two routers and a borrowing cap. Existing token balances cannot count as route revenue. Repayment is checked before any surplus goes to treasury. Loss allowances are not supported. Callback identity, nonce, deadline, premium, input/output deltas, allowances and a positive gas budget plus profit floor are enforced. The gas budget is supplied in WETH; it is NOT an exact estimate of Arbitrum L1+L2 transaction fees. This is unaudited research code, not a deployed trading service.

Positive unit-test results use explicitly synthetic mock liquidity. Real fork tests must reject a losing Sushi round trip, including with prefunded WETH. Historical liquidation retains its previously documented one-second timestamp change and is not a complete transaction replay.

The market screen checks six WETH loan sizes in both directions between two known native-USDC V2 pools on one quorum-confirmed block. Integer V2 fees and Aave premium are included; execution gas, L1 data charges, competition and flash liquidity availability are not yet priced. A positive quote remains QUOTE_ONLY_NEEDS_FORK_AND_FEE, never income or an execution authorization. A negative before-gas quote is rejected.

No wallet keys, user funds, public-network deployment, signing, broadcast or automated bounty claims are used.
