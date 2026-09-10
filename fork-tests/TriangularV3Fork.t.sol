// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {V3PathDecoder} from "../src/V3PathDecoder.sol";
interface TriangleVm { function deal(address,uint256) external; function envBytes(string calldata) external returns(bytes memory); function envUint(string calldata) external returns(uint256); }
interface TriangleToken { function deposit() external payable; function approve(address,uint256) external returns(bool); function balanceOf(address) external view returns(uint256); function allowance(address,address) external view returns(uint256); }
interface TriangleFactory { function getPool(address,address,uint24) external view returns(address); }
interface TriangleQuoter { function quoteExactInput(bytes memory,uint256) external returns(uint256,uint160[] memory,uint32[] memory,uint256); }
interface TriangleRouter {
 struct ExactInputParams { bytes path; address recipient; uint256 deadline; uint256 amountIn; uint256 amountOutMinimum; }
 function exactInput(ExactInputParams memory) external payable returns(uint256);
}
interface TriangleAave {
 function flashLoanSimple(address,address,uint256,bytes memory,uint16) external;
 function FLASHLOAN_PREMIUM_TOTAL() external view returns(uint128);
}
abstract contract TriangleAddresses {
 address constant WETH=address(bytes20(hex'82af49447d8a07e3bd95bd0d56f35241523fbab1'));
 address constant USDC=address(bytes20(hex'af88d065e77c8cc2239327c5edb3a432268e5831'));
 address constant USDCE=address(bytes20(hex'ff970a61a04b1ca14834a43f5de4533ebddb5cc8'));
 address constant FACTORY=address(bytes20(hex'1f98431c8ad98523631ae4a59f267346ea31f984'));
 address constant QUOTER=address(bytes20(hex'61ffe014ba17989e743c5f6cb21bf9697530b21e'));
 address constant ROUTER=address(bytes20(hex'e592427a0aece92de3edee1f18e0157c05861564'));
 address constant AAVE=address(bytes20(hex'794a61358d6845594f94dc1db02a252b5b4814ad'));
 // Bounded high-level decoding permits compiler memory spilling without claiming unsafe mload is safe.
 function tokenAt(bytes memory path,uint256 index) internal pure returns(address) { return V3PathDecoder.tokenAt(path,index); }
 function feeAt(bytes memory path,uint256 index) internal pure returns(uint24) { return V3PathDecoder.feeAt(path,index); }
 function validatePath(bytes memory path) internal view {
  require(block.chainid==31337 && path.length==89,'LOCAL_CYCLE_ONLY');
  require(tokenAt(path,0)==WETH && tokenAt(path,3)==WETH,'ENDPOINTS');
  address a=tokenAt(path,1); address b=tokenAt(path,2);
  require((a==USDC && b==USDCE)||(a==USDCE && b==USDC),'STABLE_IDENTITIES');
  address[3] memory pools;
  for(uint256 i;i<3;i++) {
   uint24 f=feeAt(path,i);require(f==100||f==500||f==3000,'FEE');
   pools[i]=TriangleFactory(FACTORY).getPool(tokenAt(path,i),tokenAt(path,i+1),f);
   require(pools[i].code.length>0,'POOL_CODE');
  }
  require(pools[0]!=pools[1] && pools[0]!=pools[2] && pools[1]!=pools[2],'DISTINCT_POOLS');
 }
}
/// @notice Test-only receiver: local chain 31337, no user funds, no production deployment.
contract LocalTriangleReceiver is TriangleAddresses {
 address immutable owner;
 bytes route;
 bool active;
 bytes32 plan;
 constructor(bytes memory path) { validatePath(path); owner=msg.sender; route=path; }
 function start(uint256 amount,uint256 minimumOut,uint256 minimumProfit) external {
  require(block.chainid==31337 && msg.sender==owner && !active,'AUTH');
  require(amount>0 && minimumOut>0 && minimumProfit>0,'LIMITS');
  require(TriangleToken(WETH).balanceOf(address(this))==0,'EMPTY_RECEIVER_REQUIRED');
  bytes memory params=abi.encode(minimumOut,minimumProfit);
  plan=keccak256(abi.encode(amount,params));active=true;
  TriangleAave(AAVE).flashLoanSimple(address(this),WETH,amount,params,0);
  require(TriangleToken(WETH).balanceOf(address(this))>=minimumProfit,'FINAL_PROFIT');
  require(TriangleToken(WETH).allowance(address(this),AAVE)==0,'REPAYMENT_ALLOWANCE');
  active=false;delete plan;
 }
 function executeOperation(address asset,uint256 amount,uint256 premium,address initiator,bytes calldata params) external returns(bool) {
  require(block.chainid==31337 && active && msg.sender==AAVE && initiator==address(this) && asset==WETH,'CALLBACK');
  require(plan==keccak256(abi.encode(amount,params)),'PLAN');
  require(TriangleToken(WETH).balanceOf(address(this))==amount,'LOAN_DELIVERY');
  (uint256 minimumOut,uint256 minimumProfit)=abi.decode(params,(uint256,uint256));
  require(TriangleToken(WETH).approve(ROUTER,amount),'APPROVE');
  uint256 actual=TriangleRouter(ROUTER).exactInput(TriangleRouter.ExactInputParams(route,address(this),block.timestamp,amount,minimumOut));
  require(TriangleToken(WETH).approve(ROUTER,0),'CLEAR');
  uint256 balance=TriangleToken(WETH).balanceOf(address(this));require(balance==actual,'ACTUAL_BALANCE');
  require(balance>=amount+premium+minimumProfit,'UNPROFITABLE_TRIANGLE');
  require(TriangleToken(WETH).approve(AAVE,amount+premium),'REPAY_APPROVE');
  return true;
 }
}
contract TriangularV3ForkTest is TriangleAddresses {
 TriangleVm constant vm=TriangleVm(address(uint160(uint256(keccak256('hevm cheat code')))));
 event TriangleQuoteMatched(uint256 input,uint256 output,bytes path);
 event TriangleFlashResult(uint256 amount,uint256 premium,uint256 expectedOutput,bool executedWithPositiveDelta);
 function selected() private returns(bytes memory path,uint256 amount,uint256 expected) {
  path=vm.envBytes('TRI_PATH');amount=vm.envUint('TRI_AMOUNT');expected=vm.envUint('TRI_EXPECTED');validatePath(path);
  require(amount==0.001 ether||amount==0.01 ether||amount==0.1 ether,'SIZE');
  (uint256 quote,uint160[] memory prices,uint32[] memory ticks,)=TriangleQuoter(QUOTER).quoteExactInput(path,amount);
  require(quote==expected && prices.length==3 && ticks.length==3,'PINNED_QUOTE_MISMATCH');
 }
 function testPythonMultihopSelectorMatchesSolidity() public pure {
  require(TriangleQuoter.quoteExactInput.selector==bytes4(0xcdca1753),'ABI_SELECTOR');
 }
 function testSelectedTriangleQuoteMatchesActualThreeSwaps() public {
  (bytes memory path,uint256 amount,uint256 expected)=selected();
  // Only this local test gets ETH for mechanical swap validation. Protocol state is not overridden.
  vm.deal(address(this),amount);TriangleToken(WETH).deposit{value:amount}();
  uint256 beforeWeth=TriangleToken(WETH).balanceOf(address(this));
  uint256 beforeA=TriangleToken(USDC).balanceOf(address(this));uint256 beforeB=TriangleToken(USDCE).balanceOf(address(this));
  require(TriangleToken(WETH).approve(ROUTER,amount),'APPROVE');
  uint256 actual=TriangleRouter(ROUTER).exactInput(TriangleRouter.ExactInputParams(path,address(this),block.timestamp,amount,expected));
  require(TriangleToken(WETH).approve(ROUTER,0),'CLEAR');
  require(actual==expected && TriangleToken(WETH).balanceOf(address(this))==beforeWeth-amount+expected,'BALANCE_MATCH');
  require(TriangleToken(USDC).balanceOf(address(this))==beforeA && TriangleToken(USDCE).balanceOf(address(this))==beforeB,'DUST');
  emit TriangleQuoteMatched(amount,actual,path);
 }
 function testTriangleFlashLoanAcceptsOnlyPositiveDelta() public {
  (bytes memory path,uint256 amount,uint256 expected)=selected();
  uint256 fee=(amount*TriangleAave(AAVE).FLASHLOAN_PREMIUM_TOTAL()+5000)/10000;
  LocalTriangleReceiver receiver=new LocalTriangleReceiver(path);
  require(TriangleToken(WETH).balanceOf(address(receiver))==0,'NOT_SEEDED');
  (bool ok,bytes memory data)=address(receiver).call(abi.encodeCall(receiver.start,(amount,expected,1)));
  if(expected>amount+fee) {
   require(ok,'POSITIVE_FORK_CALL_FAILED');
   require(TriangleToken(WETH).balanceOf(address(receiver))==expected-amount-fee,'NET_BALANCE');
  } else {
   require(!ok && keccak256(data)==keccak256(abi.encodeWithSignature('Error(string)','UNPROFITABLE_TRIANGLE')),'EXPECTED_PROFIT_REJECTION');
   require(TriangleToken(WETH).balanceOf(address(receiver))==0,'REVERT_BASELINE');
  }
  emit TriangleFlashResult(amount,fee,expected,ok);
 }
}
