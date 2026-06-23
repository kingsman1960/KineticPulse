import {
  Inter_300Light,
  Inter_400Regular,
  Inter_700Bold,
  useFonts
} from "@expo-google-fonts/inter";
import { registerGlobals } from "react-native-webrtc";

registerGlobals();

import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { colors, typography } from "@/theme";

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const [loaded] = useFonts({
    Inter_300Light,
    Inter_400Regular,
    Inter_700Bold
  });

  useEffect(() => {
    if (loaded) {
      SplashScreen.hideAsync();
    }
  }, [loaded]);

  if (!loaded) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.canvas }}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.canvas },
          headerTintColor: colors.ink,
          headerTitleStyle: { ...typography.titleSm, color: colors.ink },
          headerShadowVisible: false,
          headerBackTitle: "Back",
          contentStyle: { backgroundColor: colors.canvas }
        }}
      >
        <Stack.Screen name="index" options={{ title: "KineticPulse" }} />
        <Stack.Screen name="settings" options={{ title: "Server settings" }} />
        <Stack.Screen name="scan" options={{ title: "Scan setup QR" }} />
        <Stack.Screen
          name="session/[id]"
          options={{
            title: "Live session",
            headerBackTitle: "Sessions"
          }}
        />
      </Stack>
    </SafeAreaProvider>
  );
}
