/**
 * KineticPulse mobile theme — aligned with DESIGN.md (BMW corporate design tokens).
 * BMW Type Next Latin substitute: Inter 700 (display/UI) + Inter 300 (body).
 */

export const colors = {
  primary: "#1c69d4",
  primaryActive: "#0653b6",
  primaryDisabled: "#d6d6d6",
  ink: "#262626",
  body: "#3c3c3c",
  bodyStrong: "#1a1a1a",
  muted: "#6b6b6b",
  mutedSoft: "#9a9a9a",
  hairline: "#e6e6e6",
  hairlineStrong: "#cccccc",
  canvas: "#ffffff",
  surfaceSoft: "#f7f7f7",
  surfaceCard: "#fafafa",
  surfaceStrong: "#ebebeb",
  surfaceDark: "#1a2129",
  surfaceDarkElevated: "#262e38",
  onPrimary: "#ffffff",
  onDark: "#ffffff",
  onDarkSoft: "#bbbbbb",
  success: "#22c55e",
  warning: "#f59e0b",
  error: "#dc2626"
} as const;

export const spacing = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
  section: 80
} as const;

export const radius = {
  none: 0,
  xs: 2,
  sm: 4,
  md: 8,
  lg: 12,
  pill: 9999
} as const;

export const fonts = {
  regular: "Inter_700Bold",
  light: "Inter_300Light",
  caption: "Inter_400Regular"
} as const;

export const typography = {
  displayMd: {
    fontFamily: fonts.regular,
    fontSize: 32,
    lineHeight: 37,
    fontWeight: "700" as const
  },
  displaySm: {
    fontFamily: fonts.regular,
    fontSize: 24,
    lineHeight: 30,
    fontWeight: "700" as const
  },
  titleLg: {
    fontFamily: fonts.regular,
    fontSize: 20,
    lineHeight: 26,
    fontWeight: "700" as const
  },
  titleMd: {
    fontFamily: fonts.regular,
    fontSize: 18,
    lineHeight: 25,
    fontWeight: "700" as const
  },
  titleSm: {
    fontFamily: fonts.regular,
    fontSize: 16,
    lineHeight: 22,
    fontWeight: "700" as const
  },
  bodyMd: {
    fontFamily: fonts.light,
    fontSize: 16,
    lineHeight: 25,
    fontWeight: "300" as const
  },
  bodySm: {
    fontFamily: fonts.light,
    fontSize: 14,
    lineHeight: 22,
    fontWeight: "300" as const
  },
  caption: {
    fontFamily: fonts.caption,
    fontSize: 12,
    lineHeight: 17,
    fontWeight: "400" as const,
    letterSpacing: 0.5
  },
  labelUppercase: {
    fontFamily: fonts.regular,
    fontSize: 13,
    lineHeight: 17,
    fontWeight: "700" as const,
    letterSpacing: 1.5,
    textTransform: "uppercase" as const
  },
  button: {
    fontFamily: fonts.regular,
    fontSize: 14,
    lineHeight: 14,
    fontWeight: "700" as const,
    letterSpacing: 0.5
  },
  navLink: {
    fontFamily: fonts.caption,
    fontSize: 14,
    lineHeight: 20,
    fontWeight: "400" as const,
    letterSpacing: 0.3
  }
} as const;

export function tierSemanticColor(tier?: string): string {
  if (!tier) return colors.muted;
  if (tier.includes("tier_2") || tier.includes("2")) return colors.error;
  if (tier.includes("tier_1") || tier.includes("1")) return colors.warning;
  return colors.muted;
}
