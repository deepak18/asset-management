import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AllocationChart } from "@/components/portfolio/allocation-chart";
import type { AllocationWeight } from "@/types/domain";

const rows: AllocationWeight[] = [
  { key: "Technology", market_value: "3415.00", weight: "1" },
  { key: "Energy", market_value: "0", weight: "0" },
];

describe("AllocationChart", () => {
  it("renders a legend row per slice with percent and money from strings", () => {
    render(<AllocationChart title="Allocation by sector" rows={rows} currency="USD" />);
    expect(screen.getByText("Allocation by sector")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("100.00%")).toBeInTheDocument();
    expect(screen.getByText("USD 3,415.00")).toBeInTheDocument();
  });

  it("shows a 'not priced' message when there are no allocation rows", () => {
    render(<AllocationChart title="Allocation by sector" rows={[]} currency="USD" />);
    expect(
      screen.getByText("Not priced — allocation unavailable."),
    ).toBeInTheDocument();
  });
});
