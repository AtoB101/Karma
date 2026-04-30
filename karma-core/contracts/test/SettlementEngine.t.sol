// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {SettlementEngine} from "../core/SettlementEngine.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {ReentrantERC20} from "./mocks/ReentrantERC20.sol";
import {QuoteTypes} from "../libraries/QuoteTypes.sol";
import {Errors} from "../libraries/Errors.sol";

contract SettlementEngineTest is Test {
    uint256 internal constant SECP256K1N =
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
    SettlementEngine internal engine;
    MockERC20 internal token;

    uint256 internal adminPk = 0xA11CE;
    uint256 internal payerPk = 0xB0B;
    uint256 internal payeePk = 0xCAFE;

    address internal admin;
    address internal payer;
    address internal payee;

    function setUp() public {
        admin = vm.addr(adminPk);
        payer = vm.addr(payerPk);
        payee = vm.addr(payeePk);

        engine = new SettlementEngine(admin);
        token = new MockERC20();
        token.mint(payer, 1_000_000);
        vm.prank(payer);
        token.approve(address(engine), type(uint256).max);
        vm.prank(admin);
        engine.setTokenAllowed(address(token), true);
    }

    function testSubmitSettlementSuccess() public {
        QuoteTypes.Quote memory q = _buildQuote(100, 0, block.timestamp + 1 hours);
        (uint8 v, bytes32 r, bytes32 s) = _signQuote(q, payerPk);

        uint256 payeeBefore = token.balanceOf(payee);
        engine.submitSettlement(q, v, r, s);
        uint256 payeeAfter = token.balanceOf(payee);

        assertEq(payeeAfter - payeeBefore, 100);
        assertEq(engine.nonces(payer), 1);
        assertTrue(engine.executedQuotes(q.quoteId));
    }

    function testReplayFails() public {
        QuoteTypes.Quote memory q = _buildQuote(100, 0, block.timestamp + 1 hours);
        (uint8 v, bytes32 r, bytes32 s) = _signQuote(q, payerPk);

        engine.submitSettlement(q, v, r, s);
        vm.expectRevert(Errors.QuoteAlreadyExecuted.selector);
        engine.submitSettlement(q, v, r, s);
    }

    function testExpiredDeadlineFails() public {
        QuoteTypes.Quote memory q = _buildQuote(100, 0, block.timestamp - 1);
        (uint8 v, bytes32 r, bytes32 s) = _signQuote(q, payerPk);

        vm.expectRevert(Errors.DeadlineExpired.selector);
        engine.submitSettlement(q, v, r, s);
    }

    function testInvalidSignerFails() public {
        QuoteTypes.Quote memory q = _buildQuote(100, 0, block.timestamp + 1 hours);
        (uint8 v, bytes32 r, bytes32 s) = _signQuote(q, adminPk);

        vm.expectRevert(Errors.InvalidSignature.selector);
        engine.submitSettlement(q, v, r, s);
    }

    function testInvalidNonceFails() public {
        QuoteTypes.Quote memory q = _buildQuote(100, 1, block.timestamp + 1 hours);
        (uint8 v, bytes32 r, bytes32 s) = _signQuote(q, payerPk);

        vm.expectRevert(Errors.InvalidNonce.selector);
        engine.submitSettlement(q, v, r, s);
    }

    function testPauseBlocksSettlement() public {
        vm.prank(admin);
        engine.pause();
        QuoteTypes.Quote memory q = _buildQuote(100, 0, block.timestamp + 1 hours);
        (uint8 v, bytes32 r, bytes32 s) = _signQuote(q, payerPk);

        vm.expectRevert(Errors.EnginePaused.selector);
        engine.submitSettlement(q, v, r, s);
    }

    function testTokenNotAllowedFails() public {
        MockERC20 other = new MockERC20();
        other.mint(payer, 1_000_000);
        vm.prank(payer);
        other.approve(address(engine), type(uint256).max);

        QuoteTypes.Quote memory q = QuoteTypes.Quote({
            quoteId: keccak256("quote-1"),
            payer: payer,
            payee: payee,
            token: address(other),
            amount: 100,
            nonce: 0,
            deadline: block.timestamp + 1 hours,
            scopeHash: keccak256("scope")
        });
        (uint8 v, bytes32 r, bytes32 s) = _signQuote(q, payerPk);

        vm.expectRevert(Errors.TokenNotAllowed.selector);
        engine.submitSettlement(q, v, r, s);
    }

    function testSettleBatchSuccess() public {
        QuoteTypes.Quote[] memory quotes;
        uint8[] memory vs;
        bytes32[] memory rs;
        bytes32[] memory ss;
        bytes32 id1;
        bytes32 id2;
        {
            QuoteTypes.Quote memory q1 = _buildQuote(100, 0, block.timestamp + 1 hours);
            QuoteTypes.Quote memory q2 = _buildQuote(250, 1, block.timestamp + 1 hours);
            id1 = q1.quoteId;
            id2 = q2.quoteId;
            (uint8 v1, bytes32 r1, bytes32 s1) = _signQuote(q1, payerPk);
            (uint8 v2, bytes32 r2, bytes32 s2) = _signQuote(q2, payerPk);

            quotes = new QuoteTypes.Quote[](2);
            quotes[0] = q1;
            quotes[1] = q2;

            vs = new uint8[](2);
            vs[0] = v1;
            vs[1] = v2;

            rs = new bytes32[](2);
            rs[0] = r1;
            rs[1] = r2;

            ss = new bytes32[](2);
            ss[0] = s1;
            ss[1] = s2;
        }

        engine.settleBatch(quotes, vs, rs, ss);
        assertEq(token.balanceOf(payee), 350);
        assertEq(engine.nonces(payer), 2);
        assertTrue(engine.executedQuotes(id1));
        assertTrue(engine.executedQuotes(id2));
    }

    function testSettleBatchLengthMismatchFails() public {
        QuoteTypes.Quote memory q1 = _buildQuote(100, 0, block.timestamp + 1 hours);
        (uint8 v1, bytes32 r1,) = _signQuote(q1, payerPk);

        QuoteTypes.Quote[] memory quotes = new QuoteTypes.Quote[](1);
        quotes[0] = q1;

        uint8[] memory vs = new uint8[](1);
        vs[0] = v1;

        bytes32[] memory rs = new bytes32[](1);
        rs[0] = r1;

        bytes32[] memory ss = new bytes32[](0);

        vm.expectRevert(Errors.InvalidBatchInput.selector);
        engine.settleBatch(quotes, vs, rs, ss);
    }

    function testSettleBatchTooLargeFails() public {
        uint256 batchSize = 101;
        QuoteTypes.Quote[] memory quotes = new QuoteTypes.Quote[](batchSize);
        uint8[] memory vs = new uint8[](batchSize);
        bytes32[] memory rs = new bytes32[](batchSize);
        bytes32[] memory ss = new bytes32[](batchSize);
        for (uint256 i = 0; i < batchSize; ++i) {
            QuoteTypes.Quote memory q = _buildQuote(1, i, block.timestamp + 1 hours);
            (uint8 v, bytes32 r, bytes32 s) = _signQuote(q, payerPk);
            quotes[i] = q;
            vs[i] = v;
            rs[i] = r;
            ss[i] = s;
        }
        vm.expectRevert(Errors.InvalidBatchInput.selector);
        engine.settleBatch(quotes, vs, rs, ss);
    }

    function testSettleBatchReentrancyBlocked() public {
        ReentrantERC20 reentrantToken = new ReentrantERC20();
        reentrantToken.mint(payer, 1_000_000);
        vm.prank(payer);
        reentrantToken.approve(address(engine), type(uint256).max);
        vm.prank(admin);
        engine.setTokenAllowed(address(reentrantToken), true);

        QuoteTypes.Quote memory q1 = QuoteTypes.Quote({
            quoteId: keccak256("reentrant-quote-1"),
            payer: payer,
            payee: payee,
            token: address(reentrantToken),
            amount: 100,
            nonce: 0,
            deadline: block.timestamp + 1 hours,
            scopeHash: keccak256("scope")
        });
        QuoteTypes.Quote memory q2 = QuoteTypes.Quote({
            quoteId: keccak256("reentrant-quote-2"),
            payer: payer,
            payee: payee,
            token: address(reentrantToken),
            amount: 200,
            nonce: 1,
            deadline: block.timestamp + 1 hours,
            scopeHash: keccak256("scope")
        });

        (uint8 v1, bytes32 r1, bytes32 s1) = _signQuote(q1, payerPk);
        (uint8 v2, bytes32 r2, bytes32 s2) = _signQuote(q2, payerPk);

        QuoteTypes.Quote[] memory quotes = new QuoteTypes.Quote[](2);
        quotes[0] = q1;
        quotes[1] = q2;

        uint8[] memory vs = new uint8[](2);
        vs[0] = v1;
        vs[1] = v2;

        bytes32[] memory rs = new bytes32[](2);
        rs[0] = r1;
        rs[1] = r2;

        bytes32[] memory ss = new bytes32[](2);
        ss[0] = s1;
        ss[1] = s2;

        reentrantToken.armReenter(engine, q2, v2, r2, s2);

        vm.expectRevert(Errors.InvalidState.selector);
        engine.settleBatch(quotes, vs, rs, ss);
    }

    function testRejectsZeroRSValues() public {
        QuoteTypes.Quote memory q = _buildQuote(100, 0, block.timestamp + 1 hours);
        vm.expectRevert(Errors.InvalidSignature.selector);
        engine.submitSettlement(q, 27, bytes32(0), bytes32(0));
    }

    function testHighSValueFails() public {
        QuoteTypes.Quote memory q = _buildQuote(100, 0, block.timestamp + 1 hours);
        (uint8 v, bytes32 r, bytes32 s) = _signQuote(q, payerPk);
        bytes32 highS = bytes32(SECP256K1N - uint256(s));
        uint8 flippedV = v == 27 ? 28 : 27;

        vm.expectRevert(Errors.InvalidSignature.selector);
        engine.submitSettlement(q, flippedV, r, highS);
    }

    function _buildQuote(uint256 amount, uint256 nonce, uint256 deadline)
        internal
        view
        returns (QuoteTypes.Quote memory)
    {
        return QuoteTypes.Quote({
            quoteId: keccak256(abi.encodePacked("quote", amount, nonce, deadline)),
            payer: payer,
            payee: payee,
            token: address(token),
            amount: amount,
            nonce: nonce,
            deadline: deadline,
            scopeHash: keccak256("task-scope")
        });
    }

    function _signQuote(QuoteTypes.Quote memory q, uint256 signerPk) internal view returns (uint8, bytes32, bytes32) {
        bytes32 digest = engine.getQuoteDigest(q);
        return vm.sign(signerPk, digest);
    }
}
