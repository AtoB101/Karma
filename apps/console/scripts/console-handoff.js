/**
 * Settings — OpenClaw handoff v1 export (read-only draft from Karma API).
 */
(function () {
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
    const h = { Accept: "application/json" };
    const key = apiKey();
    if (key) h["X-Karma-Api-Key"] = key;
    return h;
  }

  let lastHandoffJson = "";

  function setStatus(text) {
    const el = $("[data-handoff-status]");
    if (el) el.textContent = text;
  }

  function setOut(obj) {
    const pre = $("[data-handoff-out]");
    if (!pre) return;
    pre.textContent = obj ? JSON.stringify(obj, null, 2) : "—";
  }

  function enableActions(enabled) {
    const copy = $("[data-copy-handoff]");
    const dl = $("[data-download-handoff]");
    if (copy) copy.disabled = !enabled;
    if (dl) dl.disabled = !enabled;
  }

  async function fetchDraft() {
    const taskId = $("[data-handoff-task-id]")?.value?.trim();
    if (!taskId) {
      setStatus("请输入 task_id");
      return;
    }
    const traceId = $("[data-handoff-trace-id]")?.value?.trim() || "";
    const q = new URLSearchParams({ task_id: taskId });
    if (traceId) q.set("trace_id", traceId);
    setStatus("加载中…");
    enableActions(false);
    lastHandoffJson = "";
    try {
      const url = apiBase() + "/v1/openclaw/handoff-draft?" + q.toString();
      const res = await fetch(url, { method: "GET", headers: headers() });
      const text = await res.text();
      let body;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = { raw: text };
      }
      if (!res.ok) {
        throw new Error((body && (body.detail || body.message)) || res.statusText);
      }
      setOut(body);
      lastHandoffJson = JSON.stringify(body.handoff || body, null, 2);
      enableActions(!!lastHandoffJson);
      const ok = body.validation_ok;
      const warns = (body.warnings || []).join(" · ");
      const errs = (body.validation_errors || []).join(" · ");
      setStatus(
        (ok ? "校验通过（请人工复核步骤）" : "校验未通过") +
          (warns ? " · 警告: " + warns : "") +
          (errs ? " · " + errs : "")
      );
    } catch (e) {
      setOut({ error: String(e.message || e) });
      setStatus("失败: " + (e.message || e));
      enableActions(false);
    }
  }

  function wire() {
    const root = document.querySelector("[data-openclaw-handoff]");
    if (!root) return;

    const savedTasks = localStorage.getItem("karma_console_task_ids") || "";
    const firstTask = savedTasks.split(/[\s,]+/).filter(Boolean)[0];
    const taskInp = $("[data-handoff-task-id]");
    if (taskInp && !taskInp.value && firstTask) taskInp.value = firstTask;

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
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
