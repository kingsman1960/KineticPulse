import { useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  View
} from "react-native";
import { RTCView } from "react-native-webrtc";

import { useCaregiverPeer } from "@/hooks/useCaregiverPeer";
import { FilterChip } from "@/components/FilterChip";
import { HeroBand } from "@/components/HeroBand";
import { SpecRow } from "@/components/SpecRow";
import { loadSettings } from "@/storage/settings";
import { colors, radius, spacing, tierSemanticColor, typography } from "@/theme";
import { AppSettings } from "@/types/session";

export default function SessionScreen() {
  const params = useLocalSearchParams<{ id: string }>();
  const sessionId = decodeURIComponent(params.id ?? "");
  const [settings, setSettings] = useState<AppSettings | null>(null);

  useEffect(() => {
    loadSettings().then(setSettings);
  }, []);

  const { connectionState, remoteStream, sessionMeta, error } = useCaregiverPeer({
    sessionId,
    settings,
    enabled: Boolean(sessionId && settings)
  });

  const connected = connectionState === "connected";
  const failed = connectionState === "failed";
  const statusColor = connected ? colors.success : failed ? colors.error : colors.warning;
  const tier = sessionMeta?.tier;
  const isCritical = Boolean(tier && (tier.includes("tier_2") || tier.includes("2")));

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <HeroBand
        title={sessionId}
        subtitle={
          connected
            ? "Live feed connected — triage the scene below."
            : "Establishing secure WebRTC connection to Jetson edge node."
        }
      >
        <View style={styles.statusRow}>
          <View style={[styles.statusDot, { backgroundColor: statusColor }]} />
          <Text style={styles.statusText}>Connection · {connectionState}</Text>
          {tier ? (
            <FilterChip active={isCritical} label={tier} pointerEvents="none" style={styles.tierChip} />
          ) : null}
        </View>
      </HeroBand>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <View style={styles.videoSection}>
        <Text style={styles.sectionLabel}>Live video</Text>
        <View style={styles.videoShell}>
          {remoteStream ? (
            <RTCView
              streamURL={remoteStream.toURL()}
              style={styles.video}
              objectFit="cover"
              mirror={false}
            />
          ) : (
            <View style={styles.videoPlaceholder}>
              {connectionState === "connecting" ? (
                <>
                  <ActivityIndicator color={colors.primary} size="large" />
                  <Text style={styles.placeholderText}>Connecting to Jetson feed…</Text>
                </>
              ) : (
                <Text style={styles.placeholderText}>Waiting for remote video track</Text>
              )}
            </View>
          )}
        </View>
      </View>

      <View style={styles.specPanel}>
        <Text style={styles.sectionLabel}>Alert context</Text>
        <SpecRow label="Session" value={sessionId} />
        <SpecRow label="Tier" value={sessionMeta?.tier} />
        <SpecRow label="Scenario" value={sessionMeta?.scenario} />
        <SpecRow label="Subject" value={sessionMeta?.subject_id} />
        <SpecRow label="Location" value={sessionMeta?.location} />
        <SpecRow label="Reason" value={sessionMeta?.reason} />
        <SpecRow label="Detector" value={sessionMeta?.detector_class} />
        <SpecRow label="Action" value={sessionMeta?.action_class} />
        <SpecRow
          label="Action confidence"
          value={sessionMeta?.action_confidence?.toFixed?.(2)}
          last
        />
      </View>

      {tier ? (
        <View style={[styles.ctaBand, { borderLeftColor: tierSemanticColor(tier) }]}>
          <Text style={styles.ctaTitle}>{tier}</Text>
          <Text style={styles.ctaBody}>{sessionMeta?.scenario}</Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.canvas
  },
  content: {
    paddingBottom: spacing.xl
  },
  statusRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginTop: spacing.md,
    flexWrap: "wrap"
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4
  },
  statusText: {
    ...typography.caption,
    color: colors.onDarkSoft,
    flex: 1
  },
  tierChip: {
    marginLeft: "auto"
  },
  error: {
    ...typography.bodySm,
    color: colors.error,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm
  },
  videoSection: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg
  },
  sectionLabel: {
    ...typography.labelUppercase,
    color: colors.muted,
    marginBottom: spacing.sm
  },
  videoShell: {
    borderRadius: radius.none,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.hairline,
    backgroundColor: colors.surfaceCard,
    aspectRatio: 16 / 9
  },
  video: {
    width: "100%",
    height: "100%"
  },
  videoPlaceholder: {
    flex: 1,
    minHeight: 220,
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.md,
    backgroundColor: colors.surfaceCard
  },
  placeholderText: {
    ...typography.bodySm,
    color: colors.muted
  },
  specPanel: {
    marginHorizontal: spacing.lg,
    marginTop: spacing.lg,
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.canvas,
    borderWidth: 1,
    borderColor: colors.hairline
  },
  ctaBand: {
    marginHorizontal: spacing.lg,
    marginTop: spacing.lg,
    padding: spacing.lg,
    backgroundColor: colors.surfaceDark,
    borderLeftWidth: 4
  },
  ctaTitle: {
    ...typography.titleMd,
    color: colors.onDark
  },
  ctaBody: {
    ...typography.bodyMd,
    color: colors.onDarkSoft,
    marginTop: spacing.xs
  }
});
