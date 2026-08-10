import { expect, test } from "@playwright/test";

test("loads the Sky Bridge Jet foundation shell", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Sky Bridge Jet" })).toBeVisible();
  await expect(page.getByText("Premium Private Aviation Marketplace")).toBeVisible();
});
