import {
  decimalSign,
  groupThousands,
  roundDecimalString,
  scaleByPowerOfTen,
} from "@/lib/decimal";

/**
 * Presentation layer for backend Decimal strings.
 *
 * Every helper degrades to {@link DASH} when the value is absent or malformed —
 * an unpriced position or an undefined XIRR must read as "not available", never
 * as a fabricated 0 (a real financial figure the backend never asserted).
 */

/** Em dash used everywhere a value is genuinely unknown / not computed. */
export const DASH = "—";

/** Split a canonical rounded string into its integer and fraction parts. */
function splitRounded(rounded: string): { negative: boolean; int: string; frac: string } {
  const negative = rounded.startsWith("-");
  const body = negative ? rounded.slice(1) : rounded;
  const [int = "0", frac = ""] = body.split(".");
  return { negative, int, frac };
}

interface MoneyOptions {
  /** Fractional digits to show (default 2). */
  fractionDigits?: number;
  /** Prefix non-negative values with an explicit "+" (for P&L deltas). */
  signed?: boolean;
}

/**
 * Format a Decimal string as grouped money in `currency`, e.g.
 * `"1234.5" → "USD 1,234.50"`. Returns {@link DASH} for null/blank/invalid.
 *
 * The ISO code is shown as a prefix rather than a locale currency symbol so the
 * base currency (USD now, INR next) is unambiguous and no locale guessing leaks
 * a float through `Intl.NumberFormat`.
 */
export function formatMoney(
  raw: string | null | undefined,
  currency: string,
  options: MoneyOptions = {},
): string {
  if (raw == null) {
    return DASH;
  }
  const fractionDigits = options.fractionDigits ?? 2;
  const rounded = roundDecimalString(raw, fractionDigits);
  if (rounded === null) {
    return DASH;
  }
  const { negative, int, frac } = splitRounded(rounded);
  const digits = frac.length > 0 ? `${groupThousands(int)}.${frac}` : groupThousands(int);
  const sign = negative ? "-" : options.signed ? "+" : "";
  return `${sign}${currency} ${digits}`;
}

interface PercentOptions {
  /** Fractional digits to show (default 2). */
  fractionDigits?: number;
  /** Prefix non-negative values with an explicit "+" (for return deltas). */
  signed?: boolean;
}

/**
 * Format a weight/rate *fraction* (0.2531) as a percent ("25.31%"). Multiplies
 * by 100 via decimal-point shift (no float). Returns {@link DASH} for null.
 */
export function formatPercent(
  rawFraction: string | null | undefined,
  options: PercentOptions = {},
): string {
  if (rawFraction == null) {
    return DASH;
  }
  const scaled = scaleByPowerOfTen(rawFraction, 2);
  if (scaled === null) {
    return DASH;
  }
  const fractionDigits = options.fractionDigits ?? 2;
  const rounded = roundDecimalString(scaled, fractionDigits);
  if (rounded === null) {
    return DASH;
  }
  const { negative, int, frac } = splitRounded(rounded);
  const digits = frac.length > 0 ? `${groupThousands(int)}.${frac}` : groupThousands(int);
  const sign = negative ? "-" : options.signed ? "+" : "";
  return `${sign}${digits}%`;
}

/**
 * Format a share quantity: grouped, trailing zeros trimmed (fractional shares
 * are allowed, but "10" should not read as "10.0000"). Returns {@link DASH}.
 */
export function formatQuantity(
  raw: string | null | undefined,
  maxFractionDigits = 4,
): string {
  if (raw == null) {
    return DASH;
  }
  const rounded = roundDecimalString(raw, maxFractionDigits);
  if (rounded === null) {
    return DASH;
  }
  const { negative, int, frac } = splitRounded(rounded);
  const trimmedFrac = frac.replace(/0+$/, "");
  const digits =
    trimmedFrac.length > 0 ? `${groupThousands(int)}.${trimmedFrac}` : groupThousands(int);
  return `${negative ? "-" : ""}${digits}`;
}

/**
 * Semantic direction of a signed figure for coloring: `"positive"`, `"negative"`,
 * `"zero"`, or `"unknown"` (null/invalid). Keeps color logic out of components
 * and free of float comparisons.
 */
export function signTone(
  raw: string | null | undefined,
): "positive" | "negative" | "zero" | "unknown" {
  if (raw == null) {
    return "unknown";
  }
  const sign = decimalSign(raw);
  if (sign === null) {
    return "unknown";
  }
  return sign > 0 ? "positive" : sign < 0 ? "negative" : "zero";
}
