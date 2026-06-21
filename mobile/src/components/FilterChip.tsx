import { Pressable, StyleSheet, Text, View, type PressableProps, type ViewStyle } from "react-native";

import { colors, radius, spacing, typography } from "@/theme";

type Props = PressableProps & {
  active?: boolean;
  label: string;
};

export function FilterChip({ active, label, style, ...rest }: Props) {
  return (
    <Pressable
      style={[
        styles.chip,
        active ? styles.chipActive : styles.chipInactive,
        style as ViewStyle | undefined
      ]}
      {...rest}
    >
      <Text style={[styles.label, active ? styles.labelActive : styles.labelInactive]}>
        {label.toUpperCase()}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    paddingHorizontal: 14,
    paddingVertical: spacing.xs,
    borderRadius: radius.none,
    borderWidth: 1
  },
  chipInactive: {
    backgroundColor: colors.canvas,
    borderColor: colors.hairlineStrong
  },
  chipActive: {
    backgroundColor: colors.ink,
    borderColor: colors.ink
  },
  label: {
    ...typography.caption
  },
  labelInactive: {
    color: colors.ink
  },
  labelActive: {
    color: colors.onDark
  }
});
