/**
 * Settings page — Runtime Key + local policy (must match server message format).
 */
const LS = "karma_console_agent_policy_v1";

function $(sel, root = document) {
  return root.querySelector(sel);
}

function loadLocal() {
  try {
    return JSON.parse(localStorage.getItem(LS) || "{}");
  } catch {
    return {};
  }
}

function saveLocal(obj) {
  localStorage.setItem(LS, JSON.stringify(obj));
}

function buildCreateMessage(fields) {
  const perms = [...fields.permissions].sort().join(",");
  return [
    "Karma Runtime Key Create",
    `karma_identity_id:${fields.karma_identity_id}`,
    `wallet_address:${fields.wallet_address}`,
    `permissions:${perms}`,
    `single_limit:${fields.single_limit}`,
    `daily_limit:${fields.daily_limit}`,
    `expire_time:${fields.expire_time}`,
    `agent_name:${fields.agent_name}`,
    `agent_binding:${fields.agent_binding || ""}`,
  ].join("\n");
}

function buildListMessage(fields) {
  return [
    "Karma Runtime Key List",
    `karma_identity_id:${fields.karma_identity_id}`,
    `wallet_address:${fields.wallet_address}`,
    `client_nonce:${fields.client_nonce}`,
  ].join("\n");
}

function collectPermissions() {
  const boxes = Array.from(document.querySelectorAll("[data-perm]"));
  return boxes.filter((b) => b.checked).map((b) => b.name);
}

function wire() {
  const api = window.karmaRuntimeApi;
  if (!api) return;

  const baseInput = $("[data-api-base]");
  baseInput.value = window.KARMA_API_BASE || baseInput.placeholder;

  $("[data-save-local]").addEventListener("click", () => {
    const policy = {
      auto_enabled: $("[data-k=auto_enabled]").checked,
      single_limit: Number($("[data-k=single_limit]").value || 0),
      daily_limit: Number($("[data-k=daily_limit]").value || 0),
      perm_voucher: $("[data-k=perm_voucher]").checked,
      perm_receipt: $("[data-k=perm_receipt]").checked,
      perm_progress: $("[data-k=perm_progress]").checked,
      perm_sync: $("[data-k=perm_sync]").checked,
      perm_settle: $("[data-k=perm_settle]").checked,
      high_risk: $("[data-k=high_risk]").value,
    };
    saveLocal(policy);
    alert("已保存到本浏览器 localStorage");
  });

  const saved = loadLocal();
  if (saved && Object.keys(saved).length) {
    if ("auto_enabled" in saved) $("[data-k=auto_enabled]").checked = !!saved.auto_enabled;
    if (saved.single_limit != null) $("[data-k=single_limit]").value = String(saved.single_limit);
    if (saved.daily_limit != null) $("[data-k=daily_limit]").value = String(saved.daily_limit);
    if ("perm_voucher" in saved) $("[data-k=perm_voucher]").checked = !!saved.perm_voucher;
    if ("perm_receipt" in saved) $("[data-k=perm_receipt]").checked = !!saved.perm_receipt;
    if ("perm_progress" in saved) $("[data-k=perm_progress]").checked = !!saved.perm_progress;
    if ("perm_sync" in saved) $("[data-k=perm_sync]").checked = !!saved.perm_sync;
    if ("perm_settle" in saved) $("[data-k=perm_settle]").checked = !!saved.perm_settle;
    if (saved.high_risk) $("[data-k=high_risk]").value = saved.high_risk;
  }

  $("[data-build-msg]").addEventListener("click", () => {
    window.KARMA_API_BASE = baseInput.value.trim();
    const expireLocal = $("[data-expire]").value;
    const expireIso = expireLocal ? new Date(expireLocal).toISOString() : "";
    const fields = {
      karma_identity_id: $("[data-identity]").value.trim(),
      wallet_address: $("[data-wallet]").value.trim(),
      permissions: collectPermissions(),
      single_limit: Number($("[data-k=single_limit]").value || 0),
      daily_limit: Number($("[data-k=daily_limit]").value || 0),
      expire_time: expireIso,
      agent_name: $("[data-agent-name]").value.trim() || "console-agent",
      agent_binding: "",
    };
    $("[data-sign-message]").value = buildCreateMessage(fields);
  });

  $("[data-sign-mm]").addEventListener("click", async () => {
    const eth = window.ethereum;
    if (!eth) {
      alert("未检测到 MetaMask / window.ethereum");
      return;
    }
    const msg = $("[data-sign-message]").value;
    if (!msg) {
      alert("请先生成待签名消息");
      return;
    }
    const accounts = await eth.request({ method: "eth_requestAccounts" });
    const from = accounts[0];
    const sig = await eth.request({ method: "personal_sign", params: [msg, from] });
    $("[data-signature]").value = sig;
  });

  let lastRuntimeKey = "";

  $("[data-create-key]").addEventListener("click", async () => {
    window.KARMA_API_BASE = baseInput.value.trim();
    const expireLocal = $("[data-expire]").value;
    const expireIso = expireLocal ? new Date(expireLocal).toISOString() : "";
    const payload = {
      wallet_address: $("[data-wallet]").value.trim(),
      karma_identity_id: $("[data-identity]").value.trim(),
      wallet_signature: ($("[data-signature]").value || "").trim(),
      permissions: collectPermissions(),
      single_limit: Number($("[data-k=single_limit]").value || 0),
      daily_limit: Number($("[data-k=daily_limit]").value || 0),
      expire_time: expireIso,
      agent_name: $("[data-agent-name]").value.trim() || "console-agent",
    };
    const data = await api.runtimeCreateKey(payload);
    lastRuntimeKey = data.runtime_key;
    $("[data-key-out]").textContent = JSON.stringify(data, null, 2);
    $("[data-copy-key]").disabled = !lastRuntimeKey;
    $("[data-revoke-key]").disabled = !data.key_id;
    $("[data-revoke-key]").dataset.keyId = data.key_id;
    const env = `KARMA_RUNTIME_URL=${window.KARMA_API_BASE}\nKARMA_RUNTIME_KEY=${data.runtime_key}\nKARMA_ID=${payload.karma_identity_id}`;
    $("[data-env-sample]").textContent = env;
  });

  $("[data-copy-key]").addEventListener("click", async () => {
    if (!lastRuntimeKey) return;
    await navigator.clipboard.writeText(lastRuntimeKey);
    alert("已复制 Runtime Key");
  });

  $("[data-revoke-key]").addEventListener("click", async () => {
    const keyId = $("[data-revoke-key]").dataset.keyId;
    if (!keyId) return;
    const msg = [
      "Karma Runtime Key Revoke",
      `key_id:${keyId}`,
      `karma_identity_id:${$("[data-identity]").value.trim()}`,
      `wallet_address:${$("[data-wallet]").value.trim()}`,
    ].join("\n");
    if (!window.ethereum) {
      alert("请使用钱包签名以下吊销消息并粘贴签名到 wallet_signature 字段（可扩展 UI）:\n\n" + msg);
      return;
    }
    const eth = window.ethereum;
    const accounts = await eth.request({ method: "eth_requestAccounts" });
    const sig = await eth.request({ method: "personal_sign", params: [msg, accounts[0]] });
    window.KARMA_API_BASE = baseInput.value.trim();
    await api.runtimeRevokeKey({
      key_id: keyId,
      wallet_address: $("[data-wallet]").value.trim(),
      karma_identity_id: $("[data-identity]").value.trim(),
      wallet_signature: sig,
    });
    alert("已吊销");
    lastRuntimeKey = "";
    $("[data-copy-key]").disabled = true;
    $("[data-revoke-key]").disabled = true;
  });

  $("[data-build-list-msg]").addEventListener("click", () => {
    const nonce = ($("[data-list-nonce]").value || "").trim() || `n-${Date.now()}`;
    $("[data-list-nonce]").value = nonce;
    const msg = buildListMessage({
      karma_identity_id: $("[data-identity]").value.trim(),
      wallet_address: $("[data-wallet]").value.trim(),
      client_nonce: nonce,
    });
    $("[data-list-sign-message]").value = msg;
  });

  $("[data-list-keys]").addEventListener("click", async () => {
    window.KARMA_API_BASE = baseInput.value.trim();
    const msg = $("[data-list-sign-message]").value;
    if (!msg || !window.ethereum) {
      alert("请生成 list 消息并使用 MetaMask 签名（可改进为内联签名）");
      return;
    }
    const eth = window.ethereum;
    const accounts = await eth.request({ method: "eth_requestAccounts" });
    const sig = await eth.request({ method: "personal_sign", params: [msg, accounts[0]] });
    const nonce = ($("[data-list-nonce]").value || "").trim();
    const data = await api.runtimeListKeys({
      wallet_address: $("[data-wallet]").value.trim(),
      karma_identity_id: $("[data-identity]").value.trim(),
      wallet_signature: sig,
      client_nonce: nonce,
    });
    $("[data-list-out]").textContent = JSON.stringify(data, null, 2);
  });
}

wire();
