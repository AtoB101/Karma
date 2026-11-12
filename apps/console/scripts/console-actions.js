/**
 * Wire Payments / Receiving / Disputes / Evidence buttons to live Karma HTTP API.
 */
(function (global) {
  var LS_TASK = "karma_console_selected_task";

  function api() {
    return global.cyberKarmaApi;
  }

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function applyCfg() {
    if (global.KarmaConsoleConnect && global.KarmaConsoleConnect.savePrefs) {
      global.KarmaConsoleConnect.savePrefs(document.body);
    }
    var b = $("[data-cfg=api_base]");
    var k = $("[data-cfg=api_key]");
    var i = $("[data-cfg=identity_id]");
    if (b && b.value.trim()) global.KARMA_API_BASE = b.value.trim();
    if (k) global.KARMA_API_KEY = k.value.trim();
    if (i && i.value.trim()) global.KARMA_IDENTITY_ID = i.value.trim();
  }

  function identityId() {
    return String(global.KARMA_IDENTITY_ID || $("[data-cfg=identity_id]")?.value || "").trim();
  }

  function parseTaskIds() {
    var raw = $("[data-cfg=task_ids]")?.value || "";
    return String(raw)
      .split(/[\s,;]+/)
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
  }

  function selectedTaskId() {
    var sel = $("[data-action-task-select]");
    if (sel && sel.value) return sel.value.trim();
    try {
      var saved = localStorage.getItem(LS_TASK);
      if (saved) return saved;
    } catch (_) {}
    var ids = parseTaskIds();
    return ids.length ? ids[0] : "";
  }

  function workerId() {
    return ($("[data-action-worker]")?.value || "").trim();
  }

  function amount() {
    var v = Number($("[data-action-amount]")?.value || 0);
    return v > 0 ? v : 10;
  }

  function reason() {
    return ($("[data-action-reason]")?.value || "").trim() || "console action";
  }

  function setOut(obj, err) {
    var n = $("[data-console-action-out]");
    if (!n) return;
    if (err) {
      n.textContent = "Error: " + (err.message || String(err));
      if (err.body) {
        try {
          n.textContent += "\n" + JSON.stringify(err.body, null, 2);
        } catch (_) {}
      }
      return;
    }
    try {
      n.textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
    } catch (_) {
      n.textContent = String(obj);
    }
  }

  function refreshSync() {
    if (global.KarmaConsoleSync && global.KarmaConsoleSync.refreshAll) {
      return global.KarmaConsoleSync.refreshAll();
    }
    return Promise.resolve();
  }

  function populateTaskSelect() {
    var sel = $("[data-action-task-select]");
    if (!sel) return;
    var ids = parseTaskIds();
    var cur = selectedTaskId();
    sel.innerHTML = "";
    if (!ids.length) {
      var o = document.createElement("option");
      o.value = "";
      o.textContent = "(add task IDs above)";
      sel.appendChild(o);
      return;
    }
    ids.forEach(function (tid) {
      var opt = document.createElement("option");
      opt.value = tid;
      opt.textContent = tid;
      if (tid === cur) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", function () {
      try {
        localStorage.setItem(LS_TASK, sel.value);
      } catch (_) {}
    });
  }

  async function runAction(name) {
    applyCfg();
    var a = api();
    if (!a) throw new Error("karma-public-api.js not loaded");
    var tid = selectedTaskId();
    var id = identityId();

    switch (name) {
      case "capacity-lock":
        if (!id) throw new Error("identity_id required");
        return a.lockCapacity(id, amount());
      case "capacity-release":
        if (!id) throw new Error("identity_id required");
        return a.releaseCapacity(id, amount());
      case "settlement-pending":
        if (!tid) throw new Error("select a task_id");
        return a.settlementPending(tid);
      case "settlement-lock": {
        if (!tid) throw new Error("select a task_id");
        var w = workerId();
        if (!w) throw new Error("worker identity required");
        return a.settlementLock(tid, w);
      }
      case "settlement-start":
        if (!tid) throw new Error("select a task_id");
        return a.settlementStart(tid);
      case "settlement-submit":
        if (!tid) throw new Error("select a task_id");
        return a.settlementSubmit(tid);
      case "settlement-fail":
        if (!tid) throw new Error("select a task_id");
        return a.settlementFail(tid);
      case "settlement-dispute":
        if (!tid) throw new Error("select a task_id");
        return a.settlementDispute(tid, reason());
      case "settlement-buyer-accept":
        if (!tid) throw new Error("select a task_id");
        return a.settlementBuyerAccept(tid);
      case "view-evidence":
        if (!tid) throw new Error("select a task_id");
        return a.getBundleForTask(tid);
      case "view-settlement":
        if (!tid) throw new Error("select a task_id");
        return a.getSettlement(tid);
      case "view-transitions":
        if (!tid) throw new Error("select a task_id");
        return a.listSettlementTransitions(tid);
      case "copy-bundle-hash": {
        if (!tid) throw new Error("select a task_id");
        var bundle = await a.getBundleForTask(tid);
        var h = bundle && bundle.final_result_hash;
        if (!h) throw new Error("no final_result_hash on bundle");
        if (global.navigator && global.navigator.clipboard) {
          await global.navigator.clipboard.writeText(String(h));
          return { copied: h };
        }
        return { hash: h, hint: "clipboard unavailable" };
      }
      case "export-bundle-json": {
        if (!tid) throw new Error("select a task_id");
        var b = await a.getBundleForTask(tid);
        var blob = new Blob([JSON.stringify(b, null, 2)], { type: "application/json" });
        var url = URL.createObjectURL(blob);
        var link = document.createElement("a");
        link.href = url;
        link.download = "bundle-" + tid + ".json";
        link.click();
        URL.revokeObjectURL(url);
        return { downloaded: link.download };
      }
      case "navigate-trade": {
        var custom = document.querySelector("[data-console-trade-href]");
        var href = custom && custom.getAttribute("href");
        if (!href) {
          href =
            global.location.pathname.indexOf("/pages/") !== -1
              ? "../trade/index.html"
              : "pages/trade/index.html";
        }
        global.location.href = href;
        return { navigated: href };
      }
      case "navigate-evidence": {
        var evHref =
          (document.querySelector("[data-console-evidence-href]") &&
            document.querySelector("[data-console-evidence-href]").getAttribute("href")) ||
          (global.location.pathname.indexOf("/pages/") !== -1 ? "../evidence/index.html" : "pages/evidence/index.html");
        global.location.href = evHref;
        return { navigated: evHref };
      }
      default:
        throw new Error("unknown action: " + name);
    }
  }

  function bindButtons() {
    document.querySelectorAll("[data-console-action]").forEach(function (btn) {
      if (btn.getAttribute("data-console-bound") === "1") return;
      btn.setAttribute("data-console-bound", "1");
      btn.addEventListener("click", function () {
        var action = btn.getAttribute("data-console-action");
        if (action === "navigate-trade" || action === "navigate-evidence") {
          runAction(action).catch(function (e) {
            setOut(null, e);
          });
          return;
        }
        setOut("Running " + action + "…", null);
        runAction(action)
          .then(function (res) {
            setOut(res);
            return refreshSync();
          })
          .catch(function (e) {
            setOut(null, e);
          });
      });
    });
  }

  function bindPanel() {
    populateTaskSelect();
    bindButtons();
    var taskInp = $("[data-cfg=task_ids]");
    if (taskInp) {
      taskInp.addEventListener("change", populateTaskSelect);
      taskInp.addEventListener("blur", populateTaskSelect);
    }
  }

  global.KarmaConsoleActions = { bind: bindPanel, runAction: runAction, populateTaskSelect: populateTaskSelect };

  document.addEventListener("DOMContentLoaded", function () {
    if (document.querySelector("[data-console-actions]")) bindPanel();
  });

  document.addEventListener("karma-console-sync-done", function () {
    populateTaskSelect();
  });
})(window);
