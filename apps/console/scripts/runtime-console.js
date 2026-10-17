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

function activeProfileId() {
  try {
    if (window.KarmaIdentitySwitcher && window.KarmaIdentitySwitcher.getActiveProfileId) {
      const p = window.KarmaIdentitySwitcher.getActiveProfileId();
      if (p) return p;
    }
    return sessionStorage.getItem("karma_console_active_profile") || "";
  } catch (_) {
    return "";
  }
}

let runtimeWalletState = { resolved: null };

async function resolveEthProvider() {
  if (runtimeWalletState.resolved) return runtimeWalletState.resolved;
  const auth = window.KarmaWalletAuth;
  if (auth && typeof auth.getProvider === "function") {
    runtimeWalletState.resolved = await auth.getProvider(auth.getSelectedProviderId());
    return runtimeWalletState.resolved;
  }
  if (window.ethereum && typeof window.ethereum.request === "function") {
    runtimeWalletState.resolved = { provider: window.ethereum, kind: "injected" };
    return runtimeWalletState.resolved;
  }
  throw new Error("未检测到钱包插件（注入钱包或比特派 WalletConnect）");
}

async function requestWalletAccount(resolved) {
  if (resolved.kind === "walletconnect") {
    const p = resolved.provider;
    const accounts = p.accounts && p.accounts.length ? p.accounts : await p.enable();
    if (!accounts || !accounts.length) throw new Error("No wallet account");
    return accounts[0];
  }
  const accs = await resolved.provider.request({ method: "eth_requestAccounts" });
  if (!accs || !accs.length) throw new Error("No wallet account");
  return accs[0];
}

async function walletSign(message) {
  const resolved = await resolveEthProvider();
  const address = await requestWalletAccount(resolved);
  return resolved.provider.request({ method: "personal_sign", params: [message, address] });
}

function wire() {
  const api = window.karmaRuntimeApi;
  if (!api) return;

  const baseInput = $("[data-api-base]");
  baseInput.value = window.KARMA_API_BASE || baseInput.placeholder;

  // Policy persistence handled by console-automation-policy.js (server-side).

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
    const msg = $("[data-sign-message]").value;
    if (!msg) {
      alert("请先生成待签名消息");
      return;
    }
    try {
      const sig = await walletSign(msg);
      $("[data-signature]").value = sig;
    } catch (e) {
      alert("签名失败: " + (e && e.message ? e.message : e));
    }
  });

  let lastRuntimeKey = "";

  $("[data-create-key]").addEventListener("click", async () => {
    if (window.karmaAutomationPolicy && !window.karmaAutomationPolicy.isPolicySaved()) {
      alert("请先保存服务端自动授权策略（步骤 1–2）");
      return;
    }
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
      profile_id: activeProfileId() || undefined,
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
    let sig;
    try {
      sig = await walletSign(msg);
    } catch (e) {
      alert("吊销签名失败: " + (e && e.message ? e.message : e));
      return;
    }
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
    if (!msg) {
      alert("请先生成 list 消息");
      return;
    }
    let sig;
    try {
      sig = await walletSign(msg);
    } catch (e) {
      alert("签名失败: " + (e && e.message ? e.message : e));
      return;
    }
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
