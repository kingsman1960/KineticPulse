import { describe, expect, it } from "vitest";
import { mapMockScenario } from "../lib/monitoring/mockMonitoringAdapter";

describe("mock monitoring adapter", () => {
  it("maps a mock payload into the normalized UI model", () => {
    const model = mapMockScenario("normal");

    expect(model.subjectId).toBe("resident-001");
    expect(model.system.connection).toBe("connected");
    expect(model.sensor.connection).toBe("connected");
    expect(model.heartRate).toEqual({ bpm: 72, status: "normal" });
    expect(model.motion.state).toBe("resting");
    expect(model.vision.state).toBe("stand");
    expect(model.fall).toEqual({ confidence: 0, detected: false });
    expect(model.emergency.level).toBe("none");
    expect(model.recentEvents[0].timestampMs).toBeGreaterThanOrEqual(model.recentEvents[1].timestampMs);
  });
});
