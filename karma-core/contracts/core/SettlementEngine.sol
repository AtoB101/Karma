// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ISettlementEngine} from "../interfaces/ISettlementEngine.sol";
import {IERC20} from "../interfaces/IERC20.sol";
import {QuoteTypes} from "../libraries/QuoteTypes.sol";
import {QuoteEIP712} from "../libraries/QuoteEIP712.sol";
import {Errors} from "../libraries/Errors.sol";

contract SettlementEngine is ISettlementEngine {
    uint256 internal constant SECP256K1N_DIV_2 = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;

    address public immutable admin;
    bool public paused;

    mapping(address token => bool allowed) public tokenAllowed;
    mapping(address payer => uint256 nonce) public override nonces;
    mapping(bytes32 quoteId => bool executed) public override executedQuotes;

    bytes32 internal constant EIP712_DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 internal constant NAME_HASH = keccak256("KarmaSettlementEngine");
    bytes32 internal constant VERSION_HASH = keccak256("1");
    bytes32 public immutable DOMAIN_SEPARATOR;

    event SettlementSubmitted(bytes32 indexed quoteId, address indexed payer, address indexed payee, uint256 amount);
    event SettlementSucceeded(bytes32 indexed quoteId, address indexed token, uint256 amount, uint256 nonce);
    event TokenAllowlistUpdated(address indexed token, bool allowed);
    event Paused(address indexed by);
    event Unpaused(address indexed by);

    constructor(address admin_) {
        if (admin_ == address(0)) revert Errors.InvalidAddress();
        admin = admin_;
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(EIP712_DOMAIN_TYPEHASH, NAME_HASH, VERSION_HASH, block.chainid, address(this))
        );
    }

    function submitSettlement(QuoteTypes.Quote calldata quote, uint8 v, bytes32 r, bytes32 s) external override {
        _submitSettlement(quote, v, r, s);
    }

    function settleBatch(
        QuoteTypes.Quote[] calldata quotes,
        uint8[] calldata vs,
        bytes32[] calldata rs,
        bytes32[] calldata ss
    ) external override {
        uint256 length = quotes.length;
        if (length == 0 || length != vs.length || length != rs.length || length != ss.length) {
            revert Errors.InvalidBatchInput();
        }

        for (uint256 i = 0; i < length; ++i) {
            _submitSettlement(quotes[i], vs[i], rs[i], ss[i]);
        }
    }

    function _submitSettlement(QuoteTypes.Quote calldata quote, uint8 v, bytes32 r, bytes32 s) internal {
        if (uint256(s) > SECP256K1N_DIV_2) revert Errors.InvalidSignature();
        if (v != 27 && v != 28) revert Errors.InvalidSignature();
        if (paused) revert Errors.EnginePaused();
        if (!tokenAllowed[quote.token]) revert Errors.TokenNotAllowed();
        if (quote.payer == address(0) || quote.payee == address(0) || quote.amount == 0) revert Errors.InvalidAmount();
        if (quote.deadline < block.timestamp) revert Errors.DeadlineExpired();
        if (executedQuotes[quote.quoteId]) revert Errors.QuoteAlreadyExecuted();
        if (nonces[quote.payer] != quote.nonce) revert Errors.InvalidNonce();

        bytes32 digest = getQuoteDigest(quote);
        address recovered = ecrecover(digest, v, r, s);
        if (recovered == address(0) || recovered != quote.payer) revert Errors.InvalidSignature();

        emit SettlementSubmitted(quote.quoteId, quote.payer, quote.payee, quote.amount);
        executedQuotes[quote.quoteId] = true;
        unchecked {
            nonces[quote.payer] = quote.nonce + 1;
        }

        if (!IERC20(quote.token).transferFrom(quote.payer, quote.payee, quote.amount)) {
            revert Errors.TokenTransferFailed();
        }
        emit SettlementSucceeded(quote.quoteId, quote.token, quote.amount, quote.nonce);
    }

    function getQuoteDigest(QuoteTypes.Quote calldata quote) public view override returns (bytes32) {
        bytes32 structHash = QuoteEIP712.hashQuote(quote);
        return keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));
    }

    function setTokenAllowed(address token, bool allowed) external override {
        if (msg.sender != admin) revert Errors.Unauthorized();
        if (token == address(0)) revert Errors.InvalidAddress();
        tokenAllowed[token] = allowed;
        emit TokenAllowlistUpdated(token, allowed);
    }

    function pause() external override {
        if (msg.sender != admin) revert Errors.Unauthorized();
        paused = true;
        emit Paused(msg.sender);
    }

    function unpause() external override {
        if (msg.sender != admin) revert Errors.Unauthorized();
        paused = false;
        emit Unpaused(msg.sender);
    }
}
