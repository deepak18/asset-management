import { describe, expect, it } from "vitest";
import {
  decimalSign,
  groupThousands,
  parseDecimal,
  roundDecimalString,
  scaleByPowerOfTen,
} from "@/lib/decimal";

describe("parseDecimal", () => {
  it("splits sign and digits and strips leading integer zeros", () => {
    expect(parseDecimal("00123.4500")).toEqual({
      negative: false,
      int: "123",
      frac: "4500",
    });
    expect(parseDecimal("-0.5")).toEqual({ negative: true, int: "0", frac: "5" });
  });

  it("returns null for blank, bare signs, and lone dot", () => {
    for (const bad of ["", "   ", "+", "-", ".", "abc", "1.2.3"]) {
      expect(parseDecimal(bad)).toBeNull();
    }
  });
});

describe("roundDecimalString", () => {
  it("pads to the requested precision without changing value", () => {
    expect(roundDecimalString("12", 2)).toBe("12.00");
    expect(roundDecimalString("3.5", 4)).toBe("3.5000");
  });

  it("rounds half-up and carries across nines", () => {
    expect(roundDecimalString("1.005", 2)).toBe("1.01");
    expect(roundDecimalString("9.999", 2)).toBe("10.00");
    expect(roundDecimalString("-2.675", 2)).toBe("-2.68");
  });

  it("never renders a signed zero", () => {
    expect(roundDecimalString("-0.001", 2)).toBe("0.00");
  });

  it("supports zero decimal places", () => {
    expect(roundDecimalString("2.5", 0)).toBe("3");
    expect(roundDecimalString("2.4", 0)).toBe("2");
  });

  it("returns null for invalid input", () => {
    expect(roundDecimalString("", 2)).toBeNull();
  });
});

describe("scaleByPowerOfTen", () => {
  it("multiplies a weight fraction into a percent magnitude", () => {
    expect(scaleByPowerOfTen("0.2531", 2)).toBe("25.31");
    expect(scaleByPowerOfTen("1", 2)).toBe("100");
    expect(scaleByPowerOfTen("0.001", 2)).toBe("0.1");
  });

  it("shifts left for negative powers", () => {
    expect(scaleByPowerOfTen("5", -2)).toBe("0.05");
  });

  it("preserves sign and drops it for zero", () => {
    expect(scaleByPowerOfTen("-0.25", 2)).toBe("-25");
    expect(scaleByPowerOfTen("-0", 2)).toBe("0");
  });
});

describe("groupThousands", () => {
  it("inserts separators every three digits", () => {
    expect(groupThousands("1")).toBe("1");
    expect(groupThousands("1000")).toBe("1,000");
    expect(groupThousands("1234567")).toBe("1,234,567");
  });
});

describe("decimalSign", () => {
  it("classifies sign and treats all-zero as zero", () => {
    expect(decimalSign("0.00")).toBe(0);
    expect(decimalSign("-0")).toBe(0);
    expect(decimalSign("3.2")).toBe(1);
    expect(decimalSign("-0.1")).toBe(-1);
    expect(decimalSign("bad")).toBeNull();
  });
});
