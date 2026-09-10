# Triangle fork compilation repair (2026-09-10)

Baseline: 53bb4e5a6513223be4b5266cc956bad1465ef405. Run 34420740200 failed during fork-profile Solc 0.8.24 via-IR compilation with a Yul stack-depth error and no memoryguard. Its default profile compiled; runtime tests and network jobs did not execute.

The old packed path decoder used unannotated assembly. A 32-byte load starting at the final 20-byte token can extend beyond the path's allocated payload. Blindly adding a memory-safe annotation is not justified. The replacement uses bounds-checked high-level byte reads: exactly 20 bytes per token and 3 per fee. Index bounds precede multiplication; malformed path lengths are rejected. No compiler or test checks are disabled.

The new unit suite checks one- and three-hop paths, tail decoding, malformed lengths, out-of-range/max indexes, and fuzzes all seven encoded fields. The original chain-31337 gate, empty receiver, callback authentication, exact output assertions, Aave repayment and positive-delta gate are retained.

This does not make the test-only receiver a production contract. No broadcasts, signer credentials or mainnet wallet use are added. The triangle positive-delta gate is BEFORE execution gas, not a claim of net profit. Gas consumed by a Foundry test includes fixture work; it must not be sold as a complete Arbitrum transaction fee. Full transaction estimation with L1 cost and signing authorization remain separate gates.
