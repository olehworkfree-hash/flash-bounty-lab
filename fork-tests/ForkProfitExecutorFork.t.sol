// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {ForkProfitExecutor} from "../src/ForkProfitExecutor.sol";
interface VmProfitFork { function deal(address,uint256) external; }
interface WethProfitFork { function deposit() external payable; function transfer(address,uint256) external returns(bool); function balanceOf(address) external view returns(uint256); function allowance(address,address) external view returns(uint256); }
interface PairProfitFork { function getReserves() external view returns(uint112,uint112,uint32); }
interface PremiumProfitFork { function FLASHLOAN_PREMIUM_TOTAL() external view returns(uint128); }
contract ForkProfitExecutorForkTest {
 VmProfitFork constant vm=VmProfitFork(address(uint160(uint256(keccak256("hevm cheat code")))));
 address constant POOL=0x794a61358D6845594F94dc1DB02A252b5b4814aD; address constant WETH=0x82aF49447D8a07e3bd95BD0d56f35241523fBab1; address constant USDCE=0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8; address constant ROUTER=0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506; address constant FACTORY=0xc35DADB65012eC5796536bD9864eD8773aBc74C4; address constant PAIR=address(bytes20(hex"905dfcd5649217c42684f23958568e533c711aa3")); address constant TREASURY=address(0xBEEF);
 struct Snapshot { uint256 own; uint256 pool; uint256 treasury; uint112 r0; uint112 r1; uint32 stamp; }
 function snap(address executor) private view returns(Snapshot memory s) { s.own=WethProfitFork(WETH).balanceOf(executor); s.pool=WethProfitFork(WETH).balanceOf(POOL); s.treasury=WethProfitFork(WETH).balanceOf(TREASURY); (s.r0,s.r1,s.stamp)=PairProfitFork(PAIR).getReserves(); }
 function _check(bool prefund) private {
  require(block.chainid==31337,"LOCAL_FORK_ONLY"); ForkProfitExecutor x=new ForkProfitExecutor(POOL,WETH,USDCE,[ROUTER,ROUTER],[FACTORY,FACTORY],address(this),TREASURY,1 ether);
  if(prefund) { vm.deal(address(this),1 ether); WethProfitFork(WETH).deposit{value:0.001 ether}(); require(WethProfitFork(WETH).transfer(address(x),0.001 ether)); }
  x.setPaused(false); Snapshot memory beforeState=snap(address(x));
  uint256 fee=(0.0001 ether*PremiumProfitFork(POOL).FLASHLOAN_PREMIUM_TOTAL()+5000)/10000; ForkProfitExecutor.Plan memory p=ForkProfitExecutor.Plan(0.0001 ether,1,1,fee,1,1,type(uint256).max,block.timestamp+60,1);
  (bool ok,bytes memory reason)=address(x).call(abi.encodeCall(ForkProfitExecutor.run,(p))); require(!ok && keccak256(reason)==keccak256(abi.encodeWithSignature("Error(string)","UNPROFITABLE_ROUTE")),"WRONG_PROFIT_GATE");
  require(x.nonce()==0 && keccak256(abi.encode(snap(address(x))))==keccak256(abi.encode(beforeState)),"ROLLBACK_MISMATCH"); require(WethProfitFork(WETH).allowance(address(x),POOL)==0 && WethProfitFork(WETH).allowance(address(x),ROUTER)==0,"APPROVAL_LEFT");
 }
 function testActualLosingRouteRejectedFromEmptyExecutor() public { _check(false); }
 function testActualLosingRouteCannotUseExistingWeth() public { _check(true); }
}
