import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import MonitoringDashboard from "../app/components/MonitoringDashboard";
import { mapMockScenario } from "../lib/monitoring/mockMonitoringAdapter";

describe("MonitoringDashboard", () => {
  it("renders the main dashboard from a normalized model", () => {
    render(
      <MonitoringDashboard
        model={mapMockScenario("normal")}
        loading={false}
        error={null}
        scenario="normal"
        onScenarioChange={vi.fn()}
        showScenarioSelector
      />
    );

    expect(screen.getByRole("heading", { name: /always aware/i })).toBeInTheDocument();
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("BPM")).toBeInTheDocument();
    expect(screen.getByText("ESP32 connected")).toBeInTheDocument();
    expect(screen.getByText("Recent events")).toBeInTheDocument();
    expect(screen.getByLabelText("Development scenario selector")).toBeInTheDocument();
  });
});
