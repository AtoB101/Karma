/**
 * Settings — persisted server automation policy + readiness gate for Runtime Key / handoff.
 */
(function () {
  var policySaved = false;

  function $(sel) {
    return document.querySelector(sel);
  }

  function apiBase() {
    return String(window.KARMA_API_BASE || $("[data-cfg=api_base]")?.value || "http://127.0.0.1:8000")
      .trim()
      .replace(/\/$/, "");
  }

  function apiKey() {
    return String(window.KARMA_API_KEY || $("[data-cfg=api_key]")?.value || "").trim();
  }

  function headers() {
    var h = { Accept: "application/json", "Content-Type": "application/json" };
    var key = apiKey();
    if (key) h["X-Karma-Api-Key"] = key;
    return h;
  }

  function identityId() {
    return (
      $("[data-identity]")?.value?.trim() ||
      $("[data-cfg=identity_id]")?.value?.trim() ||
      window.KARMA_IDENTITY_ID ||
      ""
    );
  }

  function collectPermissions() {
    return Array.from(document.querySelectorAll("[data-perm]"))
      .filter(function (b) {
        return b.checked;
      })
      .map(function (b) {
        return b.name;
      });
  }

  function collectPolicyBody() {
    return {
      auto_enabled: !!$("[data-k=auto_enabled]")?.checked,
      single_limit: Number($("[data-k=single_limit]")?.value || 0),
      daily_limit: Number($("[data-k=daily_limit]")?.value || 0),
      permissions: collectPermissions(),
      high_risk_mode: $("[data-k=high_risk]")?.value || "always",
      responsibility_acknowledged: !!$("[data-k=responsibility_ack]")?.checked,
    };
  }

  function setPolicyStatus(text) {
    var el = $("[data-policy-status]");
    if (el) el.textContent = text;
  }

  function updateRuntimeGate() {
    var createBtn = $("[data-create-key]");
    var gate = $("[data-runtime-gate]");
    var exportBtns = document.querySelectorAll("[data-fetch-handoff-draft], [data-copy-handoff], [data-download-handoff]");
    if (createBtn) createBtn.disabled = !policySaved;
    if (gate) {
      gate.textContent = policySaved
        ? "策略已保存，可进行步骤 3 钱包签名铸造 Runtime Key。"
        : "请先保存步骤 1–2 的服务端策略（含责任边界确认）。";
      gate.style.color = policySaved ? "var(--accent)" : "#fbbf24";
    }
    exportBtns.forEach(function (btn) {
      if (btn.hasAttribute("data-copy-handoff") || btn.hasAttribute("data-download-handoff")) {
        return;
      }
    });
  }

  async function loadPolicy() {
    var id = identityId();
    if (!id) return;
    try {
      var res = await fetch(apiBase() + "/v1/identities/" + encodeURIComponent(id) + "/automation-policy", {
        method: "GET",
        headers: headers(),
      });
      var body = await res.json();
      if (!res.ok || !body.configured) {
        policySaved = false;
        setPolicyStatus("策略：未保存");
        updateRuntimeGate();
        return;
      }
      policySaved = true;
      if ("auto_enabled" in body) $("[data-k=auto_enabled]").checked = !!body.auto_enabled;
      if (body.single_limit != null) $("[data-k=single_limit]").value = String(body.single_limit);
      if (body.daily_limit != null) $("[data-k=daily_limit]").value = String(body.daily_limit);
      if (body.high_risk_mode) $("[data-k=high_risk]").value = body.high_risk_mode;
      if ("responsibility_acknowledged" in body)
        $("[data-k=responsibility_ack]").checked = !!body.responsibility_acknowledged;
      var perms = body.permissions || [];
      document.querySelectorAll("[data-perm]").forEach(function (box) {
        box.checked = perms.indexOf(box.name) >= 0;
      });
      setPolicyStatus("策略：已保存 v" + (body.policy_version || "?"));
      updateRuntimeGate();
    } catch (e) {
      setPolicyStatus("策略加载失败: " + (e.message || e));
    }
  }

  async function savePolicy() {
    var id = identityId();
    if (!id) {
      alert("请填写 Karma Identity ID");
      return;
    }
    var body = collectPolicyBody();
    if (body.auto_enabled && !body.responsibility_acknowledged) {
      alert("开启自动执行前请勾选责任边界确认");
      return;
    }
    if (body.auto_enabled && !body.permissions.length) {
      alert("请至少选择一项 Runtime 权限");
      return;
    }
    try {
      var res = await fetch(apiBase() + "/v1/identities/" + encodeURIComponent(id) + "/automation-policy", {
        method: "PUT",
        headers: headers(),
        body: JSON.stringify(body),
      });
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      policySaved = true;
      setPolicyStatus("策略：已保存 v" + (data.policy_version || "?"));
      updateRuntimeGate();
      alert("服务端策略已保存");
    } catch (e) {
      policySaved = false;
      setPolicyStatus("保存失败");
      alert(e.message || String(e));
      updateRuntimeGate();
    }
  }

  async function checkReadiness() {
    var taskId = $("[data-handoff-task-id]")?.value?.trim();
    if (!taskId) {
      alert("请填写 task_id");
      return;
    }
    var id = identityId();
    var q = new URLSearchParams({ task_id: taskId, role: "buyer" });
    if (id) q.set("karma_identity_id", id);
    var pre = $("[data-readiness-out]");
    if (pre) pre.textContent = "检查中…";
    try {
      var res = await fetch(apiBase() + "/v1/openclaw/automation-readiness?" + q.toString(), {
        method: "GET",
        headers: headers(),
      });
      var data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      if (pre) pre.textContent = JSON.stringify(data, null, 2);
      window.__karmaLastReadiness = data;
      var copyBtn = $("[data-copy-handoff]");
      var dlBtn = $("[data-download-handoff]");
      var allowExport = !!data.ready_for_task_automation;
      if (copyBtn) copyBtn.disabled = !allowExport;
      if (dlBtn) dlBtn.disabled = !allowExport;
    } catch (e) {
      if (pre) pre.textContent = String(e.message || e);
    }
  }

  function wire() {
    if (!$("[data-automation-policy]")) return;
    $("[data-save-automation-policy]")?.addEventListener("click", savePolicy);
    $("[data-check-readiness]")?.addEventListener("click", checkReadiness);
    $("[data-identity]")?.addEventListener("change", loadPolicy);
    $("[data-cfg=identity_id]")?.addEventListener("change", loadPolicy);
    loadPolicy();
    updateRuntimeGate();
  }

  window.karmaAutomationPolicy = {
    isPolicySaved: function () {
      return policySaved;
    },
    refresh: loadPolicy,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
