/**
 * Settings — OpenClaw handoff: readiness → server attestation → export.
 */
(function () {
  var handoffAttested = false;

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

  function identityId() {
    return (
      $("[data-identity]")?.value?.trim() ||
      $("[data-cfg=identity_id]")?.value?.trim() ||
      window.KARMA_IDENTITY_ID ||
      ""
    );
  }

  function headers(json) {
    const h = { Accept: "application/json" };
    const key = apiKey();
    if (key) h["X-Karma-Api-Key"] = key;
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  let lastHandoffJson = "";
  let lastDraftBody = null;

  function setStatus(text) {
    const el = $("[data-handoff-status]");
    if (el) el.textContent = text;
  }

  function setAttestationStatus(text) {
    const el = $("[data-attestation-status]");
    if (el) el.textContent = text;
  }

  function setOut(obj) {
    const pre = $("[data-handoff-out]");
    if (!pre) return;
    pre.textContent = obj ? JSON.stringify(obj, null, 2) : "—";
  }

  function updateExportGate() {
    const ready =
      handoffAttested &&
      (!window.karmaAutomationPolicy || window.karmaAutomationPolicy.isPolicySaved());
    const copy = $("[data-copy-handoff]");
    const dl = $("[data-download-handoff]");
    const draftBtn = $("[data-fetch-handoff-draft]");
    if (copy) copy.disabled = !ready || !lastHandoffJson;
    if (dl) dl.disabled = !ready || !lastHandoffJson;
    if (draftBtn) draftBtn.disabled = !handoffAttested;
    const confirmBtn = $("[data-confirm-handoff]");
    if (confirmBtn) {
      const r = window.__karmaLastReadiness;
      confirmBtn.disabled = !(r && r.ready_for_handoff_confirm);
    }
  }

  async function checkAttestation(taskId, id) {
    const q = new URLSearchParams({ task_id: taskId, karma_identity_id: id });
    const res = await fetch(apiBase() + "/v1/openclaw/handoff-attestation?" + q.toString(), {
      method: "GET",
      headers: headers(),
    });
    const body = await res.json();
    handoffAttested = res.ok && body && body.attested === true;
    setAttestationStatus(handoffAttested ? "存证：已登记 " + (body.created_at || "") : "存证：未登记");
    updateExportGate();
    return body;
  }

  async function checkReadiness() {
    const taskId = $("[data-handoff-task-id]")?.value?.trim();
    const id = identityId();
    if (!taskId || !id) {
      alert("请填写 task_id 与 Identity");
      return;
    }
    const q = new URLSearchParams({
      task_id: taskId,
      role: "buyer",
      karma_identity_id: id,
      for_handoff_confirm: "true",
    });
    const pre = $("[data-readiness-out]");
    if (pre) pre.textContent = "检查中…";
    try {
      const res = await fetch(apiBase() + "/v1/openclaw/automation-readiness?" + q.toString(), {
        method: "GET",
        headers: headers(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      window.__karmaLastReadiness = data;
      if (pre) pre.textContent = JSON.stringify(data, null, 2);
      if (!data.ready_for_handoff_confirm) {
        setStatus("未就绪 — 请先解决 blockers");
        handoffAttested = false;
        setAttestationStatus("存证：未登记（未就绪）");
      } else {
        setStatus("可登记存证 — 请点击 ②");
        await checkAttestation(taskId, id);
      }
      updateExportGate();
    } catch (e) {
      if (pre) pre.textContent = String(e.message || e);
      setStatus("就绪检查失败");
    }
  }

  async function confirmHandoff() {
    const taskId = $("[data-handoff-task-id]")?.value?.trim();
    const id = identityId();
    const traceId = $("[data-handoff-trace-id]")?.value?.trim() || "";
    if (!taskId || !id) {
      alert("请填写 task_id 与 Identity");
      return;
    }
    const r = window.__karmaLastReadiness;
    if (!r || !r.ready_for_handoff_confirm) {
      alert("请先通过 ① 自动化就绪检查");
      return;
    }
    setAttestationStatus("存证登记中…");
    try {
      const payload = {
        task_id: taskId,
        karma_identity_id: id,
        role: "buyer",
        trace_id: traceId,
        handoff: lastDraftBody && lastDraftBody.handoff ? lastDraftBody.handoff : null,
      };
      const res = await fetch(apiBase() + "/v1/openclaw/handoff-confirm", {
        method: "POST",
        headers: headers(true),
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data.detail === "object" ? JSON.stringify(data.detail) : data.detail);
      handoffAttested = true;
      setAttestationStatus("存证：已登记 ✓");
      setStatus("服务端存证完成 — 可生成并导出 handoff");
      updateExportGate();
    } catch (e) {
      setAttestationStatus("存证失败");
      alert(e.message || String(e));
    }
  }

  async function fetchDraft() {
    const taskId = $("[data-handoff-task-id]")?.value?.trim();
    if (!taskId) {
      setStatus("请输入 task_id");
      return;
    }
    if (window.karmaAutomationPolicy && !window.karmaAutomationPolicy.isPolicySaved()) {
      setStatus("请先保存服务端自动授权策略");
      return;
    }
    if (!handoffAttested) {
      setStatus("请先完成 ② 服务端存证");
      return;
    }
    const traceId = $("[data-handoff-trace-id]")?.value?.trim() || "";
    const q = new URLSearchParams({ task_id: taskId });
    if (traceId) q.set("trace_id", traceId);
    setStatus("加载草案…");
    lastHandoffJson = "";
    try {
      const res = await fetch(apiBase() + "/v1/openclaw/handoff-draft?" + q.toString(), {
        method: "GET",
        headers: headers(),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || JSON.stringify(body));
      lastDraftBody = body;
      setOut(body);
      lastHandoffJson = JSON.stringify(body.handoff || body, null, 2);
      setStatus(body.validation_ok ? "草案有效 — 可导出" : "草案校验未通过");
      updateExportGate();
    } catch (e) {
      setOut({ error: String(e.message || e) });
      setStatus("失败: " + (e.message || e));
    }
  }

  function wire() {
    if (!$("[data-openclaw-handoff]")) return;

    const savedTasks = localStorage.getItem("karma_console_task_ids") || "";
    const firstTask = savedTasks.split(/[\s,]+/).filter(Boolean)[0];
    const taskInp = $("[data-handoff-task-id]");
    if (taskInp && !taskInp.value && firstTask) taskInp.value = firstTask;

    $("[data-check-readiness]")?.addEventListener("click", checkReadiness);
    $("[data-confirm-handoff]")?.addEventListener("click", confirmHandoff);
    $("[data-fetch-handoff-draft]")?.addEventListener("click", fetchDraft);
    $("[data-copy-handoff]")?.addEventListener("click", async () => {
      if (!lastHandoffJson) return;
      await navigator.clipboard.writeText(lastHandoffJson);
      setStatus("已复制 handoff JSON");
    });
    $("[data-download-handoff]")?.addEventListener("click", () => {
      if (!lastHandoffJson) return;
      const blob = new Blob([lastHandoffJson], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "openclaw-handoff.json";
      a.click();
      URL.revokeObjectURL(a.href);
      setStatus("已下载 openclaw-handoff.json");
    });

    updateExportGate();
  }

  window.karmaHandoffFlow = { isAttested: function () { return handoffAttested; } };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
