import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";

import { AppSettings, DEFAULT_SETTINGS } from "@/types/session";

const SETTINGS_KEY = "kp.settings.v1";
const TOKEN_KEY = "kp.caregiver_token";

export async function loadSettings(): Promise<AppSettings> {
  const raw = await AsyncStorage.getItem(SETTINGS_KEY);
  let base: AppSettings = { ...DEFAULT_SETTINGS };
  if (raw) {
    try {
      base = { ...base, ...JSON.parse(raw) };
    } catch {
      // ignore corrupt storage
    }
  }
  const token = await SecureStore.getItemAsync(TOKEN_KEY);
  if (token !== null) {
    base.caregiverToken = token;
  }
  return base;
}

export async function saveSettings(settings: AppSettings): Promise<void> {
  const { caregiverToken, ...rest } = settings;
  await AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify(rest));
  if (caregiverToken) {
    await SecureStore.setItemAsync(TOKEN_KEY, caregiverToken);
  } else {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
  }
}
