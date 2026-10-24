"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

// Server/hydration snapshots omit portal markup; ordinary client opens render
// immediately so focus still moves in the same layout commit as the trigger.
const subscribe = () => () => {};
const clientSnapshot = () => true;
const serverSnapshot = () => false;
const panels: HTMLDivElement[] = [];
let bodyOverflow = "";

function focusableControls(panel: HTMLDivElement) {
  return [
    ...panel.querySelectorAll<HTMLElement>(
      'button, a[href], input, select, textarea, [tabindex], [contenteditable="true"], audio[controls], video[controls], summary',
    ),
  ]
    .filter((element) => {
      if (element.tabIndex < 0 || element.matches(':disabled, input[type="hidden"]'))
        return false;
      for (let node: HTMLElement | null = element; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (
          node.hidden ||
          node.hasAttribute("inert") ||
          style.display === "none" ||
          style.visibility === "hidden"
        )
          return false;
      }
      return true;
    })
    .sort((a, b) => (a.tabIndex || Infinity) - (b.tabIndex || Infinity));
}

/** Viewport-bounded modal; its portal escapes ancestor filters/containing blocks. */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  className,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const panelRef = React.useRef<HTMLDivElement>(null);
  const ready = React.useSyncExternalStore(subscribe, clientSnapshot, serverSnapshot);
  const descriptionId = React.useId();
  const returnFocus = React.useRef<HTMLElement | null>(null);
  // Descendant autoFocus runs in layout before the parent layout effect.
  // Capture the trigger earlier, but acquire/restore focus only in layout.
  React.useInsertionEffect(() => {
    if (open && ready)
      returnFocus.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }, [open, ready]);
  // Focus belongs to the DOM commit: passive cleanup can run after the dialog
  // has disappeared, briefly leaving focus on body instead of its trigger.
  React.useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!open || !ready || !panel) return;
    const previous = returnFocus.current;
    if (!panels.length) {
      bodyOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    panels.push(panel);
    (focusableControls(panel)[0] ?? panel).focus({ preventScroll: true });
    return () => {
      const wasTop = panels.at(-1) === panel;
      panels.splice(panels.indexOf(panel), 1);
      if (!panels.length) document.body.style.overflow = bodyOverflow;
      if (wasTop && previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [open, ready]);

  React.useEffect(() => {
    const panel = panelRef.current;
    if (!open || !ready || !panel) return;
    // Capture Tab before consumer-specific traps; only the top modal owns it.
    const onTab = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || panels.at(-1) !== panel) return;
      const controls = focusableControls(panel);
      const first = controls[0];
      const last = controls.at(-1);
      if (!first || !last) {
        event.preventDefault();
        panel.focus();
      } else if (
        !panel.contains(document.activeElement) ||
        (event.shiftKey && document.activeElement === first) ||
        (!event.shiftKey && document.activeElement === last)
      ) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else return;
      event.stopPropagation();
    };
    // Bubble Escape so an inner combobox can consume it without dismissing.
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || panels.at(-1) !== panel)
        return;
      event.preventDefault();
      event.stopImmediatePropagation();
      onClose();
    };
    document.addEventListener("keydown", onTab, true);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("keydown", onTab, true);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open, ready, onClose]);

  if (!open || !ready) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget && panels.at(-1) === panelRef.current)
          onClose();
        event.stopPropagation();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-label={title}
        aria-describedby={description ? descriptionId : undefined}
        className={cn(
          "w-full max-w-lg rounded-lg border bg-card p-6 text-card-foreground shadow-lg",
          className,
          "max-h-[calc(100dvh-2rem)] overflow-y-auto overscroll-contain",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{title}</h2>
            {description ? (
              <p id={descriptionId} className="mt-1 text-sm text-muted-foreground">
                {description}
              </p>
            ) : null}
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0"
            aria-label="Close Dialog"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
