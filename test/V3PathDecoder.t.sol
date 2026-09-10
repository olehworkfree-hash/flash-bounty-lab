// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {V3PathDecoder} from "../src/V3PathDecoder.sol";

contract PathDecoderHarness {
    function hops(bytes memory p) external pure returns (uint256) { return V3PathDecoder.hops(p); }
    function token(bytes memory p, uint256 i) external pure returns (address) { return V3PathDecoder.tokenAt(p, i); }
    function fee(bytes memory p, uint256 i) external pure returns (uint24) { return V3PathDecoder.feeAt(p, i); }
}

contract V3PathDecoderTest {
    PathDecoderHarness h = new PathDecoderHarness();

    function path3() private pure returns (bytes memory) {
        return abi.encodePacked(address(0x1234), uint24(100), address(0x5678), uint24(500), address(0x9abc), uint24(3000), address(0xdef0));
    }
    function rejects(bytes memory callData, string memory reason) private {
        (bool ok, bytes memory result) = address(h).call(callData);
        require(!ok, "MUST_REVERT");
        require(keccak256(result) == keccak256(abi.encodeWithSignature("Error(string)", reason)), "WRONG_REVERT");
    }
    function testThreeHopTokensAndFees() public view {
        bytes memory p = path3();
        require(p.length == 89 && h.hops(p) == 3, "SHAPE");
        require(h.token(p,0) == address(0x1234) && h.token(p,1) == address(0x5678), "FIRST");
        require(h.token(p,2) == address(0x9abc) && h.token(p,3) == address(0xdef0), "LAST");
        require(h.fee(p,0) == 100 && h.fee(p,1) == 500 && h.fee(p,2) == 3000, "FEES");
    }
    function testSingleHop() public view {
        bytes memory p = abi.encodePacked(address(1), uint24(500), address(2));
        require(h.hops(p) == 1 && h.token(p,1) == address(2) && h.fee(p,0) == 500, "ONE_HOP");
    }
    function testRejectEmpty() public { rejects(abi.encodeCall(h.hops, (new bytes(0))), "PATH_SHAPE"); }
    function testRejectTruncated() public { rejects(abi.encodeCall(h.hops, (new bytes(88))), "PATH_SHAPE"); }
    function testRejectTrailingByte() public { rejects(abi.encodeCall(h.hops, (new bytes(90))), "PATH_SHAPE"); }
    function testRejectTokenOnly() public { rejects(abi.encodeCall(h.hops, (new bytes(20))), "PATH_SHAPE"); }
    function testRejectTokenIndex() public { rejects(abi.encodeCall(h.token, (path3(),4)), "TOKEN_INDEX"); }
    function testRejectFeeIndex() public { rejects(abi.encodeCall(h.fee, (path3(),3)), "FEE_INDEX"); }
    function testRejectMaxTokenIndexWithoutOverflow() public { rejects(abi.encodeCall(h.token, (path3(),type(uint256).max)), "TOKEN_INDEX"); }
    function testRejectMaxFeeIndexWithoutOverflow() public { rejects(abi.encodeCall(h.fee, (path3(),type(uint256).max)), "FEE_INDEX"); }
    function testAdjacentAllocationDoesNotChangeTail() public view {
        bytes memory p = path3();
        bytes memory neighbour = new bytes(4096);
        for (uint256 i; i < neighbour.length; ++i) neighbour[i] = 0xff;
        require(h.token(p,3) == address(0xdef0) && h.fee(p,2) == 3000, "TAIL_CHANGED");
    }
    function testFuzzAllPackedFields(address a,address b,address c,address d,uint24 f0,uint24 f1,uint24 f2) public view {
        bytes memory p = abi.encodePacked(a,f0,b,f1,c,f2,d);
        require(h.token(p,0)==a && h.token(p,1)==b && h.token(p,2)==c && h.token(p,3)==d, "TOKENS");
        require(h.fee(p,0)==f0 && h.fee(p,1)==f1 && h.fee(p,2)==f2, "FEES");
    }
}
