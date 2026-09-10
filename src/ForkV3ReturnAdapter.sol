// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {IV3AdapterToken, IV3AdapterFactory, IV3AdapterPool, IV3AdapterRouter} from "./ForkV3Adapter.sol";
interface IReturnRouter {
    struct ExactInputParams { bytes path; address recipient; uint256 deadline; uint256 amountIn; uint256 amountOutMinimum; }
    function exactInput(ExactInputParams calldata) external payable returns (uint256);
}
/// @notice LOCAL chain 31337 ONLY: fixed two-hop return leg for a triangular route.
/// @dev V2-shaped transport interface; all pricing/execution is Uniswap V3.
contract ForkV3ReturnAdapter {
    address public immutable router;
    address public immutable factory;
    address public immutable WETH;
    address public immutable input;
    address public immutable viaToken;
    address public immutable firstPool;
    address public immutable secondPool;
    uint24 public immutable firstFee;
    uint24 public immutable secondFee;
    bool private entered;
    constructor(address r,address f,address w,address a,address b,uint24 fa,uint24 fb) {
        require(block.chainid==31337,"LOCAL_FORK_ONLY");
        require(r.code.length>0 && f.code.length>0,"DEX_CODE");
        require(a!=b && b!=w && a!=w && a.code.length>0 && b.code.length>0 && w.code.length>0,"TOKENS");
        require(IV3AdapterRouter(r).factory()==f && IV3AdapterRouter(r).WETH9()==w,"PERIPHERY");
        firstPool=_pool(f,a,b,fa);secondPool=_pool(f,b,w,fb);
        require(firstPool!=secondPool,"DISTINCT_POOLS");
        router=r;factory=f;WETH=w;input=a;viaToken=b;firstFee=fa;secondFee=fb;
    }
    function swapExactTokensForTokens(uint256 amount,uint256 minimum,address[] calldata path,address recipient,uint256 deadline)
        external returns(uint256[] memory amounts) {
        require(block.chainid==31337 && !entered,"CHAIN_OR_REENTRY");
        require(path.length==2 && path[0]==input && path[1]==WETH && amount>0 && minimum>0,"INPUT");
        require(recipient==msg.sender && recipient!=address(this),"RECIPIENT");
        require(deadline>=block.timestamp && deadline<=block.timestamp+120,"DEADLINE");
        entered=true;
        uint256 oldIn=IV3AdapterToken(input).balanceOf(address(this));
        uint256 oldVia=IV3AdapterToken(viaToken).balanceOf(address(this));
        uint256 oldOut=IV3AdapterToken(WETH).balanceOf(address(this));
        uint256 recipientBefore=IV3AdapterToken(WETH).balanceOf(recipient);
        _token(input,abi.encodeCall(IV3AdapterToken.transferFrom,(msg.sender,address(this),amount)));
        require(IV3AdapterToken(input).balanceOf(address(this))==oldIn+amount,"INPUT_DELIVERY");
        _token(input,abi.encodeCall(IV3AdapterToken.approve,(router,0)));
        _token(input,abi.encodeCall(IV3AdapterToken.approve,(router,amount)));
        bytes memory route=abi.encodePacked(input,firstFee,viaToken,secondFee,WETH);
        uint256 reported=IReturnRouter(router).exactInput(IReturnRouter.ExactInputParams(route,recipient,deadline,amount,minimum));
        _token(input,abi.encodeCall(IV3AdapterToken.approve,(router,0)));
        uint256 actual=IV3AdapterToken(WETH).balanceOf(recipient)-recipientBefore;
        require(actual>=minimum && actual==reported,"OUTPUT");
        require(IV3AdapterToken(input).balanceOf(address(this))==oldIn &&
            IV3AdapterToken(viaToken).balanceOf(address(this))==oldVia &&
            IV3AdapterToken(WETH).balanceOf(address(this))==oldOut,"ADAPTER_BASELINE");
        entered=false;amounts=new uint256[](2);amounts[0]=amount;amounts[1]=actual;
    }
    function _pool(address f,address a,address b,uint24 fee) private view returns(address p) {
        p=IV3AdapterFactory(f).getPool(a,b,fee);
        require(p.code.length>0 && IV3AdapterPool(p).factory()==f && IV3AdapterPool(p).fee()==fee,"POOL");
        address x=IV3AdapterPool(p).token0();address y=IV3AdapterPool(p).token1();
        require((x==a && y==b)||(x==b && y==a),"POOL_TOKENS");
    }
    function _token(address t,bytes memory data) private {
        (bool ok,bytes memory out)=t.call(data);
        require(ok && (out.length==0 || (out.length==32 && abi.decode(out,(bool)))),"TOKEN_CALL");
    }
}
