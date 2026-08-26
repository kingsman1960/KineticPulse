import { describe, expect, it } from "vitest";
import { mapBackendMonitoringPayload } from "../lib/monitoring/backendMonitoringAdapter";
import { disconnectedMonitoringPayload, pulseLostMonitoringPayload } from "./monitoringFixture";

describe("monitoring edge states", () => {
  it("keeps a disconnected sensor distinct from pulse loss", () => {
    const model = mapBackendMonitoringPayload(disconnectedMonitoringPayload());

    expect(model.system.connection).toBe("degraded");
    expect(model.sensor.connection).toBe("disconnected");
    expect(model.heartRate).toEqual({ bpm: null, status: "unavailable" });
    expect(model.motion.state).toBe("unknown");
    expect(model.emergency.level).toBe("none");
    expect(model.fall.detected).toBe(false);
  });

  it("maps pulse loss into a critical emergency without voice verification", () => {
    const model = mapBackendMonitoringPayload(pulseLostMonitoringPayload());

    expect(model.heartRate.status).toBe("pulse_lost");
    expect(model.emergency.level).toBe("tier_2_cardiac");
    expect(model.fall.detected).toBe(true);
    expect(model.voiceVerification.status).toBe("not_required");
    expect(model.alertDispatch.status).toBe("sent");
  });
});
