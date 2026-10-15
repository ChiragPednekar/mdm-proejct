import { describe, expect, it } from "vitest";
import { ApiError, qs } from "../lib/api";
import { money, pct, prob } from "../lib/format";

describe("qs", () => {
  it("skips empty values and repeats arrays", () => {
    expect(qs({ a: 1, b: "", c: null, d: undefined, e: ["x", "y"], f: false })).toBe("?a=1&e=x&e=y&f=false");
    expect(qs({})).toBe("");
  });
});

describe("format", () => {
  it("formats currency, ratios and probabilities", () => {
    expect(money(1234567)).toContain("12,34,567");
    expect(money(null)).toBe("—");
    expect(pct(0.3684)).toBe("36.8%");
    expect(prob(0.06712)).toBe("6.7%");
  });
});

describe("ApiError", () => {
  it("maps validation details to field errors", () => {
    const e = new ApiError(422, "validation_error", "bad", [{ field: "email", message: "invalid" }]);
    expect(e.fieldErrors()).toEqual({ email: "invalid" });
    expect(new ApiError(409, "conflict", "x").fieldErrors()).toEqual({});
  });
});
