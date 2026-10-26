// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {TEESettlementVerifier} from "../core/TEESettlementVerifier.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @notice Proves Layer 2 TEE settlement: an enclave secp256k1 key, registered
///         after off-chain hardware-quote verification, can attest a settlement
///         EIP-712 payload and finalize a binding immediately (no dispute window).
contract TEESettlementTest is Test {
    KarmaBilateral       internal karma;
    TEESettlementVerifier internal verifier;
    MockERC20            internal usdc;

    address internal admin    = makeAddr("admin");
    address internal attester = makeAddr("attester");
    address internal buyer    = makeAddr("buyer");
    address internal agent    = makeAddr("agent");

    uint256 internal constant ENCLAVE_PK = 0xA11CE;
    address internal enclave;

    bytes32 internal constant IMAGE  = keccak256("nitro-image-pcr0");
    bytes32 internal constant IMAGE2 = keccak256("nitro-image-pcr0-v2");
    bytes32 internal constant PROOF  = keccak256("execution-proof");
    bytes32 internal constant SCOPE  = keccak256("scope");
    uint256 internal constant AMOUNT = 100_000_000; // 100 USDC

    bytes32 internal constant TEE_TYPEHASH =
        keccak256("TeeSettlement(uint256 bindingId,bytes32 proofHash,bytes32 imageHash)");

    function setUp() public {
        enclave = vm.addr(ENCLAVE_PK);

        usdc   = new MockERC20();
        karma  = new KarmaBilateral(admin);
        verifier = new TEESettlementVerifier(admin, address(karma));

        vm.prank(admin); karma.setTEEVerifier(address(verifier));
        vm.prank(admin); verifier.setAttester(attester);
        vm.prank(admin); karma.setTokenAllowed(address(usdc), true);
        vm.prank(admin); karma.setSettleDelay(0);

        usdc.mint(buyer, AMOUNT * 2);
        usdc.mint(agent, AMOUNT * 2);
        vm.prank(buyer); usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent); usdc.approve(address(karma), type(uint256).max);

        vm.prank(attester); verifier.registerEnclave(enclave, IMAGE);
    }

    // ── Helpers ─────────────────────────────────────────────────────────────

    function _digest(uint256 bindingId, bytes32 proofHash, bytes32 imageHash)
        internal view returns (bytes32)
    {
        bytes32 structHash = keccak256(abi.encode(TEE_TYPEHASH, bindingId, proofHash, imageHash));
        return keccak256(abi.encodePacked("\x19\x01", verifier.DOMAIN_SEPARATOR(), structHash));
    }

    function _attest(uint256 bindingId, bytes32 proofHash, bytes32 imageHash)
        internal view returns (bytes memory)
    {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ENCLAVE_PK, _digest(bindingId, proofHash, imageHash));
        return abi.encode(imageHash, v, r, s);
    }

    function _boundBinding() internal returns (uint256 bindingId) {
        vm.prank(buyer); uint256 buyerBill = karma.lock(address(usdc), AMOUNT);
        vm.prank(agent); uint256 agentBill = karma.lock(address(usdc), AMOUNT);
        vm.prank(buyer); bindingId = karma.bind(buyerBill, agentBill, SCOPE);
    }

    // ── Happy path ──────────────────────────────────────────────────────────

    function test_valid_attestation_settles_immediately() public {
        uint256 bindingId = _boundBinding();

        vm.prank(buyer);
        karma.settleWithTEE(bindingId, PROOF, _attest(bindingId, PROOF, IMAGE));

        KarmaBilateral.Binding memory b = karma.getBinding(bindingId);
        assertEq(uint256(b.state), uint256(KarmaBilateral.BindingState.SETTLED));
        // No fee bridge: full pool (200 USDC) goes to seller; buyer gets nothing back.
        assertEq(usdc.balanceOf(buyer), AMOUNT);          // 200 - 100 locked
        assertEq(usdc.balanceOf(agent), AMOUNT * 3);      // 200 - 100 locked + 200 payout
        assertEq(karma.totalLocked(address(usdc)), 0);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    // ── Rejection paths ─────────────────────────────────────────────────────

    function test_reverts_when_tee_verifier_not_set() public {
        KarmaBilateral bare = new KarmaBilateral(admin);
        vm.prank(admin); bare.setTokenAllowed(address(usdc), true);
        vm.prank(admin); bare.setSettleDelay(0);
        vm.prank(buyer); usdc.approve(address(bare), type(uint256).max);
        vm.prank(agent); usdc.approve(address(bare), type(uint256).max);
        vm.prank(buyer); uint256 buyerBill = bare.lock(address(usdc), AMOUNT);
        vm.prank(agent); uint256 agentBill = bare.lock(address(usdc), AMOUNT);
        vm.prank(buyer); uint256 bindingId = bare.bind(buyerBill, agentBill, SCOPE);

        vm.expectRevert(KarmaBilateral.TEEVerifierNotSet.selector);
        vm.prank(buyer);
        bare.settleWithTEE(bindingId, PROOF, abi.encode(IMAGE, uint8(27), bytes32(0), bytes32(0)));
    }

    function test_rejects_unregistered_enclave() public {
        uint256 bindingId = _boundBinding();
        uint256 roguePk = 0xB0B;
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(roguePk, _digest(bindingId, PROOF, IMAGE));

        vm.expectRevert();
        vm.prank(buyer);
        karma.settleWithTEE(bindingId, PROOF, abi.encode(IMAGE, v, r, s));
    }

    function test_rejects_tampered_proof_hash() public {
        uint256 bindingId = _boundBinding();
        bytes memory att = _attest(bindingId, PROOF, IMAGE); // signed over PROOF

        vm.expectRevert();
        vm.prank(buyer);
        karma.settleWithTEE(bindingId, keccak256("other-proof"), att);
    }

    function test_rejects_image_mismatch() public {
        uint256 bindingId = _boundBinding();
        // Signed over IMAGE2 with the registered enclave key → digest recovers
        // the enclave but the registered image (IMAGE) differs from IMAGE2.
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ENCLAVE_PK, _digest(bindingId, PROOF, IMAGE2));

        vm.expectRevert(
            abi.encodeWithSelector(
                TEESettlementVerifier.ImageMismatch.selector, enclave, IMAGE, IMAGE2
            )
        );
        vm.prank(buyer);
        karma.settleWithTEE(bindingId, PROOF, abi.encode(IMAGE2, v, r, s));
    }

    function test_rejects_settle_before_delay() public {
        vm.prank(admin); karma.setSettleDelay(1 days);
        uint256 bindingId = _boundBinding();

        bytes memory att = _attest(bindingId, PROOF, IMAGE);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.SettleDelayActive.selector, block.timestamp + 1 days));
        vm.prank(buyer);
        karma.settleWithTEE(bindingId, PROOF, att);
    }

    function test_rejects_double_settle() public {
        uint256 bindingId = _boundBinding();
        bytes memory att = _attest(bindingId, PROOF, IMAGE);

        vm.prank(buyer); karma.settleWithTEE(bindingId, PROOF, att);

        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector,
                bindingId, KarmaBilateral.BindingState.ACTIVE, KarmaBilateral.BindingState.SETTLED
            )
        );
        vm.prank(buyer); karma.settleWithTEE(bindingId, PROOF, att);
    }

    function test_register_requires_attester() public {
        address fresh = vm.addr(0xDECAF);
        vm.expectRevert(TEESettlementVerifier.Unauthorized.selector);
        vm.prank(buyer);
        verifier.registerEnclave(fresh, IMAGE);
    }

    function test_revoked_enclave_rejected() public {
        uint256 bindingId = _boundBinding();
        vm.prank(admin); verifier.revokeEnclave(enclave);

        bytes memory att = _attest(bindingId, PROOF, IMAGE);
        vm.expectRevert(abi.encodeWithSelector(TEESettlementVerifier.EnclaveNotActive.selector, enclave));
        vm.prank(buyer);
        karma.settleWithTEE(bindingId, PROOF, att);
    }
}
