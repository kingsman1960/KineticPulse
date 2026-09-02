import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";
import MonitoringDashboard from "../app/components/MonitoringDashboard";
import { mapBackendMonitoringPayload } from "../lib/monitoring/backendMonitoringAdapter";
import { normalMonitoringPayload } from "./monitoringFixture";

describe("MonitoringDashboard", () => {
  it("renders the main dashboard from a normalized model", () => {
    render(
      <MonitoringDashboard
        model={mapBackendMonitoringPayload(normalMonitoringPayload())}
        loading={false}
        error={null}
      />
    );

    expect(screen.getByRole("heading", { name: /always aware/i })).toBeInTheDocument();
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getAllByText("BPM").length).toBeGreaterThan(0);
    expect(screen.getByRole("img", { name: /heart-rate trend/i })).toBeInTheDocument();
    expect(screen.getByText("ESP32 connected")).toBeInTheDocument();
    expect(screen.getByText("Recent events")).toBeInTheDocument();
  });
});
