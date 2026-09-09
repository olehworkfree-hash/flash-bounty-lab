// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

interface IV3AdapterToken {
    function balanceOf(address) external view returns (uint256);
    function approve(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
}
interface IV3AdapterFactory { function getPool(address, address, uint24) external view returns (address); }
interface IV3AdapterPool {
    function factory() external view returns (address);
    function token0() external view returns (address);
    function token1() external view returns (address);
    function fee() external view returns (uint24);
}
interface IV3AdapterRouter {
    struct ExactInputSingleParams {
        address tokenIn; address tokenOut; uint24 fee; address recipient;
        uint256 deadline; uint256 amountIn; uint256 amountOutMinimum; uint160 sqrtPriceLimitX96;
    }
    function factory() external view returns (address);
    function WETH9() external view returns (address);
    function exactInputSingle(ExactInputSingleParams calldata) external payable returns (uint256);
}

/// @notice LOCAL chain 31337 ONLY. Uniswap V3 adapter for the existing profit executor.
/// @dev Exposes its V2-shaped interface, NOT V2 pricing. No arbitrary calls or recipients.
contract ForkV3Adapter {
    address public immutable router;
    address public immutable factory;
    address public immutable WETH;
    address public immutable intermediate;
    address public immutable targetPool;
    uint24 public immutable fee;
    bool private entered;

    constructor(address router_, address factory_, address weth_, address token_, uint24 fee_) {
        require(block.chainid == 31337, "LOCAL_FORK_ONLY");
        require(router_.code.length > 0 && factory_.code.length > 0, "DEX_CODE");
        require(weth_ != token_ && weth_.code.length > 0 && token_.code.length > 0, "TOKEN_CODE");
        require(IV3AdapterRouter(router_).factory() == factory_, "FACTORY");
        require(IV3AdapterRouter(router_).WETH9() == weth_, "WETH");
        address p = IV3AdapterFactory(factory_).getPool(weth_, token_, fee_);
        require(p.code.length > 0 && IV3AdapterPool(p).factory() == factory_, "POOL_FACTORY");
        address t0 = IV3AdapterPool(p).token0(); address t1 = IV3AdapterPool(p).token1();
        require((t0 == weth_ && t1 == token_) || (t0 == token_ && t1 == weth_), "POOL_TOKENS");
        require(IV3AdapterPool(p).fee() == fee_, "POOL_FEE");
        router = router_; factory = factory_; WETH = weth_; intermediate = token_;
        targetPool = p; fee = fee_;
    }

    function swapExactTokensForTokens(uint256 amount, uint256 minimum, address[] calldata path,
        address recipient, uint256 deadline) external returns (uint256[] memory amounts) {
        require(block.chainid == 31337 && !entered, "CHAIN_OR_REENTRY");
        require(path.length == 2 && amount > 0 && minimum > 0, "INPUT");
        require((path[0] == WETH && path[1] == intermediate) ||
                (path[0] == intermediate && path[1] == WETH), "PATH");
        require(recipient == msg.sender && recipient != address(this), "RECIPIENT");
        require(deadline >= block.timestamp && deadline <= block.timestamp + 120, "DEADLINE");
        entered = true;
        uint256 oldInput = IV3AdapterToken(path[0]).balanceOf(address(this));
        uint256 oldOutput = IV3AdapterToken(path[1]).balanceOf(address(this));
        uint256 recipientBefore = IV3AdapterToken(path[1]).balanceOf(recipient);
        _token(path[0], abi.encodeCall(IV3AdapterToken.transferFrom, (msg.sender, address(this), amount)));
        require(IV3AdapterToken(path[0]).balanceOf(address(this)) == oldInput + amount, "INPUT_DELIVERY");
        _token(path[0], abi.encodeCall(IV3AdapterToken.approve, (router, 0)));
        _token(path[0], abi.encodeCall(IV3AdapterToken.approve, (router, amount)));
        uint256 reported = IV3AdapterRouter(router).exactInputSingle(
            IV3AdapterRouter.ExactInputSingleParams(path[0], path[1], fee, recipient,
                deadline, amount, minimum, 0));
        _token(path[0], abi.encodeCall(IV3AdapterToken.approve, (router, 0)));
        uint256 actual = IV3AdapterToken(path[1]).balanceOf(recipient) - recipientBefore;
        require(actual >= minimum && reported == actual, "OUTPUT");
        require(IV3AdapterToken(path[0]).balanceOf(address(this)) == oldInput &&
                IV3AdapterToken(path[1]).balanceOf(address(this)) == oldOutput, "ADAPTER_BASELINE");
        entered = false;
        amounts = new uint256[](2); amounts[0] = amount; amounts[1] = actual;
    }
    function _token(address token, bytes memory data) private {
        (bool ok, bytes memory result) = token.call(data);
        require(ok && (result.length == 0 || (result.length == 32 && abi.decode(result, (bool)))), "TOKEN_CALL");
    }
}
