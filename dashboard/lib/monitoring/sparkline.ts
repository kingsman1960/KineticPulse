/** Client-side HR ring for the dashboard sparkline. Backend only ships latest_bpm. */

export type VitalSample = {
  t: number;
  bpm: number | null;
};

export const VITAL_WINDOW = 60; // ~3 min at 3 s poll

export function appendVitalSample(
  history: VitalSample[],
  sample: VitalSample,
  max = VITAL_WINDOW,
): VitalSample[] {
  const last = history[history.length - 1];
  if (last && last.t === sample.t) return history;
  return history.concat(sample).slice(-max);
}

export function bpmRange(values: number[], minSpan = 20, pad = 6): [number, number] {
  if (!values.length) return [40, 160];
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (hi - lo < minSpan) {
    const mid = (lo + hi) / 2;
    lo = mid - minSpan / 2;
    hi = mid + minSpan / 2;
  }
  return [Math.max(20, lo - pad), hi + pad];
}

export function polyline(
  values: Array<number | null>,
  width: number,
  height: number,
  min: number,
  max: number,
): string {
  const n = values.length;
  if (!n) return "";
  const span = Math.max(1e-6, max - min);
  return values
    .map((v, i) => {
      if (v == null || !Number.isFinite(v)) return null;
      const x = n === 1 ? 0 : (i / (n - 1)) * width;
      const y = height - ((Math.min(max, Math.max(min, v)) - min) / span) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .filter((p): p is string => p !== null)
    .join(" ");
}
