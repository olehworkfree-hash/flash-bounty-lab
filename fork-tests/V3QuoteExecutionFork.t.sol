// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
interface VmV3 { function deal(address,uint256) external; }
interface TokenV3 { function deposit() external payable; function approve(address,uint256) external returns(bool); function balanceOf(address) external view returns(uint256); }
interface FactoryV3 { function getPool(address,address,uint24) external view returns(address); }
interface PoolV3 { function liquidity() external view returns(uint128); }
interface QuoterV3 {
 struct QuoteExactInputSingleParams { address tokenIn; address tokenOut; uint256 amountIn; uint24 fee; uint160 sqrtPriceLimitX96; }
 function quoteExactInputSingle(QuoteExactInputSingleParams memory) external returns(uint256,uint160,uint32,uint256);
}
interface RouterV3 {
 struct ExactInputSingleParams { address tokenIn; address tokenOut; uint24 fee; address recipient; uint256 deadline; uint256 amountIn; uint256 amountOutMinimum; uint160 sqrtPriceLimitX96; }
 function exactInputSingle(ExactInputSingleParams memory) external payable returns(uint256);
}
contract V3QuoteExecutionForkTest {
 VmV3 constant vm=VmV3(address(uint160(uint256(keccak256('hevm cheat code')))));
 address constant WETH=address(bytes20(hex'82af49447d8a07e3bd95bd0d56f35241523fbab1'));
 address constant USDC=address(bytes20(hex'af88d065e77c8cc2239327c5edb3a432268e5831'));
 address constant USDCE=address(bytes20(hex'ff970a61a04b1ca14834a43f5de4533ebddb5cc8'));
 address constant FACTORY=address(bytes20(hex'1f98431c8ad98523631ae4a59f267346ea31f984'));
 address constant QUOTER=address(bytes20(hex'61ffe014ba17989e743c5f6cb21bf9697530b21e'));
 address constant ROUTER=address(bytes20(hex'e592427a0aece92de3edee1f18e0157c05861564'));
 event MatchedActualSwaps(address token,uint24 firstFee,uint24 secondFee,uint256 amountIn,uint256 middle,uint256 returnedAmount);
 function testPythonSelectorMatchesSolidity() public pure { require(QuoterV3.quoteExactInputSingle.selector==bytes4(0xc6a5026a),'ABI_SELECTOR'); }
 function selectFees(address token) private view returns(uint24 first,uint24 second) {
  uint24[4] memory fees=[uint24(500),3000,100,10000];
  for(uint256 i;i<fees.length;i++) {
   address pool=FactoryV3(FACTORY).getPool(WETH,token,fees[i]);
   if(pool!=address(0) && PoolV3(pool).liquidity()>0) { if(first==0) first=fees[i]; else {second=fees[i]; break;} }
  }
  require(first!=0 && second!=0,'TWO_ACTIVE_POOLS_REQUIRED');
 }
 function quote(address a,address b,uint256 n,uint24 f) private returns(uint256 out) {
  (out,,,)=QuoterV3(QUOTER).quoteExactInputSingle(QuoterV3.QuoteExactInputSingleParams(a,b,n,f,0));
 }
 function swap(address a,address b,uint256 n,uint256 minOut,uint24 f) private returns(uint256) {
  return RouterV3(ROUTER).exactInputSingle(RouterV3.ExactInputSingleParams(a,b,f,address(this),block.timestamp,n,minOut,0));
 }
 function check(address token) private {
  require(block.chainid==31337,'LOCAL_FORK_ONLY');
  (uint24 first,uint24 second)=selectFees(token);
  uint256 amount=0.01 ether;
  uint256 middle=quote(WETH,token,amount,first);
  uint256 returnedAmount=quote(token,WETH,middle,second);
  // Only local test ETH is allocated. No protocol storage, prices, ticks or balances are overwritten.
  vm.deal(address(this),amount); TokenV3(WETH).deposit{value:amount}();
  uint256 beforeUsd=TokenV3(token).balanceOf(address(this)); uint256 beforeWeth=TokenV3(WETH).balanceOf(address(this));
  require(TokenV3(WETH).approve(ROUTER,amount),'APPROVE_WETH');
  uint256 actualMiddle=swap(WETH,token,amount,middle,first);
  require(actualMiddle==middle && TokenV3(token).balanceOf(address(this))-beforeUsd==middle,'FIRST_QUOTE_MISMATCH');
  require(TokenV3(token).approve(ROUTER,middle),'APPROVE_USD');
  uint256 actualReturn=swap(token,WETH,middle,returnedAmount,second);
  require(actualReturn==returnedAmount && TokenV3(WETH).balanceOf(address(this))==beforeWeth-amount+returnedAmount,'SECOND_QUOTE_MISMATCH');
  require(TokenV3(token).balanceOf(address(this))==beforeUsd,'INTERMEDIATE_DUST');
  require(TokenV3(WETH).approve(ROUTER,0) && TokenV3(token).approve(ROUTER,0),'RESET_APPROVALS');
  emit MatchedActualSwaps(token,first,second,amount,middle,returnedAmount);
 }
 function testNativeUsdcQuotesMatchTwoActualSwaps() public { check(USDC); }
 function testBridgedUsdcQuotesMatchTwoActualSwaps() public { check(USDCE); }
}
