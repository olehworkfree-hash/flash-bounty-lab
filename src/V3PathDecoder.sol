// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice Bounded decoder for packed V3 paths. No assembly and no reads past bytes.length.
/// @dev Shape: token(20) + (fee(3) + token(20))*hops; accepts at least one hop.
library V3PathDecoder {
    function hops(bytes memory path) internal pure returns (uint256) {
        require(path.length >= 43 && (path.length - 20) % 23 == 0, "PATH_SHAPE");
        return (path.length - 20) / 23;
    }

    function tokenAt(bytes memory path, uint256 index) internal pure returns (address) {
        uint256 count = hops(path);
        require(index <= count, "TOKEN_INDEX");
        uint256 offset = index * 23; // index is bounded by path.length before multiplication
        uint160 value;
        for (uint256 i; i < 20; ++i) {
            value = (value << 8) | uint160(uint8(path[offset + i]));
        }
        return address(value);
    }

    function feeAt(bytes memory path, uint256 index) internal pure returns (uint24) {
        uint256 count = hops(path);
        require(index < count, "FEE_INDEX");
        uint256 offset = index * 23 + 20;
        uint24 value;
        for (uint256 i; i < 3; ++i) {
            value = (value << 8) | uint24(uint8(path[offset + i]));
        }
        return value;
    }
}
