// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {ForkProfitExecutor} from "../src/ForkProfitExecutor.sol";
import {MockToken} from "./FlashLoanProbe.t.sol";
interface VmProfit { function chainId(uint256) external; function prank(address) external; function expectRevert() external; function txGasPrice(uint256) external; }
contract ProfitPool {
 uint256 public mode; function configure(uint256 m) external { mode=m; }
 function flashLoanSimple(address receiver,address asset,uint256 amount,bytes calldata params,uint16) external {
  if(mode==4) return; MockToken t=MockToken(asset); if(mode!=6) t.transfer(receiver,amount); uint256 fee=mode==2 ? 6 : 5; address initiator=mode==3 ? address(7) : msg.sender; bytes memory payload=mode==7 ? bytes("altered") : params; require(ForkProfitExecutor(receiver).executeOperation(asset,amount,fee,initiator,payload)); if(mode==5) ForkProfitExecutor(receiver).executeOperation(asset,amount,fee,initiator,payload); if(mode!=1) t.transferFrom(receiver,address(this),amount+fee);
 }
}
contract ProfitRouter {
 address public immutable factory; address public immutable WETH; uint256 public numerator; uint256 public denominator; bool public consume=true; bool public transferOutput=true; bool public lie;
 constructor(address weth,address f,uint256 n,uint256 d) { WETH=weth; factory=f; numerator=n; denominator=d; }
 function configure(uint256 n,uint256 d,bool takeInput,bool sendOutput,bool fakeReturn) external { numerator=n; denominator=d; consume=takeInput; transferOutput=sendOutput; lie=fakeReturn; }
 function swapExactTokensForTokens(uint256 amount,uint256,address[] calldata path,address to,uint256) external returns(uint256[] memory r) { if(consume) MockToken(path[0]).transferFrom(msg.sender,address(this),amount); uint256 out=amount*numerator/denominator; if(transferOutput) MockToken(path[1]).transfer(to,out); r=new uint256[](2); r[0]=amount; r[1]=lie ? type(uint256).max : out; }
}
contract ForkProfitExecutorTest {
 VmProfit constant vm=VmProfit(address(uint160(uint256(keccak256("hevm cheat code")))));
 MockToken weth; MockToken token; ProfitPool pool; ProfitRouter buy; ProfitRouter sell; ForkProfitExecutor executor; address constant TREASURY=address(0xBEEF);
 function setUp() public {
  vm.chainId(31337); vm.txGasPrice(1); weth=new MockToken(); token=new MockToken(); pool=new ProfitPool(); buy=new ProfitRouter(address(weth),address(pool),2,1); sell=new ProfitRouter(address(weth),address(pool),6,10); executor=new ForkProfitExecutor(address(pool),address(weth),address(token),[address(buy),address(sell)],[address(pool),address(pool)],address(this),TREASURY,1000000); weth.mint(address(pool),100000000); weth.mint(address(sell),100000000); token.mint(address(buy),100000000); executor.setPaused(false);
 }
 function plan() private view returns(ForkProfitExecutor.Plan memory) { return ForkProfitExecutor.Plan(10000,1,1,5,100,100,10,block.timestamp+60,1); }
 function reject(ForkProfitExecutor.Plan memory p) private { vm.expectRevert(); executor.run(p); }
 function testProfitSettlesToTreasuryAfterRepayment() public { executor.run(plan()); require(executor.lastGrossProfit()==1995 && weth.balanceOf(TREASURY)==1995); require(weth.balanceOf(address(pool))==100000005 && weth.balanceOf(address(executor))==0); require(weth.allowance(address(executor),address(pool))==0 && weth.allowance(address(executor),address(buy))==0 && token.allowance(address(executor),address(sell))==0); }
 function testPrefundsAndIntermediateDustRemainUntouched() public { weth.mint(address(executor),99999); token.mint(address(executor),888); executor.run(plan()); require(weth.balanceOf(address(executor))==99999 && token.balanceOf(address(executor))==888 && weth.balanceOf(TREASURY)==1995); }
 function testLosingRouteCannotSpendPrefunds() public { weth.mint(address(executor),1000000); sell.configure(49,100,true,true,true); reject(plan()); require(weth.balanceOf(address(executor))==1000000 && executor.nonce()==0 && weth.balanceOf(TREASURY)==0); }
 function testFeeBudgetAndProfitFloorEnforced() public { ForkProfitExecutor.Plan memory p=plan(); p.gasBudget=1900; reject(p); }
 function testExactProfitBoundary() public { ForkProfitExecutor.Plan memory p=plan(); p.gasBudget=1895; executor.run(p); require(weth.balanceOf(TREASURY)==1995); }
 function testOneUnitBelowProfitBoundaryRejected() public { ForkProfitExecutor.Plan memory p=plan(); p.gasBudget=1896; reject(p); }
 function testMissingRepaymentRejected() public { pool.configure(1); reject(plan()); }
 function testExcessPremiumRejected() public { pool.configure(2); reject(plan()); }
 function testWrongInitiatorRejected() public { pool.configure(3); reject(plan()); }
 function testMissingCallbackRejected() public { pool.configure(4); reject(plan()); }
 function testDoubleCallbackRejected() public { pool.configure(5); reject(plan()); }
 function testMissingLoanRejectedDespitePrefund() public { pool.configure(6); weth.mint(address(executor),100000); reject(plan()); }
 function testTamperedPlanRejected() public { pool.configure(7); reject(plan()); }
 function testRouterMustConsumeExactInput() public { buy.configure(2,1,false,true,false); reject(plan()); }
 function testRouterReturnArrayCannotFakeOutput() public { sell.configure(6,10,true,false,true); reject(plan()); }
 function testFalseApprovalRejected() public { weth.reject(true); reject(plan()); }
 function testNonceReplayRejected() public { ForkProfitExecutor.Plan memory p=plan(); executor.run(p); reject(p); }
 function testUnauthorizedRunRejected() public { ForkProfitExecutor.Plan memory p=plan(); vm.prank(address(9)); vm.expectRevert(); executor.run(p); }
 function testPausedRunRejected() public { executor.setPaused(true); reject(plan()); }
 function testZeroBudgetRejected() public { ForkProfitExecutor.Plan memory p=plan(); p.gasBudget=0; reject(p); }
 function testZeroProfitRejected() public { ForkProfitExecutor.Plan memory p=plan(); p.minNetProfit=0; reject(p); }
 function testBorrowCapRejected() public { ForkProfitExecutor.Plan memory p=plan(); p.amount=1000001; reject(p); }
 function testLongDeadlineRejected() public { ForkProfitExecutor.Plan memory p=plan(); p.deadline=block.timestamp+121; reject(p); }
 function testGasPriceRejected() public { vm.txGasPrice(11); reject(plan()); }
 function testWrongChainRejected() public { vm.chainId(42161); reject(plan()); }
 function testTreasuryOnlySweep() public { executor.setPaused(true); weth.mint(address(executor),42); executor.sweep(address(weth),42); require(weth.balanceOf(TREASURY)==42); }
 function testActiveSweepRejected() public { vm.expectRevert(); executor.sweep(address(weth),1); }
 function testFakeCallbackRejected() public { vm.expectRevert(); executor.executeOperation(address(weth),10000,5,address(executor),""); }
 function testFuzzPreserveOldBalances(uint64 prefund,uint64 dust) public { weth.mint(address(executor),prefund); token.mint(address(executor),dust); executor.run(plan()); require(weth.balanceOf(address(executor))==prefund && token.balanceOf(address(executor))==dust && weth.balanceOf(TREASURY)==1995); }
}
