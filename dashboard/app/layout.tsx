import type { Metadata } from "next";
import React from "react";

export const metadata: Metadata = {
  title: "KineticPulse Caregiver Dashboard",
  description: "Live emergency streams and incident status"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "Inter, Arial, sans-serif", background: "#0f172a", color: "#e2e8f0" }}>
        {children}
      </body>
    </html>
  );
}
