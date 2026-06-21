import { StyleSheet, Text, View } from "react-native";

import { colors, spacing, typography } from "@/theme";

type Props = {
  label: string;
  value?: string | number | null;
  last?: boolean;
};

export function SpecRow({ label, value, last }: Props) {
  return (
    <View style={[styles.row, !last && styles.rowBorder]}>
      <Text style={styles.label}>{label.toUpperCase()}</Text>
      <Text style={styles.value}>{value ?? "—"}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    paddingVertical: spacing.md
  },
  rowBorder: {
    borderBottomWidth: 1,
    borderBottomColor: colors.hairline
  },
  label: {
    ...typography.labelUppercase,
    color: colors.muted,
    marginBottom: spacing.xs
  },
  value: {
    ...typography.displaySm,
    fontSize: 18,
    lineHeight: 25,
    color: colors.ink
  }
});
