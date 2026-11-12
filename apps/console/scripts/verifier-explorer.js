/**
 * Verifier Explorer — JS runtime for verifier-explorer.html
 *
 * API mapping (assumes backend implemented):
 *   GET /v1/verifiers              → [{id, wallet_address, stake_amount, reputation_score,
 *                                       total_attestations, successful_attestations, is_active}]
 *   GET /v1/attestations?limit=20  → [{id, task_id, verifier_id, decision, confidence,
 *                                       checks_passed, checks_total, created_at}]
 *   GET /v1/challenges?status=OPEN → [{id, task_id, reason, status, window_end, quorum_size}]
 *   GET /v1/network/stats          → {total_verifiers, active_challenges, attestations_24h,
 *                                       avg_confidence}
 */

;(function (global) {
  /* ──────────────────────────────────────────
   * Internal helpers
   * ────────────────────────────────────────── */
  function apiBase() {
    return String(global.KARMA_API_BASE || "").trim().replace(/\/$/, "");
  }

  function headers() {
    var h = { Accept: "application/json" };
    var key = String(global.KARMA_API_KEY || "").trim();
    if (key) h["X-Karma-Api-Key"] = key;
    return h;
  }

  function el(sel, ctx) {
    return (ctx || document).querySelector(sel);
  }

  function els(sel, ctx) {
    return Array.from((ctx || document).querySelectorAll(sel));
  }

  function truncate(str, left, right) {
    left = left == null ? 6 : left;
    right = right == null ? 4 : right;
    if (!str) return "—";
    if (str.length <= left + right + 3) return str;
    return str.slice(0, left) + "…" + str.slice(-right);
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    try {
      var d = new Date(iso);
      return d.toLocaleString();
    } catch (_) {
      return iso;
    }
  }

  function relTime(iso) {
    if (!iso) return "—";
    var diff = Date.now() - new Date(iso).getTime();
    var s = Math.floor(diff / 1000);
    if (s < 60) return s + "s ago";
    var m = Math.floor(s / 60);
    if (m < 60) return m + "m ago";
    var h = Math.floor(m / 60);
    if (h < 24) return h + "h ago";
    return Math.floor(h / 24) + "d ago";
  }

  function ratioOK(a, b) {
    if (!b) return "—";
    return ((a / b) * 100).toFixed(1) + "%";
  }

  function statusColor(decision) {
    if (decision === "OK" || decision === "ok") return "#5eead4";
    if (decision === "FAIL" || decision === "fail") return "#f87171";
    if (decision === "FLAG" || decision === "flag") return "#fbbf24";
    return "#8f9bb8";
  }

  function challengeStatusClass(status) {
    if (status === "OPEN" || status === "open") return "red";
    if (status === "EXPIRING" || status === "expiring") return "yellow";
    if (status === "RESOLVED" || status === "resolved") return "green";
    return "";
  }

  function challengeStatusLabel(status) {
    if (status === "OPEN" || status === "open") return "Active";
    if (status === "EXPIRING" || status === "expiring") return "Expiring";
    if (status === "RESOLVED" || status === "resolved") return "Resolved";
    return status || "—";
  }

  /* ──────────────────────────────────────────
   * Mock data
   * ────────────────────────────────────────── */
  var MOCK = {
    verifiers: [
      { id: "v-001", wallet_address: "0x7a3b2c1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b", stake_amount: 5000, reputation_score: 98, total_attestations: 342, successful_attestations: 338, is_active: true },
      { id: "v-002", wallet_address: "0x1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b", stake_amount: 3000, reputation_score: 91, total_attestations: 215, successful_attestations: 209, is_active: true },
      { id: "v-003", wallet_address: "0x9f8e7d6c5b4a3928170654f3e2d1c0b9a8f7e6d5", stake_amount: 8000, reputation_score: 99, total_attestations: 510, successful_attestations: 507, is_active: true },
      { id: "v-004", wallet_address: "0xabcd1234efgh5678ijkl9012mnop3456qrst7890", stake_amount: 1500, reputation_score: 76, total_attestations: 87, successful_attestations: 72, is_active: false },
      { id: "v-005", wallet_address: "0x2468ace13579bdf02468ace13579bdf02468ace1", stake_amount: 4200, reputation_score: 94, total_attestations: 298, successful_attestations: 291, is_active: true },
      { id: "v-006", wallet_address: "0xdeadbeefcafe0001deadbeefcafe0001deadbeef", stake_amount: 10000, reputation_score: 100, total_attestations: 678, successful_attestations: 678, is_active: true },
    ],
    attestations: [
      { id: "at-001", task_id: "task-a1b2c3d4-e5f6-7890-abcd-ef1234567890", verifier_id: "v-001", decision: "OK", confidence: 0.98, checks_passed: 12, checks_total: 12, created_at: new Date(Date.now() - 2 * 60000).toISOString() },
      { id: "at-002", task_id: "task-f9e8d7c6-b5a4-3210-fedc-ba9876543210", verifier_id: "v-003", decision: "OK", confidence: 0.96, checks_passed: 10, checks_total: 12, created_at: new Date(Date.now() - 5 * 60000).toISOString() },
      { id: "at-003", task_id: "task-11223344-5566-7788-99aa-bbccddeeff00", verifier_id: "v-002", decision: "FLAG", confidence: 0.65, checks_passed: 8, checks_total: 12, created_at: new Date(Date.now() - 8 * 60000).toISOString() },
      { id: "at-004", task_id: "task-22334455-6677-8899-aabb-ccddeeff0011", verifier_id: "v-005", decision: "OK", confidence: 0.99, checks_passed: 12, checks_total: 12, created_at: new Date(Date.now() - 12 * 60000).toISOString() },
      { id: "at-005", task_id: "task-33445566-7788-99aa-bbcc-ddeeff001122", verifier_id: "v-001", decision: "FAIL", confidence: 0.42, checks_passed: 3, checks_total: 12, created_at: new Date(Date.now() - 15 * 60000).toISOString() },
      { id: "at-006", task_id: "task-44556677-8899-aabb-ccdd-eeff00112233", verifier_id: "v-006", decision: "OK", confidence: 1.0, checks_passed: 12, checks_total: 12, created_at: new Date(Date.now() - 20 * 60000).toISOString() },
      { id: "at-007", task_id: "task-55667788-99aa-bbcc-ddee-ff0011223344", verifier_id: "v-003", decision: "OK", confidence: 0.94, checks_passed: 11, checks_total: 12, created_at: new Date(Date.now() - 25 * 60000).toISOString() },
      { id: "at-008", task_id: "task-66778899-aabb-ccdd-eeff-001122334455", verifier_id: "v-002", decision: "OK", confidence: 0.92, checks_passed: 12, checks_total: 12, created_at: new Date(Date.now() - 30 * 60000).toISOString() },
      { id: "at-009", task_id: "task-778899aa-bbcc-ddee-ff00-112233445566", verifier_id: "v-005", decision: "OK", confidence: 0.97, checks_passed: 12, checks_total: 12, created_at: new Date(Date.now() - 35 * 60000).toISOString() },
      { id: "at-010", task_id: "task-8899aabb-ccdd-eeff-0011-223344556677", verifier_id: "v-001", decision: "OK", confidence: 0.95, checks_passed: 12, checks_total: 12, created_at: new Date(Date.now() - 40 * 60000).toISOString() },
      { id: "at-011", task_id: "task-99aabbcc-ddee-ff00-1122-334455667788", verifier_id: "v-006", decision: "FLAG", confidence: 0.71, checks_passed: 9, checks_total: 12, created_at: new Date(Date.now() - 45 * 60000).toISOString() },
      { id: "at-012", task_id: "task-aabbccdd-eeff-0011-2233-445566778899", verifier_id: "v-003", decision: "OK", confidence: 0.93, checks_passed: 11, checks_total: 12, created_at: new Date(Date.now() - 50 * 60000).toISOString() },
    ],
    challenges: [
      { id: "ch-001", task_id: "task-11223344-5566-7788-99aa-bbccddeeff00", reason: "Confidence below threshold (0.65)", status: "OPEN", window_end: new Date(Date.now() + 3600000).toISOString(), quorum_size: 5 },
      { id: "ch-002", task_id: "task-33445566-7788-99aa-bbcc-ddeeff001122", reason: "Verification checks failed (3/12)", status: "EXPIRING", window_end: new Date(Date.now() + 300000).toISOString(), quorum_size: 3 },
      { id: "ch-003", task_id: "task-99aabbcc-ddee-ff00-1122-334455667788", reason: "Suspicious attestation pattern", status: "OPEN", window_end: new Date(Date.now() + 7200000).toISOString(), quorum_size: 5 },
      { id: "ch-004", task_id: "task-abcdef01-2345-6789-abcd-ef0123456789", reason: "Stake weight discrepancy", status: "RESOLVED", window_end: new Date(Date.now() - 86400000).toISOString(), quorum_size: 4 },
    ],
    stats: {
      total_verifiers: 6,
      active_challenges: 2,
      attestations_24h: 847,
      avg_confidence: 0.94,
    },
  };

  /* ──────────────────────────────────────────
   * API calls (with mock fallback)
   * ────────────────────────────────────────── */
  var _apiUnavailable = false;

  async function apiFetch(path) {
    var base = apiBase();
    if (!base) throw new Error("API base not configured");
    var res = await fetch(base + path, { headers: headers() });
    if (!res.ok) {
      var text = "";
      try { text = await res.text(); } catch (_) {}
      throw new Error("HTTP " + res.status + ": " + (text || res.statusText));
    }
    return res.json();
  }

  async function fetchData() {
    if (_apiUnavailable || !apiBase()) {
      return { mock: true, ...MOCK };
    }
    try {
      var _a = await apiFetch("/v1/verifiers");
      var _b = await apiFetch("/v1/attestations?limit=20");
      var _c = await apiFetch("/v1/challenges?status=OPEN");
      var _d = await apiFetch("/v1/network/stats");
      return {
        mock: false,
        verifiers: Array.isArray(_a) ? _a : (_a.data || _a.verifiers || []),
        attestations: Array.isArray(_b) ? _b : (_b.data || _b.attestations || []),
        challenges: Array.isArray(_c) ? _c : (_c.data || _c.challenges || []),
        stats: _d || _d.data || _d.stats || {},
      };
    } catch (err) {
      console.warn("[verifier-explorer] API unavailable, using mock data:", err.message);
      _apiUnavailable = true;
      return { mock: true, ...MOCK };
    }
  }

  /* ──────────────────────────────────────────
   * Render
   * ────────────────────────────────────────── */
  function renderStats(stats) {
    el("[data-stat='total-verifiers']").textContent = stats.total_verifiers || 0;
    el("[data-stat='active-challenges']").textContent = stats.active_challenges || 0;
    el("[data-stat='attestations-24h']").textContent = stats.attestations_24h || 0;
    el("[data-stat='avg-confidence']").textContent =
      stats.avg_confidence != null ? (stats.avg_confidence * 100).toFixed(1) + "%" : "—";
  }

  function renderVerifiers(verifiers) {
    var container = el("[data-list='verifiers']");
    if (!container) return;
    if (!verifiers || !verifiers.length) {
      container.innerHTML = '<div class="sub" style="padding:1rem">No verifiers found.</div>';
      return;
    }
    var html = "";
    verifiers.forEach(function (v) {
      var statusDot = v.is_active ? "#5eead4" : "#4b5563";
      var statusLabel = v.is_active ? "Active" : "Inactive";
      var scoreColor = v.reputation_score >= 90 ? "#5eead4" : v.reputation_score >= 70 ? "#fbbf24" : "#f87171";
      html +=
        '<div class="verifier-card">' +
          '<div class="verifier-card-top">' +
            '<span class="verifier-dot" style="background:' + statusDot + '"></span>' +
            '<span class="verifier-addr" title="' + esc(v.wallet_address) + '">' + esc(truncate(v.wallet_address)) + '</span>' +
            '<span class="verifier-status" style="color:' + statusDot + '">' + esc(statusLabel) + '</span>' +
          '</div>' +
          '<div class="verifier-stats">' +
            '<div class="vstat"><div class="vstat-val">' + esc(fmtNum(v.stake_amount)) + '</div><div class="vstat-lbl">Stake</div></div>' +
            '<div class="vstat"><div class="vstat-val" style="color:' + scoreColor + '">' + esc(v.reputation_score) + '</div><div class="vstat-lbl">Reputation</div></div>' +
            '<div class="vstat"><div class="vstat-val">' + esc(v.total_attestations) + '</div><div class="vstat-lbl">Verified</div></div>' +
            '<div class="vstat"><div class="vstat-val">' + esc(ratioOK(v.successful_attestations, v.total_attestations)) + '</div><div class="vstat-lbl">Success</div></div>' +
          '</div>' +
        '</div>';
    });
    container.innerHTML = html;
  }

  function renderAttestations(attestations) {
    var container = el("[data-list='attestations']");
    if (!container) return;
    if (!attestations || !attestations.length) {
      container.innerHTML = '<div class="sub" style="padding:1rem">No attestations yet.</div>';
      return;
    }
    var html = "";
    attestations.forEach(function (a) {
      var color = statusColor(a.decision);
      html +=
        '<div class="att-row">' +
          '<div class="att-dot" style="background:' + color + '"></div>' +
          '<div class="att-body">' +
            '<div class="att-task">' + esc(truncate(a.task_id, 10, 6)) + '</div>' +
            '<div class="att-meta">' +
              'by <strong>' + esc(a.verifier_id) + '</strong> · ' +
              esc(a.checks_passed || "?") + '/' + esc(a.checks_total || "?") + ' checks · ' +
              esc(relTime(a.created_at)) +
            '</div>' +
          '</div>' +
          '<div class="att-decision" style="color:' + color + '">' + esc(a.decision || "—") + '</div>' +
        '</div>';
    });
    container.innerHTML = html;
  }

  function renderChallenges(challenges) {
    var container = el("[data-list='challenges']");
    if (!container) return;
    if (!challenges || !challenges.length) {
      container.innerHTML = '<div class="sub" style="padding:1rem;color:#5eead4">No active challenges ✓</div>';
      return;
    }
    var html = "";
    challenges.forEach(function (ch) {
      var cls = challengeStatusClass(ch.status);
      var label = challengeStatusLabel(ch.status);
      html +=
        '<details class="challenge-entry">' +
          '<summary class="challenge-summary">' +
            '<span class="badge ' + cls + '">' + esc(label) + '</span>' +
            '<span class="ch-task">' + esc(truncate(ch.task_id, 10, 6)) + '</span>' +
            '<span class="ch-quorum">Quorum: ' + esc(ch.quorum_size) + '</span>' +
            '<span class="ch-time">' + esc(relTime(ch.window_end)) + '</span>' +
          '</summary>' +
          '<div class="challenge-detail">' +
            '<div class="sub">Reason: ' + esc(ch.reason) + '</div>' +
            '<div class="sub">Challenge ID: ' + esc(ch.id) + '</div>' +
            '<div class="sub">Window ends: ' + esc(fmtTime(ch.window_end)) + '</div>' +
          '</div>' +
        '</details>';
    });
    container.innerHTML = html;
  }

  function renderMockBanner() {
    var banner = el("[data-mock-banner]");
    if (banner) {
      banner.style.display = _apiUnavailable || !apiBase() ? "block" : "none";
    }
  }

  function esc(s) {
    if (s == null) return "";
    var t = String(s);
    return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function fmtNum(n) {
    if (n == null) return "—";
    n = Number(n);
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return String(n);
  }

  /* ──────────────────────────────────────────
   * Main orchestration
   * ────────────────────────────────────────── */
  var _refreshTimer = null;
  var _lastFetchTime = null;

  async function fetchAndRender() {
    var loading = el("[data-refresh-status]");
    if (loading) loading.textContent = "Refreshing…";

    try {
      var data = await fetchData();
      renderStats(data.stats);
      renderVerifiers(data.verifiers);
      renderAttestations(data.attestations);
      renderChallenges(data.challenges);
      renderMockBanner();
      _lastFetchTime = new Date();
      if (loading) loading.textContent = "Updated " + _lastFetchTime.toLocaleTimeString();
    } catch (err) {
      console.error("[verifier-explorer] render error:", err);
      if (loading) loading.textContent = "Error: " + err.message;
    }
  }

  function autoRefresh(intervalMs) {
    if (_refreshTimer) clearInterval(_refreshTimer);
    _refreshTimer = setInterval(fetchAndRender, intervalMs || 5000);
  }

  function stopAutoRefresh() {
    if (_refreshTimer) {
      clearInterval(_refreshTimer);
      _refreshTimer = null;
    }
  }

  /* ──────────────────────────────────────────
   * Public API
   * ────────────────────────────────────────── */
  global.VerifierExplorer = {
    fetchAndRender: fetchAndRender,
    autoRefresh: autoRefresh,
    stopAutoRefresh: stopAutoRefresh,
    MOCK: MOCK,
  };

  /* ──────────────────────────────────────────
   * Bootstrap on DOM ready
   * ────────────────────────────────────────── */
  function bootstrap() {
    // Read config
    var stored = {};
    try {
      stored = JSON.parse(localStorage.getItem("karma_console_cfg") || "{}");
    } catch (_) {}

    var apiBaseEl = el("[data-cfg='api_base']");
    var apiKeyEl = el("[data-cfg='api_key']");
    if (apiBaseEl) apiBaseEl.value = global.KARMA_API_BASE || stored.api_base || "";
    if (apiKeyEl) apiKeyEl.value = global.KARMA_API_KEY || stored.api_key || "";

    // Save config handler
    var saveBtn = el("[data-action='save-cfg']");
    if (saveBtn) {
      saveBtn.addEventListener("click", function () {
        var base = (apiBaseEl ? apiBaseEl.value.trim() : "");
        var key = (apiKeyEl ? apiKeyEl.value.trim() : "");
        global.KARMA_API_BASE = base;
        global.KARMA_API_KEY = key;
        var cfg = { api_base: base, api_key: key };
        localStorage.setItem("karma_console_cfg", JSON.stringify(cfg));
        _apiUnavailable = false;
        fetchAndRender();
      });
    }

    // Initial load
    fetchAndRender();

    // Auto-refresh
    var autoEl = el("[data-action='toggle-auto']");
    if (autoEl) {
      autoEl.addEventListener("change", function () {
        if (autoEl.checked) autoRefresh(5000);
        else stopAutoRefresh();
      });
      // Start auto-refresh by default
      autoEl.checked = true;
      autoRefresh(5000);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }
})(window);
