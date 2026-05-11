/**
 * Read-only Karma BFF status. Requires window.KARMA_BFF_PUBLIC_BASE (e.g. http://127.0.0.1:8820).
 */
export async function fetchKarmaBffPublicStatus(traceId) {
  const base = String(window.KARMA_BFF_PUBLIC_BASE || "")
    .trim()
    .replace(/\/$/, "");
  if (!base) {
    return { ok: false, error: "KARMA_BFF_PUBLIC_BASE 未配置" };
  }
  const url = `${base}/public/status/${encodeURIComponent(traceId)}`;
  const res = await fetch(url, { credentials: "omit", mode: "cors" });
  const text = await res.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    body = { raw: text };
  }
  return { ok: res.ok, status: res.status, body };
}
