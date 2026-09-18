/**
 * 操作台 · 行业硬指标（service_specs）表单 —— 接入向导与配对接入共用。
 *
 * 「接入一个 Agent」（高级）和「配对码接入」要主人确认的是同一份东西：这个行业在
 * Karma 里的接入边界 —— 价格、时区、营业时间、可售档位、成功率下限……服务端叫它
 * required_service_spec，页面上写「行业硬指标」。
 *
 * 两处必须完全一致，否则就会出现「向导里填得了、配对里填不了」的洞：agent 自报的
 * 硬指标不合规时，主人只看到一句 400，页面上连哪一项错了都看不到。所以渲染 / 回填 /
 * 收集都收在这一个模块里，两边都调它：
 *
 *   KarmaServiceSpec.renderForm(host, industry)   渲染（industry 来自 /v1/standards/onboarding/industries/{id}）
 *   KarmaServiceSpec.applyValues(host, specs)     把已有的申报回填进表单
 *   KarmaServiceSpec.fillFromExample(host)        按 example_service_spec 填充
 *   KarmaServiceSpec.collect(host)                -> { spec, problems }；problems 为空才该提交
 *
 * 校验口径对齐 services/agent_onboarding_template.py::_validate_service_specs：
 *   - 价格类字段必须是十进制字符串，给 number 会被 400 拒掉；
 *   - business_hours 必须有 timezone，并且 24_7 或 weekly 至少有一个。
 *
 * 文案一律写中文原文 —— i18n-cyber.js 按「中文原文 -> 译文」查表，动态插入的 DOM 由
 * MutationObserver 补翻，所以这里不要自己拼译文。
 */
(function (global) {
  "use strict";

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /** Mirrors api/routes/agents.py + agent_onboarding_template._validate_service_specs. */
  function isPricePath(path) {
    var p = String(path || "");
    return (
      p.slice(-8) === "currency" ||
      p.indexOf("price") !== -1 ||
      p.slice(-4) === "fare" ||
      p.slice(-4) === "_fee" ||
      p.slice(-6) === "per_km" ||
      p.slice(-10) === "per_minute" ||
      p.slice(-10) === "unit_price" ||
      p.slice(-13) === "rate_or_fixed" ||
      p.slice(-9) === "base_fare" ||
      p.slice(-6) === "amount" ||
      p.indexOf("nightly_rate") !== -1
    );
  }

  /** 按点路径取值；沿路任何一层不是对象就返回 null。 */
  function dig(obj, path) {
    var cur = obj;
    var parts = String(path).split(".");
    for (var i = 0; i < parts.length; i++) {
      if (cur == null || typeof cur !== "object") return null;
      cur = cur[parts[i]];
    }
    return cur === undefined ? null : cur;
  }

  function assign(target, path, value) {
    var parts = String(path).split(".");
    var cur = target;
    for (var i = 0; i < parts.length - 1; i++) {
      if (typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = value;
  }

  /**
   * 找字段一律走 data 属性而不是 id：同一页上「接入向导」和「配对码接入」会同时渲染
   * 同一批字段，id 会撞车（浏览器只认第一个），按 host 作用域查 data 属性就没这问题。
   */
  function byAttr(root, attr, value) {
    if (!root) return null;
    var nodes = root.querySelectorAll("[" + attr + "]");
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].getAttribute(attr) === value) return nodes[i];
    }
    return null;
  }

  function fieldNode(root, path) {
    return byAttr(root, "data-spec-path", String(path || ""));
  }

  function isObjectType(req) {
    return (req.type || "string") === "object" || req.path === "business_hours";
  }

  /**
   * 行业目录只给 title_zh / title_en。中文界面用中文标题；其它语言先查语言包里的
   * 行业名，查不到再回落到英文标题 —— 否则英文页会掉出一串中文行业名。
   */
  function industryTitle(row, fallback) {
    var lang = "";
    try {
      lang = (global.CYBER_I18N && global.CYBER_I18N.getLang()) || "";
    } catch (_) {}
    var zh = (row && row.title_zh) || "";
    if (lang && lang !== "zh-CN") {
      var t = "";
      try {
        if (zh && global.CYBER_I18N) t = global.CYBER_I18N.T(zh);
      } catch (_) {}
      if (t && t !== zh) return t;
      return (row && row.title_en) || zh || fallback;
    }
    return zh || (row && row.title_en) || fallback;
  }

  /** 一行硬指标 -> 一个控件。价格类字段后端只收十进制字符串，所以只能是文本框。 */
  function renderField(req) {
    var path = req.path;
    var type = req.type || "string";
    var label = req.description_zh || req.description_en || path;
    var hint = req.description_zh && req.description_zh !== path ? path : "";
    var common = ' data-spec-path="' + esc(path) + '"';

    if (isObjectType(req)) {
      return (
        '<div class="field ag-spec-field" data-spec-object="' + esc(path) + '">' +
        "<label>" + esc(label) + " <code>" + esc(path) + "</code></label>" +
        '<div class="ag-inline">' +
        '<input type="text" data-spec-part="timezone" placeholder="时区，如 Asia/Shanghai" />' +
        '<label class="ag-check"><input type="checkbox" data-spec-part="24_7" checked /> 7×24</label>' +
        "</div>" +
        '<input type="text" data-spec-part="weekly" placeholder="非 7×24 时填营业时间，如 Mon-Sun 09:00-22:00" />' +
        "</div>"
      );
    }
    if (type === "array") {
      return (
        '<div class="field ag-spec-field">' +
        "<label>" + esc(label) + " <code>" + esc(path) + "</code></label>" +
        '<textarea rows="2" data-spec-type="array"' + common + ' placeholder="每行一项 / 或用逗号分隔"></textarea>' +
        "</div>"
      );
    }
    if (type === "boolean") {
      return (
        '<div class="field ag-spec-field">' +
        "<label>" + esc(label) + " <code>" + esc(path) + "</code></label>" +
        '<select data-spec-type="boolean"' + common + '><option value="true">是</option><option value="false">否</option></select>' +
        "</div>"
      );
    }
    if (type === "integer" || type === "number") {
      var step = type === "integer" ? "1" : "0.01";
      return (
        '<div class="field ag-spec-field">' +
        "<label>" + esc(label) + " <code>" + esc(path) + "</code></label>" +
        '<input type="number" step="' + step + '" data-spec-type="' + type + '"' + common + " />" +
        "</div>"
      );
    }
    var price = isPricePath(path);
    return (
      '<div class="field ag-spec-field">' +
      "<label>" + esc(label) + " <code>" + esc(path) + "</code>" +
      (price ? ' <span class="tag muted">字符串金额</span>' : "") +
      "</label>" +
      '<input type="text" data-spec-type="string"' + common +
      (price ? ' placeholder="如 3.50（必须是字符串）"' : "") + " />" +
      (hint ? '<span class="ag-hint">' + esc(hint) + "</span>" : "") +
      "</div>"
    );
  }

  /** 渲染整个行业的硬指标表单；industry 直接来自 standards API。 */
  function renderForm(host, industry) {
    if (!host) return null;
    host.__karmaSpecIndustry = industry || null;
    if (!industry) {
      host.innerHTML = "";
      return null;
    }
    var reqs = industry.required_service_spec || [];
    if (!reqs.length) {
      host.innerHTML = '<p class="muted">该行业没有额外硬指标字段。</p>';
      return industry;
    }
    host.innerHTML =
      '<div class="ag-spec-head"><b>行业硬指标</b><span>' +
      esc(industryTitle(industry)) + " · 共 " + reqs.length + " 项（全部必填）</span>" +
      '<button type="button" class="btn" data-spec-example>按示例填充</button></div>' +
      '<div class="ag-spec-grid">' + reqs.map(renderField).join("") + "</div>";
    var btn = host.querySelector("[data-spec-example]");
    if (btn) {
      btn.addEventListener("click", function () {
        fillFromExample(host);
      });
    }
    return industry;
  }

  function industryOf(host) {
    return (host && host.__karmaSpecIndustry) || null;
  }

  function setFieldValue(root, req, value) {
    var path = req.path;
    if (isObjectType(req)) {
      var box = byAttr(root, "data-spec-object", path);
      if (!box || !value || typeof value !== "object") return;
      var tz = box.querySelector('[data-spec-part="timezone"]');
      var all = box.querySelector('[data-spec-part="24_7"]');
      var wk = box.querySelector('[data-spec-part="weekly"]');
      if (tz && value.timezone) tz.value = value.timezone;
      if (all && typeof value["24_7"] === "boolean") all.checked = value["24_7"];
      if (wk && value.weekly) {
        wk.value = Array.isArray(value.weekly) ? value.weekly.join("; ") : String(value.weekly);
      }
      return;
    }
    var node = fieldNode(root, path);
    if (!node) return;
    if (req.type === "array") {
      node.value = Array.isArray(value) ? value.join("\n") : String(value == null ? "" : value);
    } else if (req.type === "boolean") {
      node.value = value === false ? "false" : "true";
    } else {
      node.value = value == null ? "" : String(value);
    }
  }

  /** 把一份已存在的申报（agent 自报的，或上次填的）回填进表单；返回填进去的项数。 */
  function applyValues(host, specs) {
    var industry = industryOf(host);
    if (!industry || !specs || typeof specs !== "object") return 0;
    var filled = 0;
    (industry.required_service_spec || []).forEach(function (req) {
      var v = dig(specs, req.path);
      if (v === null || v === undefined) return;
      setFieldValue(host, req, v);
      filled += 1;
    });
    return filled;
  }

  function exampleSpec(industry) {
    var ex = industry && (industry.example_service_spec || industry.example_specs);
    return ex && typeof ex === "object" ? ex : null;
  }

  function fillFromExample(host) {
    var industry = industryOf(host);
    var example = exampleSpec(industry);
    if (!example) return 0;
    return applyValues(host, example);
  }

  /** 把表单还原成后端要的 service_specs；problems 非空就别提交。 */
  function collect(host) {
    var industry = industryOf(host);
    var spec = {};
    var problems = [];
    if (!industry) return { spec: spec, problems: ["请先选择行业"] };
    var reqs = industry.required_service_spec || [];
    for (var i = 0; i < reqs.length; i++) {
      var req = reqs[i];
      var path = req.path;
      var type = req.type || "string";
      if (isObjectType(req)) {
        var box = byAttr(host, "data-spec-object", path);
        var hours = {};
        if (box) {
          var tzNode = box.querySelector('[data-spec-part="timezone"]');
          var allNode = box.querySelector('[data-spec-part="24_7"]');
          var wkNode = box.querySelector('[data-spec-part="weekly"]');
          var tz = tzNode ? tzNode.value.trim() : "";
          var is247 = allNode ? allNode.checked : false;
          var weeklyRaw = wkNode ? wkNode.value.trim() : "";
          if (tz) hours.timezone = tz;
          if (is247) hours["24_7"] = true;
          if (weeklyRaw) {
            hours.weekly = weeklyRaw
              .split(/[;\n]/)
              .map(function (x) { return x.trim(); })
              .filter(Boolean);
          }
        }
        if (!hours.timezone) problems.push(path + " 需要 timezone");
        if (!hours["24_7"] && !hours.weekly) problems.push(path + " 需要 7×24 或营业时间");
        if (Object.keys(hours).length) assign(spec, path, hours);
        continue;
      }
      var node = fieldNode(host, path);
      var raw = node ? String(node.value).trim() : "";
      if (!raw) {
        problems.push((req.description_zh || path) + " 必填");
        continue;
      }
      if (type === "array") {
        var items = raw
          .split(/[\n,]/)
          .map(function (x) { return x.trim(); })
          .filter(Boolean);
        if (!items.length) {
          problems.push((req.description_zh || path) + " 至少一项");
          continue;
        }
        assign(spec, path, items);
      } else if (type === "boolean") {
        assign(spec, path, raw === "true");
      } else if (type === "integer") {
        var iv = parseInt(raw, 10);
        if (Number.isNaN(iv)) {
          problems.push(path + " 必须是整数");
          continue;
        }
        assign(spec, path, iv);
      } else if (type === "number") {
        var nv = Number(raw);
        if (Number.isNaN(nv)) {
          problems.push(path + " 必须是数字");
          continue;
        }
        assign(spec, path, nv);
      } else {
        // 价格类字段必须是字符串，给数字后端直接 400。
        assign(spec, path, raw);
      }
    }
    return { spec: spec, problems: problems };
  }

  global.KarmaServiceSpec = {
    esc: esc,
    isPricePath: isPricePath,
    dig: dig,
    assign: assign,
    fieldNode: fieldNode,
    industryTitle: industryTitle,
    renderField: renderField,
    renderForm: renderForm,
    industryOf: industryOf,
    setFieldValue: setFieldValue,
    applyValues: applyValues,
    fillFromExample: fillFromExample,
    exampleSpec: exampleSpec,
    collect: collect,
  };
})(window);
