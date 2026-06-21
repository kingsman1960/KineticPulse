import { StyleSheet, Text, View, type ViewProps } from "react-native";

import { colors, spacing, typography } from "@/theme";

type Props = ViewProps & {
  title: string;
  subtitle?: string;
  onDark?: boolean;
};

export function HeroBand({ title, subtitle, onDark = true, style, children, ...rest }: Props) {
  return (
    <View style={[styles.band, onDark ? styles.bandDark : styles.bandLight, style]} {...rest}>
      <Text style={[styles.title, onDark ? styles.titleDark : styles.titleLight]}>{title}</Text>
      {subtitle ? (
        <Text style={[styles.subtitle, onDark ? styles.subtitleDark : styles.subtitleLight]}>{subtitle}</Text>
      ) : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  band: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xl
  },
  bandDark: {
    backgroundColor: colors.surfaceDark
  },
  bandLight: {
    backgroundColor: colors.canvas,
    borderBottomWidth: 1,
    borderBottomColor: colors.hairline
  },
  title: {
    ...typography.displaySm
  },
  titleDark: {
    color: colors.onDark
  },
  titleLight: {
    color: colors.ink
  },
  subtitle: {
    ...typography.bodyMd,
    marginTop: spacing.sm
  },
  subtitleDark: {
    color: colors.onDarkSoft
  },
  subtitleLight: {
    color: colors.body
  }
});
