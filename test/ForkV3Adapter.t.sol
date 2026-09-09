// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {ForkV3Adapter, IV3AdapterRouter} from "../src/ForkV3Adapter.sol";
import {ForkProfitExecutor} from "../src/ForkProfitExecutor.sol";
import {MockToken} from "./FlashLoanProbe.t.sol";
import {ProfitPool} from "./ForkProfitExecutor.t.sol";
interface VmAdapter { function chainId(uint256) external; function expectRevert() external; function txGasPrice(uint256) external; }
contract AdapterPair {
    address public factory; address public token0; address public token1; uint24 public fee;
    constructor(address a,address b,uint24 f) { factory=msg.sender; token0=a; token1=b; fee=f; }
}
contract AdapterFactory {
    mapping(uint24=>address) public pools;
    function create(address a,address b,uint24 f) external { pools[f]=address(new AdapterPair(a,b,f)); }
    function getPool(address,address,uint24 f) external view returns(address) { return pools[f]; }
}
contract AdapterRouter is IV3AdapterRouter {
    address public immutable factory; address public immutable WETH9;
    uint256 public mode;
    constructor(address f,address w) { factory=f; WETH9=w; }
    function configure(uint256 m) external { mode=m; }
    function exactInputSingle(ExactInputSingleParams calldata p) external payable returns(uint256 out) {
        if(mode!=1) MockToken(p.tokenIn).transferFrom(msg.sender,address(this),p.amountIn);
        out=p.tokenIn==WETH9 ? p.amountIn*2 : p.amountIn*(mode==4 ? 4 : 6)/10;
        if(mode!=2) MockToken(p.tokenOut).transfer(p.recipient,out);
        if(mode==3) return type(uint256).max;
    }
}
contract ForkV3AdapterTest {
    VmAdapter constant vm=VmAdapter(address(uint160(uint256(keccak256("hevm cheat code")))));
    MockToken weth; MockToken token; AdapterFactory factory; AdapterRouter router;
    ForkV3Adapter buy; ForkV3Adapter sell; ProfitPool pool; ForkProfitExecutor executor;
    address constant TREASURY=address(0xBEEF);
    function setUp() public {
        vm.chainId(31337); vm.txGasPrice(1);
        weth=new MockToken(); token=new MockToken(); factory=new AdapterFactory();
        factory.create(address(weth),address(token),500); factory.create(address(weth),address(token),3000);
        router=new AdapterRouter(address(factory),address(weth));
        buy=new ForkV3Adapter(address(router),address(factory),address(weth),address(token),500);
        sell=new ForkV3Adapter(address(router),address(factory),address(weth),address(token),3000);
        pool=new ProfitPool();
        executor=new ForkProfitExecutor(address(pool),address(weth),address(token),[address(buy),address(sell)],
            [address(factory),address(factory)],address(this),TREASURY,1000000);
        weth.mint(address(pool),100000000); weth.mint(address(router),100000000); token.mint(address(router),100000000);
        executor.setPaused(false);
    }
    function plan() private view returns(ForkProfitExecutor.Plan memory) {
        return ForkProfitExecutor.Plan(10000,1,1,5,100,100,10,block.timestamp+60,1);
    }
    function reject() private { vm.expectRevert(); executor.run(plan()); }
    function path() private view returns(address[] memory p) { p=new address[](2); p[0]=address(weth); p[1]=address(token); }
    function testAtomicLoanRepaymentAndTreasury() public {
        executor.run(plan()); require(weth.balanceOf(TREASURY)==1995 && weth.balanceOf(address(pool))==100000005);
        require(weth.allowance(address(executor),address(buy))==0 && token.allowance(address(executor),address(sell))==0);
        require(weth.allowance(address(buy),address(router))==0 && token.allowance(address(sell),address(router))==0);
    }
    function testAdapterDustAndExecutorBaselinesPreserved() public {
        weth.mint(address(buy),77); token.mint(address(buy),88); weth.mint(address(sell),99); token.mint(address(sell),111);
        weth.mint(address(executor),1234); token.mint(address(executor),4321);
        executor.run(plan()); require(weth.balanceOf(address(buy))==77 && token.balanceOf(address(buy))==88);
        require(weth.balanceOf(address(sell))==99 && token.balanceOf(address(sell))==111);
        require(weth.balanceOf(address(executor))==1234 && token.balanceOf(address(executor))==4321);
    }
    function testLosingRouteCannotUsePrefund() public {
        router.configure(4); weth.mint(address(executor),1000000); reject();
        require(weth.balanceOf(address(executor))==1000000 && executor.nonce()==0);
    }
    function testInputNotConsumedRejected() public { router.configure(1); reject(); }
    function testOutputNotDeliveredRejected() public { router.configure(2); reject(); }
    function testFakeOutputRejected() public { router.configure(3); reject(); }
    function testApprovalFailureRejected() public { weth.reject(true); reject(); }
    function testRecipientSubstitutionRejected() public { address[] memory p=path(); vm.expectRevert(); buy.swapExactTokensForTokens(1,1,p,TREASURY,block.timestamp); }
    function testUnrelatedTokenRejected() public { address[] memory p=path(); p[1]=address(pool); vm.expectRevert(); buy.swapExactTokensForTokens(1,1,p,address(this),block.timestamp); }
    function testZeroMinimumRejected() public { address[] memory p=path(); vm.expectRevert(); buy.swapExactTokensForTokens(1,0,p,address(this),block.timestamp); }
    function testLongDeadlineRejected() public { address[] memory p=path(); vm.expectRevert(); buy.swapExactTokensForTokens(1,1,p,address(this),block.timestamp+121); }
    function testWrongChainDeployRejected() public { vm.chainId(42161); vm.expectRevert(); new ForkV3Adapter(address(router),address(factory),address(weth),address(token),500); }
    function testMissingPoolRejected() public { vm.expectRevert(); new ForkV3Adapter(address(router),address(factory),address(weth),address(token),100); }
    function testWrongFactoryRejected() public { vm.expectRevert(); new ForkV3Adapter(address(router),address(pool),address(weth),address(token),500); }
    function testNonceReplayRejected() public { executor.run(plan()); reject(); }
    function testFuzzAdapterBaseline(uint64 dust) public {
        weth.mint(address(buy),dust); token.mint(address(sell),dust); executor.run(plan());
        require(weth.balanceOf(address(buy))==dust && token.balanceOf(address(sell))==dust && weth.balanceOf(TREASURY)==1995);
    }
}
