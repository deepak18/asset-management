/**
 * Float-free helpers for the Decimal-as-string money model.
 *
 * The backend serializes every monetary/quantity/weight/rate value as a STRING
 * because IEEE-754 `float` cannot represent decimal fractions exactly (0.1 + 0.2
 * != 0.3). We must never route those values through `Number()` for arithmetic we
 * display, or we reintroduce the very rounding error the string encoding avoids.
 *
 * These functions operate purely on the digit strings — parsing, half-up
 * rounding, and power-of-ten scaling are all done by manipulating characters, so
 * a value with 30 significant digits round-trips without precision loss.
 */

/** A decimal split into sign and unpadded integer/fraction digit strings. */
export interface ParsedDecimal {
  negative: boolean;
  int: string; // integer digits, no leading zeros (except a single "0")
  frac: string; // fractional digits, no trailing normalization applied
}

/** Matches the backend's Decimal string shape: optional sign, digits, optional point. */
const DECIMAL_RE = /^[+-]?\d*\.?\d*$/;

/**
 * Parse a backend Decimal string into sign + digit parts, or `null` if the input
 * is not a well-formed decimal (empty, bare sign, or a lone "."). Callers treat
 * `null` as "no value" and render a dash rather than a misleading zero.
 */
export function parseDecimal(raw: string): ParsedDecimal | null {
  const s = raw.trim();
  if (s === "" || s === "." || s === "+" || s === "-" || !DECIMAL_RE.test(s)) {
    return null;
  }
  let negative = false;
  let body = s;
  if (body.startsWith("+")) {
    body = body.slice(1);
  } else if (body.startsWith("-")) {
    negative = true;
    body = body.slice(1);
  }
  const dotIndex = body.indexOf(".");
  const intRaw = dotIndex === -1 ? body : body.slice(0, dotIndex);
  const fracRaw = dotIndex === -1 ? "" : body.slice(dotIndex + 1);
  const int = intRaw.replace(/^0+(?=\d)/, "") || "0";
  return { negative, int, frac: fracRaw };
}

/** Add 1 to a non-negative integer digit string, carrying as needed. */
function incrementDigits(digits: string): string {
  const out = digits.split("");
  for (let i = out.length - 1; i >= 0; i -= 1) {
    if (out[i] === "9") {
      out[i] = "0";
    } else {
      out[i] = String(Number(out[i]) + 1);
      return out.join("");
    }
  }
  return "1" + out.join("");
}

/** True when every digit is zero (used to normalize away a signed zero). */
function isAllZero(int: string, frac: string): boolean {
  return /^0*$/.test(int) && /^0*$/.test(frac);
}

/**
 * Round a decimal string to exactly `dp` fractional digits using half-up
 * rounding, returning a canonical string. Returns `null` for invalid input.
 */
export function roundDecimalString(raw: string, dp: number): string | null {
  const parsed = parseDecimal(raw);
  if (parsed === null) {
    return null;
  }
  let { int, frac } = parsed;
  let { negative } = parsed;

  if (frac.length > dp) {
    const roundUp = (frac.charCodeAt(dp) - 48) >= 5;
    let combined = int + frac.slice(0, dp);
    if (roundUp) {
      combined = incrementDigits(combined);
    }
    const fracOut = dp === 0 ? "" : combined.slice(-dp).padStart(dp, "0");
    const intOut = (dp === 0 ? combined : combined.slice(0, -dp)) || "0";
    int = intOut.replace(/^0+(?=\d)/, "") || "0";
    frac = fracOut;
  } else {
    frac = frac.padEnd(dp, "0");
  }

  if (isAllZero(int, frac)) {
    negative = false; // never render "-0.00"
  }
  const sign = negative ? "-" : "";
  return dp === 0 ? `${sign}${int}` : `${sign}${int}.${frac}`;
}

/**
 * Multiply a decimal string by 10^power by shifting the decimal point — used to
 * turn a weight fraction (0.2531) into a percent (25.31) with no float involved.
 * Negative powers shift left. Returns `null` for invalid input.
 */
export function scaleByPowerOfTen(raw: string, power: number): string | null {
  const parsed = parseDecimal(raw);
  if (parsed === null) {
    return null;
  }
  const { negative, int, frac } = parsed;
  const digits = (int === "0" ? "" : int) + frac;
  // pointPos = index within `digits` where the decimal point sits, measured
  // from the left; the original point is after the integer digits.
  const originalPoint = int === "0" ? 0 : int.length;
  let pointPos = originalPoint + power;

  let working = digits;
  if (pointPos <= 0) {
    // Pad enough leading zeros that the point lands just after the first one,
    // e.g. "5" scaled by 10^-2 → "005" with the point at index 1 → "0.05".
    working = "0".repeat(1 - pointPos) + working;
    pointPos = 1;
  } else if (pointPos >= working.length) {
    working = working + "0".repeat(pointPos - working.length);
  }
  const intPart = working.slice(0, pointPos).replace(/^0+(?=\d)/, "") || "0";
  const fracPart = working.slice(pointPos);
  const sign = negative && !isAllZero(intPart, fracPart) ? "-" : "";
  return fracPart.length > 0 ? `${sign}${intPart}.${fracPart}` : `${sign}${intPart}`;
}

/** Insert thousands separators into a run of integer digits. */
export function groupThousands(intDigits: string): string {
  return intDigits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * Sign of a decimal string: -1 / 0 / 1, or `null` if unparseable. Lets callers
 * pick a color (loss vs. gain) without doing float comparisons.
 */
export function decimalSign(raw: string): -1 | 0 | 1 | null {
  const parsed = parseDecimal(raw);
  if (parsed === null) {
    return null;
  }
  if (isAllZero(parsed.int, parsed.frac)) {
    return 0;
  }
  return parsed.negative ? -1 : 1;
}
