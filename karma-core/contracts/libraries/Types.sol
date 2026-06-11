// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

library Types {
    struct AgentDID {
        address owner;
        address agent;
        uint256 registeredAt;
        uint256 validUntil;
        bytes32 permissionsHash;
        bool isActive;
    }

    struct LockPool {
        bytes32 poolId;
        address owner;
        address agent;
        address token;
        uint256 totalLocked;
        uint256 mappingBalance;
        uint256 pendingAmount;
        uint256 settledAmount;
        uint256 batchId;
        uint256 createdAt;
    }

    struct Bill {
        uint256 billId;
        uint256 batchId;
        address fromAgent;
        address toAgent;
        uint256 amount;
        string purpose;
        string proofHash;
        BillStatus status;
        uint256 createdAt;
        uint256 deadline;
    }

    struct Batch {
        uint256 batchId;
        bytes32 poolId;
        uint256 totalPending;
        uint256 billCount;
        BatchStatus status;
        uint256 createdAt;
        uint256 settledAt;
    }

    struct AuthToken {
        bytes32 tokenId;
        address owner;
        address agent;
        OperationType opType;
        uint256 maxAmount;
        uint256 validUntil;
        bool used;
        uint256 nonce;
    }

    enum OperationType {
        CreateBill,
        ConfirmBill,
        CancelBill,
        SetThreshold
    }

    enum BillStatus {
        Pending,
        Confirmed,
        Cancelled,
        Settled,
        Expired
    }

    enum BatchStatus {
        Open,
        Closed,
        Settled
    }

    // ═══════════════════════════ Intent Package (V2 — 全场景细粒度) ═════════

    enum ServiceCategory {
        None,
        SoftwareDevelopment,
        DesignCreative,
        LogisticsDelivery,
        ConsultingAdvisory,
        ContentCreation,
        Manufacturing,
        RealEstateServices,
        FinancialServices,
        MarketingAdvertising,
        EducationTraining,
        HealthcareMedical,
        LegalCompliance,
        CustomService
    }

    enum BreachTier {
        None,
        Minor,        // 可补救, 无实质损失
        Material,     // 部分损失, 影响里程碑
        Fundamental   // 根本违约, 合同目的落空
    }

    enum ResolutionPath {
        Optimistic,   // 无争议直接结算
        Mediation,    // 调解 -> 仲裁
        Arbitration   // 直接仲裁
    }

    enum QualityModel {
        PassFail,     // 通过/不通过
        Graded,       // A/B/C/D 等级
        Weighted,     // 加权评分
        Threshold     // 多阈值
    }

    // ═══ Payment Specification — 支付结构细粒度 ═══
    struct PaymentSpec {
        uint16  installmentCount;       // 分期数量
        uint24  penaltyRateBps;         // 违约罚息 (bps, max 10000)
        uint16  maxPenaltyBps;          // 罚息上限
        uint16  earlyPaymentDiscount;   // 提前付款折扣
        uint16  lateFeeRateBps;         // 滞纳金
        uint32  paymentDueDays;         // 完成后付款期限
        uint8   currencyType;           // 0=stablecoin 1=native 2=wrapped
        bytes32 paymentConditions;      // 付款条件的哈希 (e.g. "upon_delivery_acceptance")
        bytes32[] milestoneIds;         // 里程碑标识
        uint16[] milestoneShares;       // per-milestone bps (sum=10000)
        uint48[] milestoneDeadlines;    // per-milestone deadline timestamps
    }

    // ═══ Delivery Specification — 交付标准细粒度 ═══
    struct DeliverySpec {
        uint8   deliveryType;           // 0=service 1=physical 2=digital 3=composite
        uint16  deliverableCount;       // 可交付物数量
        uint16  requiredCompletionRate; // 最低完成率 bps (8000=80%)
        uint32  gracePeriodSeconds;     // 宽限期
        uint32  acceptanceWindow;       // 验收窗口 (秒)
        bytes32[] deliverables;         // 可交付物哈希列表
        bytes32   acceptanceProtocol;   // 验收协议哈希
        bytes32   qualityStandard;      // 质量标准引用哈希
        bytes32   deliveryLocation;     // 交付地点 (0=链上)
        bytes32   shippingConditions;   // 运输条件
        bool      requireDigitalSignature; // 需电子签收
        bool      allowPartialDelivery;    // 允许部分交付
    }

    // ═══ Breach Specification — 违约定义细粒度 ═══
    struct BreachSpec {
        uint8   breachClassification;   // 0=simple 1=tiered 2=custom
        uint16  tier1PenaltyBps;        // 轻微违约罚息
        uint16  tier2PenaltyBps;        // 实质违约罚息
        uint16  tier3PenaltyBps;        // 根本违约罚息
        uint32  curePeriodSeconds;      // 补救期
        uint8   maxCureAttempts;        // 最大补救次数
        uint8   terminateAfterBreaches; // 多少次违约后终止
        bytes32 breachDefinitions;      // 违约定义文档哈希
        bytes32[] breachTypes;          // 分类的违约类型
        uint16[] breachPenaltyRates;    // per-type 罚息
        bool    autoTriggerPenalty;     // 自动触发罚则
        bool    penaltyIsCumulative;    // 罚则是否累积
    }

    // ═══ Quality Specification — 质量标准细粒度 ═══
    struct QualitySpec {
        uint8   qualityModel;           // 0=pass_fail 1=graded 2=weighted 3=threshold
        uint16  acceptanceThreshold;    // 最低接受阈值 bps
        uint16  bonusThreshold;         // 奖励阈值 bps
        uint16  bonusRate;              // 奖励比例 bps
        bytes32 standardReference;      // 标准引用
        bytes32[] metrics;              // 度量指标哈希列表
        uint16[] metricWeights;         // 各指标权重 (sum=10000)
        uint16[] metricThresholds;      // 各指标最低阈值
        bytes32[] acceptanceCriteria;   // 验收标准哈希列表
        uint8   minConfirmations;       // 最少确认数
    }

    // ═══ Dispute Specification — 争议机制细粒度 ═══
    struct DisputeSpec {
        uint8   resolutionPath;         // 0=optimistic 1=mediation 2=arbitration
        uint32  negotiationWindow;      // 协商窗口 (秒)
        uint32  mediationWindow;        // 调解窗口
        uint32  arbitrationWindow;      // 仲裁窗口
        uint16  appealBondBps;          // 上诉押金 bps
        uint8   maxAppeals;             // 最大上诉次数
        address[]       arbitrators;    // 仲裁员列表
        bool    bindingArbitration;     // 仲裁是否终局
        bytes32 evidenceStandard;       // 证据标准哈希
        bytes32[] requiredEvidenceTypes;// 每阶段所需证据类型
        uint16  frivolousDisputePenalty;// 恶意争议罚息
    }

    // ═══ Comprehensive Intent Package — 全场景意图包 ═══
    struct IntentPackage {
        // ── Core (backwards compatible, always required) ──
        address buyer;
        address seller;
        bytes32 serviceType;             // hashed service type ID
        ServiceCategory serviceCategory; // 服务大类
        bytes   requirements;            // human-readable requirements
        uint256 amount;
        uint256 penaltyRate;             // base penalty (bps) — kept for compat
        uint256 deadline;
        uint256 expiresAt;
        bytes32 proofSchema;
        bytes32[] requiredProofFields;
        address verifier;
        uint256 disputeWindow;

        // ── Sub-Specification Commitments (hashed off-chain sub-docs) ──
        bytes32 paymentSpecHash;         // keccak256(abi.encode(PaymentSpec))
        bytes32 deliverySpecHash;        // keccak256(abi.encode(DeliverySpec))
        bytes32 breachSpecHash;          // keccak256(abi.encode(BreachSpec))
        bytes32 qualitySpecHash;         // keccak256(abi.encode(QualitySpec))
        bytes32 disputeSpecHash;         // keccak256(abi.encode(DisputeSpec))
        bytes32 fullDocumentHash;        // SHA256 of canonical JSON intent doc
        bytes32 schemaVersion;           // intent schema version (e.g. "karma-intent-v2")

        // ── Grace & Cure (on-chain computable) ──
        uint256 gracePeriod;             // buffer before penalty triggers
        uint256 curePeriod;              // time to remedy breach
        uint256 acceptanceWindow;        // time to accept/reject delivery

        // ── Payment Structure (on-chain essential) ──
        uint256[] milestoneAmounts;      // per-milestone amounts
        bytes32[] milestoneIds;          // milestone identifiers
        uint256[] milestoneDeadlines;    // per-milestone deadline timestamps
        uint256 maxPenalty;              // penalty cap

        // ── Quality / Deliverables ──
        bytes32[] deliverables;          // hashed deliverable IDs
        bytes32   qualityStandard;       // quality criteria hash

        // ── Breach — basic on-chain ═══
        bytes32 breachDefinitions;       // hash of breach classification doc
        uint8   maxCureAttempts;

        // ── Governance Flags ──
        bool allowPartialSettlement;     // can settle partially
        bool bindingArbitration;         // arbitration is final
        bool sellerMustStake;            // seller must post stake/bond
        bool buyerMustStake;             // buyer must post stake/bond

        // ── Arbitrators (required for escalation) ──
        address[] arbitrators;
    }

    struct ScoringVector {
        uint256 totalTransactions;
        uint256 reputationScore;
        uint256 completionRate;
        uint256 avgCompletionSpeed;
        uint256 disputeRate;
        uint256 disputeWinRate;
        uint256 penaltyCount;
        uint256 confirmationSpeed;
        uint256 maliciousDisputeRate;
        uint256 verificationAccuracy;
        uint256 verificationVolume;
        uint256 slashedCount;
        uint256 lastUpdated;
    }

    struct Evidence {
        uint256 evidenceId;
        uint256 bindingId;
        address verifier;
        bytes   data;
        bytes32 fieldHash;
        uint256 timestamp;
        bool    valid;
    }

    /// @notice Persistent Agent Key — issued once, reused until revoked.
    ///         Grants an agent EOA the right to call lock/bind on master's behalf.
    struct AgentKey {
        bytes32 keyId;
        address master;       // key owner (bill owner / responsible party)
        address agent;        // agent EOA that can use this key
        uint256 dailyLimit;   // max spend per UTC day
        uint256 spentToday;
        uint256 lastResetDay; // days since Unix epoch
        uint256 expiresAt;
        bool    active;
    }
}
