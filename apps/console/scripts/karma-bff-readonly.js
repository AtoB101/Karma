/**
 * Read-only Karma BFF status (no secrets). Set window.KARMA_BFF_PUBLIC_BASE before this script
 * (e.g. in an inline script or config.js) to your BFF origin, e.g. http://127.0.0.1:8820
 */
(function () {
  function base() {
    return String(window.KARMA_BFF_PUBLIC_BASE || "")
      .trim()
      .replace(/\/$/, "");
  }

  async function fetchStatus(traceId) {
    const b = base();
    if (!b) return { ok: false, error: "KARMA_BFF_PUBLIC_BASE is empty" };
    const url = b + "/public/status/" + encodeURIComponent(traceId);
    const res = await fetch(url, { credentials: "omit", mode: "cors" });
    const text = await res.text();
    try {
      return { ok: res.ok, status: res.status, body: JSON.parse(text) };
    } catch {
      return { ok: res.ok, status: res.status, body: { raw: text } };
    }
  }

  function bind(root) {
    var traceEl = root.querySelector("[data-karma-bff-trace]");
    var btn = root.querySelector("[data-karma-bff-refresh]");
    var out = root.querySelector("[data-karma-bff-out]");
    var link = root.querySelector("[data-karma-bff-lock-link]");
    if (!traceEl || !btn || !out) return;
    var key = "karma_bff_last_trace_console";
    try {
      if (!traceEl.value) traceEl.value = sessionStorage.getItem(key) || "";
    } catch (_) {}
    btn.addEventListener("click", async function () {
      var tid = String(traceEl.value || "").trim();
      out.textContent = "…";
      if (link) link.textContent = "—";
      if (!tid) {
        out.textContent = "请输入 trace_id";
        return;
      }
      try {
        var r = await fetchStatus(tid);
        out.textContent = JSON.stringify(r, null, 2);
        try {
          sessionStorage.setItem(key, tid);
        } catch (_) {}
        if (link) {
          var b = base();
          if (b && r.ok && r.body && !r.body.error) {
            var href =
              (r.body.buyer_lock_page_url && String(r.body.buyer_lock_page_url)) ||
              b + "/public/lock/" + encodeURIComponent(tid);
            link.innerHTML =
              '<a href="' +
              href.replace(/"/g, "&quot;") +
              '" target="_blank" rel="noopener noreferrer">买家锁仓说明页</a>';
          } else if (b) {
            link.textContent = "状态异常或 BFF 不可达";
          } else {
            link.textContent = "未配置 KARMA_BFF_PUBLIC_BASE";
          }
        }
      } catch (e) {
        out.textContent = String(e && e.message ? e.message : e);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-karma-bff-panel]").forEach(bind);
  });
})();
