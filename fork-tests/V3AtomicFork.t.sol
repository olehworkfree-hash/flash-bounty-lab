// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {ForkV3Adapter} from "../src/ForkV3Adapter.sol";
import {ForkProfitExecutor} from "../src/ForkProfitExecutor.sol";
import {TokenV3,FactoryV3,PoolV3,QuoterV3} from "./V3QuoteExecutionFork.t.sol";
interface VmAtomic { function deal(address,uint256) external; function expectRevert(bytes calldata) external; }
interface AtomicToken { function transfer(address,uint256) external returns(bool); function allowance(address,address) external view returns(uint256); }
interface AtomicAave { function FLASHLOAN_PREMIUM_TOTAL() external view returns(uint128); }
contract V3AtomicForkTest {
    VmAtomic constant vm=VmAtomic(address(uint160(uint256(keccak256("hevm cheat code")))));
    address constant WETH=address(bytes20(hex'82af49447d8a07e3bd95bd0d56f35241523fbab1'));
    address constant USDC=address(bytes20(hex'af88d065e77c8cc2239327c5edb3a432268e5831'));
    address constant USDCE=address(bytes20(hex'ff970a61a04b1ca14834a43f5de4533ebddb5cc8'));
    address constant FACTORY=address(bytes20(hex'1f98431c8ad98523631ae4a59f267346ea31f984'));
    address constant QUOTER=address(bytes20(hex'61ffe014ba17989e743c5f6cb21bf9697530b21e'));
    address constant ROUTER=address(bytes20(hex'e592427a0aece92de3edee1f18e0157c05861564'));
    address constant AAVE=address(bytes20(hex'794a61358d6845594f94dc1db02a252b5b4814ad'));
    address constant TREASURY=address(0xBEEF);
    event AtomicV3Result(address token,uint256 amount,uint256 middle,uint256 returned,uint256 premium,bool rejected,uint256 prefund);
    function selectFees(address token) private view returns(uint24 a,uint24 b) {
        uint24[4] memory fs=[uint24(500),3000,100,10000];
        for(uint256 i;i<fs.length;i++) {
            address p=FactoryV3(FACTORY).getPool(WETH,token,fs[i]);
            if(p!=address(0) && PoolV3(p).liquidity()>0) { if(a==0) a=fs[i]; else { b=fs[i]; break; } }
        }
        require(a!=0 && b!=0,"TWO_POOLS_REQUIRED");
    }
    function quote(address a,address b,uint256 amount,uint24 f) private returns(uint256 n) {
        (n,,,)=QuoterV3(QUOTER).quoteExactInputSingle(QuoterV3.QuoteExactInputSingleParams(a,b,amount,f,0));
    }
    function check(address token,uint256 prefund) private {
        require(block.chainid==31337,"LOCAL_FORK_ONLY");
        (uint24 fa,uint24 fb)=selectFees(token);
        ForkV3Adapter buy=new ForkV3Adapter(ROUTER,FACTORY,WETH,token,fa);
        ForkV3Adapter sell=new ForkV3Adapter(ROUTER,FACTORY,WETH,token,fb);
        require(buy.targetPool()!=sell.targetPool(),"DISTINCT_POOLS");
        ForkProfitExecutor e=new ForkProfitExecutor(AAVE,WETH,token,[address(buy),address(sell)],
            [FACTORY,FACTORY],address(this),TREASURY,1 ether);
        e.setPaused(false);
        if(prefund>0) {
            // This is local test funding, NEVER earnings. It must remain untouched.
            vm.deal(address(this),prefund); TokenV3(WETH).deposit{value:prefund}();
            require(AtomicToken(WETH).transfer(address(e),prefund));
        }
        uint256 n=0.01 ether; uint256 mid=quote(WETH,token,n,fa); uint256 back=quote(token,WETH,mid,fb);
        uint256 fee=(n*AtomicAave(AAVE).FLASHLOAN_PREMIUM_TOTAL()+5000)/10000;
        uint256 treasuryBefore=TokenV3(WETH).balanceOf(TREASURY);
        // 1 wei budgets exercise arithmetic only, NOT a real Arbitrum fee estimate.
        ForkProfitExecutor.Plan memory p=ForkProfitExecutor.Plan(n,mid,back,fee,1,1,type(uint256).max,block.timestamp+60,1);
        bool rejected=back<n+fee+2;
        if(rejected) vm.expectRevert(abi.encodeWithSignature("Error(string)","UNPROFITABLE_ROUTE"));
        e.run(p);
        require(TokenV3(WETH).balanceOf(address(e))==prefund && TokenV3(token).balanceOf(address(e))==0,"BASELINES");
        require(e.nonce()==(rejected?0:1),"NONCE");
        require(TokenV3(WETH).balanceOf(TREASURY)-treasuryBefore==(rejected?0:back-n-fee),"TREASURY");
        require(AtomicToken(WETH).allowance(address(e),AAVE)==0 && AtomicToken(WETH).allowance(address(e),address(buy))==0,"EXEC_APPROVALS");
        require(AtomicToken(WETH).allowance(address(buy),ROUTER)==0 && AtomicToken(token).allowance(address(sell),ROUTER)==0,"ADAPTER_APPROVALS");
        require(TokenV3(WETH).balanceOf(address(buy))==0 && TokenV3(token).balanceOf(address(sell))==0,"ADAPTER_DUST");
        emit AtomicV3Result(token,n,mid,back,fee,rejected,prefund);
    }
    function testAaveNativeUsdcAtomicNoPrefund() public { check(USDC,0); }
    function testAaveNativeUsdcAtomicCannotSpendPrefund() public { check(USDC,0.1 ether); }
    function testAaveBridgedUsdcAtomicNoPrefund() public { check(USDCE,0); }
    function testAaveBridgedUsdcAtomicCannotSpendPrefund() public { check(USDCE,0.1 ether); }
}
