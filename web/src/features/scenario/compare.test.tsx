import { describe, expect, it } from "vitest";
import { DEFAULT_LEVERS } from "@/app/api/normalize";
import { leverRows } from "./ComparePage";

describe("compare lever table", () => {
  it("lists enrollment speed and added assumed countries, so the lever table explains the metric difference", () => {
    const rows = leverRows(DEFAULT_LEVERS, { ...DEFAULT_LEVERS, enrollment_rate_multiplier: 0.8, added_country_count: 2 });
    expect(rows).toContainEqual({ label: "Enrollment speed", a: "100%", b: "80%", differs: true });
    expect(rows).toContainEqual({ label: "Added countries · planned", a: "0", b: "2", differs: true });
    expect(rows.filter((r) => r.differs).map((r) => r.label)).toEqual(["Enrollment speed", "Added countries · planned"]);
  });

  it("marks no row as different for equal levers", () => {
    expect(leverRows(DEFAULT_LEVERS, { ...DEFAULT_LEVERS }).every((r) => !r.differs)).toBe(true);
  });
});
