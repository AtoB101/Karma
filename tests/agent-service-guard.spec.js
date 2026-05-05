const { test, expect } = require("@playwright/test");

test.describe("Karma Guard public MVP smoke", () => {
  test("can run happy path and route checks", async ({ page }) => {
    await page.goto("/apps/agent-service-guard/frontend/index.html");
    await expect(page.getByRole("heading", { name: "Karma Guard for Agent Services" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Create Protected Service" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Pay with Protection" })).toBeVisible();
    await expect(page.getByRole("link", { name: "View Dashboard" })).toBeVisible();
    await expect(page.getByRole("link", { name: "View Trust Badge" })).toBeVisible();

    // Route-level checks required by public demo contract.
    await expect(page.locator('a[href="./service-create.html"]')).toBeVisible();
    await expect(page.locator('a[href="./pay.html"]')).toBeVisible();
    await expect(page.locator('a[href="./dashboard.html"]')).toBeVisible();
    await expect(page.locator('a[href="./badge.html"]')).toBeVisible();

    await page.getByRole("link", { name: "Create Protected Service" }).click();
    await expect(page).toHaveURL(/service-create\.html$/);

    await page.locator('input[name="service_name"]').fill("Agent SEO Audit");
    await page.locator('input[name="service_type"]').fill("agent-api");
    await page.locator('textarea[name="description"]').fill("SEO report + fix plan");
    await page.locator('input[name="price"]').fill("120");
    await page.locator('input[name="currency"]').fill("USDC");
    await page.locator('input[name="delivery_time"]').fill("24h");
    await page.locator('textarea[name="refund_policy"]').fill("Refund if no delivery.");
    await page.locator('input[name="seller_wallet"]').fill("0xSeller001");
    await page.locator('input[name="seller_bond_rate"]').fill("30");
    await page.getByRole("button", { name: "Create Service" }).click();

    await expect(page.getByRole("link", { name: "Open Payment Page" })).toBeVisible({ timeout: 15000 });
    await page.getByRole("link", { name: "Open Payment Page" }).click();
    await expect(page).toHaveURL(/pay\.html\?service_id=/);

    await page.locator('input[name="buyer_wallet"]').fill("0xBuyer001");
    await page.getByRole("button", { name: "Create Protected Order" }).click();
    await expect(page).toHaveURL(/order\.html\?order_id=/);

    await expect(page.locator("#order-card")).toContainText("payment_status");
    await expect(page.locator("#order-card")).toContainText("MOCK_LOCKED");

    await page.locator("#output-summary").fill("Delivery package generated");
    await page.getByRole("button", { name: /Submit Delivery/ }).click();
    await expect(page.locator("#order-card")).toContainText("DELIVERED");

    await page.getByRole("button", { name: "Confirm Completion" }).click();
    await expect(page.locator("#order-card")).toContainText("SETTLED");

    await page.getByRole("link", { name: "Go Dashboard" }).click();
    await expect(page).toHaveURL(/dashboard\.html$/);
    await expect(page.getByRole("heading", { name: "Karma Guard Dashboard" })).toBeVisible();
  });

  test("shows clear message when required query params are missing", async ({ page }) => {
    await page.goto("/apps/agent-service-guard/frontend/pay.html");
    await expect(page.locator("#service-view")).toContainText("service_id is required");

    await page.goto("/apps/agent-service-guard/frontend/order.html");
    await expect(page.locator("#order-card")).toContainText("order_id is required");
  });
});
