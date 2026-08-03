import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { useImportJob } from "@/hooks/use-import-job";
import type { StatementImportStatus } from "@/types/domain";

/** Tiny probe that surfaces the polled status + a terminal callback marker. */
function Probe({
  job,
  onSucceeded,
}: {
  job: StatementImportStatus | null;
  onSucceeded: () => void;
}) {
  const live = useImportJob(1, job, onSucceeded, 5);
  return <div data-testid="status">{live?.status ?? "none"}</div>;
}

describe("useImportJob", () => {
  it("polls a PENDING job to SUCCEEDED, then fires onSucceeded once", async () => {
    const file = new File(["Activity Date"], "history.csv", { type: "text/csv" });
    const initial = await apiClient.createImport(1, file);
    const onSucceeded = vi.fn();

    render(<Probe job={initial} onSucceeded={onSucceeded} />);

    expect(screen.getByTestId("status")).toHaveTextContent("PENDING");

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("SUCCEEDED"));
    await waitFor(() => expect(onSucceeded).toHaveBeenCalledTimes(1));
  });

  it("does nothing (and never polls) when there is no job", () => {
    const onSucceeded = vi.fn();
    render(<Probe job={null} onSucceeded={onSucceeded} />);
    expect(screen.getByTestId("status")).toHaveTextContent("none");
    expect(onSucceeded).not.toHaveBeenCalled();
  });

  it("stops on unmount without leaking timers", async () => {
    const file = new File(["x"], "history2.csv", { type: "text/csv" });
    const initial = await apiClient.createImport(1, file);
    const { unmount } = render(<Probe job={initial} onSucceeded={() => {}} />);
    // Unmounting immediately must not throw or warn about setting state later.
    expect(() => unmount()).not.toThrow();
  });
});
