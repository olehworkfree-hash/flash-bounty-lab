// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IERC20Probe {
    function balanceOf(address who) external view returns (uint256);
    function approve(address spender, uint256 value) external returns (bool);
    function transfer(address to, uint256 value) external returns (bool);
}
interface IAavePoolProbe {
    function flashLoanSimple(address receiver, address asset, uint256 amount, bytes calldata params, uint16 referralCode) external;
}

/// @notice Non-production repayment probe. Only chain 31337; no swaps or profits.
/// @dev Review and test before reuse. A chain ID check is a guard, not node authentication.
contract FlashLoanProbe {
    address public immutable owner;
    address public immutable pool;
    uint256 public nonce;
    uint256 public lastPremium;
    uint256 private stage; // 0 idle, 1 waiting, 2 callback completed
    address private expectedAsset;
    uint256 private expectedAmount;
    uint256 private premiumCap;
    bytes32 private expectedParams;

    constructor(address pool_) {
        require(block.chainid == 31337, "LOCAL_CHAIN_ONLY");
        require(pool_.code.length != 0, "POOL_HAS_NO_CODE");
        owner = msg.sender;
        pool = pool_;
    }
    modifier onlyOwner() {
        require(msg.sender == owner, "OWNER_ONLY");
        _;
    }
    function probe(address asset, uint256 amount, uint256 maxPremium) external onlyOwner {
        require(block.chainid == 31337 && stage == 0, "CHAIN_OR_BUSY");
        require(asset.code.length != 0 && amount != 0, "INVALID_LOAN");
        uint256 beforeBalance = IERC20Probe(asset).balanceOf(address(this));
        require(beforeBalance >= maxPremium, "PREFUND_TEST_FEE");
        bytes memory params = abi.encode(++nonce, asset, amount, maxPremium);
        expectedAsset = asset;
        expectedAmount = amount;
        premiumCap = maxPremium;
        expectedParams = keccak256(params);
        stage = 1;
        IAavePoolProbe(pool).flashLoanSimple(address(this), asset, amount, params, 0);
        require(stage == 2, "CALLBACK_MISSING");
        require(IERC20Probe(asset).balanceOf(address(this)) == beforeBalance - lastPremium, "BAD_REPAYMENT");
        _approve(asset, 0);
        stage = 0;
        expectedAsset = address(0);
        expectedAmount = 0;
        premiumCap = 0;
        expectedParams = bytes32(0);
    }
    function executeOperation(address asset, uint256 amount, uint256 premium, address initiator, bytes calldata params) external returns (bool) {
        require(msg.sender == pool && initiator == address(this), "UNTRUSTED_CALLBACK");
        require(stage == 1, "CALLBACK_STATE");
        require(asset == expectedAsset && amount == expectedAmount && keccak256(params) == expectedParams, "CALLBACK_MISMATCH");
        require(premium <= premiumCap, "PREMIUM_CAP");
        require(IERC20Probe(asset).balanceOf(address(this)) >= amount + premium, "INSUFFICIENT_REPAYMENT");
        stage = 2;
        lastPremium = premium;
        _approve(asset, 0);
        _approve(asset, amount + premium);
        return true;
    }
    function rescue(address asset, uint256 amount) external onlyOwner {
        require(stage == 0, "BUSY");
        _callToken(asset, abi.encodeCall(IERC20Probe.transfer, (owner, amount)));
    }
    function _approve(address asset, uint256 amount) private {
        _callToken(asset, abi.encodeCall(IERC20Probe.approve, (pool, amount)));
    }
    function _callToken(address asset, bytes memory data) private {
        require(asset.code.length != 0, "TOKEN_HAS_NO_CODE");
        (bool ok, bytes memory result) = asset.call(data);
        require(ok && (result.length == 0 || (result.length == 32 && abi.decode(result, (bool)))), "TOKEN_CALL_FAILED");
    }
}
