import * as React from "react";
import { apiClient } from "@/lib/api-client";
import { useRetirementOperation, useRetirementResource } from "@/hooks/use-retirement";
import type { AccountType, AccountUpdate } from "@/types/domain";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const accountTypes: { value: AccountType; label: string }[] = [
  { value: "UNKNOWN", label: "Unknown" },
  { value: "TAXABLE", label: "Taxable Brokerage" },
  { value: "TRADITIONAL_401K", label: "Traditional 401(k)" },
  { value: "ROTH_401K", label: "Roth 401(k)" },
  { value: "TRADITIONAL_IRA", label: "Traditional IRA" },
  { value: "ROTH_IRA", label: "Roth IRA" },
  { value: "OTHER", label: "Other" },
];

export function AccountSettings(props: {
  portfolioId: number;
  refreshToken: number;
  onChanged: () => void;
}) {
  return <SettingsScope key={props.portfolioId} {...props} />;
}

function SettingsScope({
  portfolioId,
  refreshToken,
  onChanged,
}: {
  portfolioId: number;
  refreshToken: number;
  onChanged: () => void;
}) {
  const account = useRetirementResource(
    `metadata:${portfolioId}:${refreshToken}`,
    (signal) => apiClient.getPortfolio(portfolioId, signal),
  );
  const [draft, setDraft] = React.useState<AccountUpdate | null>(null);
  const [pending, setPending] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [error, setError] = React.useState("");
  const operation = useRetirementOperation(String(portfolioId));
  const uid = React.useId();

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!draft) return;
    const controller = operation.start();
    if (!controller) return;
    setPending(true);
    setError("");
    setMessage("");
    try {
      await apiClient.updateAccount(portfolioId, draft, controller.signal);
      if (!operation.active(controller)) return;
      setDraft(null);
      setMessage("Account settings saved.");
      onChanged();
    } catch (err: unknown) {
      if (operation.active(controller))
        setError(
          err instanceof Error ? err.message : "Account settings could not be saved.",
        );
    } finally {
      if (operation.active(controller)) setPending(false);
      operation.finish(controller);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account Settings</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {account.status === "loading" && <p role="status">Loading account settings…</p>}
        {account.status === "error" && <p role="alert">{account.error.message}</p>}
        {account.status === "success" && !draft && (
          <>
            <dl>
              <dt>Account type</dt>
              <dd>
                {
                  accountTypes.find(
                    (type) => type.value === (account.data.account_type ?? "UNKNOWN"),
                  )?.label
                }
              </dd>
              <dt>Custodian</dt>
              <dd>{account.data.custodian ?? "—"}</dd>
              <dt>Account ID</dt>
              <dd>{account.data.external_account_id ?? "—"}</dd>
            </dl>
            <Button
              variant="outline"
              onClick={() => {
                setDraft({
                  account_type: account.data.account_type ?? "UNKNOWN",
                  custodian: account.data.custodian ?? null,
                  external_account_id: account.data.external_account_id ?? null,
                });
                setError("");
                setMessage("");
              }}
            >
              Edit Account Settings
            </Button>
          </>
        )}
        {draft && (
          <form onSubmit={save} className="space-y-3">
            <fieldset disabled={pending} className="space-y-3">
              <div>
                <Label htmlFor={`${uid}-type`}>Account type</Label>
                <select
                  id={`${uid}-type`}
                  aria-describedby={`${uid}-type-help`}
                  className="block rounded border bg-background p-2"
                  value={draft.account_type}
                  onChange={(e) => {
                    const value = accountTypes.find(
                      (type) => type.value === e.target.value,
                    )?.value;
                    if (value) setDraft({ ...draft, account_type: value });
                  }}
                >
                  {accountTypes.map((type) => (
                    <option key={type.value} value={type.value}>
                      {type.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <Label htmlFor={`${uid}-custodian`}>Custodian</Label>
                <Input
                  id={`${uid}-custodian`}
                  maxLength={120}
                  placeholder="Vanguard"
                  value={draft.custodian ?? ""}
                  onChange={(e) =>
                    setDraft({ ...draft, custodian: e.target.value || null })
                  }
                />
              </div>
              <div>
                <Label htmlFor={`${uid}-account`}>Account ID</Label>
                <Input
                  id={`${uid}-account`}
                  type="text"
                  maxLength={120}
                  value={draft.external_account_id ?? ""}
                  onChange={(e) =>
                    setDraft({ ...draft, external_account_id: e.target.value || null })
                  }
                />
              </div>
              <p className="text-sm text-muted-foreground" id={`${uid}-type-help`}>
                Keep leading zeros. Blank custodian or account ID clears that field.
                Account type is not inferred from a fund name. Taxable Brokerage means
                an ordinary, non-retirement investment account, unlike a 401(k) or IRA.
              </p>
              <Button type="submit">
                {pending ? "Saving…" : "Save Account Settings"}
              </Button>
            </fieldset>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                operation.cancel();
                setPending(false);
                setDraft(null);
                setError("");
              }}
            >
              Cancel Account Settings
            </Button>
          </form>
        )}
        {error && <p role="alert">{error}</p>}
        {message && <p role="status">{message}</p>}
      </CardContent>
    </Card>
  );
}
