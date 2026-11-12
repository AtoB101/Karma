// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title KarmaVerifierBond
/// @notice 去中心化验证节点的**质押金库**（bond vault）—— 把「质押即准入」从
///         入场券升级成真实经济担保。
///
/// 为什么要有这一份合约（G12）
/// ---------------------------
/// 在此之前节点质押只是一个数字（`verifier_nodes.stake_amount`）：没有锁仓背书、
/// 没有下限，也没有罚没 / 退出闭环 —— 节点作恶没有成本。本合约把三件事落到链上：
///
/// 1. **真托管**：`stake()` 用 `transferFrom` 把质押代币**真**收进本合约，
///    `totalBonded` 逐笔累加。`solvencyGap()` 让「合约余额 < 保证金 + 罚没池」
///    当场可查 —— 账目失真必须能被看见。
/// 2. **罚没 80 / 20**：`slash()` 把罚没额按 `victimShareBps`（默认 8000 = 80%）
///    真转给受害方，余下进 `slashPool`（罚没池）；罚没后保证金低于 `minBond`
///    当场停用（`active = false`）。**不足即停用**是「押金走则岗停」的链上版本。
/// 3. **冷却退出**：`requestUnstake()` 起算冷却期，冷却期内保证金**仍可被罚没**；
///    冷却期满 `withdrawUnstake()` 才放款 —— 堵住「出事前抢先跑」。
///
/// 罚没池累积到 `minPoolPayout` 以上，由 admin（生产环境必须是治理多签 / 时间锁）
/// 调 `distributePool()` 平分给表现好的节点，实现「20% 沉淀，后期奖励优秀节点」。
///
/// 权限边界
/// --------
/// - `admin`（不可变）：改参数、分池。生产环境只能是多签 / 时间锁，不能是热钱包。
/// - `slasher`：唯一可调 `slash()` 的地址，由 admin 指定。它对应链下的
///   「争议裁决 → 罚没」状态机（`POST /verifier-network/challenges/{id}/resolve`
///   判负后触发）。合约不判断谁对谁错 —— 判断属于链下仲裁，合约只保证
///   「一旦判定罚没，钱真的从保证金里划走、按比例分账、不足即停用」。
contract KarmaVerifierBond {
    uint256 public constant BPS_DENOMINATOR = 10_000;

    // ──────────────────────────────── Errors ─────────────────────────────────

    error Unauthorized();
    error InvalidAddress();
    error InvalidAmount();
    error InvalidConfig();
    error TokenNotSet();
    error TransferFailed();
    error NotRegistered();
    error InsufficientBond();
    error UnstakingNotRequested();
    error CooldownActive(uint256 readyAt);
    error PoolUnderThreshold(uint256 pool, uint256 threshold);
    error PoolInsolvent(uint256 requested, uint256 available);
    error NoWinners();
    error Reentrancy();

    // ─────────────────────────────── Immutables ──────────────────────────────

    /// @notice 治理账户：改参数、分池。
    address public immutable admin;

    // ──────────────────────────────── Storage ────────────────────────────────

    /// @notice 唯一可调用 `slash()` 的地址（链下裁决 → 罚没的落点）。
    address public slasher;

    /// @notice 质押代币（USDC / KARMA）。
    address public token;

    /// @notice 有效节点维持的最低保证金。低于它即 `active = false`。
    uint256 public minBond;

    /// @notice 退出冷却期（秒）。冷却期内保证金仍可被罚没。
    uint256 public unbondCooldown = 3 days;

    /// @notice 罚没池的起奖线：池子没到这个数不许分配。
    uint256 public minPoolPayout;

    /// @notice 罚没额中给受害方的比例（bps）。默认 8000 = 80%，余下 20% 进池。
    uint16 public victimShareBps = 8_000;

    /// @notice 当前托管在本合约里的保证金总额。
    uint256 public totalBonded;

    /// @notice 罚没池余额（同样托管在本合约里）。
    uint256 public slashPool;

    struct Bond {
        uint256 amount;
        uint256 slashedTotal;
        uint256 unbondAmount;
        uint256 unbondRequestedAt;
        bool registered;
        bool active;
    }

    mapping(address => Bond) internal _bonds;

    /// @notice 登记过的节点地址（供池子分账时枚举）。
    address[] public members;

    mapping(address => bool) internal _member;

    uint256 private _locked = 1;

    // ───────────────────────────────── Events ────────────────────────────────

    event BondStaked(address indexed verifier, uint256 amount, uint256 total);
    event VerifierActivated(address indexed verifier, uint256 bond);
    event BondSlashed(
        address indexed verifier,
        address indexed victim,
        uint256 amount,
        uint256 victimAmount,
        uint256 poolAmount,
        bytes32 reason
    );
    event BondUnstakeRequested(address indexed verifier, uint256 amount, uint256 readyAt);
    event BondWithdrawn(address indexed verifier, uint256 amount, uint256 remaining);
    event VerifierDeactivated(address indexed verifier, uint256 remainingBond);
    event PoolFunded(uint256 amount, uint256 poolTotal);
    event PoolDistributed(address[] winners, uint256 amount, uint256 perWinner);
    event SlasherUpdated(address indexed slasher);
    event StakeConfigUpdated(
        address token,
        uint256 minBond,
        uint256 unbondCooldown,
        uint256 minPoolPayout
    );
    event SlashSplitUpdated(uint16 victimShareBps);

    // ─────────────────────────────── Modifiers ───────────────────────────────

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlySlasher() {
        if (msg.sender != slasher) revert Unauthorized();
        _;
    }

    modifier nonReentrant() {
        if (_locked != 1) revert Reentrancy();
        _locked = 2;
        _;
        _locked = 1;
    }

    // ────────────────────────────── Constructor ──────────────────────────────

    /// @param admin_   治理账户（生产：多签 / 时间锁）。
    /// @param token_   质押代币；可传零地址，稍后用 `setToken` 设。
    /// @param minBond_ 有效节点最低保证金。
    constructor(address admin_, address token_, uint256 minBond_) {
        if (admin_ == address(0)) revert InvalidAddress();
        admin = admin_;
        token = token_;
        minBond = minBond_;
    }

    // ───────────────────────────── Admin Functions ───────────────────────────

    /// @notice 指定（或轮换）罚没执行方。
    function setSlasher(address slasher_) external onlyAdmin {
        slasher = slasher_;
        emit SlasherUpdated(slasher_);
    }

    /// @notice 设置质押代币。只在金库还是空的时候允许换 —— 避免把旧代币的账目留在新代币上。
    function setToken(address token_) external onlyAdmin {
        if (token_ == address(0)) revert InvalidAddress();
        if (totalBonded != 0 || slashPool != 0) revert InvalidConfig();
        token = token_;
        emit StakeConfigUpdated(token_, minBond, unbondCooldown, minPoolPayout);
    }

    /// @notice 一次性改三项参数（最低保证金 / 冷却期 / 起奖线）。
    function setStakeConfig(
        uint256 minBond_,
        uint256 unbondCooldown_,
        uint256 minPoolPayout_
    ) external onlyAdmin {
        minBond = minBond_;
        unbondCooldown = unbondCooldown_;
        minPoolPayout = minPoolPayout_;
        emit StakeConfigUpdated(token, minBond_, unbondCooldown_, minPoolPayout_);
    }

    /// @notice 改罚没分账比例。只能 0..10000（0 = 全进池，10000 = 全给受害方）。
    function setSlashSplit(uint16 victimShareBps_) external onlyAdmin {
        if (uint256(victimShareBps_) > BPS_DENOMINATOR) revert InvalidConfig();
        victimShareBps = victimShareBps_;
        emit SlashSplitUpdated(victimShareBps_);
    }

    // ───────────────────────────── Staking Path ──────────────────────────────

    /// @notice 节点自质押：代币真转进本合约。
    /// @dev 首次质押即登记；累计保证金达到 `minBond` 才 `active`。
    function stake(uint256 amount) external nonReentrant {
        if (token == address(0)) revert TokenNotSet();
        if (amount == 0) revert InvalidAmount();
        if (!_erc20().transferFrom(msg.sender, address(this), amount)) revert TransferFailed();

        Bond storage b = _bonds[msg.sender];
        if (!b.registered) {
            b.registered = true;
            if (!_member[msg.sender]) {
                _member[msg.sender] = true;
                members.push(msg.sender);
            }
        }
        b.amount += amount;
        totalBonded += amount;

        if (!b.active && b.amount >= minBond) {
            b.active = true;
            emit VerifierActivated(msg.sender, b.amount);
        }
        emit BondStaked(msg.sender, amount, b.amount);
    }

    /// @notice 发起退出：冻结提取额度，开始冷却计时。
    /// @dev 冷却期内保证金仍可被罚没（这正是冷却期的意义）。
    function requestUnstake(uint256 amount) external {
        Bond storage b = _bonds[msg.sender];
        if (!b.registered) revert NotRegistered();
        if (amount == 0 || amount > b.amount) revert InvalidAmount();
        b.unbondAmount = amount;
        b.unbondRequestedAt = block.timestamp;
        emit BondUnstakeRequested(msg.sender, amount, block.timestamp + unbondCooldown);
    }

    /// @notice 冷却期满后放款。被罚没后按**剩余**额度放款，不会多给。
    function withdrawUnstake() external nonReentrant {
        Bond storage b = _bonds[msg.sender];
        if (b.unbondRequestedAt == 0) revert UnstakingNotRequested();

        uint256 readyAt = b.unbondRequestedAt + unbondCooldown;
        if (block.timestamp < readyAt) revert CooldownActive(readyAt);

        uint256 amount = b.unbondAmount;
        if (amount > b.amount) amount = b.amount;

        b.unbondAmount = 0;
        b.unbondRequestedAt = 0;
        b.amount -= amount;
        totalBonded -= amount;

        if (b.active && b.amount < minBond) {
            b.active = false;
            emit VerifierDeactivated(msg.sender, b.amount);
        }

        if (amount > 0) {
            if (!_erc20().transfer(msg.sender, amount)) revert TransferFailed();
        }
        emit BondWithdrawn(msg.sender, amount, b.amount);
    }

    // ───────────────────────────────── Slashing ──────────────────────────────

    /// @notice 罚没保证金：80% 给受害方、20% 进罚没池；不足 `minBond` 当场停用。
    /// @param verifier 被罚节点。
    /// @param victim   受害方收款项；地址为零则全部进池。
    /// @param amount   请求罚没额（超过保证金时按保证金全额扣，不会扣成负数）。
    /// @param reason   罚没原因哈希（对应链下裁决 id / 理由，便于对账）。
    /// @return victimAmount 实际转给受害方的金额。
    /// @return poolAmount   实际进罚没池的金额。
    function slash(
        address verifier,
        address victim,
        uint256 amount,
        bytes32 reason
    ) external onlySlasher nonReentrant returns (uint256 victimAmount, uint256 poolAmount) {
        Bond storage b = _bonds[verifier];
        if (!b.registered) revert NotRegistered();
        if (amount == 0) revert InvalidAmount();
        if (b.amount == 0) revert InsufficientBond();

        uint256 take = amount > b.amount ? b.amount : amount;

        b.amount -= take;
        b.slashedTotal += take;
        totalBonded -= take;

        // 冷却期内的待提取额不能超过剩余保证金。
        if (b.unbondRequestedAt != 0 && b.unbondAmount > b.amount) {
            b.unbondAmount = b.amount;
        }

        if (b.active && b.amount < minBond) {
            b.active = false;
            emit VerifierDeactivated(verifier, b.amount);
        }

        victimAmount = victim == address(0) ? 0 : (take * victimShareBps) / BPS_DENOMINATOR;
        poolAmount = take - victimAmount;

        if (victimAmount > 0) {
            if (!_erc20().transfer(victim, victimAmount)) revert TransferFailed();
        }
        slashPool += poolAmount;

        emit BondSlashed(verifier, victim, take, victimAmount, poolAmount, reason);
        if (poolAmount > 0) {
            emit PoolFunded(poolAmount, slashPool);
        }
    }

    /// @notice 罚没池达起奖线后，由治理平分奖励给优秀节点。
    /// @dev 余数给最后一名，保证「池子分干净、不多不少」。
    function distributePool(
        address[] calldata winners,
        uint256 amount
    ) external onlyAdmin nonReentrant {
        if (winners.length == 0) revert NoWinners();
        if (amount == 0) revert InvalidAmount();
        if (amount > slashPool) revert PoolInsolvent(amount, slashPool);
        if (slashPool < minPoolPayout) revert PoolUnderThreshold(slashPool, minPoolPayout);

        slashPool -= amount;

        uint256 per = amount / winners.length;
        uint256 remainder = amount - per * winners.length;

        for (uint256 i = 0; i < winners.length; i++) {
            uint256 payout = (i == winners.length - 1) ? per + remainder : per;
            if (payout > 0 && !_erc20().transfer(winners[i], payout)) revert TransferFailed();
        }
        emit PoolDistributed(winners, amount, per);
    }

    // ─────────────────────────────────── Views ───────────────────────────────

    /// @notice 读一个节点的完整保证金状态。
    function bondOf(address verifier) external view returns (Bond memory) {
        return _bonds[verifier];
    }

    function isRegistered(address verifier) external view returns (bool) {
        return _bonds[verifier].registered;
    }

    /// @notice 节点现在算不算「在任」：已登记且保证金 ≥ `minBond`。
    function isActive(address verifier) external view returns (bool) {
        Bond storage b = _bonds[verifier];
        return b.registered && b.active;
    }

    function bondAmount(address verifier) external view returns (uint256) {
        return _bonds[verifier].amount;
    }

    /// @notice 这个节点现在最多可被罚没多少。
    function slashable(address verifier) external view returns (uint256) {
        return _bonds[verifier].amount;
    }

    function memberCount() external view returns (uint256) {
        return members.length;
    }

    /// @notice 罚没池是否已达起奖线。
    function poolReady() external view returns (bool) {
        return minPoolPayout > 0 && slashPool >= minPoolPayout;
    }

    /// @notice 账目自证：合约余额必须 ≥ 保证金总额 + 罚没池。返回缺口（0 = 平）。
    function solvencyGap() external view returns (uint256) {
        if (token == address(0)) return 0;
        uint256 required = totalBonded + slashPool;
        uint256 balance = _erc20().balanceOf(address(this));
        return balance >= required ? 0 : required - balance;
    }

    // ───────────────────────────────── Internal ──────────────────────────────

    function _erc20() internal view returns (IERC20Bond) {
        return IERC20Bond(token);
    }
}

interface IERC20Bond {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address who) external view returns (uint256);
}