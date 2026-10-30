/**
 * 操作台 · 接入授权交互向导（可嵌入任何 agent 交互页面）。
 *
 * 用法：当主人对 agent 说「接入 Karma」时，agent 先调
 *   POST /v1/onboarding-authorization/start  → 拿 flow_id + 第一步 prompt
 * 然后把这个 prompt 交给本组件渲染；主人每操作一步，组件回调
 *   respond(action, value) → 后端推进 → 返回下一步 prompt → 继续渲染，
 * 直到 status === "complete"。
 *
 * 本组件只做「渲染 + 收集 + 回传」，不持有私钥/助记词；wallet_sign 步骤
 * 由外部 wallet 适配器注入（见 options.walletSign）。
 *
 * 暴露全局 KarmaOnboardingFlow：
 *   KarmaOnboardingFlow.render(prompt, container, options)
 *   KarmaOnboardingFlow.mount(container, options)   // 返回 {start, respond, abort}
 */
(function (global) {
  "use strict";

  var PROMPT_CN = {
    yes_no: { title: "请确认", hint: "下面这步需要你本人确认。" },
    ack: { title: "责任确认", hint: "勾选后表示你已阅读并接受该边界。" },
    wallet_sign: { title: "钱包签名", hint: "请在钱包里签名确认。" },
    matching_code: { title: "对照码配对", hint: "把 agent 展示的 8 位码输入下方确认。" },
    info: { title: "信息确认", hint: "核对后点继续。" },
  };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  function stepHeader(prompt) {
    var head = el("div", "kof-head");
    var kicker = el("div", "kof-kicker",
      "第 " + prompt.step_index + " / " + prompt.total_steps + " 步 · " + (PROMPT_CN[prompt.prompt_type] || {}).title);
    head.appendChild(kicker);
    head.appendChild(el("h3", "kof-title", prompt.title_zh || prompt.step_id));
    if (prompt.body_zh) head.appendChild(el("p", "kof-body", prompt.body_zh));
    if (prompt.protects_zh) head.appendChild(el("p", "kof-protects", "这一步在保护：" + prompt.protects_zh));
    return head;
  }

  function footer(respond, actions, extra) {
    var bar = el("div", "kof-actions");
    (actions || []).forEach(function (a) {
      var b = el("button", "kof-btn kof-" + a, labelFor(a));
      b.addEventListener("click", function () {
        respond(a, extra ? extra() : {});
      });
      bar.appendChild(b);
    });
    return bar;
  }

  function labelFor(a) {
    return {
      confirm: "确认",
      reject: "拒绝",
      cancel: "取消",
      continue: "继续",
      sign: "钱包签名",
    }[a] || a;
  }

  /**
   * 把一步 prompt 渲染进 container。
   * @param prompt 后端返回的 prompt 对象（prompt_type/actions/payload/title_zh…）
   * @param container DOM 节点
   * @param respond (action, value) => void  回传主人动作
   * @param options {walletSign?: (payload, onSigned) => void, onAbort?: () => void}
   */
  function render(prompt, container, respond, options) {
    options = options || {};
    clear(container).classList.add("kof-step");
    var card = el("div", "kof-card");
    card.appendChild(stepHeader(prompt));

    var type = prompt.prompt_type;
    var body = el("div", "kof-control");

    if (type === "wallet_sign") {
      var msg = el("pre", "kof-sign-msg", (prompt.payload && prompt.payload.sign_message) || "");
      body.appendChild(msg);
      body.appendChild(el("p", "kof-note", (prompt.payload && prompt.payload.note_zh) || "请在钱包里对上面的内容签名。"));
      var signBtn = el("button", "kof-btn kof-sign", "连接钱包并签名");
      signBtn.addEventListener("click", function () {
        if (typeof options.walletSign === "function") {
          options.walletSign(prompt.payload || {}, function (signed) {
            respond("sign", signed);
          });
        } else {
          respond("sign", {
            address: prompt.address || "",
            signature: prompt.signature || "",
          });
        }
      });
      body.appendChild(signBtn);
      var cancelBtn = el("button", "kof-btn kof-cancel", "取消");
      cancelBtn.addEventListener("click", function () { respond("cancel", {}); });
      body.appendChild(cancelBtn);
    } else if (type === "matching_code") {
      body.appendChild(el("p", "kof-code-label", "请核对 agent 出示的对照码："));
      body.appendChild(el("div", "kof-match-code", prompt.payload && prompt.payload.match_code));
      body.appendChild(el("p", "kof-note", (prompt.payload && prompt.payload.note_zh) || ""));
      var input = el("input", "kof-code-input");
      input.placeholder = "输入 8 位对照码";
      input.maxLength = 16;
      body.appendChild(input);
      var confirm = el("button", "kof-btn kof-confirm", "确认");
      confirm.addEventListener("click", function () {
        respond("confirm", { code: input.value });
      });
      body.appendChild(confirm);
      var rejectBtn = el("button", "kof-btn kof-reject", "拒绝");
      rejectBtn.addEventListener("click", function () { respond("reject", {}); });
      body.appendChild(rejectBtn);
    } else if (type === "ack") {
      var label = el("label", "kof-ack");
      var cb = el("input", "kof-checkbox");
      cb.type = "checkbox";
      label.appendChild(cb);
      label.appendChild(el("span", null, "我已阅读并接受上面的责任边界"));
      body.appendChild(label);
      var ackConfirm = el("button", "kof-btn kof-confirm", "确认");
      ackConfirm.disabled = true;
      cb.addEventListener("change", function () { ackConfirm.disabled = !cb.checked; });
      ackConfirm.addEventListener("click", function () { respond("confirm", {}); });
      body.appendChild(ackConfirm);
      var ackRejectBtn = el("button", "kof-btn kof-reject", "拒绝");
      ackRejectBtn.addEventListener("click", function () { respond("reject", {}); });
      body.appendChild(ackRejectBtn);
    } else if (type === "info") {
      body.appendChild(el("p", "kof-note", prompt.body_zh || ""));
      var contBtn = el("button", "kof-btn kof-continue", "继续");
      contBtn.addEventListener("click", function () { respond("continue", {}); });
      body.appendChild(contBtn);
    } else {
      body.appendChild(footer(respond, prompt.actions || ["confirm", "reject"]));
    }

    card.appendChild(body);
    container.appendChild(card);
  }

  function mount(container, options) {
    var api = options.api || {}; // {base, token, start, get, respond, abort}
    var state = { flowId: null, busy: false };

    function start(identityId, profileId) {
      return api.start({ identity_id: identityId, profile_id: profileId })
        .then(function (res) {
          state.flowId = res.flow.flow_id;
          render(res.prompt, container, respond, options);
          return res;
        });
    }
    function respond(action, value) {
      if (!state.flowId) return Promise.reject(new Error("no flow"));
      return api.respond(state.flowId, action, value).then(function (res) {
        if (res.status === "complete") {
          renderComplete(container, res, options);
        } else if (res.status === "aborted") {
          renderAborted(container, res, options);
        } else {
          render(res.prompt, container, respond, options);
        }
        return res;
      });
    }
    return { start: start, respond: respond, flowId: function () { return state.flowId; } };
  }

  function renderComplete(container, res, options) {
    clear(container).classList.add("kof-step");
    var card = el("div", "kof-card kof-done");
    card.appendChild(el("h3", "kof-title", "接入授权完成"));
    card.appendChild(el("p", "kof-body", "七步授权已全部完成，agent 可以继续铸钥匙与配对。"));
    (res.next_steps || []).forEach(function (s) {
      card.appendChild(el("div", "kof-next-step", s));
    });
    container.appendChild(card);
  }

  function renderAborted(container, res, options) {
    clear(container).classList.add("kof-step");
    var card = el("div", "kof-card kof-aborted");
    card.appendChild(el("h3", "kof-title", "已取消接入"));
    card.appendChild(el("p", "kof-body", "你已终止本次接入，未产生任何资金划转。"));
    container.appendChild(card);
  }

  global.KarmaOnboardingFlow = {
    mount: mount,
    render: render,
    promptTypes: PROMPT_CN,
  };
})(typeof window !== "undefined" ? window : this);
