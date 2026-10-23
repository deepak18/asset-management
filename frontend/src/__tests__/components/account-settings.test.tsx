import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { AccountSettings } from "@/components/portfolio/account-settings";
import { apiClient } from "@/lib/api-client";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { findPortfolio, updateMockAccount } from "@/mocks/state";

const base = `${env.apiBaseUrl}/api/v1`;
it("loads real account metadata, saves leading zeros accessibly, refreshes and clears nullable strings", async () => {
  const user = userEvent.setup();
  updateMockAccount(99, {
    custodian: "Existing custodian",
    external_account_id: "000009",
  });
  const onChanged = vi.fn();
  const view = render(
    <AccountSettings portfolioId={99} refreshToken={0} onChanged={onChanged} />,
  );
  await user.click(
    await screen.findByRole("button", { name: "Edit Account Settings" }),
  );
  expect(screen.getByLabelText("Account ID")).toHaveValue("000009");
  await user.clear(screen.getByLabelText("Account ID"));
  await user.type(screen.getByLabelText("Account ID"), "000042");
  await user.clear(screen.getByLabelText("Custodian"));
  await user.type(screen.getByLabelText("Custodian"), "Vanguard");
  await user.selectOptions(screen.getByLabelText("Account type"), "ROTH_401K");
  await user.click(screen.getByRole("button", { name: "Save Account Settings" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  view.rerender(
    <AccountSettings portfolioId={99} refreshToken={1} onChanged={onChanged} />,
  );
  expect(await screen.findByText("000042")).toBeInTheDocument();
  expect(screen.getByText("Roth 401(k)")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Edit Account Settings" }));
  await user.clear(screen.getByLabelText("Custodian"));
  await user.click(screen.getByRole("button", { name: "Save Account Settings" }));
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2));
  expect(await apiClient.getPortfolio(99)).toMatchObject({
    external_account_id: "000042",
    custodian: null,
  });
});

it("preserves failure drafts and unsaved drafts across refresh, cancel restores server values", async () => {
  const user = userEvent.setup();
  server.use(
    http.patch(`${base}/portfolios/99/account`, () =>
      HttpResponse.json({ detail: "Account metadata invalid" }, { status: 422 }),
    ),
  );
  const onChanged = vi.fn();
  const view = render(
    <AccountSettings portfolioId={99} refreshToken={0} onChanged={onChanged} />,
  );
  await user.click(
    await screen.findByRole("button", { name: "Edit Account Settings" }),
  );
  await user.type(screen.getByLabelText("Account ID"), "0000");
  await user.click(screen.getByRole("button", { name: "Save Account Settings" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Account metadata invalid",
  );
  expect(screen.getByLabelText("Account ID")).toHaveValue("0000");
  view.rerender(
    <AccountSettings portfolioId={99} refreshToken={1} onChanged={onChanged} />,
  );
  expect(screen.getByLabelText("Account ID")).toHaveValue("0000");
  await user.click(screen.getByRole("button", { name: "Cancel Account Settings" }));
  await user.click(
    await screen.findByRole("button", { name: "Edit Account Settings" }),
  );
  expect(screen.getByLabelText("Account ID")).toHaveValue("");
  expect(onChanged).not.toHaveBeenCalled();
});

it("aborts pending saves on cancel and ignores stale account reads after scope changes", async () => {
  const user = userEvent.setup();
  let releaseRead!: () => void;
  let signal: AbortSignal | undefined;
  const deferredRead = new Promise<void>((resolve) => {
    releaseRead = resolve;
  });
  server.use(
    http.get(`${base}/portfolios/1`, async ({ request }) => {
      signal = request.signal;
      await deferredRead;
      return HttpResponse.json({
        ...findPortfolio(1)!,
        external_account_id: "old-scope",
      });
    }),
  );
  const changed = vi.fn();
  const view = render(
    <AccountSettings portfolioId={1} refreshToken={0} onChanged={changed} />,
  );
  await waitFor(() => expect(signal).toBeDefined());
  view.rerender(
    <AccountSettings portfolioId={99} refreshToken={0} onChanged={changed} />,
  );
  await screen.findByRole("button", { name: "Edit Account Settings" });
  await act(async () => releaseRead());
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByText("old-scope")).not.toBeInTheDocument();
  let releaseWrite!: () => void;
  let writeSignal: AbortSignal | undefined;
  server.use(
    http.patch(`${base}/portfolios/99/account`, async ({ request }) => {
      writeSignal = request.signal;
      await new Promise<void>((resolve) => {
        releaseWrite = resolve;
      });
      return HttpResponse.json(findPortfolio(99)!);
    }),
  );
  await user.click(screen.getByRole("button", { name: "Edit Account Settings" }));
  await user.type(screen.getByLabelText("Account ID"), "000042");
  await user.click(screen.getByRole("button", { name: "Save Account Settings" }));
  await waitFor(() => expect(writeSignal).toBeDefined());
  await user.click(screen.getByRole("button", { name: "Cancel Account Settings" }));
  await act(async () => releaseWrite());
  expect(writeSignal?.aborted).toBe(true);
  expect(changed).not.toHaveBeenCalled();
});
