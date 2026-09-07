// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {ForkLiquidationProbe, ILiquidationPool, ILiquidationToken} from "../src/ForkLiquidationProbe.sol";
interface VmLiquidation {
    function warp(uint256) external;
    function roll(uint256) external;
    function envUint(string calldata) external returns (uint256);
}
contract HistoricalLiquidationForkTest {
    VmLiquidation constant vm = VmLiquidation(address(uint160(uint256(keccak256("hevm cheat code")))));
    address constant POOL = 0x794a61358D6845594F94dc1DB02A252b5b4814aD;
    address constant DAI = 0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1;
    address constant BORROWER = address(bytes20(hex"a7c1ffdd40705b56785b31d48ff355e7b6f0336d"));
    uint256 constant PRE_BLOCK = 501873950;
    event HistoricalLiquidationResult(uint256 healthBefore, uint256 healthAtRecordedTime, uint256 borrowedDai, uint256 premiumDai, uint256 forkSurplusDai, uint256 remainingDebtBase);

    function _fixture() private returns (ForkLiquidationProbe p) {
        require(block.chainid == 31337 && block.number == PRE_BLOCK, "WRONG_FORK");
        p = new ForkLiquidationProbe(POOL, DAI);
        require(ILiquidationToken(DAI).balanceOf(address(p)) == 0, "PROBE_MUST_START_EMPTY");
    }
    function testHealthyPreviousBlockIsRejected() public {
        ForkLiquidationProbe p = _fixture();
        (,,,,,uint256 hf) = ILiquidationPool(POOL).getUserAccountData(BORROWER);
        require(hf == 1000000000174597223, "PRESTATE_HEALTH_MISMATCH");
        (bool ok, bytes memory reason) = address(p).call(abi.encodeCall(ForkLiquidationProbe.run, (BORROWER, 1)));
        require(!ok && keccak256(reason) == keccak256(abi.encodeWithSignature("Error(string)", "NOT_LIQUIDATABLE")), "HEALTHY_POSITION_ACCEPTED");
        require(p.nonce() == 0 && ILiquidationToken(DAI).balanceOf(address(p)) == 0, "FAILED_ATTEMPT_CHANGED_STATE");
    }
    function testHistoricalSameAssetLiquidationUsingActualAaveLoan() public {
        ForkLiquidationProbe p = _fixture();
        (,,,,,uint256 beforeHealth) = ILiquidationPool(POOL).getUserAccountData(BORROWER);
        uint256 recordedTimestamp = vm.envUint("LIQUIDATION_TIMESTAMP");
        require(recordedTimestamp > block.timestamp && recordedTimestamp <= block.timestamp + 60, "UNBOUNDED_TIME_CHANGE");
        // Use the real liquidation block's verified time. No price, balance or storage mocking.
        // This is a pre-state experiment, NOT a full replay of all transactions in that block.
        vm.warp(recordedTimestamp);
        vm.roll(PRE_BLOCK + 1);
        (,,,,,uint256 health) = ILiquidationPool(POOL).getUserAccountData(BORROWER);
        require(health < 1 ether, "POSITION_NOT_LIQUIDATABLE_AT_RECORDED_TIME");
        p.run(BORROWER, 1);
        (,uint256 remainingDebt,,,,) = ILiquidationPool(POOL).getUserAccountData(BORROWER);
        require(p.lastProfit() > 0 && p.nonce() == 1, "NO_FORK_SURPLUS");
        require(ILiquidationToken(DAI).allowance(address(p), POOL) == 0, "RESIDUAL_APPROVAL");
        emit HistoricalLiquidationResult(beforeHealth, health, 5 ether, p.lastPremium(), p.lastProfit(), remainingDebt);
    }
    function testUnauthenticatedCallbackIsRejected() public {
        ForkLiquidationProbe p = _fixture();
        (bool ok,) = address(p).call(abi.encodeCall(ForkLiquidationProbe.executeOperation, (DAI, 5 ether, 0, address(p), bytes(""))));
        require(!ok, "FAKE_CALLBACK_ACCEPTED");
    }
}
