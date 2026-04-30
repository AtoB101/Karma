// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAuthTokenManager} from "../interfaces/IAuthTokenManager.sol";
import {Types} from "../libraries/Types.sol";
import {Errors} from "../libraries/Errors.sol";
import {Events} from "../libraries/Events.sol";
import {EIP712Auth} from "../libraries/EIP712Auth.sol";

contract AuthTokenManager is IAuthTokenManager {
    uint256 internal constant SECP256K1N_DIV_2 = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;

    mapping(bytes32 tokenId => Types.AuthToken) public authTokens;
    mapping(address owner => uint256) public ownerNonce;
    mapping(bytes32 digest => bool) public usedDigests;

    bytes32 internal constant EIP712_DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 internal constant NAME_HASH = keccak256("KarmaAuth");
    bytes32 internal constant VERSION_HASH = keccak256("1");

    bytes32 public immutable DOMAIN_SEPARATOR;

    constructor() {
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(EIP712_DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, block.chainid, address(this))
        );
    }

    function issueAuthToken(address agent, Types.OperationType opType, uint256 maxAmount, uint256 validitySeconds)
        external
        override
        returns (bytes32 tokenId)
    {
        if (agent == address(0)) revert Errors.InvalidAddress();
        if (maxAmount == 0 || validitySeconds == 0) revert Errors.InvalidAmount();

        uint256 nonce = ++ownerNonce[msg.sender];
        uint256 validUntil = block.timestamp + validitySeconds;
        tokenId = keccak256(abi.encodePacked(msg.sender, agent, opType, maxAmount, nonce, validUntil, block.chainid));

        authTokens[tokenId] = Types.AuthToken({
            tokenId: tokenId,
            owner: msg.sender,
            agent: agent,
            opType: opType,
            maxAmount: maxAmount,
            validUntil: validUntil,
            used: false,
            nonce: nonce
        });

        emit Events.AuthTokenIssued(tokenId, msg.sender, agent, validUntil);
    }

    function revokeAuthToken(bytes32 tokenId) external override {
        Types.AuthToken storage token = authTokens[tokenId];
        if (token.owner != msg.sender) revert Errors.Unauthorized();
        if (token.used) revert Errors.TokenUsed();

        token.used = true;
        emit Events.AuthTokenRevoked(tokenId, msg.sender);
    }

    function validateAuth(bytes32 tokenId, address agent, Types.OperationType opType, uint256 amount)
        external
        view
        override
        returns (bool)
    {
        Types.AuthToken memory token = authTokens[tokenId];
        if (token.agent != agent) return false;
        if (token.opType != opType) return false;
        if (token.used) return false;
        if (token.validUntil < block.timestamp) return false;
        if (amount > token.maxAmount) return false;
        return true;
    }

    function getAuthDigest(
        bytes32 tokenId,
        address agent,
        Types.OperationType opType,
        uint256 amount,
        uint256 deadline
    ) public view override returns (bytes32) {
        bytes32 structHash = EIP712Auth.hashAuth(tokenId, agent, uint8(opType), amount, authTokens[tokenId].nonce, deadline);
        return keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));
    }

    function consumeAuth(
        bytes32 tokenId,
        address agent,
        Types.OperationType opType,
        uint256 amount,
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external override returns (bool) {
        Types.AuthToken storage token = authTokens[tokenId];
        if (token.owner == address(0)) revert Errors.NotFound();
        if (token.agent != agent) revert Errors.InvalidToken();
        if (token.opType != opType) revert Errors.InvalidToken();
        if (token.used) revert Errors.TokenUsed();
        if (amount == 0 || amount > token.maxAmount) revert Errors.InvalidAmount();
        if (deadline < block.timestamp || token.validUntil < block.timestamp || deadline > token.validUntil) {
            revert Errors.DeadlineExpired();
        }

        bytes32 digest = getAuthDigest(tokenId, agent, opType, amount, deadline);
        if (usedDigests[digest]) revert Errors.DigestAlreadyUsed();
        if (uint256(s) > SECP256K1N_DIV_2) revert Errors.InvalidSignature();
        if (v != 27 && v != 28) revert Errors.InvalidSignature();

        address recovered = ecrecover(digest, v, r, s);
        if (recovered == address(0) || recovered != token.owner) revert Errors.InvalidSignature();

        usedDigests[digest] = true;
        token.used = true;
        return true;
    }
}
