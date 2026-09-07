// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
interface IProfitToken { function balanceOf(address) external view returns(uint256); function approve(address,uint256) external returns(bool); function transfer(address,uint256) external returns(bool); }
interface IProfitPool { function flashLoanSimple(address,address,uint256,bytes calldata,uint16) external; }
interface IProfitRouter { function factory() external view returns(address); function WETH() external view returns(address); function swapExactTokensForTokens(uint256,uint256,address[] calldata,address,uint256) external returns(uint256[] memory); }
/// @notice EXPERIMENTAL: isolated chain 31337 only. Not audited or mainnet-ready.
/// @dev gasBudget is a conservative operator-supplied WETH budget, NOT a measured fee.
contract ForkProfitExecutor {
 struct Plan { uint256 amount; uint256 minIntermediate; uint256 minReturn; uint256 maxPremium; uint256 gasBudget; uint256 minNetProfit; uint256 maxGasPrice; uint256 deadline; uint256 nonce; }
 address public immutable owner; address public immutable operator; address public immutable treasury; address public immutable pool; address public immutable borrowed; address public immutable intermediate; address public immutable buyRouter; address public immutable sellRouter; uint256 public immutable borrowCap;
 bool public paused=true; uint256 public nonce; uint256 public lastGrossProfit; uint256 public lastPremium; uint256 private stage; uint256 private baseline; bytes32 private activeHash;
 event Settled(uint256 indexed nonce,uint256 borrowedAmount,uint256 premium,uint256 grossProfit,uint256 gasBudget,uint256 minNetProfit);
 constructor(address pool_,address weth_,address token_,address[2] memory routers,address[2] memory factories,address operator_,address treasury_,uint256 cap_) {
  require(block.chainid==31337,"LOCAL_FORK_ONLY"); require(pool_.code.length>0 && weth_.code.length>0 && token_.code.length>0,"MISSING_CODE"); require(weth_!=token_ && cap_>0,"INVALID_ASSET_CAP"); require(operator_!=address(0) && treasury_!=address(0) && treasury_!=address(this),"INVALID_ROLES");
  for(uint256 i;i<2;++i) { require(routers[i].code.length>0 && factories[i].code.length>0,"MISSING_DEX_CODE"); require(IProfitRouter(routers[i]).factory()==factories[i],"WRONG_FACTORY"); require(IProfitRouter(routers[i]).WETH()==weth_,"WRONG_WETH"); }
  owner=msg.sender; operator=operator_; treasury=treasury_; pool=pool_; borrowed=weth_; intermediate=token_; buyRouter=routers[0]; sellRouter=routers[1]; borrowCap=cap_;
 }
 function setPaused(bool value) external { require(msg.sender==owner && stage==0,"OWNER_IDLE_ONLY"); paused=value; }
 function run(Plan calldata p) external {
  require(block.chainid==31337 && msg.sender==operator && stage==0,"OPERATOR_CHAIN_IDLE"); require(!paused,"PAUSED"); require(p.amount>0 && p.amount<=borrowCap && p.minIntermediate>0 && p.minReturn>0,"AMOUNT_LIMIT"); require(p.gasBudget>0 && p.minNetProfit>0 && p.maxGasPrice>0,"PROFIT_BUDGET_REQUIRED"); require(tx.gasprice<=p.maxGasPrice,"GAS_PRICE"); require(p.deadline>=block.timestamp && p.deadline<=block.timestamp+120,"DEADLINE"); require(p.nonce==nonce+1,"NONCE");
  baseline=IProfitToken(borrowed).balanceOf(address(this)); nonce=p.nonce; bytes memory params=abi.encode(p); activeHash=keccak256(params); stage=1; IProfitPool(pool).flashLoanSimple(address(this),borrowed,p.amount,params,0);
  require(stage==3,"MISSING_CALLBACK"); require(IProfitToken(borrowed).balanceOf(address(this))==baseline+lastGrossProfit,"REPAYMENT_MISMATCH"); _approve(borrowed,pool,0); _call(borrowed,abi.encodeCall(IProfitToken.transfer,(treasury,lastGrossProfit))); require(IProfitToken(borrowed).balanceOf(address(this))==baseline,"BASELINE_CHANGED"); activeHash=bytes32(0); baseline=0; stage=0; emit Settled(p.nonce,p.amount,lastPremium,lastGrossProfit,p.gasBudget,p.minNetProfit);
 }
 function executeOperation(address asset,uint256 amount,uint256 premium,address initiator,bytes calldata params) external returns(bool) {
  require(msg.sender==pool && initiator==address(this) && stage==1,"CALLBACK_AUTH"); require(keccak256(params)==activeHash,"PLAN_MISMATCH"); Plan memory p=abi.decode(params,(Plan)); require(asset==borrowed && amount==p.amount && premium<=p.maxPremium,"LOAN_MISMATCH"); require(IProfitToken(borrowed).balanceOf(address(this))==baseline+amount,"LOAN_NOT_DELIVERED"); stage=2;
  uint256 oldIntermediate=IProfitToken(intermediate).balanceOf(address(this)); uint256 received=_swap(buyRouter,borrowed,intermediate,amount,p.minIntermediate,p.deadline); uint256 returned=_swap(sellRouter,intermediate,borrowed,received,p.minReturn,p.deadline);
  require(returned>=amount+premium+p.gasBudget+p.minNetProfit,"UNPROFITABLE_ROUTE"); require(IProfitToken(intermediate).balanceOf(address(this))==oldIntermediate,"INTERMEDIATE_CHANGED"); require(IProfitToken(borrowed).balanceOf(address(this))==baseline+returned,"ROUTE_BALANCE_MISMATCH"); lastGrossProfit=returned-amount-premium; lastPremium=premium; _approve(borrowed,pool,amount+premium); stage=3; return true;
 }
 function sweep(address token,uint256 amount) external { require(msg.sender==owner && paused && stage==0,"PAUSED_OWNER_IDLE_ONLY"); _call(token,abi.encodeCall(IProfitToken.transfer,(treasury,amount))); }
 function _swap(address router,address input,address output,uint256 amount,uint256 minimum,uint256 deadline) private returns(uint256 received) {
  address[] memory path=new address[](2); path[0]=input; path[1]=output; uint256 inputBefore=IProfitToken(input).balanceOf(address(this)); uint256 outputBefore=IProfitToken(output).balanceOf(address(this)); _approve(input,router,0); _approve(input,router,amount); IProfitRouter(router).swapExactTokensForTokens(amount,minimum,path,address(this),deadline); _approve(input,router,0); require(IProfitToken(input).balanceOf(address(this))+amount==inputBefore,"INPUT_NOT_CONSUMED"); received=IProfitToken(output).balanceOf(address(this))-outputBefore; require(received>=minimum,"MIN_OUTPUT");
 }
 function _approve(address token,address spender,uint256 amount) private { _call(token,abi.encodeCall(IProfitToken.approve,(spender,amount))); }
 function _call(address token,bytes memory data) private { require(token.code.length>0,"TOKEN_NO_CODE"); (bool ok,bytes memory result)=token.call(data); require(ok && (result.length==0 || (result.length==32 && abi.decode(result,(bool)))),"TOKEN_CALL_FAILED"); }
}
