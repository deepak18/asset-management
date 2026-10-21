"use client";

import * as React from "react";
import { Input } from "@/components/ui/input";
import type { HoldingInfo } from "@/types/domain";

/** Keep the first existing spelling; normalize only for comparison and sorting. */
export function classificationSuggestions(holdings: readonly HoldingInfo[]) {
  const values = (field: "sector" | "industry") => {
    const unique = new Map<string, string>();
    for (const holding of holdings) {
      const value = holding[field]?.trim();
      if (value && !unique.has(value.toLowerCase()))
        unique.set(value.toLowerCase(), value);
    }
    return [...unique.entries()]
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([, value]) => value);
  };
  return { sector: values("sector"), industry: values("industry") };
}

/** Editable, manual-selection combobox: choosing an option never submits a write. */
export function ClassificationCombobox({
  label,
  value,
  suggestions,
  disabled,
  invalid,
  onChange,
}: {
  label: string;
  value: string;
  suggestions: readonly string[];
  disabled: boolean;
  invalid: boolean;
  onChange: (value: string) => void;
}) {
  const id = React.useId();
  const root = React.useRef<HTMLDivElement>(null);
  const [open, setOpen] = React.useState(true);
  const [active, setActive] = React.useState<string | null>(null);
  const matches = suggestions.filter((option) =>
    option.toLowerCase().includes(value.trim().toLowerCase()),
  );
  const expanded = open && !disabled && matches.length > 0;
  const activeIndex = expanded && active !== null ? matches.indexOf(active) : -1;
  const listId = `${id}-list`;
  const optionId = (index: number) => `${id}-option-${index}`;

  React.useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) {
        setOpen(false);
        setActive(null);
      }
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, []);

  function select(option: string) {
    onChange(option);
    setOpen(false);
    setActive(null);
  }

  return (
    <div
      ref={root}
      className="relative"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setOpen(false);
          setActive(null);
        }
      }}
    >
      <Input
        autoFocus
        role="combobox"
        aria-label={label}
        aria-autocomplete="list"
        aria-haspopup="listbox"
        aria-expanded={expanded}
        aria-controls={expanded ? listId : undefined}
        aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
        aria-invalid={invalid || undefined}
        autoComplete="off"
        maxLength={80}
        value={value}
        disabled={disabled}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onChange={(event) => {
          onChange(event.target.value);
          setActive(null);
          setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            // Consume Escape before document-level enclosing dialog listeners.
            event.preventDefault();
            event.stopPropagation();
            setOpen(false);
            setActive(null);
          } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            const next =
              event.key === "ArrowDown"
                ? (activeIndex + 1) % matches.length
                : activeIndex <= 0
                  ? matches.length - 1
                  : activeIndex - 1;
            setActive(matches[next] ?? null);
          } else if (event.key === "Enter" && expanded) {
            event.preventDefault();
            event.stopPropagation();
            if (activeIndex >= 0) select(matches[activeIndex]!);
          }
        }}
      />
      {expanded ? (
        <ul
          id={listId}
          role="listbox"
          aria-label={`${label} suggestions`}
          className="absolute z-20 max-h-48 w-full overflow-auto rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
        >
          {matches.map((option, index) => (
            <li
              key={option}
              id={optionId(index)}
              role="option"
              aria-selected={index === activeIndex}
              className={`cursor-pointer rounded px-2 py-1 ${index === activeIndex ? "bg-accent" : "hover:bg-accent"}`}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => select(option)}
            >
              {option}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
