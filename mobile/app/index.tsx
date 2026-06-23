import { Link, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  View
} from "react-native";

import { fetchSessions, formatTime } from "@/api/sessions";
import { Button } from "@/components/Button";
import { FilterChip } from "@/components/FilterChip";
import { HeroBand } from "@/components/HeroBand";
import { InventoryCard } from "@/components/InventoryCard";
import { loadSettings } from "@/storage/settings";
import { colors, spacing, typography } from "@/theme";
import { AppSettings, SessionSummary } from "@/types/session";

function SessionCard({ session }: { session: SessionSummary }) {
  const meta = session.meta ?? {};
  const tier = meta.tier ?? "n/a";
  const scenario = meta.scenario ?? "n/a";
  const isCritical = tier.includes("tier_2") || tier.includes("2");

  return (
    <Link
      href={{
        pathname: "/session/[id]",
        params: { id: session.session_id }
      }}
      asChild
    >
      <InventoryCard
        title={session.session_id}
        lines={[
          `Status · ${session.status}`,
          `Scenario · ${scenario}`,
          `${meta.subject_id ?? "unknown"} · ${meta.location ?? "unknown"}`,
          `Started ${formatTime(session.created_at_ms)}`
        ]}
        ctaLabel="Open live feed"
        headerRight={
          <FilterChip
            active={isCritical}
            label={tier}
            pointerEvents="none"
          />
        }
      />
    </Link>
  );
}

export default function HomeScreen() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    try {
      const cfg = await loadSettings();
      setSettings(cfg);
      const list = await fetchSessions(cfg);
      setSessions(list);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      refresh();
      const timer = setInterval(() => refresh(), 3000);
      return () => clearInterval(timer);
    }, [refresh])
  );

  return (
    <View style={styles.container}>
      <HeroBand
        title="Caregiver dashboard"
        subtitle="Active emergency sessions from Jetson edge nodes. Select a session to open the live feed."
      />

      <View style={styles.toolbar}>
        <Link href="/settings" asChild>
          <Button label="Server settings" variant="secondary" style={styles.toolbarButton} />
        </Link>
        <Link href="/scan" asChild>
          <Button label="Scan setup QR" variant="secondary" style={styles.toolbarButton} />
        </Link>
        {settings ? (
          <Text style={styles.serverHint} numberOfLines={1}>
            {settings.signalingHttpBase}
          </Text>
        ) : null}
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {loading ? (
        <ActivityIndicator color={colors.primary} style={styles.loader} />
      ) : (
        <FlatList
          data={sessions}
          keyExtractor={(item) => item.session_id}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => refresh(true)}
              tintColor={colors.primary}
            />
          }
          ListHeaderComponent={
            <Text style={styles.sectionLabel}>Active sessions</Text>
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>No active sessions</Text>
              <Text style={styles.emptyBody}>
                When KineticPulse triggers an alert, a session appears here for caregiver triage.
              </Text>
            </View>
          }
          renderItem={({ item }) => <SessionCard session={item} />}
        />
      )}

      <View style={styles.footer}>
        <Text style={styles.footerText}>KineticPulse · Edge-AI fall detection</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.canvas
  },
  toolbar: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.sm,
    backgroundColor: colors.surfaceSoft,
    borderBottomWidth: 1,
    borderBottomColor: colors.hairline
  },
  toolbarButton: {
    alignSelf: "flex-start",
    paddingHorizontal: spacing.lg
  },
  serverHint: {
    ...typography.caption,
    color: colors.muted
  },
  error: {
    ...typography.bodySm,
    color: colors.error,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm
  },
  loader: {
    marginTop: spacing.xl
  },
  list: {
    padding: spacing.lg,
    flexGrow: 1
  },
  sectionLabel: {
    ...typography.labelUppercase,
    color: colors.muted,
    marginBottom: spacing.md
  },
  empty: {
    paddingVertical: spacing.xl,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surfaceCard,
    borderWidth: 1,
    borderColor: colors.hairline
  },
  emptyTitle: {
    ...typography.titleMd,
    color: colors.ink,
    marginBottom: spacing.sm
  },
  emptyBody: {
    ...typography.bodySm,
    color: colors.body
  },
  footer: {
    backgroundColor: colors.surfaceSoft,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.hairline
  },
  footerText: {
    ...typography.bodySm,
    color: colors.muted
  }
});
