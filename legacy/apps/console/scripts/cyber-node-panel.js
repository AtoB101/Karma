/**
 * 节点面板 UI：顶栏那颗「节点」胶囊 + 设置页的「接入节点」卡片。
 *
 * 逻辑全在 karma-nodes.js，这里只负责画出来、把点击接上。
 * 文案一律写成页面里的中文原文，由 i18n-cyber.js 的短语表整句翻译；
 * 动态值（节点名 / 延迟）单独放进 <code>，避免出现半句中文半句外文。
 */
(function (global) {
  "use strict";

  var N = global.KarmaNodes;
  if (!N || typeof document === "undefined") return;

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  /**
   * 提示语里的「值」也放在 <code> 里（等宽，一眼认出是地址 / 节点名），
   * 但要让它能被翻译：<code> 默认在翻译器的跳过名单里（里面常是 JSON、签名原文），
   * 而「当前站点（同源）」这种内置节点名本身就是给人看的文案 ——
   * 不打这个标记的话，整页都换成英文了，容灾提示里还留着一截中文。
   */
  function codeValue(text) {
    var el = h("code", null, text);
    el.setAttribute("data-i18n-phrase", "");
    return el;
  }

  function dot(health) {
    var d = h("span", "node-dot");
    d.classList.add(!health || !health.tested ? "unknown" : health.ok ? "ok" : "down");
    return d;
  }

  function msText(health) {
    return health && health.tested ? health.ms + " ms" : "";
  }

  function stateWord(selected, health) {
    if (selected) return "当前";
    if (!health || !health.tested) return "未测速";
    return health.ok ? "可用" : "不可用";
  }

  function setStatus(root, text, value) {
    var scope = root && root.nodeType === 1 ? root : document;
    var box = scope.querySelector("[data-node-status]");
    if (!box) return;
    box.textContent = "";
    if (!text) return;
    box.appendChild(document.createTextNode(text));
    if (value) {
      box.appendChild(document.createTextNode(" "));
      box.appendChild(codeValue(value));
    }
  }

  /** 切完节点后，顶栏那颗胶囊得跟着变；连不上时变成红色。 */
  function renderChip() {
    var chip = $("#node-chip");
    if (!chip) return;
    var cur = N.current();
    var health = N.healthOf(cur.id);
    var name = chip.querySelector("[data-node-name]");
    var ms = chip.querySelector("[data-node-ms]");
    var d = chip.querySelector(".node-dot");
    if (name) name.textContent = cur.label || "—";
    if (ms) ms.textContent = msText(health);
    if (d) {
      d.classList.remove("ok", "down", "unknown");
      d.classList.add(!health || !health.tested ? "unknown" : health.ok ? "ok" : "down");
    }
    chip.classList.toggle("is-down", !!(health && health.tested && !health.ok));
    chip.setAttribute("title", cur.endpoint || "");
  }

  function rowButton(r, withRemove) {
    var row = h("div", "node-row");
    row.setAttribute("data-node-row", r.id);
    if (r.selected) row.classList.add("is-current");
    row.appendChild(dot(r.health));
    var label = h("span", "node-row-label", r.label);
    row.appendChild(label);
    // 自定义节点常常是「给人看的名字」，真正连的是哪个地址要能直接看到。
    if (r.custom && r.label !== r.endpoint) {
      row.appendChild(h("code", "node-row-url", r.endpoint));
    }
    if (r.custom) row.appendChild(h("span", "node-row-kind", "自定义"));
    var ms = h("span", "node-row-ms", msText(r.health));
    row.appendChild(ms);
    row.appendChild(h("span", "node-row-state", stateWord(r.selected, r.health)));
    var pick = h("button", "btn small", r.selected ? "当前节点" : "切换到它");
    pick.type = "button";
    pick.setAttribute("data-node-action", "select");
    pick.setAttribute("data-node-id", r.id);
    if (r.selected) pick.disabled = true;
    row.appendChild(pick);
    if (withRemove && r.custom) {
      var rm = h("button", "btn small ghost", "移除");
      rm.type = "button";
      rm.setAttribute("data-node-action", "remove");
      rm.setAttribute("data-node-id", r.id);
      row.appendChild(rm);
    }
    return row;
  }

  function renderMenu() {
    var menu = $("#node-menu");
    if (!menu) return;
    var wasOpen = !menu.hidden;
    menu.textContent = "";
    var head = h("div", "node-menu-head");
    head.appendChild(h("b", null, "接入节点（去中心化）"));
    head.appendChild(
      h(
        "p",
        null,
        "操作台只是界面，账本与资金都在链上。这里决定它跟哪台节点要数据 —— 能上链读的一律链上读，节点只做索引与转发。"
      )
    );
    menu.appendChild(head);

    var list = h("div", "node-menu-list");
    N.list().forEach(function (r) {
      list.appendChild(rowButton(r, false));
    });
    menu.appendChild(list);

    var foot = h("div", "node-menu-foot");
    var probe = h("button", "btn", "测速");
    probe.type = "button";
    probe.setAttribute("data-node-action", "probe");
    var manage = h("button", "btn ghost", "管理节点");
    manage.type = "button";
    manage.setAttribute("data-node-action", "manage");
    foot.appendChild(probe);
    foot.appendChild(manage);
    menu.appendChild(foot);

    var status = h("div", "node-status");
    status.setAttribute("data-node-status", "");
    menu.appendChild(status);
    menu.hidden = wasOpen ? false : menu.hidden;
  }

  function renderSettings() {
    var box = $("[data-karma-nodes-settings]");
    if (!box) return;
    box.textContent = "";

    var head = h("div", "section-header");
    var left = h("div");
    left.appendChild(h("h3", null, "接入节点（去中心化）"));
    left.appendChild(
      h(
        "p",
        null,
        "操作台只是界面，账本与资金都在链上。这里决定它跟哪台节点要数据 —— 能上链读的一律链上读，节点只做索引与转发。"
      )
    );
    head.appendChild(left);
    box.appendChild(head);

    var auto = h("label", "node-auto");
    var cb = h("input");
    cb.type = "checkbox";
    cb.setAttribute("data-node-autofail", "");
    cb.checked = N.autofailOn();
    auto.appendChild(cb);
    auto.appendChild(h("span", null, "连不上时自动换节点"));
    box.appendChild(auto);
    box.appendChild(
      h("p", "node-auto-hint", "开启后，当前节点探活失败会自动切到下一个可用节点，并记住选择。")
    );

    var list = h("div", "node-settings-list");
    N.list().forEach(function (r) {
      list.appendChild(rowButton(r, true));
    });
    box.appendChild(list);

    var add = h("div", "node-add");
    var nameIn = h("input");
    nameIn.type = "text";
    nameIn.setAttribute("data-node-add-label", "");
    nameIn.setAttribute("placeholder", "名称（可选）");
    var baseIn = h("input");
    baseIn.type = "text";
    baseIn.setAttribute("data-node-add-base", "");
    baseIn.setAttribute("placeholder", "节点地址（http:// 或 https://）");
    var addBtn = h("button", "btn", "添加");
    addBtn.type = "button";
    addBtn.setAttribute("data-node-action", "add");
    add.appendChild(h("b", null, "添加自定义节点"));
    add.appendChild(nameIn);
    add.appendChild(baseIn);
    add.appendChild(addBtn);
    box.appendChild(add);

    var copy = h("div", "node-copy");
    copy.appendChild(h("p", null, "把接入地址交给你的 agent："));
    copy.appendChild(h("code", "node-endpoint", N.effectiveBase()));
    var copyBtn = h("button", "btn", "复制接入地址");
    copyBtn.type = "button";
    copyBtn.setAttribute("data-node-action", "copy");
    copy.appendChild(copyBtn);
    box.appendChild(copy);

    var status = h("div", "node-status");
    status.setAttribute("data-node-status", "");
    box.appendChild(status);
  }

  var toastTimer = null;
  function toast(text, value, sticky) {
    var el = $("#node-toast");
    if (!el) return;
    el.textContent = "";
    if (!text) {
      el.hidden = true;
      return;
    }
    el.appendChild(document.createTextNode(text));
    if (value) {
      el.appendChild(document.createTextNode(" "));
      el.appendChild(codeValue(value));
    }
    el.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    if (!sticky) {
      toastTimer = setTimeout(function () {
        el.hidden = true;
      }, 6000);
    }
  }

  function renderAll() {
    renderChip();
    renderMenu();
    renderSettings();
  }

  function activeRoot() {
    var menu = $("#node-menu");
    if (menu && !menu.hidden) return menu;
    var box = $("[data-karma-nodes-settings]");
    if (box && box.closest(".page.active")) return box;
    return menu || box || document;
  }

  function statusRoot() {
    return activeRoot();
  }

  function doProbe() {
    var root = statusRoot();
    setStatus(root, "正在测速…");
    return N.probeAll().then(function (rows) {
      var okCount = rows.filter(function (r) {
        return r.ok;
      }).length;
      // 先重绘再写状态：renderAll 会把面板整块重建，反过来的话状态行会被抹掉。
      renderAll();
      setStatus(statusRoot(), okCount ? "测速完成" : "没有可用的备用节点");
      return rows;
    });
  }

  function doSelect(id) {
    var node = N.select(id);
    if (!node) return;
    renderAll();
    setStatus(statusRoot(), "已切换节点", node.label);
    try {
      document.dispatchEvent(new CustomEvent("karma-node-changed", { detail: { id: id } }));
    } catch (_) {}
  }

  function doAdd() {
    var box = $("[data-karma-nodes-settings]");
    if (!box) return;
    var nameIn = box.querySelector("[data-node-add-label]");
    var baseIn = box.querySelector("[data-node-add-base]");
    var res = N.addCustom({ label: nameIn && nameIn.value, base: baseIn && baseIn.value });
    if (!res.ok) {
      setStatus(box, res.error);
      return;
    }
    if (nameIn) nameIn.value = "";
    if (baseIn) baseIn.value = "";
    renderAll();
    setStatus(box, "节点已添加", res.node.label);
  }

  function doRemove(id) {
    if (!N.removeCustom(id)) return;
    renderAll();
    setStatus(statusRoot(), "已移除该节点");
  }

  function doCopy() {
    var text = N.effectiveBase();
    var done = function () {
      setStatus(statusRoot(), "接入地址已复制", text);
    };
    try {
      if (global.navigator && global.navigator.clipboard && global.navigator.clipboard.writeText) {
        global.navigator.clipboard.writeText(text).then(done, function () {
          setStatus(statusRoot(), "复制失败，请手动选中下面的地址");
        });
        return;
      }
    } catch (_) {}
    setStatus(statusRoot(), "复制失败，请手动选中下面的地址");
  }

  function openMenu(open) {
    var menu = $("#node-menu");
    var chip = $("#node-chip");
    if (!menu || !chip) return;
    menu.hidden = !open;
    chip.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      renderMenu();
      doProbe();
    }
  }

  function bind() {
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.closest) return;

      if (t.closest("#node-chip")) {
        var menu = $("#node-menu");
        openMenu(!!(menu && menu.hidden));
        return;
      }
      if (!t.closest("#node-menu") && !t.closest("[data-karma-nodes-settings]")) {
        openMenu(false);
      }

      var btn = t.closest("[data-node-action]");
      if (!btn) return;
      var action = btn.getAttribute("data-node-action");
      var id = btn.getAttribute("data-node-id") || "";
      if (action === "probe") {
        ev.preventDefault();
        doProbe();
      } else if (action === "select") {
        ev.preventDefault();
        doSelect(id);
      } else if (action === "remove") {
        ev.preventDefault();
        doRemove(id);
      } else if (action === "add") {
        ev.preventDefault();
        doAdd();
      } else if (action === "copy") {
        ev.preventDefault();
        doCopy();
      } else if (action === "manage") {
        ev.preventDefault();
        openMenu(false);
        if (typeof global.cyberSwitchPage === "function") global.cyberSwitchPage("settings");
        var box = $("[data-karma-nodes-settings]");
        if (box && box.scrollIntoView) box.scrollIntoView({ block: "start" });
      }
    });

    document.addEventListener("change", function (ev) {
      var t = ev.target;
      if (!t || !t.hasAttribute || !t.hasAttribute("data-node-autofail")) return;
      N.setAutofail(!!t.checked);
    });

    N.onChange(function (detail) {
      renderAll();
      if (detail && detail.reason === "failover") {
        toast("当前节点连不上，已自动切到", (detail.node && detail.node.label) || "");
      }
    });

    document.addEventListener("karma-page-shown", function (ev) {
      if (ev && ev.detail && ev.detail.page === "settings") renderSettings();
    });
    document.addEventListener("karma-lang-changed", function () {
      renderAll();
    });
  }

  function start() {
    N.bootstrap();
    renderAll();
    bind();
    // 首屏探一次当前节点：胶囊上的延迟点不能永远灰着。
    N.probe(N.current().id).then(function (r) {
      if (r && typeof r.ok === "boolean") {
        try {
          renderChip();
        } catch (_) {}
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  global.KarmaNodePanel = { render: renderAll, probe: doProbe, open: openMenu };
})(typeof window !== "undefined" ? window : globalThis);
