// SPDX-License-Identifier: MIT
/*
 * Karma Trust Protocol — Certora (CVL2)
 * Contract: AuthTokenManager.sol
 *
 * Single, consistent typing for authTokens(bytes32) public getter return tuple.
 */
import "contracts/libraries/Types.sol";

methods {
    function DOMAIN_SEPARATOR() external returns (bytes32) envfree;
    function authTokens(bytes32)
        external
        returns (bytes32, address, address, Types.OperationType, uint256, uint256, bool, uint256)
        envfree;
    function issueAuthToken(address, Types.OperationType, uint256, uint256) external returns (bytes32);
    function revokeAuthToken(bytes32) external;
}

// ── Issue with zero agent must revert ──────────────────────────────────────
rule issueZeroAgentReverts(Types.OperationType opType, uint256 maxAmount, uint256 validitySeconds) {
    env e;
    require maxAmount > 0;
    require validitySeconds > 0;
    issueAuthToken@withrevert(e, address(0), opType, maxAmount, validitySeconds);
    assert lastReverted, "Zero agent must revert on issueAuthToken";
}
