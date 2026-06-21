import { Pressable, StyleSheet, Text, type PressableProps, type TextStyle, type ViewStyle } from "react-native";

import { colors, radius, spacing, typography } from "@/theme";

type Variant = "primary" | "secondary" | "secondaryOnDark";

type Props = PressableProps & {
  label: string;
  variant?: Variant;
};

export function Button({ label, variant = "primary", disabled, style, ...rest }: Props) {
  const variantStyle = styles[variant];
  const pressedStyle = variant === "primary" ? styles.primaryPressed : styles.secondaryPressed;

  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      style={({ pressed }) => [
        styles.base,
        variantStyle,
        disabled && styles.disabled,
        pressed && !disabled && pressedStyle,
        style as ViewStyle
      ]}
      {...rest}
    >
      <Text
        style={[
          styles.label,
          variant === "primary" ? styles.labelPrimary : variant === "secondaryOnDark" ? styles.labelOnDark : styles.labelSecondary,
          disabled && styles.labelDisabled
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

type TextLinkProps = PressableProps & {
  label: string;
  onDark?: boolean;
};

export function TextLink({ label, onDark, style, ...rest }: TextLinkProps) {
  return (
    <Pressable accessibilityRole="link" style={style as ViewStyle} {...rest}>
      <Text style={[styles.textLink, onDark && styles.textLinkOnDark]}>
        {label.toUpperCase()} ›
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    minHeight: 48,
    paddingHorizontal: 32,
    paddingVertical: 14,
    borderRadius: radius.none,
    alignItems: "center",
    justifyContent: "center"
  },
  primary: {
    backgroundColor: colors.primary
  },
  primaryPressed: {
    backgroundColor: colors.primaryActive
  },
  secondary: {
    backgroundColor: colors.canvas,
    borderWidth: 1,
    borderColor: colors.hairlineStrong
  },
  secondaryOnDark: {
    backgroundColor: "transparent",
    borderWidth: 1,
    borderColor: colors.onDark
  },
  secondaryPressed: {
    opacity: 0.88
  },
  disabled: {
    backgroundColor: colors.primaryDisabled,
    borderColor: colors.primaryDisabled
  },
  label: {
    ...typography.button
  },
  labelPrimary: {
    color: colors.onPrimary
  },
  labelSecondary: {
    color: colors.ink
  },
  labelOnDark: {
    color: colors.onDark
  },
  labelDisabled: {
    color: colors.muted
  },
  textLink: {
    ...typography.labelUppercase,
    color: colors.ink
  },
  textLinkOnDark: {
    color: colors.onDark
  }
});
