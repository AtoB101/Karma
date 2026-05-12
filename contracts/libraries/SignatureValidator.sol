// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

library SignatureValidator {
    uint256 internal constant SECP256K1N_DIV_2 =
        0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;

    function recoverStrict(bytes32 digest, uint8 v, bytes32 r, bytes32 s) internal pure returns (address) {
        if (uint256(r) == 0 || uint256(s) == 0) return address(0);
        if (uint256(s) > SECP256K1N_DIV_2) return address(0);
        if (v != 27 && v != 28) return address(0);
        return ecrecover(digest, v, r, s);
    }
}
