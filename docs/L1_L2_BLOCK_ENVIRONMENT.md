# L1 and L2 block numbers are different

The local RPC fork remains pinned to Arbitrum L2 block 501873950 and its verified hash. Foundry v1.8.1 normalizes Solidity NUMBER to the L1 number from the source header independently of the local CHAINID override. Source: foundry-rs/foundry v1.8.1 crates/evm/core/src/utils.rs, apply_chain_and_block_specific_env_changes_for_chain.

The quorum now includes l1BlockNumber in both the previous and actual liquidation-block headers. The local Cast header must match all six fields. Tests compare Solidity block.number with the confirmed L1 field and change time/NUMBER only to the actual next block's values. Never compare an Arbitrum RPC L2 block height with Solidity block.number as though they were the same clock.

This fixes a test harness error, not an Aave vulnerability. Fork output remains simulated, and no user funds or mainnet transactions are involved.
