const { test, expect } = require("@playwright/test");

test.describe("Karma Guard portal + studio", () => {
  test("portal loads and links to sign-in and studio", async ({ page }) => {
    await page.goto("/apps/agent-service-guard/frontend/index.html");
    await expect(page.locator(".brand h1")).toContainText("Karma");
    const consoleLinks = page.locator('a[href*="web3-login"][href*="studio"]');
    await expect(consoleLinks.first()).toBeVisible();
    await expect(consoleLinks.first()).toHaveAttribute("href", /web3-login\.html/);
    await expect(page.getByRole("link", { name: /Sign in|登录/i })).toHaveAttribute("href", /web3-login\.html/);
  });

  test("sign-in page loads", async ({ page }) => {
    await page.goto("/apps/agent-service-guard/frontend/web3-login.html");
    await expect(page.getByText("KARMA.PAY")).toBeVisible();
    await expect(page.getByRole("link", { name: "Home" })).toHaveAttribute("href", /index\.html/);
  });

  test("studio entry references sign-in when unauthenticated", async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem("karma_web3_session");
    });
    await page.goto("/apps/agent-service-guard/frontend/studio/index.html");
    await page.waitForURL(/web3-login\.html/, { timeout: 8000 });
  });

  test("studio loads when session is valid (auth coverage)", async ({ page }) => {
    const wallet = "0x1234567890123456789012345678901234567890";
    await page.addInitScript((w) => {
      sessionStorage.setItem(
        "karma_web3_session",
        JSON.stringify({
          wallet: w,
          loginMethod: "walletconnect-v2-qr",
          loginAt: new Date().toISOString(),
          chainId: "eip155:1",
          signature: "0x00",
          challenge: "KarmaPay login challenge",
          wcTopic: "test-topic",
        }),
      );
    }, wallet);
    await page.goto("/apps/agent-service-guard/frontend/studio/index.html");
    await expect(page).toHaveURL(/studio\/index\.html/);
    await expect(page.locator("#wallet-pill")).toContainText("0x1234");
  });

  test("studio rejects tampered wallet in session", async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.setItem(
        "karma_web3_session",
        JSON.stringify({
          wallet: "not-a-valid-wallet",
          loginMethod: "walletconnect-v2-qr",
          loginAt: new Date().toISOString(),
          chainId: "eip155:1",
          signature: "0x00",
          challenge: "KarmaPay login challenge",
          wcTopic: "",
        }),
      );
    });
    await page.goto("/apps/agent-service-guard/frontend/studio/index.html");
    await page.waitForURL(/web3-login\.html/, { timeout: 8000 });
  });

  test("cross-origin API base is blocked without allowlist (CORS client guard)", async ({
    page,
  }) => {
    const wallet = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd";
    await page.addInitScript((w) => {
      window.KARMAPAY_STUDIO_API_BASE = "https://disallowed-origin.example";
      sessionStorage.setItem(
        "karma_web3_session",
        JSON.stringify({
          wallet: w,
          loginMethod: "walletconnect-v2-qr",
          loginAt: new Date().toISOString(),
          chainId: "eip155:1",
          signature: "0x00",
          challenge: "KarmaPay login challenge",
          wcTopic: "",
        }),
      );
    }, wallet);
    await page.goto("/apps/agent-service-guard/frontend/studio/index.html");
    const res = await page.evaluate(async () => {
      const mod = await import("/apps/agent-service-guard/frontend/studio/api-client.js");
      return mod.getDashboardStats("0xabcdefabcdefabcdefabcdefabcdefabcdefabcd");
    });
    expect(res.ok).toBe(false);
    expect(res.status).toBe(0);
    expect(res.body && res.body.error).toBe("studio_api_cross_origin_blocked");
  });
});
