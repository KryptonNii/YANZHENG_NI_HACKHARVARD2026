import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { normalizeHealth } from "./api";
import { countryEnrollment, EnrollmentChart } from "./EnrollmentChart";

const plan = [{ p10: 1, p50: 2, p90: 3 }, { p10: 2, p50: 4, p90: 6 }, { p10: 3, p50: 6, p90: 9 }];
const site = { site_id: "S1", country: "US", enrolled: 7, weekly_enrollment: { actual_cumulative: [2, 5, 7], plan } };

describe("weekly observations (URS-011, URS-012)", () => {
  it("excludes the open week without extending the actual curve to the current total", () => {
    const h = normalizeHealth({ clock: { clock_day: 17 }, sites: [site] });
    expect(h.sites[0].enrolled).toBe(7);
    expect(h.sites[0].weekly_enrollment?.actual_cumulative).toEqual([2, 5]);
    render(<EnrollmentChart series={h.sites[0].weekly_enrollment} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/2 complete weeks; last cumulative 5/);
  });

  it("retains gaps and missing arrays; never constructs history from enrolled", () => {
    const h = normalizeHealth({ sites: [
      { ...site, weekly_enrollment: undefined },
      { ...site, weekly_enrollment: { actual_cumulative: [2, null, 7], plan } },
      { ...site, weekly_enrollment: { actual_cumulative: [2, 5, 7], plan: [plan[0]] } },
    ] });
    expect(h.sites[0].weekly_enrollment).toBeNull();
    expect(h.sites[1].weekly_enrollment?.actual_cumulative).toEqual([2, null, 7]);
    expect(h.sites[2].weekly_enrollment?.plan).toEqual([plan[0], null, null]);
    const { container } = render(<EnrollmentChart series={h.sites[1].weekly_enrollment} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/gaps in weekly data/);
    expect(container.querySelectorAll('polyline[stroke="#0f766e"]')).toHaveLength(2);
  });

  it("preserves empty pre-week arrays and zero backup plans", () => {
    const h = normalizeHealth({ clock_day: 3, sites: [site] });
    render(<EnrollmentChart series={h.sites[0].weekly_enrollment} />);
    expect(screen.getByText("No complete weeks yet")).toBeInTheDocument();
    const backup = normalizeHealth({ sites: [{ ...site, backup: true, weekly_enrollment: { actual_cumulative: [0, 3], plan: Array(2).fill({ p10: 0, p50: 0, p90: 0 }) } }] }).sites[0];
    expect(backup.backup).toBe(true);
    expect(backup.weekly_enrollment?.plan[1]?.p90).toBe(0);
    expect(backup.weekly_enrollment?.actual_cumulative[1]).toBe(3);
  });

  it("sums all country sites by week and leaves incomplete membership or weeks unknown", () => {
    const h = normalizeHealth({ countries: [{ country: "US", n_sites: 2 }], sites: [site, { ...site, site_id: "S2", weekly_enrollment: { actual_cumulative: [1, 3], plan } }] });
    const sum = countryEnrollment(h.countries[0], h.sites);
    expect(sum?.actual_cumulative).toEqual([3, 8, null]);
    expect(sum?.plan[1]).toEqual({ p10: 4, p50: 8, p90: 12 });
    expect(countryEnrollment(h.countries[0], h.sites.slice(0, 1))).toBeNull();
    expect(countryEnrollment(h.countries[0], [h.sites[0], { ...h.sites[1], weekly_enrollment: null }])).toBeNull();
  });
});
