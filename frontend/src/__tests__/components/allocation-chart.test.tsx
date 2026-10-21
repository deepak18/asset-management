import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  AllocationChart,
  AllocationCharts,
} from "@/components/portfolio/allocation-chart";
import type { AllocationWeight } from "@/types/domain";

const rows: AllocationWeight[] = [
  { key: "Technology", market_value: "9007199254740993.125", weight: "0.70505" },
  { key: "Energy", market_value: "120.00", weight: "0.29495" },
];
const chart = (data = rows) => (
  <AllocationChart title="Allocation by sector" rows={data} currency="USD" />
);
const category = (key: string) =>
  screen.getByRole("button", { name: new RegExp(`^${key} `) });
const paths = (container: HTMLElement) =>
  container.querySelectorAll<SVGPathElement>(".recharts-pie-sector path");
function details(button: HTMLElement) {
  const id = button.getAttribute("aria-describedby")?.split(" ").at(-1);
  const element = id ? document.getElementById(id) : null;
  if (!element) throw new Error("Missing accessible details");
  return element;
}

describe("AllocationChart", () => {
  it("formats original decimal strings exactly in legend and linked detail card", async () => {
    const user = userEvent.setup();
    render(chart());
    expect(screen.getByText("USD 9,007,199,254,740,993.13")).toBeInTheDocument();
    expect(screen.getByText("70.51%")).toBeInTheDocument();
    const technology = category("Technology");
    await user.hover(technology);
    expect(details(technology)).toHaveTextContent(
      "TechnologyUSD 9,007,199,254,740,993.13 · 70.51%",
    );
    expect(technology).toHaveClass("bg-accent", "motion-reduce:transition-none");
    expect(details(technology).parentElement).toHaveClass(
      "bg-popover",
      "text-popover-foreground",
      "border-border",
    );
  });

  it("links actual wedge hover to legend, enlarges/strokes the arc and restores default on leave", () => {
    const { container } = render(chart());
    const original = paths(container)[0]!.getAttribute("d");
    fireEvent.mouseEnter(paths(container)[0]!);
    const technology = category("Technology");
    expect(technology).toHaveClass("bg-accent");
    expect(technology).toHaveAttribute("aria-pressed", "false");
    expect(details(technology)).toHaveTextContent("Technology");
    expect(paths(container)[0]).toHaveAttribute("stroke", "hsl(var(--foreground))");
    expect(paths(container)[0]).toHaveAttribute("stroke-width", "2");
    expect(paths(container)[0]!.getAttribute("d")).not.toBe(original);
    expect(paths(container)[1]).toHaveAttribute("fill-opacity", "0.75");
    expect(paths(container)[0]).toHaveClass(
      "cursor-pointer",
      "motion-reduce:transition-none",
    );
    fireEvent.mouseLeave(paths(container)[0]!);
    expect(technology).not.toHaveClass("bg-accent");
    expect(paths(container)[0]).toHaveAttribute("d", original);
    expect(paths(container)[1]).toHaveAttribute("fill-opacity", "1");
    expect(
      screen.getByText("Hover or focus to inspect. Select to pin."),
    ).toBeInTheDocument();
  });

  it("pins and unpins by wedge click, previews another legend item and restores the pin", async () => {
    const user = userEvent.setup();
    const { container } = render(chart());
    fireEvent.click(paths(container)[0]!);
    const technology = category("Technology");
    expect(technology).toHaveAttribute("aria-pressed", "true");
    await user.hover(category("Energy"));
    expect(category("Energy")).toHaveClass("bg-accent");
    expect(technology).toHaveAttribute("aria-pressed", "true");
    await user.unhover(category("Energy"));
    expect(technology).toHaveClass("bg-accent");
    fireEvent.click(paths(container)[0]!);
    expect(technology).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByText("Hover or focus to inspect. Select to pin."),
    ).toBeInTheDocument();
  });

  it("pins by legend click and restores pin after previewing another actual wedge", async () => {
    const user = userEvent.setup();
    const { container } = render(chart());
    await user.click(category("Energy"));
    fireEvent.mouseEnter(paths(container)[0]!);
    expect(category("Technology")).toHaveClass("bg-accent");
    fireEvent.mouseLeave(paths(container)[0]!);
    expect(category("Energy")).toHaveClass("bg-accent");
    await user.click(category("Energy"));
    expect(category("Energy")).toHaveAttribute("aria-pressed", "false");
  });

  it("supports focus preview, native Enter/Space pinning, blur restoration and Escape", async () => {
    const user = userEvent.setup();
    render(chart());
    await user.tab();
    const technology = category("Technology");
    expect(technology).toHaveFocus();
    expect(details(technology)).toHaveTextContent("Technology");
    const detailId = details(technology).id;
    await user.keyboard("{Enter}");
    expect(technology).toHaveAttribute("aria-pressed", "true");
    await user.tab();
    expect(category("Energy")).toHaveFocus();
    expect(details(category("Energy")).id).toBe(detailId);
    await user.tab();
    expect(technology).toHaveClass("bg-accent");
    await user.keyboard("{Escape}");
    expect(technology).toHaveAttribute("aria-pressed", "false");
    await user.tab({ shift: true });
    await user.keyboard(" ");
    expect(category("Energy")).toHaveAttribute("aria-pressed", "true");
    await user.keyboard(" ");
    expect(category("Energy")).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("clears selection explicitly and restores focus without reopening the preview", async () => {
    const user = userEvent.setup();
    render(chart());
    expect(screen.getByRole("button", { name: "Clear Selection" })).toBeDisabled();
    await user.click(category("Energy"));
    await user.click(screen.getByRole("button", { name: "Clear Selection" }));
    expect(category("Energy")).toHaveFocus();
    expect(category("Energy")).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByText("Hover or focus to inspect. Select to pin."),
    ).toBeInTheDocument();
  });

  it("keeps sector and industry selection and description IDs independent", async () => {
    const user = userEvent.setup();
    render(<AllocationCharts currency="USD" bySector={rows} byIndustry={rows} />);
    const lists = screen.getAllByRole("list");
    const sector = within(lists[0]!).getByRole("button", { name: /^Technology / });
    const industry = within(lists[1]!).getByRole("button", { name: /^Technology / });
    await user.click(sector);
    expect(industry).toHaveAttribute("aria-pressed", "false");
    await user.click(industry);
    expect(details(sector).id).not.toBe(details(industry).id);
    const cards = screen.getAllByRole("button", { name: "Clear Selection" });
    await user.click(cards[0]!);
    expect(industry).toHaveAttribute("aria-pressed", "true");
  });

  it("reconciles by category key after reorder/update and permanently clears removed selections", async () => {
    const user = userEvent.setup();
    const { rerender, container } = render(chart());
    await user.click(category("Technology"));
    rerender(chart([rows[1]!, { ...rows[0]!, market_value: "42.125", weight: "0.5" }]));
    expect(category("Technology")).toHaveAttribute("aria-pressed", "true");
    expect(details(category("Technology"))).toHaveTextContent("USD 42.13 · 50.00%");
    expect(paths(container)[1]).toHaveAttribute("stroke-width", "2");
    rerender(chart([rows[1]!]));
    expect(
      screen.getByText("Hover or focus to inspect. Select to pin."),
    ).toBeInTheDocument();
    rerender(chart());
    expect(category("Technology")).toHaveAttribute("aria-pressed", "false");
  });

  it("preserves the unpriced empty state without a ring or controls", () => {
    const { container } = render(chart([]));
    expect(
      screen.getByText("Not priced — allocation unavailable."),
    ).toBeInTheDocument();
    expect(container.querySelector("svg")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("retains honest zero, negative and invalid legend values without fabricating arcs", async () => {
    const user = userEvent.setup();
    const { container } = render(
      chart([
        { key: "zero category", market_value: "0", weight: "0" },
        { key: "Negative", market_value: "-12", weight: "-0.1" },
        { key: "Unavailable", market_value: "invalid", weight: "invalid" },
      ]),
    );
    expect(container.querySelector("svg")).not.toBeInTheDocument();
    expect(category("zero category")).toHaveTextContent("USD 0.00");
    expect(category("Negative")).toHaveTextContent("-10.00%");
    expect(category("Unavailable")).not.toHaveTextContent("0.00");
    await user.click(category("zero category"));
    expect(details(category("zero category"))).toHaveTextContent(
      "No visible slice for this weight.",
    );
    expect(category("zero category")).toHaveAttribute("aria-pressed", "true");
  });
});
