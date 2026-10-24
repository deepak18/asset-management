import * as React from "react";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Dialog } from "@/components/ui/dialog";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";

it.each(["button", "escape"])(
  "moves focus during the dialog commit, including restoration on %s dismissal",
  async (dismissal) => {
    const user = userEvent.setup();
    const committedFocus = vi.fn();
    function Harness() {
      const [open, setOpen] = React.useState(false);
      // Observe the committed DOM before passive effects. Removing the dialog
      // must not leave focus on body until a later passive-effect flush.
      React.useLayoutEffect(() => {
        committedFocus(open, document.activeElement);
      }, [open]);
      return (
        <>
          <button onClick={() => setOpen(true)}>Open Review</button>
          {open && (
            <Dialog open title="Focus review" onClose={() => setOpen(false)}>
              <button onClick={() => setOpen(false)}>Finish Review</button>
            </Dialog>
          )}
        </>
      );
    }
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open Review" });
    await user.click(trigger);
    const close = screen.getByRole("button", { name: "Close Dialog" });
    const openingFocus = committedFocus.mock.calls.at(-1);
    expect(close).toHaveFocus();
    if (dismissal === "escape") await user.keyboard("{Escape}");
    else await user.click(screen.getByRole("button", { name: "Finish Review" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(committedFocus).toHaveBeenLastCalledWith(false, trigger);
    expect(openingFocus).toEqual([true, close]);
    expect(trigger).toHaveFocus();
  },
);

it("portals outside a filtered ancestor and traps all enabled visible controls, not only buttons", async () => {
  const user = userEvent.setup();
  const { container } = render(
    <header style={{ backdropFilter: "blur(8px)" }}>
      <Dialog open title="Controls" onClose={() => {}}>
        <label>
          Name
          <input />
        </label>
        <label>
          Currency
          <select>
            <option>USD</option>
          </select>
        </label>
        <a href="#record">Record</a>
        <label>
          Notes
          <textarea />
        </label>
        <button disabled>Disabled</button>
        <fieldset disabled>
          <input aria-label="Disabled field" />
        </fieldset>
        <input type="hidden" />
        <input hidden aria-label="Hidden" />
        <input style={{ display: "none" }} aria-label="CSS hidden" />
        <input tabIndex={-1} aria-label="Programmatic" />
        <label>
          Reviewed
          <input type="checkbox" />
        </label>
        <div tabIndex={0}>Focusable region</div>
      </Dialog>
    </header>,
  );
  const panel = screen.getByRole("dialog", { name: "Controls" });
  expect(container.contains(panel)).toBe(false);
  expect(panel.parentElement?.parentElement).toBe(document.body);
  expect(panel).toHaveAttribute("aria-modal", "true");
  const controls = [
    within(panel).getByRole("button", { name: "Close Dialog" }),
    screen.getByLabelText("Name"),
    screen.getByLabelText("Currency"),
    screen.getByRole("link"),
    screen.getByLabelText("Notes"),
    screen.getByLabelText("Reviewed"),
    screen.getByText("Focusable region"),
  ];
  for (const target of [...controls.slice(1), controls[0]!]) {
    await user.tab();
    expect(target).toHaveFocus();
  }
  for (const target of [...controls.slice(1).reverse(), controls[0]!]) {
    await user.tab({ shift: true });
    expect(target).toHaveFocus();
  }
});

it("restores prior inline body overflow on close, reopen and unmount in Strict Mode", async () => {
  const user = userEvent.setup();
  document.body.style.overflow = "scroll";
  function Harness() {
    const [open, setOpen] = React.useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>Open</button>
        <Dialog open={open} title="Lock" onClose={() => setOpen(false)}>
          Content
        </Dialog>
      </>
    );
  }
  const view = render(
    <React.StrictMode>
      <Harness />
    </React.StrictMode>,
  );
  try {
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(document.body.style.overflow).toBe("hidden");
    await user.keyboard("{Escape}");
    expect(document.body.style.overflow).toBe("scroll");
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(document.body.style.overflow).toBe("hidden");
    view.unmount();
    expect(document.body.style.overflow).toBe("scroll");
  } finally {
    view.unmount();
    document.body.style.overflow = "";
  }
});

it("only dismisses/traps the top nested dialog and keeps the body locked until both close", async () => {
  const user = userEvent.setup();
  function Harness() {
    const [outer, setOuter] = React.useState(false);
    const [inner, setInner] = React.useState(false);
    return (
      <>
        <button onClick={() => setOuter(true)}>Open Outer</button>
        {outer && (
          <Dialog open title="Outer" onClose={() => setOuter(false)}>
            <button onClick={() => setInner(true)}>Open Inner</button>
            {inner && (
              <Dialog open title="Inner" onClose={() => setInner(false)}>
                <label>
                  Inner input
                  <input />
                </label>
              </Dialog>
            )}
          </Dialog>
        )}
      </>
    );
  }
  render(<Harness />);
  const trigger = screen.getByRole("button", { name: "Open Outer" });
  await user.click(trigger);
  const innerTrigger = screen.getByRole("button", { name: "Open Inner" });
  await user.click(innerTrigger);
  const inner = screen.getByRole("dialog", { name: "Inner" });
  await user.tab({ shift: true });
  expect(screen.getByLabelText("Inner input")).toHaveFocus();
  await user.tab();
  expect(within(inner).getByRole("button", { name: "Close Dialog" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "Inner" })).toBeNull();
  expect(screen.getByRole("dialog", { name: "Outer" })).toBeVisible();
  expect(innerTrigger).toHaveFocus();
  expect(document.body.style.overflow).toBe("hidden");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(trigger).toHaveFocus();
  expect(document.body.style.overflow).toBe("");
});

it("hydrates an initially open server-rendered dialog without mismatched portal markup", async () => {
  const recoverable = vi.fn();
  const content = (
    <Dialog open title="Hydration" onClose={() => {}}>
      Ready
    </Dialog>
  );
  const host = document.createElement("div");
  host.innerHTML = renderToString(content);
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  document.body.append(host);
  let root: ReturnType<typeof hydrateRoot> | undefined;
  try {
    await act(async () => {
      root = hydrateRoot(host, content, { onRecoverableError: recoverable });
    });
    expect(screen.getByRole("dialog", { name: "Hydration" })).toBeVisible();
    expect(recoverable).not.toHaveBeenCalled();
  } finally {
    await act(async () => root?.unmount());
    host.remove();
  }
});
it("restores the trigger rather than a descendant autofocus input", async () => {
  const user = userEvent.setup();
  function Harness() {
    const [open, setOpen] = React.useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>Autofocus Trigger</button>
        <Dialog open={open} title="Autofocus" onClose={() => setOpen(false)}>
          <label>
            Autofocus Name
            <input autoFocus />
          </label>
        </Dialog>
      </>
    );
  }
  render(<Harness />);
  const trigger = screen.getByRole("button", { name: "Autofocus Trigger" });
  await user.click(trigger);
  expect(screen.getByRole("button", { name: "Close Dialog" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(trigger).toHaveFocus();
});
