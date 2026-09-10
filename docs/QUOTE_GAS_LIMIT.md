# Explicit quote gas limits are not missing state or a price

The first combined run failed closed for USDC.e/DAI because a Quoter eth_call returned JSON-RPC -32000. An isolated repeat of that exact call, at the same block hash on the official Arbitrum RPC, returned the explicit message `out of gas`. The call used a 10,000,000-gas simulation cap. No transaction or payment occurred.

Only that exact normalized message with code -32000 is classified OUT_OF_GAS. Unknown server errors, rate limits, missing responses and malformed ABI still fail. Required state reads reject even a classified OUT_OF_GAS. Only the quote loop can retain it as QUOTE_GAS_LIMIT_UNAVAILABLE, without any return value or profit. It is not called a revert, and unavailable/pruned/exact counts stay separate. Complete providers must agree on all actual prices and unavailable identities; a disagreement stops the run.

This does not solve or authorize the unavailable route. It preserves the independently verified quotes for other routes and exposes the remaining research gap.
