import type { Locator, Page, TestInfo } from "@playwright/test";
import { test, expect } from "./fixtures";

async function evidence(page: Page, panel: Locator, info: TestInfo, label: string) {
  const geometry = await panel.evaluate((element) => {
    const rect = (node: Element) => {
      const { x, y, width, height, top, right, bottom, left } =
        node.getBoundingClientRect();
      return { x, y, width, height, top, right, bottom, left };
    };
    return {
      viewport: { width: innerWidth, height: innerHeight },
      overlay: rect(element.parentElement!),
      panel: rect(element),
      controls: [...element.querySelectorAll("h2, button, input, select")].map(
        (node) => ({
          label: node.getAttribute("aria-label") ?? node.textContent ?? node.id,
          ...rect(node),
        }),
      ),
      scrollTop: element.scrollTop,
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
    };
  });
  await info.attach(`${label}-geometry`, {
    body: JSON.stringify(geometry, null, 2),
    contentType: "application/json",
  });
  await info.attach(`${label}-screenshot`, {
    body: await page.screenshot(),
    contentType: "image/png",
  });
  return geometry;
}

async function reachable(page: Page, target: Locator) {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  expect(box).not.toBeNull();
  const viewport = page.viewportSize()!;
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
  expect(
    await target.evaluate((node) => {
      const box = node.getBoundingClientRect();
      return node.contains(
        document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2),
      );
    }),
    "Control center must receive pointer events",
  ).toBe(true);
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
  { width: 1280, height: 320 },
  { width: 844, height: 390 },
]) {
  test(`creation layout covers viewport ${viewport.width}x${viewport.height}`, async ({
    page,
  }, info) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByRole("combobox", { name: "Select portfolio" })).toHaveValue(
      "1",
    );
    const trigger = page.getByRole("button", { name: "New Portfolio", exact: true });
    await trigger.click();
    const panel = page.getByRole("dialog", { name: "Create portfolio", exact: true });
    await expect(panel).toBeVisible();
    // Attach before asserting, so the old clipping failure has inspectable evidence too.
    const geometry = await evidence(page, panel, info, "creation-open");
    expect(geometry.overlay).toMatchObject({
      x: 0,
      y: 0,
      width: viewport.width,
      height: viewport.height,
    });
    expect(geometry.panel.top).toBeGreaterThanOrEqual(16);
    expect(geometry.panel.bottom).toBeLessThanOrEqual(viewport.height - 16);
    for (const target of [
      panel.getByRole("heading", { name: "Create portfolio", exact: true }),
      panel.getByRole("button", { name: "Close Dialog" }),
      panel.getByRole("textbox", { name: "Name", exact: true }),
      panel.getByRole("combobox", { name: "Base currency" }),
      panel.getByRole("button", { name: "Cancel", exact: true }),
      panel.getByRole("button", { name: "Create", exact: true }),
    ])
      await reachable(page, target);
    await evidence(page, panel, info, "creation-footer");
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });
}

test("creation keyboard includes Name and currency; every cancellation restores focus without writes", async ({
  page,
}) => {
  let writes = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/v1/portfolios"
    )
      writes++;
  });
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Select portfolio" })).toHaveValue(
    "1",
  );
  const trigger = page.getByRole("button", { name: "New Portfolio", exact: true });
  for (const dismissal of ["escape", "backdrop", "close", "cancel"]) {
    await trigger.click();
    const panel = page.getByRole("dialog", { name: "Create portfolio", exact: true });
    const controls = [
      panel.getByRole("button", { name: "Close Dialog" }),
      panel.getByRole("textbox", { name: "Name", exact: true }),
      panel.getByRole("combobox", { name: "Base currency" }),
      panel.getByRole("button", { name: "Cancel", exact: true }),
      panel.getByRole("button", { name: "Create", exact: true }),
    ];
    await expect(controls[0]!).toBeFocused();
    for (const target of [...controls.slice(1), controls[0]!]) {
      await page.keyboard.press("Tab");
      await expect(target).toBeFocused();
    }
    for (const target of [...controls.slice(1).reverse(), controls[0]!]) {
      await page.keyboard.press("Shift+Tab");
      await expect(target).toBeFocused();
    }
    await controls[1]!.fill("Fictitious discarded draft");
    if (dismissal === "escape") await page.keyboard.press("Escape");
    else if (dismissal === "backdrop")
      await page.mouse.click(2, page.viewportSize()!.height - 2);
    else
      await panel
        .getByRole("button", {
          name: dismissal === "close" ? "Close Dialog" : "Cancel",
          exact: true,
        })
        .click();
    await expect(panel).toHaveCount(0);
    await expect(trigger).toBeFocused();
  }
  expect(writes).toBe(0);
});

test("fictitious portfolio creates once through MSW and refreshes/auto-selects the picker", async ({
  page,
}) => {
  const writes: string[] = [];
  const lists: string[] = [];
  page.on("response", (response) => {
    if (new URL(response.url()).pathname !== "/api/v1/portfolios") return;
    if (response.request().method() === "GET") lists.push(response.url());
    if (response.request().method() === "POST") writes.push(response.url());
  });
  await page.goto("/");
  const picker = page.getByRole("combobox", { name: "Select portfolio" });
  await expect(picker).toHaveValue("1");
  const readsBefore = lists.length;
  const trigger = page.getByRole("button", { name: "New Portfolio", exact: true });
  await trigger.click();
  const panel = page.getByRole("dialog", { name: "Create portfolio", exact: true });
  await panel
    .getByRole("textbox", { name: "Name", exact: true })
    .fill("Fictitious Browser Portfolio");
  await panel.getByRole("combobox", { name: "Base currency" }).selectOption("USD");
  const createdResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/v1/portfolios" &&
      response.request().method() === "POST",
  );
  await panel.getByRole("button", { name: "Create", exact: true }).click();
  const response = await createdResponse;
  expect(response.fromServiceWorker()).toBe(true);
  expect(response.status()).toBe(201);
  expect(response.request().postDataJSON()).toEqual({
    name: "Fictitious Browser Portfolio",
    base_currency: "USD",
  });
  const created: { id: number; name: string; base_currency: string } =
    await response.json();
  await expect(panel).toHaveCount(0);
  await expect(picker).toHaveValue(String(created.id));
  await expect(picker.locator("option:checked")).toHaveText(
    "Fictitious Browser Portfolio \u00b7 USD",
  );
  await expect(trigger).toBeFocused();
  expect(lists.length).toBe(readsBefore + 1);
  expect(writes).toHaveLength(1);
  await page
    .getByRole("navigation", { name: "Primary navigation" })
    .getByRole("link", { name: "Account Settings", exact: true })
    .click();
  await expect(picker).toHaveValue(String(created.id));
  expect(writes).toHaveLength(1);
});

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
  { width: 1280, height: 320 },
]) {
  test(`long history stays reachable with internal scroll ${viewport.width}x${viewport.height}`, async ({
    page,
  }, info) => {
    await page.setViewportSize(viewport);
    await page.goto("/ledger?portfolio=1");
    const trigger = page.getByRole("button", {
      name: "Review History For AAPL",
      exact: true,
    });
    await trigger.click();
    const panel = page.getByRole("dialog", { name: /^Review history: AAPL/ });
    await expect(
      panel.getByRole("button", { name: "Reload History / Retry" }),
    ).toBeVisible();
    await expect(panel.getByRole("table")).toBeVisible();
    const geometry = await evidence(page, panel, info, "history-top");
    expect(geometry.overlay).toMatchObject({
      x: 0,
      y: 0,
      width: viewport.width,
      height: viewport.height,
    });
    expect(geometry.panel.top).toBeGreaterThanOrEqual(16);
    expect(geometry.panel.bottom).toBeLessThanOrEqual(viewport.height - 16);
    expect(geometry.scrollHeight).toBeGreaterThan(geometry.clientHeight);
    await reachable(page, panel.getByRole("heading", { level: 2 }));
    await reachable(page, panel.getByRole("button", { name: "Close Dialog" }));
    await reachable(page, panel.getByRole("button", { name: "Cancel", exact: true }));
    expect(await panel.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
    await evidence(page, panel, info, "history-footer");
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("hidden");
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    await expect(trigger).toBeFocused();
    expect(await page.evaluate(() => document.body.style.overflow)).toBe("");
  });
}
