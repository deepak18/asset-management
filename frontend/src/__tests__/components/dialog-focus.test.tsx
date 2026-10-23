import * as React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Dialog } from "@/components/ui/dialog";

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
