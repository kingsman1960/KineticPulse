import { router } from "expo-router";
import { useEffect, useState } from "react";
import { Alert, ScrollView, StyleSheet, Text, View } from "react-native";

import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { loadSettings, saveSettings } from "@/storage/settings";
import { colors, spacing, typography } from "@/theme";
import { AppSettings, DEFAULT_SETTINGS } from "@/types/session";

export default function SettingsScreen() {
  const [form, setForm] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadSettings().then(setForm);
  }, []);

  const update = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const onSave = async () => {
    setSaving(true);
    try {
      await saveSettings(form);
      Alert.alert("Saved", "Server settings updated.");
      router.back();
    } catch (e) {
      Alert.alert("Error", e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.help}>
        Point the app at your KineticPulse signaling server. Use your LAN IP during development
        (e.g. http://192.168.1.10:8787). Production should use HTTPS/WSS.
      </Text>

      <View style={styles.form}>
        <TextField
          label="HTTP base (session list)"
          value={form.signalingHttpBase}
          onChangeText={(v) => update("signalingHttpBase", v)}
          autoCapitalize="none"
          placeholder="http://192.168.1.10:8787"
        />
        <TextField
          label="WebSocket base"
          value={form.signalingWsBase}
          onChangeText={(v) => update("signalingWsBase", v)}
          autoCapitalize="none"
          placeholder="ws://192.168.1.10:8787/ws"
        />
        <TextField
          label="Caregiver token"
          value={form.caregiverToken}
          onChangeText={(v) => update("caregiverToken", v)}
          autoCapitalize="none"
          secureTextEntry
          placeholder="CAREGIVER_SIGNAL_TOKEN"
        />
        <TextField
          label="ICE servers"
          value={form.iceServersText}
          onChangeText={(v) => update("iceServersText", v)}
          autoCapitalize="none"
          multiline
          placeholder={"stun:stun.l.google.com:19302\nturn:turn.example:3478"}
          hint="One URL per line, or a JSON array with username/credential for TURN."
        />
      </View>

      <Button
        label={saving ? "Saving…" : "Save settings"}
        onPress={onSave}
        disabled={saving}
        style={styles.saveButton}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.canvas
  },
  content: {
    padding: spacing.lg,
    gap: spacing.lg
  },
  help: {
    ...typography.bodySm,
    color: colors.body
  },
  form: {
    gap: spacing.lg,
    padding: spacing.lg,
    backgroundColor: colors.surfaceCard,
    borderWidth: 1,
    borderColor: colors.hairline
  },
  saveButton: {
    alignSelf: "stretch"
  }
});
