const { test, expect } = require("@playwright/test");

test.describe("Karma Guard portal + studio", () => {
  test("portal loads and links to sign-in and studio", async ({ page }) => {
    await page.goto("/apps/agent-service-guard/frontend/index.html");
    await expect(page.locator(".logo")).toContainText("KARMA//PAY");
    await expect(page.getByRole("link", { name: /Sign in/i })).toHaveAttribute("href", /web3-login\.html/);
    await expect(page.getByRole("link", { name: /Open user studio/i })).toHaveAttribute("href", /web3-login\.html/);
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
});
