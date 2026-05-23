import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { KarmaAnchor } from "../target/types/karma_anchor";
import { createHash } from "crypto";
import { assert } from "chai";

describe("karma-anchor", () => {
  // Configure the client to use the local cluster
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);

  const program = anchor.workspace.KarmaAnchor as Program<KarmaAnchor>;

  // Helper: generate a task_id from string
  function taskId(id: string): number[] {
    const buf = Buffer.alloc(16);
    buf.write(id.slice(0, 16), 0, "utf-8");
    return Array.from(buf);
  }

  // Helper: keccak256 hash
  function keccakHash(data: Buffer): number[] {
    const hash = createHash("keccak256").update(data).digest();
    return Array.from(hash);
  }

  // Helper: pad string to fixed-size buffer
  function padStr(s: string, len: number): number[] {
    const buf = Buffer.alloc(len);
    buf.write(s.slice(0, len), 0, "utf-8");
    return Array.from(buf);
  }

  // Helper: compute Merkle root from leaves (off-chain)
  function computeMerkleRoot(leaves: Buffer[]): Buffer {
    let level = leaves.map((l) => Buffer.from(l));
    while (level.length > 1) {
      const next: Buffer[] = [];
      for (let i = 0; i < level.length; i += 2) {
        const left = level[i];
        const right = i + 1 < level.length ? level[i + 1] : level[i];
        const combined = Buffer.concat(
          left.compare(right) < 0 ? [left, right] : [right, left]
        );
        next.push(createHash("keccak256").update(combined).digest());
      }
      level = next;
    }
    return level[0];
  }

  // Helper: generate Merkle proof
  function generateProof(leaves: Buffer[], leafIndex: number): Buffer[] {
    const proof: Buffer[] = [];
    let level = leaves.map((l) => Buffer.from(l));
    let idx = leafIndex;

    while (level.length > 1) {
      const next: Buffer[] = [];
      const pairIdx = idx % 2 === 0 ? idx + 1 : idx - 1;

      if (pairIdx < level.length) {
        proof.push(Buffer.from(level[pairIdx]));
      } else {
        // Odd number of nodes — duplicate the last
        proof.push(Buffer.from(level[idx]));
      }

      for (let i = 0; i < level.length; i += 2) {
        const left = level[i];
        const right = i + 1 < level.length ? level[i + 1] : level[i];
        const combined = Buffer.concat(
          left.compare(right) < 0 ? [left, right] : [right, left]
        );
        next.push(createHash("keccak256").update(combined).digest());
      }
      level = next;
      idx = Math.floor(idx / 2);
    }
    return proof;
  }

  const TASK_ID = taskId("task-001");
  const DERIVED_PDA = (() => {
    // We'll derive the PDA using the program
    const [pda] = anchor.web3.PublicKey.findProgramAddressSync(
      [Buffer.from("karma_merkle"), Buffer.from(TASK_ID)],
      program.programId
    );
    return pda;
  })();

  it("Initializes a Merkle tree for a task", async () => {
    await program.methods
      .initializeTree(TASK_ID)
      .accounts({
        merkleTree: DERIVED_PDA,
        authority: provider.wallet.publicKey,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .rpc();

    const treeAccount = await program.account.karmaMerkleTree.fetch(DERIVED_PDA);
    assert.equal(treeAccount.leafCount.toNumber(), 0);
    assert.deepEqual(Array.from(treeAccount.currentRoot), new Array(32).fill(0));
    assert.deepEqual(Array.from(treeAccount.taskId), TASK_ID);
  });

  it("Appends leaf hashes and emits ReceiptsAnchored event", async () => {
    const leaf1 = keccakHash(Buffer.from("receipt-1"));
    const leaf2 = keccakHash(Buffer.from("receipt-2"));
    const leaf3 = keccakHash(Buffer.from("receipt-3"));

    const metadata = {
      taskId: TASK_ID,
      scenario: padStr("e-commerce-checkout", 32),
      billingState: padStr("funded", 16),
      receiptCount: 3,
      costAccruedUsdc: 1500, // $15.00 scaled by 100
    };

    const listener = program.addEventListener("ReceiptsAnchored", (event) => {
      assert.equal(event.leafCount, 3);
      assert.deepEqual(event.taskId, TASK_ID);
    });

    await program.methods
      .appendLeaves([leaf1, leaf2, leaf3], metadata)
      .accounts({
        merkleTree: DERIVED_PDA,
        authority: provider.wallet.publicKey,
      })
      .rpc();

    program.removeEventListener(listener);

    const treeAccount = await program.account.karmaMerkleTree.fetch(DERIVED_PDA);
    assert.equal(treeAccount.leafCount.toNumber(), 3);
    // root should be non-zero now
    assert.notDeepEqual(Array.from(treeAccount.currentRoot), new Array(32).fill(0));
    // root history should have the previous root (zero root)
    assert.equal(treeAccount.rootHistory.length, 1);
  });

  it("Verifies a receipt proof against the on-chain root", async () => {
    const receiptData = Buffer.from("receipt-1");
    const leafHash = Buffer.from(keccakHash(receiptData));

    // Build the same set of leaves as in the append test
    const allLeaves = [
      Buffer.from(keccakHash(Buffer.from("receipt-1"))),
      Buffer.from(keccakHash(Buffer.from("receipt-2"))),
      Buffer.from(keccakHash(Buffer.from("receipt-3"))),
    ];

    const proof = generateProof(allLeaves, 0); // leaf index 0

    await program.methods
      .verifyReceipt(
        Array.from(leafHash),
        proof.map((p) => Array.from(p)),
        new anchor.BN(0)
      )
      .accounts({
        merkleTree: DERIVED_PDA,
      })
      .rpc();

    // Should succeed — no error thrown
    assert.ok(true, "Verification passed");
  });

  it("Rejects invalid Merkle proof", async () => {
    const fakeLeaf = keccakHash(Buffer.from("fake-receipt"));
    const proof = [Buffer.alloc(32).fill(1)];

    try {
      await program.methods
        .verifyReceipt(fakeLeaf, proof.map((p) => Array.from(p)), new anchor.BN(0))
        .accounts({
          merkleTree: DERIVED_PDA,
        })
        .rpc();
      assert.fail("Should have thrown");
    } catch (err: any) {
      assert.include(err.message, "ProofVerificationFailed");
    }
  });

  it("Gets the current Merkle root", async () => {
    const root = await program.methods
      .getRoot()
      .accounts({
        merkleTree: DERIVED_PDA,
      })
      .view();

    assert.isArray(root);
    assert.equal(root.length, 32);
    assert.notDeepEqual(root, new Array(32).fill(0));
  });
});
