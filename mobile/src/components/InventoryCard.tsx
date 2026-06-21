import { forwardRef, type ReactNode } from "react";
import { Pressable, StyleSheet, Text, View, type PressableProps, type ViewStyle } from "react-native";

import { TextLink } from "@/components/Button";
import { colors, radius, spacing, typography } from "@/theme";

type Props = PressableProps & {
  title: string;
  lines?: string[];
  ctaLabel?: string;
  headerRight?: ReactNode;
  footer?: ReactNode;
};

export const InventoryCard = forwardRef<View, Props>(function InventoryCard(
  { title, lines = [], ctaLabel = "Open live feed", headerRight, footer, style, ...rest },
  ref
) {
  return (
    <Pressable ref={ref} style={[styles.card, style as ViewStyle | undefined]} {...rest}>
      <View style={styles.photoPlate}>{headerRight}</View>
      <View style={styles.body}>
        <Text style={styles.title}>{title}</Text>
        {lines.map((line) => (
          <Text key={line} style={styles.line}>
            {line}
          </Text>
        ))}
        {footer}
        <TextLink label={ctaLabel} style={styles.cta} pointerEvents="none" />
      </View>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.canvas,
    borderRadius: radius.none,
    borderWidth: 1,
    borderColor: colors.hairline,
    marginBottom: spacing.md
  },
  photoPlate: {
    backgroundColor: colors.surfaceCard,
    minHeight: 56,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "flex-end"
  },
  body: {
    padding: spacing.md
  },
  title: {
    ...typography.titleSm,
    color: colors.ink,
    marginBottom: spacing.xs
  },
  line: {
    ...typography.bodySm,
    color: colors.body,
    marginBottom: 2
  },
  cta: {
    marginTop: spacing.sm,
    alignSelf: "flex-start"
  }
});
