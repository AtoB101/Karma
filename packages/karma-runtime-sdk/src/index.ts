import { createHash, createHmac, randomUUID, timingSafeEqual } from "node:crypto";
import { fetch as undiciFetch, type RequestInit } from "undici";

export interface KarmaRuntimeOptions {
  runtimeKey: string;
  runtimeUrl?: string;
  expectedChainId?: number;
  timeoutMs?: number;
  /** Optional shared secret to verify ``X-Karma-Response-Signature`` (same as server ``app_secret_key``). */
  appSecretForHmac?: string;
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  const o = value as Record<string, unknown>;
  return `{${Object.keys(o)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${stableStringify(o[k])}`)
    .join(",")}}`;
}

function sha256Hex(value: unknown): string {
  const raw = typeof value === "string" ? value : stableStringify(value);
  return createHash("sha256").update(raw).digest("hex");
}

function verifyHmac(bodyText: string, sigHeader: string | null, secret: string | undefined): void {
  if (!secret) return;
  if (!sigHeader || !sigHeader.startsWith("sha256=")) {
    throw new Error("missing or invalid X-Karma-Response-Signature header");
  }
  const digest = sigHeader.slice("sha256=".length);
  const expected = createHmac("sha256", secret).update(bodyText, "utf8").digest("hex");
  if (digest.length !== expected.length || !timingSafeEqual(Buffer.from(digest, "utf8"), Buffer.from(expected, "utf8"))) {
    throw new Error("response HMAC verification failed");
  }
}

export class KarmaRuntime {
  private readonly runtimeKey: string;
  private readonly baseUrl: string;
  private readonly expectedChainId?: number;
  private readonly timeoutMs: number;
  private readonly appSecret?: string;
  private readonly submittedReceiptIds = new Set<string>();
  private readonly receiptSteps = new Map<string, number>();
  private cachedIdentity: string | null = null;

  constructor(opts: KarmaRuntimeOptions) {
    this.runtimeKey = opts.runtimeKey.trim();
    this.baseUrl = (opts.runtimeUrl ?? "https://runtime.karma.network").replace(/\/$/, "");
    if (this.baseUrl.startsWith("http://") && !this.baseUrl.includes("localhost") && !this.baseUrl.includes("127.0.0.1")) {
      throw new Error("runtimeUrl must use https except for localhost development");
    }
    this.expectedChainId = opts.expectedChainId;
    this.timeoutMs = opts.timeoutMs ?? 120_000;
    this.appSecret = opts.appSecretForHmac ?? process.env.KARMA_APP_SECRET;
  }

  static fromEnv(): KarmaRuntime {
    const key = process.env.KARMA_RUNTIME_KEY?.trim();
    if (!key) throw new Error("KARMA_RUNTIME_KEY is not set");
    const url = process.env.KARMA_RUNTIME_URL?.trim();
    const chain = process.env.KARMA_EXPECTED_CHAIN_ID?.trim();
    return new KarmaRuntime({
      runtimeKey: key,
      runtimeUrl: url || "https://runtime.karma.network",
      expectedChainId: chain && /^\d+$/.test(chain) ? Number(chain) : undefined,
    });
  }

  private headers(): Record<string, string> {
    return {
      "X-Karma-Runtime-Key": this.runtimeKey,
      Accept: "application/json",
      "Content-Type": "application/json",
    };
  }

  private async request(path: string, init: RequestInit = {}): Promise<unknown> {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const res = await undiciFetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: { ...this.headers(), ...(init.headers as Record<string, string> | undefined) },
        signal: ctrl.signal,
      });
      const text = await res.text();
      let data: unknown;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        throw new Error("runtime response is not valid JSON");
      }
      if (!res.ok) {
        const detail = typeof data === "object" && data && "detail" in data ? (data as { detail: unknown }).detail : data;
        throw new Error(`HTTP ${res.status}: ${String(detail)}`);
      }
      verifyHmac(text, res.headers.get("x-karma-response-signature"), this.appSecret);
      return data;
    } finally {
      clearTimeout(t);
    }
  }

  async verifyKey(): Promise<Record<string, unknown>> {
    return this.getPermissions();
  }

  async getPermissions(): Promise<Record<string, unknown>> {
    const data = (await this.request("/runtime/permissions")) as Record<string, unknown>;
    if (this.expectedChainId != null && Number(data.chain_id) !== this.expectedChainId) {
      throw new Error("chain_id mismatch between SDK expectation and runtime permissions");
    }
    return data;
  }

  private async identity(): Promise<string> {
    if (this.cachedIdentity) return this.cachedIdentity;
    const p = await this.getPermissions();
    this.cachedIdentity = String(p.karma_identity_id ?? "");
    return this.cachedIdentity;
  }

  async getCapacity(): Promise<unknown> {
    return this.request("/runtime/capacity");
  }

  async requestVoucher(voucher: Record<string, unknown>, clientNonce: string): Promise<unknown> {
    return this.request("/runtime/request-voucher", {
      method: "POST",
      body: JSON.stringify({ client_nonce: clientNonce, voucher }),
    });
  }

  async submitReceipt(receipt: Record<string, unknown>): Promise<unknown> {
    const rid = String(receipt.receipt_id ?? "");
    if (rid && this.submittedReceiptIds.has(rid)) {
      throw new Error(`duplicate receipt submission blocked locally: ${rid}`);
    }
    const out = await this.request("/runtime/submit-receipt", { method: "POST", body: JSON.stringify(receipt) });
    if (rid) this.submittedReceiptIds.add(rid);
    return out;
  }

  async updateProgress(progress: Record<string, unknown>): Promise<unknown> {
    return this.request("/runtime/update-progress", { method: "POST", body: JSON.stringify(progress) });
  }

  async requestSettlement(payload: Record<string, unknown>): Promise<unknown> {
    return this.request("/runtime/request-settlement", { method: "POST", body: JSON.stringify(payload) });
  }

  async getTaskStatus(taskId: string): Promise<unknown> {
    return this.request(`/runtime/task-status/${encodeURIComponent(taskId)}`);
  }

  revokeSession(): void {
    this.submittedReceiptIds.clear();
    this.receiptSteps.clear();
    this.cachedIdentity = null;
  }

  async wrapToolCall<T>(opts: {
    taskId: string;
    toolName: string;
    fn: (input: unknown) => T | Promise<T>;
    input: unknown;
    agentSignature?: string;
  }): Promise<T> {
    const { taskId, toolName, fn, input } = opts;
    const agentSignature = opts.agentSignature ?? "runtime-sdk";
    const inputDigest = sha256Hex(input);
    const t0 = performance.now();
    let statusCode = 200;
    let err: string | null = null;
    let result: unknown;
    try {
      const maybe = fn(input);
      result = maybe instanceof Promise ? await maybe : maybe;
    } catch (e) {
      statusCode = 500;
      err = String(e);
      result = null;
    }
    const durationMs = Math.round(performance.now() - t0);
    const outputDigest = sha256Hex(statusCode < 400 ? result : { error: err });
    const ended = new Date();
    const started = new Date(ended.getTime() - durationMs);
    const logEnvelope = { taskId, toolName, inputDigest, outputDigest, durationMs, statusCode };
    const runtimeLogHash = sha256Hex(logEnvelope);
    const step = (this.receiptSteps.get(taskId) ?? 0) + 1;
    const receipt = {
      receipt_id: randomUUID(),
      task_id: taskId,
      agent_id: await this.identity(),
      step_index: step,
      tool_name: toolName,
      input_hash: inputDigest,
      output_hash: outputDigest,
      started_at: started.toISOString(),
      ended_at: ended.toISOString(),
      duration_ms: durationMs,
      status: statusCode < 400 ? "success" : "failure",
      error_message: err,
      metadata: { runtime_log_hash: runtimeLogHash, status_code: statusCode, agent_signature: agentSignature },
    };
    try {
      await this.submitReceipt(receipt);
      this.receiptSteps.set(taskId, step);
    } finally {
      try {
        await this.getTaskStatus(taskId);
      } catch {
        /* best-effort sync */
      }
    }
    if (statusCode >= 400) throw new Error(err || "tool execution failed");
    return result as T;
  }
}
