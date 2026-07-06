import { describe, it, expect } from "vitest";
import { usd, usdCompact, usdTip, pct, value } from "./format";

describe("usd", () => {
  it("formats positive with 3 decimals by default", () => {
    expect(usd(1234.5)).toBe("$1,234.500");
  });
  it("clamps tiny CE negative floats to zero", () => {
    expect(usd(-0.00001)).toBe("$0.000");
  });
  it("puts the sign before the dollar for real negatives", () => {
    expect(usd(-12.34, 2)).toBe("-$12.34");
  });
});

describe("usdCompact", () => {
  it("compacts thousands and millions", () => {
    expect(usdCompact(1500)).toBe("$1.5k");
    expect(usdCompact(2_500_000)).toBe("$2.5M");
  });
  it("compacts negatives symmetrically", () => {
    expect(usdCompact(-1500)).toBe("-$1.5k");
  });
});

describe("usdTip", () => {
  it("keeps cents in tooltips", () => {
    expect(usdTip(45.678)).toBe("$45.68");
  });
});

describe("pct/value", () => {
  it("signs percentages", () => {
    expect(pct(3.14159)).toBe("+3.1%");
    expect(pct(-2)).toBe("-2.0%");
  });
  it("value falls back on null/undefined", () => {
    expect(value(null, 7)).toBe(7);
    expect(value("3")).toBe(3);
  });
});
