// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {ForkLiquidationProbe, ILiquidationPool, ILiquidationToken} from "../src/ForkLiquidationProbe.sol";
interface VmLiquidation {
    function warp(uint256) external;
    function envUint(string calldata) external returns (uint256);
}
contract HistoricalLiquidationForkTest {
    VmLiquidation constant vm = VmLiquidation(address(uint160(uint256(keccak256("hevm cheat code")))));
    address constant POOL = 0x794a61358D6845594F94dc1DB02A252b5b4814aD;
    address constant DAI = 0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1;
    address constant BORROWER = address(bytes20(hex"a7c1ffdd40705b56785b31d48ff355e7b6f0336d"));
    // L2 RPC block 501873950 and the following block both report l1BlockNumber
    // 0x18b54bc in BOTH archived provider captures. Arbitrum NUMBER is L1-based.
    // The shell independently checks L2 block hash, stateRoot, parent, number and time.
    uint256 constant EVM_BLOCK = 25908412;
    uint256 constant PRE_TIME = 1788578580;
    event ForkEnvironment(uint256 chainId, uint256 evmBlock, uint256 timestamp);
    event HistoricalLiquidationResult(uint256 healthBefore, uint256 healthAtRecordedTime, uint256 borrowedDai, uint256 premiumDai, uint256 forkSurplusDai, uint256 remainingDebtBase);

    function _fixture() private returns (ForkLiquidationProbe p) {
        emit ForkEnvironment(block.chainid, block.number, block.timestamp);
        require(block.chainid == 31337, "LOCAL_CHAIN_REQUIRED");
        require(block.number == EVM_BLOCK, "ARBITRUM_L1_NUMBER_MISMATCH");
        require(block.timestamp == PRE_TIME, "PRESTATE_TIME_MISMATCH");
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
        require(recordedTimestamp == PRE_TIME + 1, "WRONG_RECORDED_TIMESTAMP");
        // Verified next L2 block time only. Both L2 blocks have the same L1 number:
        // do NOT roll the EVM to an unrelated L2 height. No balances/prices mocked.
        // This is a local historical-state experiment, NOT ordered full-TX replay.
        vm.warp(recordedTimestamp);
        require(block.number == EVM_BLOCK, "EVM_NUMBER_CHANGED");
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
