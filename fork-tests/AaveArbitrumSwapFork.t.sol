// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {ForkSwapProbe} from "../src/ForkSwapProbe.sol";
interface VmSwapFork { function deal(address, uint256) external; }
interface IWethSwapFork {
    function deposit() external payable;
    function transfer(address, uint256) external returns (bool);
    function balanceOf(address) external view returns (uint256);
    function allowance(address, address) external view returns (uint256);
}
interface IFactorySwapFork { function getPair(address, address) external view returns (address); }
interface IPairSwapFork { function getReserves() external view returns (uint112, uint112, uint32); }
interface IQuoteSwapFork { function getAmountsOut(uint256, address[] calldata) external view returns (uint256[] memory); }
interface IPremiumSwapFork { function FLASHLOAN_PREMIUM_TOTAL() external view returns (uint128); }
contract AaveArbitrumSwapForkTest {
    VmSwapFork constant vm = VmSwapFork(address(uint160(uint256(keccak256("hevm cheat code")))));
    address constant POOL = 0x794a61358D6845594F94dc1DB02A252b5b4814aD;
    address constant WETH = 0x82aF49447D8a07e3bd95BD0d56f35241523fBab1;
    // Bridged USDC.e, NOT Circle native USDC. Used solely as a known V2 route.
    address constant USDCE = 0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8;
    address constant ROUTER = 0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506;
    address constant FACTORY = 0xc35DADB65012eC5796536bD9864eD8773aBc74C4;
    uint256 constant AMOUNT = 0.0001 ether;
    uint256 constant TEST_RESERVE = 0.001 ether;
    event MeasuredForkRoundTrip(uint256 borrowedWeth, uint256 receivedUsdce, uint256 returnedWeth, uint256 premiumWeth, uint256 lossWeth, uint256 diagnosticGas);

    function _fixture() private returns (ForkSwapProbe receiver, ForkSwapProbe.Plan memory plan) {
        require(block.chainid == 31337, "LOCAL_FORK_REQUIRED");
        address pair = IFactorySwapFork(FACTORY).getPair(WETH, USDCE);
        require(pair.code.length > 0, "MISSING_PAIR");
        (uint112 r0, uint112 r1,) = IPairSwapFork(pair).getReserves();
        require(r0 > 0 && r1 > 0, "EMPTY_PAIR");
        receiver = new ForkSwapProbe(POOL, WETH, USDCE, ROUTER, FACTORY);
        vm.deal(address(this), 1 ether); // Simulated funds; no real wallet or income.
        IWethSwapFork(WETH).deposit{value: TEST_RESERVE}();
        require(IWethSwapFork(WETH).transfer(address(receiver), TEST_RESERVE), "FUND_TEST");
        address[] memory path = new address[](2);
        path[0] = WETH;
        path[1] = USDCE;
        uint256 quoted = IQuoteSwapFork(ROUTER).getAmountsOut(AMOUNT, path)[1];
        require(quoted > 100, "QUOTE_TOO_SMALL");
        uint256 fee = (AMOUNT * IPremiumSwapFork(POOL).FLASHLOAN_PREMIUM_TOTAL() + 5000) / 10000;
        plan = ForkSwapProbe.Plan(AMOUNT, quoted * 99 / 100, AMOUNT * 95 / 100, fee, AMOUNT / 10, block.timestamp + 60, 1);
    }

    function testActualFlashLoanTwoSwapsAndRepayment() public {
        (ForkSwapProbe receiver, ForkSwapProbe.Plan memory plan) = _fixture();
        uint256 beforeBalance = IWethSwapFork(WETH).balanceOf(address(receiver));
        uint256 gasStart = gasleft();
        receiver.run(plan);
        uint256 gasUsed = gasStart - gasleft();
        uint256 afterBalance = IWethSwapFork(WETH).balanceOf(address(receiver));
        require(afterBalance < beforeBalance, "ROUNDTRIP_MUST_NOT_BE_CALLED_PROFIT");
        require(beforeBalance - afterBalance == AMOUNT + receiver.lastPremium() - receiver.lastReturn(), "LOSS_ACCOUNTING");
        require(IWethSwapFork(WETH).allowance(address(receiver), POOL) == 0, "POOL_ALLOWANCE_LEFT");
        require(IWethSwapFork(WETH).allowance(address(receiver), ROUTER) == 0, "ROUTER_ALLOWANCE_LEFT");
        emit MeasuredForkRoundTrip(AMOUNT, receiver.lastIntermediate(), receiver.lastReturn(), receiver.lastPremium(), beforeBalance - afterBalance, gasUsed);
    }

    function testUnprofitableRouteRevertsDespitePrefundedBalance() public {
        (ForkSwapProbe receiver, ForkSwapProbe.Plan memory plan) = _fixture();
        plan.maxLoss = 0;
        address pair = IFactorySwapFork(FACTORY).getPair(WETH, USDCE);
        (uint112 r0, uint112 r1, uint32 timeBefore) = IPairSwapFork(pair).getReserves();
        (bool ok, bytes memory reason) = address(receiver).call(abi.encodeCall(ForkSwapProbe.run, (plan)));
        require(!ok, "LOSING_ROUTE_ACCEPTED");
        require(keccak256(reason) == keccak256(abi.encodeWithSignature("Error(string)", "UNPROFITABLE_ROUTE")), "WRONG_REVERT");
        require(IWethSwapFork(WETH).balanceOf(address(receiver)) == TEST_RESERVE && receiver.nonce() == 0, "NOT_ATOMIC");
        (uint112 a0, uint112 a1, uint32 timeAfter) = IPairSwapFork(pair).getReserves();
        require(r0 == a0 && r1 == a1 && timeBefore == timeAfter, "RESERVES_NOT_REVERTED");
    }

    function testExcessiveMinOutputRollsBackEverything() public {
        (ForkSwapProbe receiver, ForkSwapProbe.Plan memory plan) = _fixture();
        plan.minIntermediate = type(uint128).max;
        (bool ok,) = address(receiver).call(abi.encodeCall(ForkSwapProbe.run, (plan)));
        require(!ok && receiver.nonce() == 0, "SLIPPAGE_GUARD_FAILED");
        require(IWethSwapFork(WETH).balanceOf(address(receiver)) == TEST_RESERVE, "FUNDS_NOT_REVERTED");
    }
}
