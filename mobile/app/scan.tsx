import { CameraView, useCameraPermissions } from "expo-camera";
import { router } from "expo-router";
import { useCallback, useState } from "react";
import { Alert, StyleSheet, Text, View } from "react-native";

import { Button } from "@/components/Button";
import { parseConfigQrPayload } from "@/lib/configQr";
import { saveSettings } from "@/storage/settings";
import { colors, spacing, typography } from "@/theme";

export default function ScanSettingsScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const [scanned, setScanned] = useState(false);

  const onBarcode = useCallback(
    async ({ data }: { data: string }) => {
      if (scanned) return;
      const settings = parseConfigQrPayload(data);
      if (!settings) {
        Alert.alert("Invalid QR", "This code is not a KineticPulse caregiver config.");
        return;
      }
      setScanned(true);
      try {
        await saveSettings(settings);
        Alert.alert("Connected", "Server settings saved from QR.", [
          { text: "OK", onPress: () => router.replace("/") }
        ]);
      } catch (e) {
        setScanned(false);
        Alert.alert("Error", e instanceof Error ? e.message : String(e));
      }
    },
    [scanned]
  );

  if (!permission) {
    return (
      <View style={styles.center}>
        <Text style={styles.body}>Checking camera permission…</Text>
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={styles.center}>
        <Text style={styles.title}>Camera access</Text>
        <Text style={styles.body}>
          Allow camera access to scan the setup QR from the Jetson deploy handoff.
        </Text>
        <Button label="Allow camera" onPress={requestPermission} style={styles.button} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.help}>
        Scan the QR on the Jetson (`deploy/handoff/caregiver-qr.png`) or shown after `./bootstrap.sh`.
      </Text>
      <View style={styles.cameraWrap}>
        <CameraView
          style={styles.camera}
          facing="back"
          barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
          onBarcodeScanned={scanned ? undefined : onBarcode}
        />
      </View>
      {scanned ? (
        <Text style={styles.body}>Saving settings…</Text>
      ) : (
        <Button
          label="Enter manually"
          variant="secondary"
          onPress={() => router.back()}
          style={styles.button}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: spacing.lg,
    gap: spacing.md,
    backgroundColor: colors.canvas
  },
  center: {
    flex: 1,
    padding: spacing.lg,
    justifyContent: "center",
    gap: spacing.md,
    backgroundColor: colors.canvas
  },
  help: {
    ...typography.bodySm,
    color: colors.body
  },
  cameraWrap: {
    flex: 1,
    minHeight: 280,
    borderWidth: 1,
    borderColor: colors.hairline,
    overflow: "hidden"
  },
  camera: {
    flex: 1
  },
  title: {
    ...typography.titleMd,
    color: colors.ink
  },
  body: {
    ...typography.bodySm,
    color: colors.body
  },
  button: {
    alignSelf: "stretch"
  }
});
