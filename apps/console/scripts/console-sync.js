/**
 * Console — periodic state sync against Karma public HTTP API (openapi/karma-v1 aligned reads).
 * Uses same localStorage keys as cyber-console where applicable.
 */
(function (global) {
  var LS_BASE = "karma_cyber_api_base";
  var LS_KEY = "karma_cyber_api_key";
  var LS_ID = "karma_cyber_identity_id";
  var LS_TASKS = "karma_console_task_ids";
  var LS_AUTO = "karma_console_auto_sync";
  var DEFAULT_INTERVAL_MS = 10000;

  function api() {
    return global.cyberKarmaApi;
  }

  function el(root, sel) {
    return (root || document).querySelector(sel);
  }

  function els(root, sel) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function parseTaskIds(raw) {
    if (!raw || !String(raw).trim()) return [];
    return String(raw)
      .split(/[\s,;]+/)
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
  }

  function applyWindowFromInputs() {
    var b = el(document.body, "[data-cfg=api_base]");
    var k = el(document.body, "[data-cfg=api_key]");
    var i = el(document.body, "[data-cfg=identity_id]");
    if (b && b.value.trim()) global.KARMA_API_BASE = b.value.trim();
    if (k) global.KARMA_API_KEY = k.value.trim();
    if (i && i.value.trim()) global.KARMA_IDENTITY_ID = i.value.trim();
  }

  function saveLocalPrefs() {
    try {
      var b = el(document.body, "[data-cfg=api_base]");
      var k = el(document.body, "[data-cfg=api_key]");
      var i = el(document.body, "[data-cfg=identity_id]");
      var t = el(document.body, "[data-cfg=task_ids]");
      var a = el(document.body, "[data-cfg=auto_sync]");
      if (b) localStorage.setItem(LS_BASE, b.value.trim());
      if (k) localStorage.setItem(LS_KEY, k.value.trim());
      if (i) localStorage.setItem(LS_ID, i.value.trim());
      if (t) localStorage.setItem(LS_TASKS, t.value.trim());
      if (a) localStorage.setItem(LS_AUTO, a.checked ? "1" : "");
    } catch (_) {}
  }

  function loadTaskIdsIntoInput() {
    var inp = el(document.body, "[data-cfg=task_ids]");
    if (!inp) return;
    try {
      var v = localStorage.getItem(LS_TASKS) || "";
      if (v && !inp.value.trim()) inp.value = v;
    } catch (_) {}
    var cb = el(document.body, "[data-cfg=auto_sync]");
    if (cb) {
      try {
        cb.checked = localStorage.getItem(LS_AUTO) === "1";
      } catch (_) {}
    }
  }

  function setText(root, selector, text) {
    var n = el(root, selector) || el(document, selector);
    if (n) n.textContent = text == null ? "—" : String(text);
  }

  function fmtNum(x) {
    var n = Number(x);
    if (Number.isNaN(n)) return "—";
    return n.toFixed(2);
  }

  function applyCapacity(cap) {
    if (!cap || typeof cap !== "object") return;
    setText(document.body, "[data-bind=total_locked_usdc]", fmtNum(cap.total_locked_usdc));
    setText(document.body, "[data-bind=available_credits]", fmtNum(cap.available_credits));
    var comb = (Number(cap.in_progress_credits) || 0) + (Number(cap.reserved_credits) || 0);
    setText(document.body, "[data-bind=in_progress_bucket]", fmtNum(comb));
    setText(document.body, "[data-bind=pending_settlement_credits]", fmtNum(cap.pending_settlement_credits));
    setText(document.body, "[data-bind=disputed_credits]", fmtNum(cap.disputed_credits));
    els(document, "[data-sync-bind=capacity_json]").forEach(function (n) {
      try {
        n.textContent = JSON.stringify(cap, null, 2);
      } catch (_) {
        n.textContent = String(cap);
      }
    });
  }

  function maxProgressPct(progressList) {
    if (!Array.isArray(progressList) || !progressList.length) return 0;
    var m = 0;
    progressList.forEach(function (p) {
      var v = Number(p.claimed_value_percent != null ? p.claimed_value_percent : p.progress_percent);
      if (!Number.isNaN(v) && v > m) m = v;
    });
    return m;
  }

  function roleHint(identityId, contract, settlement) {
    if (!identityId) return "—";
    if (contract && contract.client_agent_id === identityId) return "buyer";
    if (settlement && settlement.worker_agent_id === identityId) return "seller";
    if (contract && contract.worker_agent_id === identityId) return "seller";
    return "—";
  }

  function counterparty(identityId, contract, settlement) {
    if (!contract && !settlement) return "—";
    var cid = contract && contract.client_agent_id;
    var wid = (settlement && settlement.worker_agent_id) || (contract && contract.worker_agent_id);
    if (identityId === cid) return wid || "—";
    if (identityId === wid) return cid || "—";
    return (wid || "—") + " / " + (cid || "—");
  }

  function renderTasksTbody(tbody, identityId, taskIds) {
    if (!tbody) return;
    if (!taskIds.length) {
      tbody.innerHTML =
        '<tr><td colspan="8" style="color:var(--muted)">Configure comma-separated <code>task_id</code> values, Save, then Refresh / enable auto-sync.</td></tr>';
      return;
    }
    var a = api();
    if (!a || !a.getSettlement) {
      tbody.innerHTML =
        '<tr><td colspan="8" style="color:var(--muted)">Missing karma-public-api.js</td></tr>';
      return;
    }
    tbody.innerHTML = "";
    taskIds.forEach(function (tid) {
      var tr = document.createElement("tr");
      var tdLoad = document.createElement("td");
      tdLoad.colSpan = 8;
      tdLoad.textContent = tid + " …";
      tr.appendChild(tdLoad);
      tbody.appendChild(tr);
      Promise.all([
        a.getSettlement(tid).catch(function (e) {
          return { _err: e.message || String(e) };
        }),
        a.getContract(tid).catch(function () {
          return null;
        }),
        a.listReceiptsForTask(tid).catch(function () {
          return [];
        }),
        a.listProgressForTask(tid).catch(function () {
          return [];
        }),
      ]).then(function (parts) {
        var s = parts[0];
        var c = parts[1];
        var rcpts = parts[2];
        var prog = parts[3];
        tr.innerHTML = "";
        function addCell(text) {
          var td = document.createElement("td");
          td.textContent = text;
          tr.appendChild(td);
        }
        if (s && s._err) {
          var tdErr = document.createElement("td");
          tdErr.colSpan = 8;
          tdErr.textContent = tid + ": " + s._err;
          tr.appendChild(tdErr);
          return;
        }
        var rc = Array.isArray(rcpts) ? rcpts.length : 0;
        addCell(tid);
        tr.setAttribute("data-task-row", tid);
        tr.style.cursor = "pointer";
        tr.title = "Click to select for quick actions";
        tr.addEventListener("click", function () {
          try {
            localStorage.setItem("karma_console_selected_task", tid);
          } catch (_) {}
          if (global.KarmaConsoleActions && global.KarmaConsoleActions.populateTaskSelect) {
            global.KarmaConsoleActions.populateTaskSelect();
          }
          var sel = document.querySelector("[data-action-task-select]");
          if (sel) sel.value = tid;
        });
        addCell(roleHint(identityId, c, s));
        addCell(counterparty(identityId, c, s));
        addCell(s ? fmtNum(s.escrow_amount) + " " + (s.currency || "") : "—");
        addCell(String(maxProgressPct(prog)) + "%");
        addCell(s ? String(s.status) : "—");
        var nxt =
          s && s.status === "delivered"
            ? "buyer-accept / dispute"
            : s && s.status === "disputed"
              ? "arbitration"
              : "—";
        addCell(nxt);
        addCell(String(rc));
      });
    });
  }

  function renderAgentsTbody(tbody) {
    if (!tbody) return;
    var a = api();
    tbody.innerHTML = '<tr><td colspan="5">…</td></tr>';
    a
      .listAgents()
      .then(function (list) {
        tbody.innerHTML = "";
        if (!Array.isArray(list) || !list.length) {
          tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted)">No agents</td></tr>';
          return;
        }
        list.slice(0, 200).forEach(function (ag) {
          var tr = document.createElement("tr");
          ["agent_id", "name", "role", "endpoint_url", "capabilities"].forEach(function (k) {
            var td = document.createElement("td");
            var v = ag[k];
            td.textContent = k === "capabilities" && Array.isArray(v) ? v.join(", ") : v == null ? "—" : String(v);
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
      })
      .catch(function (e) {
        tbody.innerHTML =
          '<tr><td colspan="5" style="color:var(--muted)">' + (e.message || e) + "</td></tr>";
      });
  }

  function renderEvidenceTbody(tbody, taskIds) {
    if (!tbody) return;
    if (!taskIds.length) {
      tbody.innerHTML =
        '<tr><td colspan="4" style="color:var(--muted)">Add task IDs to load evidence bundles.</td></tr>';
      return;
    }
    var a = api();
    tbody.innerHTML = '<tr><td colspan="4">…</td></tr>';
    Promise.all(
      taskIds.map(function (tid) {
        return a
          .getBundleForTask(tid)
          .then(function (b) {
            return { tid: tid, b: b, err: null };
          })
          .catch(function (e) {
            return { tid: tid, b: null, err: e.message || String(e) };
          });
      })
    ).then(function (rows) {
      tbody.innerHTML = "";
      rows.forEach(function (row) {
        var tr = document.createElement("tr");
        [row.tid, row.b && row.b.bundle_id, row.b && row.b.final_result_hash ? String(row.b.final_result_hash).slice(0, 20) + "…" : "—", row.err || "ok"].forEach(
          function (t) {
            var td = document.createElement("td");
            td.textContent = t;
            tr.appendChild(td);
          });
        tbody.appendChild(tr);
      });
    });
  }

  function renderDisputesTbody(tbody, identityId, taskIds) {
    if (!tbody) return;
    if (!taskIds.length) {
      tbody.innerHTML =
        '<tr><td colspan="5" style="color:var(--muted)">Add task IDs; only <code>disputed</code> settlements are listed.</td></tr>';
      return;
    }
    var a = api();
    tbody.innerHTML = '<tr><td colspan="5">…</td></tr>';
    Promise.all(
      taskIds.map(function (tid) {
        return a.getSettlement(tid).catch(function () {
          return null;
        });
      })
    ).then(function (states) {
      tbody.innerHTML = "";
      var any = false;
      taskIds.forEach(function (tid, i) {
        var s = states[i];
        if (!s || String(s.status) !== "disputed") return;
        any = true;
        var tr = document.createElement("tr");
        [tid, String(s.status), s.dispute_reason || "—", fmtNum(s.escrow_amount), identityId || "—"].forEach(function (t) {
          var td = document.createElement("td");
          td.textContent = t;
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      if (!any) {
        tbody.innerHTML =
          '<tr><td colspan="5" style="color:var(--muted)">No disputed tasks in the current ID list.</td></tr>';
      }
    });
  }

  async function refreshAll() {
    applyWindowFromInputs();
    var a = api();
    if (!a) return;
    var identityId = String(global.KARMA_IDENTITY_ID || el(document.body, "[data-cfg=identity_id]")?.value || "").trim();
    var taskRaw = el(document.body, "[data-cfg=task_ids]")?.value || localStorage.getItem(LS_TASKS) || "";
    var taskIds = parseTaskIds(taskRaw);

    var tstr = new Date().toLocaleTimeString();
    setText(document.body, "[data-bind=console_last_sync]", tstr);

    try {
      var h = await a.getHealth();
      setText(document.body, "[data-bind=health_status]", (h && h.status) || "ok");
    } catch (e) {
      setText(document.body, "[data-bind=health_status]", "err: " + (e.message || e));
    }

    try {
      var info = await a.getV1Info();
      setText(document.body, "[data-bind=api_env]", (info && info.app_env) || "—");
      setText(document.body, "[data-bind=api_version]", (info && info.version) || "—");
    } catch (_) {
      setText(document.body, "[data-bind=api_env]", "—");
      setText(document.body, "[data-bind=api_version]", "—");
    }

    if (identityId) {
      try {
        setText(document.body, "[data-bind=sync_capacity_error]", "");
        var cap = await a.getCapacity(identityId);
        applyCapacity(cap);
      } catch (e) {
        setText(document.body, "[data-bind=sync_capacity_error]", e.message || String(e));
      }
    }

    try {
      var sm = await a.getRuntimeSafetyMode();
      setText(document.body, "[data-bind=safety_enabled]", sm && sm.enabled ? "yes" : "no");
      setText(document.body, "[data-bind=safety_detail]", (sm && (sm.reason || "")) || "—");
    } catch (e) {
      setText(document.body, "[data-bind=safety_enabled]", "n/a");
      setText(document.body, "[data-bind=safety_detail]", e.message || String(e));
    }

    var tbTasks = el(document.body, "[data-sync-table=tasks]");
    if (tbTasks) renderTasksTbody(tbTasks, identityId, taskIds);

    var tbAgents = el(document.body, "[data-sync-table=agents]");
    if (tbAgents) renderAgentsTbody(tbAgents);

    var tbEv = el(document.body, "[data-sync-table=evidence]");
    if (tbEv) renderEvidenceTbody(tbEv, taskIds);

    var tbDisp = el(document.body, "[data-sync-table=disputes]");
    if (tbDisp) renderDisputesTbody(tbDisp, identityId, taskIds);

    try {
      document.dispatchEvent(new CustomEvent("karma-console-sync-done"));
    } catch (_) {}
  }

  var _timer = null;

  function stopAuto() {
    if (_timer) {
      clearInterval(_timer);
      _timer = null;
    }
  }

  function startAuto(root) {
    stopAuto();
    var r = root || document.body;
    var ms = parseInt(r.getAttribute("data-sync-interval-ms") || String(DEFAULT_INTERVAL_MS), 10);
    if (ms < 3000) ms = 3000;
    var cb = el(r, "[data-cfg=auto_sync]") || el(document.body, "[data-cfg=auto_sync]");
    if (cb && !cb.checked) return;
    _timer = setInterval(function () {
      if (document.visibilityState !== "visible") return;
      refreshAll().catch(function () {});
    }, ms);
  }

  function hydrateInputsFromLS() {
    try {
      var b = el(document.body, "[data-cfg=api_base]");
      var k = el(document.body, "[data-cfg=api_key]");
      var i = el(document.body, "[data-cfg=identity_id]");
      var t = el(document.body, "[data-cfg=task_ids]");
      if (b && !b.value.trim()) b.value = localStorage.getItem(LS_BASE) || "";
      if (k && !k.value.trim()) k.value = localStorage.getItem(LS_KEY) || "";
      if (i && !i.value.trim()) i.value = localStorage.getItem(LS_ID) || "";
      if (t && !t.value.trim()) t.value = localStorage.getItem(LS_TASKS) || "";
    } catch (_) {}
  }

  function bind(root) {
    hydrateInputsFromLS();
    var r = root || document.body;
    loadTaskIdsIntoInput();

    els(r, "[data-action=karma-save-cfg]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        applyWindowFromInputs();
        saveLocalPrefs();
        refreshAll().catch(function () {});
        startAuto(r);
      });
    });
    els(document, "[data-action=karma-refresh-now]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        applyWindowFromInputs();
        refreshAll().catch(function () {});
      });
    });
    var cbAuto = el(r, "[data-cfg=auto_sync]") || el(document.body, "[data-cfg=auto_sync]");
    if (cbAuto) {
      cbAuto.addEventListener("change", function () {
        saveLocalPrefs();
        stopAuto();
        startAuto(r);
      });
    }
    els(document, "[data-action=save-cfg]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setTimeout(function () {
          saveLocalPrefs();
          startAuto(document.body);
        }, 0);
      });
    });

    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") refreshAll().catch(function () {});
    });

    refreshAll()
      .then(function () {
        startAuto(r);
      })
      .catch(function () {});
  }

  global.KarmaConsoleSync = { refreshAll: refreshAll, startAuto: startAuto, stopAuto: stopAuto, bind: bind };

  document.addEventListener("DOMContentLoaded", function () {
    var root = document.querySelector("[data-karma-console-root]");
    if (root) bind(root);
    else if (document.querySelector("[data-sync-table]") || document.querySelector("[data-sync-bind]"))
      bind(document.body);
  });
})(window);
