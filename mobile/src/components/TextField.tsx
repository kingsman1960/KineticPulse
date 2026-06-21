import { StyleSheet, Text, TextInput, View, type TextInputProps } from "react-native";

import { colors, radius, spacing, typography } from "@/theme";

type Props = TextInputProps & {
  label: string;
  hint?: string;
};

export function TextField({ label, hint, style, ...props }: Props) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label.toUpperCase()}</Text>
      <TextInput
        {...props}
        placeholderTextColor={colors.mutedSoft}
        style={[styles.input, props.multiline && styles.inputMultiline, style]}
      />
      {hint ? <Text style={styles.hint}>{hint}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  field: {
    gap: spacing.xs
  },
  label: {
    ...typography.labelUppercase,
    color: colors.muted
  },
  input: {
    ...typography.bodyMd,
    color: colors.ink,
    backgroundColor: colors.canvas,
    borderWidth: 1,
    borderColor: colors.hairline,
    borderRadius: radius.none,
    minHeight: 48,
    paddingHorizontal: spacing.md,
    paddingVertical: 14
  },
  inputMultiline: {
    minHeight: 96,
    textAlignVertical: "top"
  },
  hint: {
    ...typography.bodySm,
    color: colors.muted
  }
});
