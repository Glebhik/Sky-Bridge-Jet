import { describe, expect, it } from "vitest";
import {
  decimalToMinorUnits,
  minorUnitsToDecimal,
} from "@/lib/operator/offers";

describe("operator offer money helpers", () => {
  it.each([
    ["0", 0],
    ["1", 100],
    ["1.2", 120],
    ["1.23", 123],
    [" 99.01 ", 9901],
  ])("converts %s without floating-point authority", (input, expected) => {
    expect(decimalToMinorUnits(input as string)).toBe(expected);
  });
  it.each(["", "-1", "1.234", "1e2", "NaN", "10000000000001"])(
    "rejects invalid value %s",
    (input) => {
      expect(decimalToMinorUnits(input)).toBeNull();
    },
  );
  it("round-trips integer minor units for editing", () => {
    expect(minorUnitsToDecimal(12345)).toBe("123.45");
  });
});
