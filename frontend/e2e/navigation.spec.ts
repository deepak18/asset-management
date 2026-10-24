import { test, expect } from "./fixtures";

const destinations = [
  { path: "/holdings", label: "Reported Holdings" },
  { path: "/ledger", label: "Ledger Analytics" },
  { path: "/imports", label: "Imports" },
  { path: "/settings", label: "Account Settings" },
  { path: "/", label: "Overview" },
] as const;

test("feature links navigate real routes and expose exactly one active page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Select portfolio" })).toHaveValue("1");
  const navigation = page.getByRole("navigation", { name: "Primary navigation" });

  for (const { path, label } of destinations) {
    await navigation.getByRole("link", { name: label, exact: true }).click();
    await expect(page).toHaveURL(`http://127.0.0.1:3100${path}?portfolio=1`);
    await expect(navigation.getByRole("link", { name: label, exact: true })).toHaveAttribute(
      "aria-current", "page",
    );
    await expect(navigation.locator('[aria-current="page"]')).toHaveCount(1);
    await expect(page.getByRole("main")).toBeVisible();
    if (path === "/holdings" || path === "/settings") {
      await expect(page.getByRole("heading", { name: label, exact: true, level: 1 })).toBeVisible();
    } else if (path === "/imports") {
      await expect(page.getByRole("combobox", { name: "Brokerage" })).toBeVisible();
    } else {
      await expect(page.getByRole("button", { name: "Review History For AAPL", exact: true })).toBeVisible();
    }
  }

  // Overview is not an import workspace, even when its automatic view is ledger-based.
  await expect(page.getByRole("combobox", { name: "Brokerage" })).toHaveCount(0);
  await expect(page.getByLabel("Upload Broker Statement")).toHaveCount(0);
  await expect(page.getByLabel("Vanguard CSV", { exact: true })).toHaveCount(0);
});

test("portfolio choice survives navigation and reload; query bookmarks override storage", async ({ page }) => {
  await page.goto("/");
  const picker = page.getByRole("combobox", { name: "Select portfolio" });
  await expect(picker).toHaveValue("1");
  await picker.selectOption("3");
  const navigation = page.getByRole("navigation", { name: "Primary navigation" });
  await navigation.getByRole("link", { name: "Account Settings", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\?portfolio=3$/);
  await expect(page.getByRole("button", { name: "Edit Account Settings", exact: true })).toBeVisible();
  await expect(picker).toHaveValue("3");
  await page.reload();
  await expect(picker).toHaveValue("3");
  // No query: this specifically tests persisted storage, not only URL restoration.
  await page.goto("/holdings");
  await expect(picker).toHaveValue("3");
  await expect(page.getByRole("heading", { name: "Reported Holdings", exact: true, level: 1 })).toBeVisible();
  await page.goto("/settings?portfolio=1");
  await expect(picker).toHaveValue("1");
  await expect(page.getByRole("button", { name: "Edit Account Settings", exact: true })).toBeVisible();
  await page.goto("/holdings");
  await expect(picker).toHaveValue("1");
});

test("brokerage selection shows only its actual import form and leaving resets it", async ({ page }) => {
  await page.goto("/imports?portfolio=3");
  const brokerage = page.getByRole("combobox", { name: "Brokerage" });
  await expect(brokerage).toHaveValue("robinhood");
  await expect(page.getByRole("heading", { name: "Import broker statement", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Choose File", exact: true })).toBeVisible();
  await expect(page.getByLabel("Upload Broker Statement")).toHaveCount(1);
  await expect(page.getByLabel("Vanguard CSV", { exact: true })).toHaveCount(0);

  await brokerage.selectOption("vanguard");
  await expect(page.getByRole("heading", { name: "Vanguard Retirement Import", exact: true })).toBeVisible();
  await expect(page.getByLabel("Vanguard CSV", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Holdings as of date", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Preview Vanguard Import", exact: true })).toBeDisabled();
  await expect(page.getByLabel("Upload Broker Statement")).toHaveCount(0);

  await brokerage.selectOption("robinhood");
  await expect(page.getByRole("button", { name: "Choose File", exact: true })).toBeVisible();
  await expect(page.getByLabel("Vanguard CSV", { exact: true })).toHaveCount(0);
  await brokerage.selectOption("vanguard");
  await page.getByRole("navigation", { name: "Primary navigation" })
    .getByRole("link", { name: "Overview", exact: true }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3100/?portfolio=3");
  await expect(brokerage).toHaveCount(0);
  await expect(page.getByLabel("Vanguard CSV", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Upload Broker Statement")).toHaveCount(0);
  await page.getByRole("navigation", { name: "Primary navigation" })
    .getByRole("link", { name: "Imports", exact: true }).click();
  await expect(brokerage).toHaveValue("robinhood");
  await expect(page.getByRole("combobox", { name: "Select portfolio" })).toHaveValue("3");
});
