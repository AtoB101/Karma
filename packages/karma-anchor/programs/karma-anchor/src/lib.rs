use anchor_lang::prelude::*;
use tiny_keccak::{Hasher, Keccak};

declare_id!("2nMJG572zrnQiRpBQf3N7DBEX6Ufiwz4NikxVTcgDMka");

#[program]
pub mod karma_anchor {
    use super::*;

    /// Initialize a new Merkle tree account for a given task.
    pub fn initialize_tree(ctx: Context<InitializeTree>, task_id: [u8; 16]) -> Result<()> {
        let tree = &mut ctx.accounts.merkle_tree;
        tree.task_id = task_id;
        tree.current_root = [0u8; 32];
        tree.leaf_count = 0;
        tree.bump = ctx.bumps.merkle_tree;
        
        // Initialize root_history with empty vec
        // The vec is stored after the fixed fields via Borsh serialization
        Ok(())
    }

    /// Append a batch of leaf hashes to the Merkle tree.
    /// Updates current_root and appends to root_history.
    pub fn append_leaves(
        ctx: Context<AppendLeaves>,
        leaves: Vec<[u8; 32]>,
        metadata: KarmaAnchorMetadata,
    ) -> Result<()> {
        let tree = &mut ctx.accounts.merkle_tree;

        // Build all leaf hashes (existing + new)
        let mut all_hashes: Vec<[u8; 32]> = Vec::new();

        // When we have an existing tree, seed with previous state
        if tree.leaf_count > 0 {
            for _ in 0..tree.leaf_count {
                all_hashes.push(tree.current_root);
            }
        }

        for leaf in leaves.iter() {
            all_hashes.push(*leaf);
        }

        // Recompute the Merkle root from all leaves
        let new_root = compute_merkle_root_from_leaves(&all_hashes);

        // Record the previous root in history
        if tree.leaf_count > 0 {
            let prev_root = tree.current_root;
            tree.root_history.push(prev_root);
            // Keep history bounded (max 100 entries)
            if tree.root_history.len() > 100 {
                tree.root_history.remove(0);
            }
        }

        tree.current_root = new_root;
        tree.leaf_count = tree
            .leaf_count
            .checked_add(leaves.len() as u64)
            .ok_or(KarmaError::LeafCountOverflow)?;

        // Emit event
        emit!(ReceiptsAnchored {
            task_id: metadata.task_id,
            scenario: metadata.scenario,
            billing_state: metadata.billing_state,
            leaf_count: leaves.len() as u16,
            timestamp: Clock::get()?.unix_timestamp,
        });

        Ok(())
    }

    /// Verify that a leaf hash belongs to a given Merkle root.
    pub fn verify_receipt(
        ctx: Context<VerifyReceipt>,
        leaf_hash: [u8; 32],
        merkle_proof: Vec<[u8; 32]>,
        leaf_index: u64,
    ) -> Result<()> {
        let tree = &ctx.accounts.merkle_tree;

        // Compute root from leaf_hash + proof
        let computed = compute_merkle_root_from_proof(leaf_hash, &merkle_proof, leaf_index);

        // Check against current root
        let matches_current = computed == tree.current_root;

        // Also check against root history (for historical verification)
        let matches_history = tree.root_history.iter().any(|r| *r == computed);

        let verified = matches_current || matches_history;

        emit!(ReceiptVerified {
            root: tree.current_root,
            leaf_hash,
            leaf_index,
            verified,
        });

        if !verified {
            return Err(KarmaError::ProofVerificationFailed.into());
        }

        Ok(())
    }

    /// Get the current Merkle root for a task.
    pub fn get_root(ctx: Context<GetRoot>) -> Result<[u8; 32]> {
        Ok(ctx.accounts.merkle_tree.current_root)
    }
}

/// Build a Merkle root from a list of leaf hashes (bottom-up).
fn compute_merkle_root_from_leaves(leaves: &[[u8; 32]]) -> [u8; 32] {
    if leaves.is_empty() {
        return [0u8; 32];
    }

    let mut level: Vec<[u8; 32]> = leaves.to_vec();

    while level.len() > 1 {
        let mut next_level: Vec<[u8; 32]> = Vec::with_capacity((level.len() + 1) / 2);

        for pair in level.chunks(2) {
            let left = pair[0];
            let right = if pair.len() > 1 { pair[1] } else { pair[0] };

            let mut data = Vec::with_capacity(64);
            if left < right {
                data.extend_from_slice(&left);
                data.extend_from_slice(&right);
            } else {
                data.extend_from_slice(&right);
                data.extend_from_slice(&left);
            }

            let mut keccak = Keccak::v256();
            keccak.update(&data);
            let mut hash_bytes = [0u8; 32];
            keccak.finalize(&mut hash_bytes);
            next_level.push(hash_bytes);
        }

        level = next_level;
    }

    level[0]
}

/// Compute Merkle root from a single leaf, proof path, and leaf index.
fn compute_merkle_root_from_proof(
    leaf: [u8; 32],
    proof: &[[u8; 32]],
    leaf_index: u64,
) -> [u8; 32] {
    let mut current = leaf;
    let mut idx = leaf_index;

    for sibling in proof {
        let mut data = Vec::with_capacity(64);

        // Determine node ordering from index parity
        if idx % 2 == 0 {
            // current is left, sibling is right
            data.extend_from_slice(&current);
            data.extend_from_slice(sibling);
        } else {
            // sibling is left, current is right
            data.extend_from_slice(sibling);
            data.extend_from_slice(&current);
        }

        let mut keccak = Keccak::v256();
        keccak.update(&data);
        keccak.finalize(&mut current);
        idx /= 2;
    }

    current
}

/// Metadata attached to each anchoring operation.
#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct KarmaAnchorMetadata {
    pub task_id: [u8; 16],
    pub scenario: [u8; 32],
    pub billing_state: [u8; 16],
    pub receipt_count: u16,
    pub cost_accrued_usdc: u32,
}

/// On-chain Merkle tree account for a Karma task.
/// Space: 8 (discriminator) + 16 + 32 + 8 + 1 + 4 (vec prefix) + 100*32 = 3269
#[account]
pub struct KarmaMerkleTree {
    pub task_id: [u8; 16],       // 16 bytes
    pub current_root: [u8; 32],  // 32 bytes
    pub leaf_count: u64,          // 8 bytes
    pub bump: u8,                 // 1 byte
    pub root_history: Vec<[u8; 32]>, // dynamic, max 100 entries * 32 bytes = 3200 + 4 prefix
}

impl KarmaMerkleTree {
    pub const MAX_ROOT_HISTORY: usize = 100;
    pub const SPACE: usize = 8 + 16 + 32 + 8 + 1 + 4 + (Self::MAX_ROOT_HISTORY * 32);
}

/// Accounts for initializing a Merkle tree PDA.
#[derive(Accounts)]
#[instruction(task_id: [u8; 16])]
pub struct InitializeTree<'info> {
    #[account(
        init,
        payer = authority,
        space = KarmaMerkleTree::SPACE,
        seeds = [b"karma_merkle", task_id.as_ref()],
        bump
    )]
    pub merkle_tree: Account<'info, KarmaMerkleTree>,

    #[account(mut)]
    pub authority: Signer<'info>,

    pub system_program: Program<'info, System>,
}

/// Accounts for appending leaf hashes.
#[derive(Accounts)]
pub struct AppendLeaves<'info> {
    #[account(
        mut,
        seeds = [b"karma_merkle", merkle_tree.task_id.as_ref()],
        bump = merkle_tree.bump,
    )]
    pub merkle_tree: Account<'info, KarmaMerkleTree>,

    #[account(mut)]
    pub authority: Signer<'info>,
}

/// Accounts for verifying a receipt.
#[derive(Accounts)]
pub struct VerifyReceipt<'info> {
    #[account(
        seeds = [b"karma_merkle", merkle_tree.task_id.as_ref()],
        bump = merkle_tree.bump,
    )]
    pub merkle_tree: Account<'info, KarmaMerkleTree>,
}

/// Accounts for reading the current root.
#[derive(Accounts)]
pub struct GetRoot<'info> {
    pub merkle_tree: Account<'info, KarmaMerkleTree>,
}

/// Emitted when receipts are anchored to Solana.
#[event]
pub struct ReceiptsAnchored {
    pub task_id: [u8; 16],
    pub scenario: [u8; 32],
    pub billing_state: [u8; 16],
    pub leaf_count: u16,
    pub timestamp: i64,
}

/// Emitted when a receipt is verified against the on-chain root.
#[event]
pub struct ReceiptVerified {
    pub root: [u8; 32],
    pub leaf_hash: [u8; 32],
    pub leaf_index: u64,
    pub verified: bool,
}

/// Error codes for the Karma Anchor program.
#[error_code]
pub enum KarmaError {
    #[msg("Merkle proof verification failed")]
    ProofVerificationFailed,
    #[msg("Leaf count overflow")]
    LeafCountOverflow,
}
