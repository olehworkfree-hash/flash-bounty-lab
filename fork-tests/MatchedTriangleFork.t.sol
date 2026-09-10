// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {ForkV3Adapter} from "../src/ForkV3Adapter.sol";
import {ForkV3ReturnAdapter} from "../src/ForkV3ReturnAdapter.sol";
import {ForkProfitExecutor} from "../src/ForkProfitExecutor.sol";
import {TokenV3,FactoryV3,QuoterV3} from "./V3QuoteExecutionFork.t.sol";
import {AtomicToken,AtomicAave} from "./V3AtomicFork.t.sol";
interface VmMatched {
    function deal(address,uint256) external;
    function expectRevert(bytes calldata) external;
    function envAddress(string calldata) external returns(address);
    function envUint(string calldata) external returns(uint256);
}
interface IMultiQuote { function quoteExactInput(bytes calldata,uint256) external returns(uint256,uint160[] memory,uint32[] memory,uint256); }
contract MatchedTriangleForkTest {
    VmMatched constant vm=VmMatched(address(uint160(uint256(keccak256("hevm cheat code")))));
    address constant WETH=address(bytes20(hex'82af49447d8a07e3bd95bd0d56f35241523fbab1'));
    address constant USDC=address(bytes20(hex'af88d065e77c8cc2239327c5edb3a432268e5831'));
    address constant USDCE=address(bytes20(hex'ff970a61a04b1ca14834a43f5de4533ebddb5cc8'));
    address constant FACTORY=address(bytes20(hex'1f98431c8ad98523631ae4a59f267346ea31f984'));
    address constant QUOTER=address(bytes20(hex'61ffe014ba17989e743c5f6cb21bf9697530b21e'));
    address constant ROUTER=address(bytes20(hex'e592427a0aece92de3edee1f18e0157c05861564'));
    address constant AAVE=address(bytes20(hex'794a61358d6845594f94dc1db02a252b5b4814ad'));
    address constant TREASURY=address(0xBEEF);
    event MatchedTriangle(uint256 amount,uint256 quotedReturn,uint256 premium,bool rejected,uint256 executorFrameGas,uint256 localPrefund);
    function _slot(address p) private view returns(bytes32 h) {
        (bool ok,bytes memory data)=p.staticcall(hex'3850c7bd');require(ok);return keccak256(data);
    }
    function _check(uint256 prefund) private {
        require(block.chainid==31337,"LOCAL_FORK_ONLY");
        address a=vm.envAddress("TRI_TOKEN1");address b=vm.envAddress("TRI_TOKEN2");
        require((a==USDC && b==USDCE)||(a==USDCE && b==USDC),"STABLE_ALLOWLIST");
        uint24 f0=uint24(vm.envUint("TRI_FEE0"));uint24 f1=uint24(vm.envUint("TRI_FEE1"));uint24 f2=uint24(vm.envUint("TRI_FEE2"));
        uint256 n=vm.envUint("TRI_AMOUNT");uint256 expected=vm.envUint("TRI_RETURN");
        uint256 expectedFee=vm.envUint("TRI_PREMIUM");
        require(n==0.001 ether || n==0.01 ether || n==0.1 ether || n==1 ether,"AMOUNT_ALLOWLIST");
        bytes memory fullPath=abi.encodePacked(WETH,f0,a,f1,b,f2,WETH);
        (uint256 back,,,)=IMultiQuote(QUOTER).quoteExactInput(fullPath,n);
        require(back==expected,"SCREEN_QUOTE_MISMATCH");
        (uint256 mid,,,)=QuoterV3(QUOTER).quoteExactInputSingle(QuoterV3.QuoteExactInputSingleParams(WETH,a,n,f0,0));
        uint256 fee=(n*AtomicAave(AAVE).FLASHLOAN_PREMIUM_TOTAL()+5000)/10000;
        require(fee==expectedFee,"PREMIUM_MISMATCH");
        ForkV3Adapter buy=new ForkV3Adapter(ROUTER,FACTORY,WETH,a,f0);
        ForkV3ReturnAdapter sell=new ForkV3ReturnAdapter(ROUTER,FACTORY,WETH,a,b,f1,f2);
        require(buy.targetPool()!=sell.firstPool() && buy.targetPool()!=sell.secondPool(),"DISTINCT_POOLS");
        address[3] memory pools=[buy.targetPool(),sell.firstPool(),sell.secondPool()];
        for(uint256 j;j<3;j++)require(pools[j]==vm.envAddress(j==0?"TRI_POOL0":j==1?"TRI_POOL1":"TRI_POOL2"),"SCREEN_POOL_MISMATCH");
        bytes32[3] memory slots=[_slot(pools[0]),_slot(pools[1]),_slot(pools[2])];
        ForkProfitExecutor e=new ForkProfitExecutor(AAVE,WETH,a,[address(buy),address(sell)],[FACTORY,FACTORY],address(this),TREASURY,1 ether);
        e.setPaused(false);
        if(prefund>0) { vm.deal(address(this),prefund);TokenV3(WETH).deposit{value:prefund}();require(AtomicToken(WETH).transfer(address(e),prefund)); }
        uint256 treasuryBefore=TokenV3(WETH).balanceOf(TREASURY);
        // Arithmetic threshold only. Not a production gas estimate.
        ForkProfitExecutor.Plan memory p=ForkProfitExecutor.Plan(n,mid,back,fee,1,1,type(uint256).max,block.timestamp+60,1);
        bool rejected=back<n+fee+2;
        if(rejected)vm.expectRevert(abi.encodeWithSignature("Error(string)","UNPROFITABLE_ROUTE"));
        uint256 start=gasleft();e.run(p);uint256 frameGas=start-gasleft();
        require(TokenV3(WETH).balanceOf(address(e))==prefund && TokenV3(a).balanceOf(address(e))==0 && TokenV3(b).balanceOf(address(e))==0,"BASELINES");
        require(e.nonce()==(rejected?0:1),"NONCE");
        require(TokenV3(WETH).balanceOf(TREASURY)-treasuryBefore==(rejected?0:back-n-fee),"TREASURY");
        require(AtomicToken(WETH).allowance(address(e),AAVE)==0 && AtomicToken(WETH).allowance(address(e),address(buy))==0 && AtomicToken(a).allowance(address(e),address(sell))==0,"EXEC_ALLOWANCE");
        require(AtomicToken(WETH).allowance(address(buy),ROUTER)==0 && AtomicToken(a).allowance(address(sell),ROUTER)==0,"ADAPTER_ALLOWANCE");
        require(TokenV3(WETH).balanceOf(address(buy))==0 && TokenV3(a).balanceOf(address(sell))==0 && TokenV3(b).balanceOf(address(sell))==0 && TokenV3(WETH).balanceOf(address(sell))==0,"ADAPTER_DUST");
        if(rejected)for(uint256 i;i<3;i++)require(_slot(pools[i])==slots[i],"POOL_ROLLBACK");
        else require(e.lastGrossProfit()==back-n-fee,"ACTUAL_GROSS");
        emit MatchedTriangle(n,back,fee,rejected,frameGas,prefund);
    }
    function testMatchedTriangleZeroPrefund() public {_check(0);}
    function testMatchedTriangleCannotSpendPrefund() public {_check(0.1 ether);}
}
