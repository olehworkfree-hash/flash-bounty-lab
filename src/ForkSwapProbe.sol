// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IProbeToken {
    function balanceOf(address account) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
}
interface IProbePool {
    function flashLoanSimple(address receiver, address asset, uint256 amount, bytes calldata params, uint16 code) external;
}
interface IProbeRouter {
    function factory() external view returns (address);
    function WETH() external view returns (address);
    function swapExactTokensForTokens(uint256 amount, uint256 minimum, address[] calldata path, address to, uint256 deadline) external returns (uint256[] memory);
}

/// @notice DIAGNOSTIC ONLY. Real deployed protocol code, but exclusively on a local fork.
/// @dev Loss allowance is explicit test expenditure, never profit. No mainnet use.
contract ForkSwapProbe {
    struct Plan {
        uint256 amount;
        uint256 minIntermediate;
        uint256 minReturn;
        uint256 maxPremium;
        uint256 maxLoss;
        uint256 deadline;
        uint256 nonce;
    }
    address public immutable owner;
    address public immutable pool;
    address public immutable borrowed;
    address public immutable intermediate;
    address public immutable router;
    uint256 public nonce;
    uint256 public lastReturn;
    uint256 public lastPremium;
    uint256 public lastIntermediate;
    uint256 private stage;
    bytes32 private activeHash;
    event RoundTrip(uint256 loan, uint256 intermediateReceived, uint256 returned, uint256 premium, uint256 loss);

    constructor(address pool_, address borrowed_, address intermediate_, address router_, address factory_) {
        require(block.chainid == 31337, "LOCAL_FORK_ONLY");
        require(pool_.code.length > 0 && borrowed_.code.length > 0 && intermediate_.code.length > 0 && router_.code.length > 0, "MISSING_CODE");
        require(borrowed_ != intermediate_, "SAME_TOKEN");
        require(IProbeRouter(router_).factory() == factory_, "WRONG_FACTORY");
        require(IProbeRouter(router_).WETH() == borrowed_, "WRONG_WETH");
        owner = msg.sender;
        pool = pool_;
        borrowed = borrowed_;
        intermediate = intermediate_;
        router = router_;
    }

    function run(Plan calldata plan) external {
        require(msg.sender == owner && block.chainid == 31337 && stage == 0, "OWNER_CHAIN_STATE");
        require(plan.amount > 0 && plan.minIntermediate > 0 && plan.minReturn > 0, "INVALID_AMOUNTS");
        require(plan.deadline >= block.timestamp && plan.deadline <= block.timestamp + 120, "DEADLINE");
        require(plan.nonce == nonce + 1, "NONCE");
        uint256 beforeBalance = IProbeToken(borrowed).balanceOf(address(this));
        require(beforeBalance >= plan.maxLoss, "TEST_LOSS_NOT_PREFUNDED");
        nonce = plan.nonce;
        bytes memory params = abi.encode(plan);
        activeHash = keccak256(params);
        stage = 1;
        IProbePool(pool).flashLoanSimple(address(this), borrowed, plan.amount, params, 0);
        require(stage == 2, "MISSING_CALLBACK");
        uint256 afterBalance = IProbeToken(borrowed).balanceOf(address(this));
        uint256 loss = plan.amount + lastPremium > lastReturn ? plan.amount + lastPremium - lastReturn : 0;
        require(afterBalance + plan.maxLoss >= beforeBalance, "LOSS_LIMIT");
        require(afterBalance + plan.amount + lastPremium == beforeBalance + lastReturn, "BALANCE_MISMATCH");
        _approve(borrowed, pool, 0);
        stage = 0;
        activeHash = bytes32(0);
        emit RoundTrip(plan.amount, lastIntermediate, lastReturn, lastPremium, loss);
    }

    function executeOperation(address asset, uint256 amount, uint256 premium, address initiator, bytes calldata params) external returns (bool) {
        require(msg.sender == pool && initiator == address(this) && stage == 1, "CALLBACK_AUTH");
        require(keccak256(params) == activeHash, "PLAN_MISMATCH");
        Plan memory p = abi.decode(params, (Plan));
        require(asset == borrowed && amount == p.amount && premium <= p.maxPremium, "LOAN_MISMATCH");
        stage = 2;
        uint256 intermediateBefore = IProbeToken(intermediate).balanceOf(address(this));
        uint256 received = _swap(borrowed, intermediate, amount, p.minIntermediate, p.deadline);
        uint256 returned = _swap(intermediate, borrowed, received, p.minReturn, p.deadline);
        // Crucial: old prefunded balances MUST NOT turn a losing route into profit.
        require(returned + p.maxLoss >= amount + premium, "UNPROFITABLE_ROUTE");
        require(IProbeToken(intermediate).balanceOf(address(this)) == intermediateBefore, "INTERMEDIATE_DUST");
        lastIntermediate = received;
        lastReturn = returned;
        lastPremium = premium;
        _approve(borrowed, pool, amount + premium);
        return true;
    }

    function _swap(address input, address output, uint256 amount, uint256 minimum, uint256 deadline) private returns (uint256 received) {
        address[] memory path = new address[](2);
        path[0] = input;
        path[1] = output;
        uint256 beforeBalance = IProbeToken(output).balanceOf(address(this));
        _approve(input, router, amount);
        IProbeRouter(router).swapExactTokensForTokens(amount, minimum, path, address(this), deadline);
        _approve(input, router, 0);
        received = IProbeToken(output).balanceOf(address(this)) - beforeBalance;
        require(received >= minimum, "MIN_OUTPUT");
    }

    function _approve(address token, address spender, uint256 amount) private {
        (bool ok, bytes memory result) = token.call(abi.encodeCall(IProbeToken.approve, (spender, amount)));
        require(ok && (result.length == 0 || (result.length == 32 && abi.decode(result, (bool)))), "APPROVE_FAILED");
    }
}
