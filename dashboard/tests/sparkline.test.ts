import { describe, expect, it } from "vitest";
import { appendVitalSample, bpmRange, polyline } from "../lib/monitoring/sparkline";

describe("vital sparkline", () => {
  it("dedupes the same timestamp and caps the window", () => {
    const once = appendVitalSample([], { t: 1, bpm: 72 });
    expect(appendVitalSample(once, { t: 1, bpm: 80 })).toEqual(once);
    const filled = Array.from({ length: 5 }, (_, i) => ({ t: i, bpm: 70 + i }));
    const capped = filled.reduce((h, s) => appendVitalSample(h, s, 3), [] as typeof filled);
    expect(capped.map((s) => s.t)).toEqual([2, 3, 4]);
  });

  it("autoscales a tight resting band instead of flattening against 40–160", () => {
    const [lo, hi] = bpmRange([70, 72, 74]);
    expect(hi - lo).toBeGreaterThanOrEqual(20);
    expect(lo).toBeLessThan(70);
    expect(hi).toBeGreaterThan(74);
  });

  it("maps bpm into svg points", () => {
    expect(polyline([40, 160], 100, 50, 40, 160)).toBe("0.0,50.0 100.0,0.0");
    expect(polyline([], 100, 50, 40, 160)).toBe("");
  });
});
