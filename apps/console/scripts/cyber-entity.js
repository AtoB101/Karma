/**
 * 主体认证（企业 / 数据 API） + 技能市场。
 *
 * 两条红线在这份脚本里体现得很直接：
 *  1. 资质原件的**明文永远不出这台设备**：文件在这里读成字节 → AES-GCM-256 加密
 *     （密钥由钱包签名在本地派生）→ 只把密文包和 sha256 摘要传上去。
 *  2. 上架声明**不由前端拼串**：先问服务端要「待签声明」，原样显示给用户看，
 *     再让钱包签它。前后端各写一遍规范化，差一个字节就会白签。
 */
(function () {
  "use strict";

  var PBKDF2_ITERATIONS = 250000;
  var MAX_PACKAGE_BYTES = 6 * 1024 * 1024;
  var ENTITY_PATH = "/v1/identity/";
  var SKILLS_PATH = "/v1/skills";

  var entity = { certs: [] };
  var prepared = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function api() {
    return window.cyberKarmaApi || {};
  }

  function identity() {
    try {
      return (
        String(window.KARMA_IDENTITY_ID || "").trim() ||
        sessionStorage.getItem("karma_console_identity") ||
        ""
      );
    } catch (_) {
      return String(window.KARMA_IDENTITY_ID || "").trim();
    }
  }

  function session() {
    try {
      return JSON.parse(sessionStorage.getItem("karma_console_session") || "{}") || {};
    } catch (_) {
      return {};
    }
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function say(node, text, ok) {
    if (!node) return;
    node.textContent = text == null ? "—" : String(text);
    node.classList.remove("ok", "err");
    if (ok === true) node.classList.add("ok");
    if (ok === false) node.classList.add("err");
  }

  function money(n) {
    var v = Number(n || 0);
    return (Math.round(v * 1e6) / 1e6).toString();
  }

  function bufToB64(buf) {
    var bytes = new Uint8Array(buf);
    var out = "";
    for (var i = 0; i < bytes.length; i += 1) out += String.fromCharCode(bytes[i]);
    return window.btoa(out);
  }

  function randomHex(len) {
    var bytes = new Uint8Array(len);
    window.crypto.getRandomValues(bytes);
    var out = "";
    for (var i = 0; i < bytes.length; i += 1) out += ("0" + bytes[i].toString(16)).slice(-2);
    return out;
  }

  function sha256Hex(input) {
    var buf = typeof input === "string" ? new window.TextEncoder().encode(input) : input;
    return window.crypto.subtle.digest("SHA-256", buf).then(function (d) {
      var bytes = new Uint8Array(d);
      var out = "";
      for (var i = 0; i < bytes.length; i += 1) out += ("0" + bytes[i].toString(16)).slice(-2);
      return out;
    });
  }

  function walletProvider() {
    var auth = window.KarmaWalletAuth;
    if (auth && typeof auth.activeProvider === "function") {
      var p = auth.activeProvider();
      if (p && typeof p.request === "function") return p;
    }
    if (window.ethereum && typeof window.ethereum.request === "function") return window.ethereum;
    return null;
  }

  async function signMessage(message) {
    var provider = walletProvider();
    var addr = session().wallet;
    if (!provider || !addr) throw new Error("请先连接钱包（顶部「连接钱包」）");
    return provider.request({ method: "personal_sign", params: [message, addr] });
  }

  async function deriveKey(signatureHex, saltHex) {
    var enc = new window.TextEncoder();
    var material = await window.crypto.subtle.importKey(
      "raw", enc.encode(signatureHex), { name: "PBKDF2" }, false, ["deriveKey"]
    );
    return window.crypto.subtle.deriveKey(
      { name: "PBKDF2", salt: enc.encode(saltHex), iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
      material,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt"]
    );
  }

  function readFileB64(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onerror = function () { reject(new Error("读取文件失败：" + file.name)); };
      reader.onload = function () {
        var bytes = new Uint8Array(reader.result);
        var out = "";
        for (var i = 0; i < bytes.length; i += 1) out += String.fromCharCode(bytes[i]);
        resolve(window.btoa(out));
      };
      reader.readAsArrayBuffer(file);
    });
  }

  // ---- 主体认证：状态 ------------------------------------------------------

  function renderEntity(state) {
    var badge = byId("ent-badge");
    var labels = {
      none: "未认证", draft: "草稿", pending: "审核中", verified: "已认证", rejected: "已驳回",
    };
    if (badge) {
      badge.textContent = labels[state && state.status] || "未认证";
      badge.classList.toggle("ok", !!state && state.status === "verified");
    }
    var out = byId("ent-out");
    if (out) out.textContent = JSON.stringify(state || {}, null, 2);
    entity.website_verified = !!(state && state.website_verified);
    if (!state) return;
    if (state.official_domain) {
      var d = byId("ent-domain");
      if (d && !d.value) d.value = state.official_domain;
    }
    if (state.website_verified) say(byId("ent-site-state"), "官网已校验", true);
    if (state.status === "rejected" && state.review_note) {
      say(byId("ent-status"), "被驳回：" + state.review_note, false);
    }
    if (state.status === "pending") say(byId("ent-status"), "已提交，等待复核", null);
    if (state.status === "verified") say(byId("ent-status"), "已认证通过 —— 现在可以上架技能", true);
  }

  async function loadEntity() {
    var id = identity();
    if (!id) {
      renderEntity(null);
      say(byId("ent-status"), "先连接钱包", false);
      return null;
    }
    try {
      var state = await api().karmaFetch(ENTITY_PATH + encodeURIComponent(id) + "/entity-verification", {
        method: "GET", headers: api().headers(),
      });
      renderEntity(state);
      return state;
    } catch (e) {
      say(byId("ent-status"), (e && e.message) || "读取失败", false);
      return null;
    }
  }

  function entityBody() {
    return {
      subject_type: (byId("ent-subject") || {}).value || "business",
      legal_name: ((byId("ent-legal-name") || {}).value || "").trim(),
      registration_no: ((byId("ent-reg-no") || {}).value || "").trim(),
      legal_rep: ((byId("ent-legal-rep") || {}).value || "").trim(),
      official_domain: ((byId("ent-domain") || {}).value || "").trim(),
      contact_email: ((byId("ent-email") || {}).value || "").trim(),
      service_category: (byId("ent-category") || {}).value || "data_api",
      service_scope: ((byId("ent-scope") || {}).value || "").trim(),
      // 商业注册流程要落下来的三项：对外 API 入口、文档地址、办公地点。
      api_endpoint: ((byId("ent-api-endpoint") || {}).value || "").trim(),
      api_docs_url: ((byId("ent-api-docs") || {}).value || "").trim(),
      office_address: ((byId("ent-office-address") || {}).value || "").trim(),
    };
  }

  async function requestChallenge() {
    var id = identity();
    if (!id) return say(byId("ent-challenge-state"), "先连接钱包", false);
    try {
      var res = await api().jsonPost(
        ENTITY_PATH + encodeURIComponent(id) + "/entity-verification/website-challenge",
        { official_domain: entityBody().official_domain }
      );
      var ch = res.challenge || {};
      var box = byId("ent-challenge-box");
      if (box) box.hidden = false;
      var line = byId("ent-challenge-line");
      if (line) line.textContent = ch.expected_line || "";
      var url = byId("ent-challenge-url");
      if (url) url.textContent = "放到这个地址：" + (ch.url || "");
      entity.challenge = ch;
      say(byId("ent-challenge-state"), "已生成，请放到官网后点「回读校验」", true);
      renderEntity(res);
    } catch (e) {
      say(byId("ent-challenge-state"), (e && e.message) || "生成失败", false);
    }
  }

  async function verifySite() {
    var id = identity();
    if (!id) return say(byId("ent-site-state"), "先连接钱包", false);
    say(byId("ent-site-state"), "回读中…", null);
    try {
      var res = await api().jsonPost(
        ENTITY_PATH + encodeURIComponent(id) + "/entity-verification/website-verify", {}
      );
      say(byId("ent-site-state"), res.website_verified ? "官网已校验" : "未校验", !!res.website_verified);
      renderEntity(res);
    } catch (e) {
      say(byId("ent-site-state"), (e && e.message) || "回读失败", false);
    }
  }

  // ---- 主体认证：资质清单 --------------------------------------------------

  function renderCerts() {
    var host = byId("ent-cert-list");
    if (host) {
      host.innerHTML = entity.certs.length
        ? entity.certs
            .map(function (c, i) {
              return (
                "<li><b>" + esc(c.kind) + "</b> " + esc(c.name) +
                " · 摘要 " + esc(String(c.digest).slice(0, 12)) + "…" +
                ' <button type="button" class="btn" data-cert-drop="' + i + '">移除</button></li>'
              );
            })
            .join("")
        : "<li>还没有资质 —— 企业主体至少要有营业执照。</li>";
    }
    var count = byId("ent-cert-count");
    if (count) count.textContent = entity.certs.length + " 份";
  }

  async function addCert() {
    var fileInput = byId("ent-cert-file");
    var file = fileInput && fileInput.files && fileInput.files[0];
    if (!file) return say(byId("ent-cert-state"), "先选择一个文件", false);
    if (file.size > MAX_PACKAGE_BYTES / 2) {
      return say(byId("ent-cert-state"), "文件太大，请压到 3MB 以内", false);
    }
    say(byId("ent-cert-state"), "读取并计算摘要…", null);
    try {
      var b64 = await readFileB64(file);
      var digest = await sha256Hex(b64);
      entity.certs.push({
        kind: (byId("ent-cert-kind") || {}).value || "OTHER",
        name: ((byId("ent-cert-name") || {}).value || file.name).trim(),
        digest: digest,
        b64: b64,
        filename: file.name,
      });
      fileInput.value = "";
      renderCerts();
      say(byId("ent-cert-state"), "已加入（原件只留在本地，提交时统一加密）", true);
    } catch (e) {
      say(byId("ent-cert-state"), (e && e.message) || "读取失败", false);
    }
  }

  async function submitEntity() {
    var id = identity();
    if (!id) return say(byId("ent-status"), "先连接钱包", false);
    var consent = byId("ent-consent");
    if (!consent || !consent.checked) return say(byId("ent-status"), "请先勾选真实性确认", false);
    if (!entity.certs.length) return say(byId("ent-status"), "至少要加入一份资质（营业执照）", false);

    var body = entityBody();
    if (!body.legal_name || !body.official_domain || !body.contact_email) {
      return say(byId("ent-status"), "主体全称 / 官网域名 / 联系邮箱都要填", false);
    }

    try {
      say(byId("ent-status"), "① 等钱包签名派生密钥…", null);
      var saltHex = randomHex(16);
      var message = [
        "Karma Entity Doc Key v1",
        "karma_identity_id:" + id,
        "official_domain:" + body.official_domain,
        "salt:" + saltHex,
      ].join("\n");
      var signature = await signMessage(message);

      say(byId("ent-status"), "② 本地加密资质包…", null);
      var key = await deriveKey(signature, saltHex);
      var iv = new Uint8Array(12);
      window.crypto.getRandomValues(iv);
      var bundle = {
        kind: "karma_entity_certifications_v1",
        subject: body,
        certifications: entity.certs.map(function (c) {
          return { kind: c.kind, name: c.name, filename: c.filename, b64: c.b64 };
        }),
      };
      var plaintext = new window.TextEncoder().encode(JSON.stringify(bundle));
      var cipher = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, key, plaintext);

      var docDigest = await sha256Hex(entity.certs.map(function (c) { return c.digest; }).join("|"));
      var payload = Object.assign({}, body, {
        certifications: entity.certs.map(function (c) {
          return { kind: c.kind, name: c.name, digest: c.digest };
        }),
        doc_digest: docDigest,
        package_digest: await sha256Hex(cipher),
        package_cipher: bufToB64(cipher),
        encryption: {
          algo: "AES-GCM-256",
          kdf: "PBKDF2-SHA256",
          iterations: PBKDF2_ITERATIONS,
          salt_b64: window.btoa(saltHex),
          iv_b64: bufToB64(iv),
          key_wrap: "wallet-signature-v1",
        },
        extracted: {
          consent: true,
          legal_name: body.legal_name,
          official_domain: body.official_domain,
          registration_no_mask:
            body.registration_no.length > 4
              ? "****" + body.registration_no.slice(-4)
              : body.registration_no,
          office_address: body.office_address,
          api_endpoint: body.api_endpoint,
          api_docs_url: body.api_docs_url,
          contact_email: body.contact_email,
        },
      });

      say(byId("ent-status"), "③ 提交审核…", null);
      var res = await api().jsonPost(
        ENTITY_PATH + encodeURIComponent(id) + "/entity-verification/submit", payload
      );
      renderEntity(res);
      await ensureEnterpriseIdentity(body.legal_name);
      say(byId("ent-status"), "已提交，等待复核（密文包 " + money(res.package_bytes / 1024) + " KB）", true);
    } catch (e) {
      say(byId("ent-status"), (e && e.message) || "提交失败", false);
    }
  }

  /** 企业主体也要在侧栏「选择身份」里占一行：认证过了却没有身份可选是说不通的。 */
  async function ensureEnterpriseIdentity(legalName) {
    var c = window.KarmaCert;
    if (!c || !c.ensureProfile) return;
    try {
      await c.ensureProfile("enterprise", legalName);
      await c.refreshIdentities();
    } catch (e) {
      // 主体认证本身已经提交成功；这里只是让侧栏跟上，失败不该反过来吓用户。
      say(byId("ent-status"), "主体已提交，但企业身份档案没建上：" + ((e && e.message) || e), false);
    }
  }

  // ---- 技能市场 ------------------------------------------------------------

  function renderCatalog(data) {
    var host = byId("mk-list");
    var skills = (data && data.skills) || [];
    if (host) {
      host.innerHTML = skills.length
        ? skills
            .map(function (s) {
              return (
                "<li><b>" + esc(s.name) + "</b> · " + esc(s.slug) +
                " — 单价 " + esc(money(s.unit_price_usdc)) + " USDC / " + esc(s.unit || "call") +
                "，累计 " + esc(money(s.settlement_threshold_usdc)) + " USDC 出账" +
                "<br /><span style='color:var(--text-dim)'>" + esc(s.summary) +
                "</span><br /><span style='color:var(--text-dim)'>endpoint: " + esc(s.endpoint_url) +
                " · 认证域名: " + esc(s.verified_domain || "-") + "</span></li>"
              );
            })
            .join("")
        : "<li>目录还是空的 —— 完成主体认证后就可以上架第一个技能。</li>";
    }
    var out = byId("mk-catalog-out");
    if (out) out.textContent = JSON.stringify(data || {}, null, 2);
  }

  async function loadCatalog() {
    var cat = (byId("mk-filter-cat") || {}).value || "";
    var q = ((byId("mk-filter-q") || {}).value || "").trim();
    var qs = new URLSearchParams();
    if (cat) qs.set("category", cat);
    if (q) qs.set("q", q);
    var suffix = qs.toString() ? "?" + qs.toString() : "";
    say(byId("mk-catalog-state"), "读取中…", null);
    try {
      var data = await api().karmaFetch(SKILLS_PATH + suffix, {
        method: "GET", headers: api().headers(),
      });
      renderCatalog(data);
      say(byId("mk-catalog-state"), "共 " + ((data && data.count) || 0) + " 个技能", true);
    } catch (e) {
      say(byId("mk-catalog-state"), (e && e.message) || "读取失败", false);
    }
  }

  function renderMine(data) {
    var host = byId("mk-mine-list");
    var badge = byId("mk-mine-badge");
    if (badge) {
      var ok = !!(data && data.can_publish);
      badge.textContent = ok ? "主体已认证 · 可上架" : "需先完成主体认证";
      badge.classList.toggle("ok", ok);
    }
    var skills = (data && data.skills) || [];
    if (host) {
      host.innerHTML = skills.length
        ? skills
            .map(function (s) {
              var act = s.status === "published"
                ? '<button type="button" class="btn" data-skill-pause="' + esc(s.slug) + '">暂停</button>'
                : '<button type="button" class="btn" data-skill-resume="' + esc(s.slug) + '">恢复</button>';
              return (
                "<li><b>" + esc(s.name) + "</b> · " + esc(s.slug) + " · 版本 v" + esc(s.version) +
                " · 状态 " + esc(s.status) +
                "<br /><span style='color:var(--text-dim)'>" + esc(money(s.unit_price_usdc)) +
                " USDC / " + esc(s.unit || "call") + "，累计 " +
                esc(money(s.settlement_threshold_usdc)) + " 出账 · 摘要 " +
                esc(String(s.manifest_digest || "").slice(0, 16)) + "…</span><br />" + act + "</li>"
              );
            })
            .join("")
        : "<li>你还没有上架任何技能。</li>";
    }
  }

  async function loadMine() {
    if (!identity()) return say(byId("mk-status"), "先连接钱包", false);
    try {
      var data = await api().karmaFetch(SKILLS_PATH + "/mine", {
        method: "GET", headers: api().headers(),
      });
      renderMine(data);
    } catch (e) {
      say(byId("mk-status"), (e && e.message) || "读取失败", false);
    }
  }

  function skillPayload() {
    var cap = ((byId("mk-cap") || {}).value || "").trim();
    return {
      slug: ((byId("mk-slug") || {}).value || "").trim().toLowerCase(),
      name: ((byId("mk-name") || {}).value || "").trim(),
      category: (byId("mk-category") || {}).value || "data_api",
      summary: ((byId("mk-summary") || {}).value || "").trim(),
      description: ((byId("mk-description") || {}).value || "").trim(),
      endpoint_url: ((byId("mk-endpoint") || {}).value || "").trim(),
      method: "POST",
      unit: (byId("mk-unit") || {}).value || "call",
      unit_price_usdc: Number((byId("mk-price") || {}).value || 0),
      settlement_threshold_usdc: Number((byId("mk-threshold") || {}).value || 0),
      default_cap_usdc: cap === "" ? null : Number(cap),
    };
  }

  async function prepareSkill() {
    if (!identity()) return say(byId("mk-status"), "先连接钱包", false);
    var box = byId("mk-sign-message");
    say(byId("mk-status"), "生成待签声明…", null);
    try {
      var res = await api().jsonPost(SKILLS_PATH + "/prepare", skillPayload());
      prepared = res;
      if (box) box.textContent = res.message;
      var btn = byId("mk-publish");
      if (btn) btn.disabled = false;
      say(
        byId("mk-status"),
        "待签声明已生成（版本 v" + res.version + "，域名 " + res.verified_domain + "）——请核对下面内容后再签名",
        true
      );
    } catch (e) {
      prepared = null;
      var pub = byId("mk-publish");
      if (pub) pub.disabled = true;
      if (box) box.textContent = "① 先生成待签声明";
      say(byId("mk-status"), (e && e.message) || "生成失败", false);
    }
  }

  async function publishSkill() {
    if (!prepared) return say(byId("mk-status"), "先点「① 生成待签声明」", false);
    try {
      say(byId("mk-status"), "① 等钱包签名…", null);
      var signature = await signMessage(prepared.message);
      say(byId("mk-status"), "② 上架中…", null);
      var payload = Object.assign({}, skillPayload(), { publisher_signature: signature });
      var res = await api().jsonPost(SKILLS_PATH, payload);
      say(byId("mk-status"), "已上架：" + res.slug + " v" + res.version, true);
      await loadMine();
      await loadCatalog();
    } catch (e) {
      say(byId("mk-status"), (e && e.message) || "上架失败", false);
    }
  }

  async function skillAction(slug, action) {
    try {
      if (action === "resume") {
        // 恢复同样要本人表态：拿当前内容重新签一次。
        var mine = await api().karmaFetch(SKILLS_PATH + "/mine", {
          method: "GET", headers: api().headers(),
        });
        var row = ((mine && mine.skills) || []).filter(function (s) { return s.slug === slug; })[0];
        if (!row) throw new Error("找不到这个技能");
        var prep = await api().jsonPost(SKILLS_PATH + "/prepare", {
          slug: row.slug, name: row.name, category: row.category, summary: row.summary,
          description: row.description, endpoint_url: row.endpoint_url, method: row.method,
          unit: row.unit, unit_price_usdc: row.unit_price_usdc,
          settlement_threshold_usdc: row.settlement_threshold_usdc,
          default_cap_usdc: row.default_cap_usdc,
        });
        var sig = await signMessage(prep.message);
        await api().jsonPost(SKILLS_PATH + "/" + encodeURIComponent(slug) + "/resume", {
          publisher_signature: sig,
        });
      } else {
        await api().jsonPost(SKILLS_PATH + "/" + encodeURIComponent(slug) + "/pause", {});
      }
      say(byId("mk-status"), slug + (action === "resume" ? " 已恢复" : " 已暂停"), true);
      await loadMine();
      await loadCatalog();
    } catch (e) {
      say(byId("mk-status"), (e && e.message) || "操作失败", false);
    }
  }

  async function loadUsage() {
    var slug = ((byId("mk-use-slug") || {}).value || "").trim();
    if (!slug) return say(byId("mk-usage-state"), "先填技能 slug", false);
    var payer = ((byId("mk-use-payer") || {}).value || "").trim();
    var qs = new URLSearchParams();
    if (payer) qs.set("payer_identity_id", payer);
    say(byId("mk-usage-state"), "读取中…", null);
    try {
      var data = await api().karmaFetch(
        SKILLS_PATH + "/" + encodeURIComponent(slug) + "/usage" + (qs.toString() ? "?" + qs.toString() : ""),
        { method: "GET", headers: api().headers() }
      );
      var out = byId("mk-usage-out");
      if (out) out.textContent = JSON.stringify(data, null, 2);
      var host = byId("mk-usage-body");
      if (host) {
        var m = data.meter;
        var rows = [];
        if (m) {
          rows.push(
            "<li><b>计费器</b>：调用 " + m.calls + " 次 · 待出账 " + money(m.accrued_usdc) +
            " · 已出账 " + money(m.billed_usdc) + " · 已结算 " + money(m.settled_usdc) +
            " USDC（阈值 " + money(m.threshold_usdc) + "，上限 " +
            (m.cap_usdc == null ? "不限" : money(m.cap_usdc)) + "）</li>"
          );
        } else {
          rows.push("<li>还没有调用记录。</li>");
        }
        ((data.settlements || [])).slice(0, 10).forEach(function (s) {
          rows.push(
            "<li><b>结算单</b> " + esc(s.settlement_id) + " · " + money(s.amount_usdc) +
            " USDC（质押 " + money(s.stake_usdc) + "）· 状态 " + esc(s.status) +
            (s.tx_hash ? " · tx " + esc(String(s.tx_hash).slice(0, 18)) + "…" : "") +
            (s.failure_reason ? "<br /><span style='color:var(--text-dim)'>" + esc(s.failure_reason) + "</span>" : "") +
            "</li>"
          );
        });
        var meters = data.meters || [];
        meters.slice(0, 10).forEach(function (mm) {
          rows.push(
            "<li><b>付款方</b> " + esc(mm.payer_identity_id) + "：调用 " + mm.calls +
            " 次 · 待出账 " + money(mm.accrued_usdc) + " · 已出账 " + money(mm.billed_usdc) +
            " · 已结算 " + money(mm.settled_usdc) + " USDC</li>"
          );
        });
        host.innerHTML = rows.join("");
      }
      say(byId("mk-usage-state"), "已读取", true);
    } catch (e) {
      say(byId("mk-usage-state"), (e && e.message) || "读取失败", false);
    }
  }

  // ---- 绑定 ----------------------------------------------------------------

  function bind() {
    var ch = byId("ent-challenge");
    if (ch) ch.addEventListener("click", requestChallenge);
    var vs = byId("ent-verify-site");
    if (vs) vs.addEventListener("click", verifySite);
    var ca = byId("ent-cert-add");
    if (ca) ca.addEventListener("click", addCert);
    var cc = byId("ent-cert-clear");
    if (cc) {
      cc.addEventListener("click", function () {
        entity.certs = [];
        renderCerts();
      });
    }
    var list = byId("ent-cert-list");
    if (list) {
      list.addEventListener("click", function (ev) {
        var attr = ev.target && ev.target.getAttribute && ev.target.getAttribute("data-cert-drop");
        if (attr == null) return;
        entity.certs.splice(Number(attr), 1);
        renderCerts();
      });
    }
    var sub = byId("ent-submit");
    if (sub) sub.addEventListener("click", submitEntity);
    var pc = byId("ent-precheck");
    if (pc) {
      pc.addEventListener("click", function () {
        var b = entityBody();
        var run = (window.KarmaCert || {}).runPrecheck;
        if (!run) return say(byId("ent-status"), "自检组件没加载", false);
        run(
          "entity",
          {
            legal_name: b.legal_name,
            registration_no: b.registration_no,
            official_domain: b.official_domain,
            contact_email: b.contact_email,
            service_scope: b.service_scope,
          },
          !!entity.website_verified,
          byId("ent-precheck-list"),
          byId("ent-status")
        );
      });
    }

    var rc = byId("mk-refresh");
    if (rc) rc.addEventListener("click", loadCatalog);
    var prep = byId("mk-prepare");
    if (prep) prep.addEventListener("click", prepareSkill);
    var pub = byId("mk-publish");
    if (pub) pub.addEventListener("click", publishSkill);
    var lm = byId("mk-load-mine");
    if (lm) lm.addEventListener("click", loadMine);
    var ur = byId("mk-usage-refresh");
    if (ur) ur.addEventListener("click", loadUsage);
    var mineList = byId("mk-mine-list");
    if (mineList) {
      mineList.addEventListener("click", function (ev) {
        var t = ev.target;
        if (!t || !t.getAttribute) return;
        var pause = t.getAttribute("data-skill-pause");
        var resume = t.getAttribute("data-skill-resume");
        if (pause) skillAction(pause, "pause");
        if (resume) skillAction(resume, "resume");
      });
    }

    document.addEventListener("karma-wallet-connected", function () {
      loadEntity();
      loadMine();
      loadCatalog();
    });
    document.addEventListener("karma-session-restored", function () {
      loadEntity();
      loadMine();
      loadCatalog();
    });
    document.addEventListener("karma-page-shown", function (ev) {
      var detail = (ev && ev.detail) || {};
      if (detail.page === "identity" && detail.sub === "enterprise") loadEntity();
      if (detail.page === "market") {
        if (detail.sub === "mine") loadMine();
        else if (detail.sub === "usage") { /* 等用户填 slug */ }
        else loadCatalog();
      }
    });

    renderCerts();
    loadEntity();
    loadMine();
    loadCatalog();
  }

  window.KarmaEntityConsole = {
    refresh: function () { loadEntity(); loadMine(); loadCatalog(); },
    loadUsage: loadUsage,
    state: entity,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();