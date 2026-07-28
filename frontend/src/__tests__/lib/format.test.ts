import { describe, expect, it } from "vitest";
import {
  DASH,
  formatMoney,
  formatPercent,
  formatQuantity,
  signTone,
} from "@/lib/format";

describe("formatMoney", () => {
  it("formats grouped money with an ISO prefix", () => {
    expect(formatMoney("1234.5", "USD")).toBe("USD 1,234.50");
    expect(formatMoney("0", "USD")).toBe("USD 0.00");
    expect(formatMoney("-42", "INR")).toBe("-INR 42.00");
  });

  it("optionally shows an explicit plus for gains", () => {
    expect(formatMoney("176.4", "USD", { signed: true })).toBe("+USD 176.40");
    expect(formatMoney("-5", "USD", { signed: true })).toBe("-USD 5.00");
  });

  it("renders a dash for null, undefined, or malformed values", () => {
    expect(formatMoney(null, "USD")).toBe(DASH);
    expect(formatMoney(undefined, "USD")).toBe(DASH);
    expect(formatMoney("not-a-number", "USD")).toBe(DASH);
  });
});

describe("formatPercent", () => {
  it("converts a weight fraction to a percent", () => {
    expect(formatPercent("0.6222")).toBe("62.22%");
    expect(formatPercent("1")).toBe("100.00%");
  });

  it("respects custom precision and signed option", () => {
    expect(formatPercent("0.1842", { fractionDigits: 1 })).toBe("18.4%");
    expect(formatPercent("0.05", { signed: true })).toBe("+5.00%");
  });

  it("renders a dash for a null return (undefined XIRR)", () => {
    expect(formatPercent(null)).toBe(DASH);
  });
});

describe("formatQuantity", () => {
  it("trims trailing zeros but keeps meaningful fractions", () => {
    expect(formatQuantity("10")).toBe("10");
    expect(formatQuantity("10.5000")).toBe("10.5");
    expect(formatQuantity("1234.25")).toBe("1,234.25");
  });

  it("renders a dash for missing values", () => {
    expect(formatQuantity(null)).toBe(DASH);
  });
});

describe("signTone", () => {
  it("maps values to color tones", () => {
    expect(signTone("5")).toBe("positive");
    expect(signTone("-5")).toBe("negative");
    expect(signTone("0")).toBe("zero");
    expect(signTone(null)).toBe("unknown");
    expect(signTone("oops")).toBe("unknown");
  });
});
