// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {ForkV3ReturnAdapter,IReturnRouter} from "../src/ForkV3ReturnAdapter.sol";
import {AdapterFactory,VmAdapter} from "./ForkV3Adapter.t.sol";
import {MockToken} from "./FlashLoanProbe.t.sol";
interface IMultiSelector {function quoteExactInput(bytes calldata,uint256) external returns(uint256);}
contract ReturnMockRouter is IReturnRouter {
    address public immutable factory;address public immutable WETH9;address public immutable input;
    uint256 public mode;bytes public lastPath;
    constructor(address f,address w,address a){factory=f;WETH9=w;input=a;}
    function configure(uint256 m) external {mode=m;}
    function exactInput(ExactInputParams calldata p) external payable returns(uint256) {
        lastPath=p.path;
        if(mode!=1)MockToken(input).transferFrom(msg.sender,address(this),p.amountIn);
        uint256 out=p.amountIn*2;
        if(mode!=2)MockToken(WETH9).transfer(p.recipient,out);
        return mode==3?out+1:out;
    }
}
contract ForkV3ReturnAdapterTest {
    VmAdapter constant vm=VmAdapter(address(uint160(uint256(keccak256("hevm cheat code")))));
    MockToken w;MockToken a;MockToken b;AdapterFactory f;ReturnMockRouter r;ForkV3ReturnAdapter adapter;
    function setUp() public {
        vm.chainId(31337);w=new MockToken();a=new MockToken();b=new MockToken();f=new AdapterFactory();
        f.create(address(a),address(b),100);f.create(address(b),address(w),500);
        r=new ReturnMockRouter(address(f),address(w),address(a));
        adapter=new ForkV3ReturnAdapter(address(r),address(f),address(w),address(a),address(b),100,500);
        a.mint(address(this),10000);w.mint(address(r),100000);a.approve(address(adapter),10000);
    }
    function path() private view returns(address[] memory p){p=new address[](2);p[0]=address(a);p[1]=address(w);}
    function swap() private returns(uint256[] memory){return adapter.swapExactTokensForTokens(100,200,path(),address(this),block.timestamp);}
    function testExactPathOutputAndZeroAllowance() public {
        uint256[] memory out=swap();require(out[1]==200 && w.balanceOf(address(this))==200);
        require(keccak256(r.lastPath())==keccak256(abi.encodePacked(address(a),uint24(100),address(b),uint24(500),address(w))));
        require(a.allowance(address(adapter),address(r))==0);
    }
    function testPrefundedAllTokensPreserved() public {a.mint(address(adapter),7);b.mint(address(adapter),8);w.mint(address(adapter),9);swap();require(a.balanceOf(address(adapter))==7 && b.balanceOf(address(adapter))==8 && w.balanceOf(address(adapter))==9);}
    function testInputNotConsumedRejected() public {r.configure(1);vm.expectRevert();swap();}
    function testOutputMissingRejected() public {r.configure(2);vm.expectRevert();swap();}
    function testFakeReportedOutputRejected() public {r.configure(3);vm.expectRevert();swap();}
    function testMissingPoolRejected() public {vm.expectRevert();new ForkV3ReturnAdapter(address(r),address(f),address(w),address(a),address(b),3000,500);}
    function testWrongPoolTokensRejected() public {vm.expectRevert();new ForkV3ReturnAdapter(address(r),address(f),address(w),address(b),address(a),100,500);}
    function testDuplicateTokenRejected() public {vm.expectRevert();new ForkV3ReturnAdapter(address(r),address(f),address(w),address(a),address(a),100,500);}
    function testMainnetDeploymentBlocked() public {vm.chainId(42161);vm.expectRevert();new ForkV3ReturnAdapter(address(r),address(f),address(w),address(a),address(b),100,500);}
    function testMainnetCallBlocked() public {address[] memory p=path();vm.chainId(42161);vm.expectRevert();adapter.swapExactTokensForTokens(100,1,p,address(this),block.timestamp);}
    function testWrongRecipientRejected() public {address[] memory p=path();vm.expectRevert();adapter.swapExactTokensForTokens(100,1,p,address(123),block.timestamp);}
    function testWrongDirectionRejected() public {address[] memory p=path();p[0]=address(w);p[1]=address(a);vm.expectRevert();adapter.swapExactTokensForTokens(100,1,p,address(this),block.timestamp);}
    function testZeroMinimumRejected() public {address[] memory p=path();vm.expectRevert();adapter.swapExactTokensForTokens(100,0,p,address(this),block.timestamp);}
    function testLongDeadlineRejected() public {address[] memory p=path();vm.expectRevert();adapter.swapExactTokensForTokens(100,1,p,address(this),block.timestamp+121);}
    function testApprovalFailureRejected() public {a.reject(true);vm.expectRevert();swap();}
    function testMultiQuoteSelectorMatchesPython() public pure {require(IMultiSelector.quoteExactInput.selector==bytes4(hex'cdca1753'));}
    function testFuzzBaselines(uint64 n) public {a.mint(address(adapter),n);b.mint(address(adapter),n);w.mint(address(adapter),n);swap();require(a.balanceOf(address(adapter))==n && b.balanceOf(address(adapter))==n && w.balanceOf(address(adapter))==n);}
}
