// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ISettlementEngine} from "../../interfaces/ISettlementEngine.sol";
import {QuoteTypes} from "../../libraries/QuoteTypes.sol";

contract ReentrantERC20 {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    ISettlementEngine internal _engine;
    QuoteTypes.Quote internal _quote;
    uint8 internal _v;
    bytes32 internal _r;
    bytes32 internal _s;
    QuoteTypes.Quote[] internal _batchQuotes;
    uint8[] internal _batchVs;
    bytes32[] internal _batchRs;
    bytes32[] internal _batchSs;
    bool internal _batchMode;
    bool internal _armed;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function armReenter(ISettlementEngine engine_, QuoteTypes.Quote calldata quote_, uint8 v_, bytes32 r_, bytes32 s_) external {
        _engine = engine_;
        _quote = quote_;
        _v = v_;
        _r = r_;
        _s = s_;
        _batchMode = false;
        _armed = true;
    }

    function armReenterBatch(
        ISettlementEngine engine_,
        QuoteTypes.Quote[] calldata quotes_,
        uint8[] calldata vs_,
        bytes32[] calldata rs_,
        bytes32[] calldata ss_
    ) external {
        _engine = engine_;
        delete _batchQuotes;
        delete _batchVs;
        delete _batchRs;
        delete _batchSs;
        for (uint256 i = 0; i < quotes_.length; ++i) {
            _batchQuotes.push(quotes_[i]);
            _batchVs.push(vs_[i]);
            _batchRs.push(rs_[i]);
            _batchSs.push(ss_[i]);
        }
        _batchMode = true;
        _armed = true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        if (balanceOf[from] < amount) return false;
        if (allowance[from][msg.sender] < amount) return false;
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;

        if (_armed) {
            _armed = false;
            if (_batchMode) {
                _engine.settleBatch(_batchQuotes, _batchVs, _batchRs, _batchSs);
            } else {
                _engine.submitSettlement(_quote, _v, _r, _s);
            }
        }
        return true;
    }
}
