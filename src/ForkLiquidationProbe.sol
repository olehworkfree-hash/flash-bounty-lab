// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface ILiquidationToken {
    function balanceOf(address) external view returns (uint256);
    function allowance(address, address) external view returns (uint256);
    function approve(address, uint256) external returns (bool);
}
interface ILiquidationPool {
    function flashLoanSimple(address, address, uint256, bytes calldata, uint16) external;
    function liquidationCall(address, address, address, uint256, bool) external;
    function getUserAccountData(address) external view returns (uint256,uint256,uint256,uint256,uint256,uint256);
    function FLASHLOAN_PREMIUM_TOTAL() external view returns (uint128);
}

/// @notice Isolated local-fork integration probe, NOT a mainnet executor or an audited contract.
/// @dev Deliberately limited to one same-asset DAI liquidation. No keys, funding or live deployment.
contract ForkLiquidationProbe {
    address public immutable owner;
    ILiquidationPool public immutable pool;
    ILiquidationToken public immutable token;
    bool private active;
    bytes32 private pending;
    uint256 private initialBalance;
    uint256 public lastPremium;
    uint256 public lastProfit;
    uint256 public nonce;
    uint256 private constant BORROW = 5 ether; // Five 18-decimal DAI, not five ETH.

    constructor(address pool_, address token_) {
        require(block.chainid == 31337, "LOCAL_FORK_ONLY");
        require(pool_.code.length != 0 && token_.code.length != 0, "MISSING_CODE");
        owner = msg.sender;
        pool = ILiquidationPool(pool_);
        token = ILiquidationToken(token_);
    }

    function run(address borrower, uint256 minProfit) external {
        require(block.chainid == 31337 && msg.sender == owner, "LOCAL_OWNER_ONLY");
        require(!active && minProfit > 0, "BAD_PLAN");
        (,,,,,uint256 hf) = pool.getUserAccountData(borrower);
        require(hf < 1 ether, "NOT_LIQUIDATABLE");
        initialBalance = token.balanceOf(address(this));
        uint256 premiumLimit = (BORROW * pool.FLASHLOAN_PREMIUM_TOTAL() + 5000) / 10000;
        bytes memory plan = abi.encode(borrower, minProfit, premiumLimit, ++nonce);
        pending = keccak256(plan);
        active = true;
        pool.flashLoanSimple(address(this), address(token), BORROW, plan, 0);
        require(!active && pending == bytes32(0), "CALLBACK_MISSING");
        require(token.allowance(address(this), address(pool)) == 0, "ALLOWANCE_LEFT");
        lastProfit = token.balanceOf(address(this)) - initialBalance;
        require(lastProfit >= minProfit, "POST_REPAYMENT_LOSS");
    }

    function executeOperation(address asset, uint256 amount, uint256 premium, address initiator, bytes calldata plan)
        external returns (bool)
    {
        require(block.chainid == 31337 && active, "NO_ACTIVE_LOCAL_LOAN");
        require(msg.sender == address(pool) && initiator == address(this), "BAD_CALLBACK");
        require(asset == address(token) && amount == BORROW && keccak256(plan) == pending, "BAD_LOAN");
        (address borrower, uint256 minProfit, uint256 premiumLimit, uint256 planNonce) =
            abi.decode(plan, (address,uint256,uint256,uint256));
        require(premium <= premiumLimit && planNonce == nonce, "BAD_PREMIUM_OR_NONCE");
        // Allow only the received loan for liquidation, not an unlimited token approval.
        require(token.approve(address(pool), 0) && token.approve(address(pool), amount), "APPROVE_LIQUIDATION");
        pool.liquidationCall(asset, asset, borrower, type(uint256).max, false);
        require(token.approve(address(pool), 0), "CLEAR_LIQUIDATION_ALLOWANCE");
        // Existing token balances cannot subsidize a loss.
        require(token.balanceOf(address(this)) >= initialBalance + amount + premium + minProfit, "UNPROFITABLE_LIQUIDATION");
        lastPremium = premium;
        active = false;
        pending = bytes32(0);
        require(token.approve(address(pool), amount + premium), "APPROVE_REPAYMENT");
        return true;
    }
}
