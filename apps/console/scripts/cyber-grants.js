/**
 * 消费授权管理（主人视角）：查看 / 暂停 / 恢复 / 撤销 / 调低额度。
 *
 * 每份授权 = 一张卡：agent 名称、公钥指纹、币种、总额/单笔、已用/剩余、有效期、
 * 用途范围、最近动态。管理动作都需要主人钱包签名（personal_sign），待签文本由
 * 服务端 /v1/spending-grants/{id}/action-message 返回，前端只负责调钱包签名。
 *
 * 安全边界：只调 eth_requestAccounts / eth_accounts / personal_sign，从不接触
 * 私钥 / 助记词；降低额度是即时生效，提高额度必须走新的审批（本页没有提额入口）。
 */
(function (global) {
  "use strict";

  function api() { return global.cyberKarmaApi; }
  function byId(id) { return document.getElementById(id); }
  function identity() {
    return String(global.KARMA_IDENTITY_ID || "").trim();
  }

  function node(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined && text !== null) el.textContent = text;
    return el;
  }

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"\x27]/g, function (c) {
      if (c === "&") return "&amp;";
      if (c === "<") return "&lt;";
      if (c === ">") return "&gt;";
      if (c === String.fromCharCode(34)) return "&quot;";
      return "&#39;";
    });
  }

  var LIST_ID = "grant-list";
  var STATUS_ID = "grant-status";

  function fmtNum(n) {
    var x = Number(n);
    if (!isFinite(x)) return "0.00";
    return x.toFixed(2);
  }

  function shortDate(iso) {
    if (!iso) return null;
    var d = Date.parse(iso);
    if (!isFinite(d)) return String(iso).slice(0, 10);
    return new Date(d).toISOString().slice(0, 10);
  }

  function fingerprint(pub) {
    if (!pub) return "";
    var s = String(pub);
    return s.length > 12 ? s.slice(0, 6) + "\u2026" + s.slice(-6) : s;
  }

  function setStatus(text, detail, isErr) {
    var el = byId(STATUS_ID);
    if (!el) return;
    el.textContent = text + (detail ? " " + detail : "");
    el.classList.toggle("err", !!isErr);
  }

  function statusLabel(status) {
    if (status === "active") return "活跃";
    if (status === "paused") return "已暂停";
    if (status === "revoked") return "已撤销";
    if (status === "expired") return "已过期";
    return String(status || "\u2014");
  }

  function eventLabel(type) {
    if (type === "created") return "已创建";
    if (type === "spend") return "已消费";
    if (type === "deny") return "已拒绝";
    if (type === "paused") return "已暂停";
    if (type === "resumed") return "已恢复";
    if (type === "revoked") return "已撤销";
    if (type === "limit_reduced") return "额度调低";
    return String(type || "");
  }

  function kv(label, value) {
    var row = node("div", "grant-kv");
    row.appendChild(node("span", "grant-kv-label", label));
    row.appendChild(node("span", "grant-kv-value", value));
    return row;
  }

  function clearList() {
    var list = byId(LIST_ID);
    while (list && list.firstChild) list.removeChild(list.firstChild);
    return list;
  }

  function renderEmpty(list) {
    var empty = node("div", "grant-empty");
    empty.appendChild(node("div", "grant-empty-title", "暂无授权"));
    empty.appendChild(node("p", "grant-empty-hint", "连接钱包后，这里会显示你给 agent 批的消费授权。"));
    list.appendChild(empty);
  }

  function actionButton(text, action, grant) {
    var btn = node("button", "btn", text);
    btn.type = "button";
    btn.addEventListener("click", function () {
      if (action === "reduce") return beginReduce(grant);
      return runAction(action, grant, null);
    });
    return btn;
  }

  function renderActions(actions, grant) {
    var row = node("div", "grant-actions");
    if (grant.status === "active") {
      row.appendChild(actionButton("暂停", "pause", grant));
      row.appendChild(actionButton("调低额度", "reduce", grant));
      row.appendChild(actionButton("撤销授权", "revoke", grant));
    } else if (grant.status === "paused") {
      row.appendChild(actionButton("恢复", "resume", grant));
      row.appendChild(actionButton("撤销授权", "revoke", grant));
    }
    actions.appendChild(row);
  }

  function beginReduce(grant) {
    var actions = byId("grant-actions-" + encodeURIComponent(grant.grant_id));
    if (!actions) return;
    while (actions.firstChild) actions.removeChild(actions.firstChild);

    var form = node("div", "grant-reduce");
    var label = node("label", "grant-reduce-label", "新的总额上限");
    label.setAttribute("for", "grant-reduce-input-" + encodeURIComponent(grant.grant_id));
    form.appendChild(label);
    var input = document.createElement("input");
    input.type = "number";
    input.id = "grant-reduce-input-" + encodeURIComponent(grant.grant_id);
    input.className = "grant-input";
    input.min = "0";
    input.step = "0.01";
    input.value = String(grant.total_limit);
    form.appendChild(input);
    form.appendChild(node("div", "grant-reduce-hint", "只能调低，不能调高"));
    var err = node("div", "grant-reduce-error");
    err.id = "grant-reduce-err-" + encodeURIComponent(grant.grant_id);
    err.hidden = true;
    form.appendChild(err);
    var buttons = node("div", "grant-actions");
    var ok = node("button", "btn primary", "确认");
    ok.type = "button";
    ok.addEventListener("click", function () {
      var newLimit = Number(input.value);
      if (!isFinite(newLimit) || newLimit <= 0) {
        err.textContent = "新的总额上限";
        err.hidden = false;
        return;
      }
      if (newLimit >= grant.total_limit) {
        err.textContent = "只能调低，不能调高";
        err.hidden = false;
        return;
      }
      if (newLimit < Number(grant.used_amount)) {
        err.textContent = "只能调低，不能调高";
        err.hidden = false;
        return;
      }
      runAction("reduce", grant, { new_total_limit: newLimit });
    });
    buttons.appendChild(ok);
    var cancel = node("button", "btn", "取消");
    cancel.type = "button";
    cancel.addEventListener("click", function () { renderCardActions(grant); });
    buttons.appendChild(cancel);
    form.appendChild(buttons);
    actions.appendChild(form);
  }

  function renderCardActions(grant) {
    var actions = byId("grant-actions-" + encodeURIComponent(grant.grant_id));
    if (!actions) return;
    while (actions.firstChild) actions.removeChild(actions.firstChild);
    renderActions(actions, grant);
  }

  function renderEvents(events) {
    var box = node("div", "grant-events");
    box.appendChild(node("div", "grant-events-title", "最近动态"));
    if (!events || !events.length) {
      box.appendChild(node("div", "grant-events-empty", "\u2014"));
      return box;
    }
    events.slice(0, 4).forEach(function (e) {
      var row = node("div", "grant-event");
      var left = node("span", "grant-event-type", eventLabel(e.event_type));
      row.appendChild(left);
      var mid = node("span", "grant-event-detail");
      if (e.amount !== null && e.amount !== undefined) {
        mid.appendChild(node("span", "", " " + fmtNum(e.amount)));
      }
      if (e.reason) {
        mid.appendChild(node("span", "grant-event-reason", " " + String(e.reason)));
      }
      if (e.created_at) {
        mid.appendChild(node("span", "grant-event-time", " " + String(e.created_at).replace("T", " ").slice(0, 16)));
      }
      row.appendChild(mid);
      box.appendChild(row);
    });
    return box;
  }

  function renderCard(grant, events) {
    var card = node("div", "grant-card");
    var head = node("div", "grant-card-head");
    var name = node("div", "grant-agent");
    name.appendChild(node("span", "grant-agent-name", grant.agent_name || grant.agent_id));
    if (grant.agent_public_key) {
      name.appendChild(node("span", "grant-agent-fp", fingerprint(grant.agent_public_key)));
    }
    head.appendChild(name);
    var badge = node("span", "grant-badge grant-badge-" + String(grant.status), statusLabel(grant.status));
    head.appendChild(badge);
    card.appendChild(head);

    var grid = node("div", "grant-grid");
    grid.appendChild(kv("Agent 名称", grant.agent_name || grant.agent_id));
    grid.appendChild(kv("公钥指纹", fingerprint(grant.agent_public_key) || "\u2014"));
    grid.appendChild(kv("币种", grant.currency || "USDC"));
    grid.appendChild(kv("总额上限", fmtNum(grant.total_limit)));
    grid.appendChild(kv("单笔上限", fmtNum(grant.per_tx_limit)));
    grid.appendChild(kv("已用", fmtNum(grant.used_amount)));
    grid.appendChild(kv("剩余", fmtNum(grant.remaining)));
    grid.appendChild(kv("有效期至", shortDate(grant.expires_at) || "长期有效"));
    grid.appendChild(kv("用途范围", (grant.purpose_scope || []).join(", ") || "\u2014"));
    card.appendChild(grid);

    var actions = node("div", "grant-actions");
    actions.id = "grant-actions-" + encodeURIComponent(grant.grant_id);
    renderActions(actions, grant);
    card.appendChild(actions);

    card.appendChild(renderEvents(events));
    return card;
  }

  async function loadEvents(grantId) {
    try {
      if (api() && typeof api().listGrantEvents === "function") {
        var res = await api().listGrantEvents(grantId);
        return (res && res.events) || [];
      }
      return [];
    } catch (e) {
      return [];
    }
  }

  async function render() {
    var list = clearList();
    if (!list) return;
    if (!identity()) {
      renderEmpty(list);
      return;
    }
    setStatus("", "", false);
    try {
      var res = await api().listSpendingGrants(identity());
      var grants = (res && res.grants) || [];
      if (!grants.length) {
        renderEmpty(list);
        return;
      }
      for (var i = 0; i < grants.length; i += 1) {
        var events = await loadEvents(grants[i].grant_id);
        list.appendChild(renderCard(grants[i], events));
      }
    } catch (e) {
      renderEmpty(list);
      setStatus("加载失败，请刷新重试", "", true);
    }
  }

  function currentWallet() {
    if (global.KarmaOnboardingWallet && typeof global.KarmaOnboardingWallet.currentAccount === "function") {
      return Promise.resolve(global.KarmaOnboardingWallet.currentAccount()).then(function (a) {
        return a || null;
      });
    }
    return Promise.resolve(null);
  }

  async function ensureWallet() {
    var wallet = await currentWallet();
    if (wallet) return wallet;
    var auth = global.KarmaWalletAuth;
    if (auth && typeof auth.connect === "function") {
      await auth.connect();
      wallet = await currentWallet();
    }
    return wallet;
  }

  function fetchActionMessage(grant, action, wallet, extra) {
    var q = "/v1/spending-grants/" + encodeURIComponent(grant.grant_id) +
      "/action-message?action=" + encodeURIComponent(action) +
      "&wallet_address=" + encodeURIComponent(wallet);
    if (action === "reduce" && extra && extra.new_total_limit != null) {
      q += "&new_total_limit=" + encodeURIComponent(String(extra.new_total_limit));
    }
    var base = (api() && typeof api().apiBase === "function") ? api().apiBase() : "";
    return fetch(base + q, { method: "GET", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
  }

  async function runAction(action, grant, extra) {
    setStatus("正在连接钱包…", "", false);
    var wallet;
    try {
      wallet = await ensureWallet();
    } catch (e) {
      setStatus("连接失败", "", true);
      return;
    }
    if (!wallet) {
      setStatus("请先连接钱包", "", true);
      return;
    }

    var message;
    try {
      var signBody = await fetchActionMessage(grant, action, wallet, extra);
      message = signBody && signBody.message;
      if (!message) throw new Error("no message");
    } catch (e) {
      setStatus("连接失败", "", true);
      return;
    }

    setStatus("请在钱包里签名", "", false);
    var signer = global.KarmaOnboardingWallet;
    if (!signer || typeof signer.sign !== "function") {
      setStatus("连接失败", "", true);
      return;
    }
    signer.sign(
      message,
      function (signed) {
        submitAction(action, grant, wallet, signed, extra);
      },
      function (err) {
        setStatus("签名失败", ": " + (err && err.message ? err.message : String(err)), true);
      }
    );
  }

  async function submitAction(action, grant, wallet, signed, extra) {
    try {
      var payload = {
        wallet_address: wallet,
        wallet_signature: signed.signature,
      };
      if (action === "reduce") {
        payload.new_total_limit = extra.new_total_limit;
      } else if (action === "revoke") {
        payload.reason = "";
      }
      await api().grantAction(action, grant.grant_id, payload);
      await render();
    } catch (e) {
      setStatus("操作失败", ": " + (e && e.message ? e.message : String(e)), true);
    }
  }

  function bindNavRefresh() {
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      while (t && t !== document) {
        if (t && t.getAttribute && t.getAttribute("data-page") === "agents") {
          render();
          return;
        }
        t = t.parentNode;
      }
    });
  }

  function init() {
    bindNavRefresh();
    var refresh = byId("grant-refresh");
    if (refresh) refresh.addEventListener("click", render);
    render();
  }

  function onReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  global.KarmaGrants = { refresh: render };
  onReady(init);
})(typeof window !== "undefined" ? window : this);
