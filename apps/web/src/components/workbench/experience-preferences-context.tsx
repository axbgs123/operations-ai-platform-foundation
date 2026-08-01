"use client";

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useSyncExternalStore,
} from "react";

import {
  readExperiencePreferences,
  writeCopyMode,
  writePageGuidance,
  type CopyMode,
  type ExperiencePreferences,
  type PageGuidancePreference,
} from "./experience-preferences";

export type ExperiencePreferenceContextValue = ExperiencePreferences & {
  setCopyMode: (mode: CopyMode) => void;
  setPageGuidance: (preference: PageGuidancePreference) => void;
};

const ExperiencePreferenceContext =
  createContext<ExperiencePreferenceContextValue | null>(null);

export function ExperiencePreferencesProvider({
  memberId,
  children,
}: {
  memberId: string;
  children: ReactNode;
}) {
  const eventName = `operations-ai:experience-change:${memberId}`;
  const subscribe = useCallback((notify: () => void) => {
    const onStorage = (event: StorageEvent) => {
      if (event.key?.endsWith(`:${memberId}`)) notify();
    };
    window.addEventListener("storage", onStorage);
    window.addEventListener(eventName, notify);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(eventName, notify);
    };
  }, [eventName, memberId]);
  const snapshot = useCallback(() => {
    const value = readExperiencePreferences(window.localStorage, memberId);
    return `${value.copyMode}|${value.pageGuidance}`;
  }, [memberId]);
  const serialized = useSyncExternalStore(
    subscribe,
    snapshot,
    () => "simple|on",
  );
  const [copyMode, pageGuidance] = serialized.split("|") as [
    CopyMode,
    PageGuidancePreference,
  ];
  const preferences = { copyMode, pageGuidance };
  const notify = () => window.dispatchEvent(new Event(eventName));
  return (
    <ExperiencePreferenceContext.Provider value={{
      ...preferences,
      setCopyMode: (mode) => {
        writeCopyMode(window.localStorage, memberId, mode);
        notify();
      },
      setPageGuidance: (preference) => {
        writePageGuidance(window.localStorage, memberId, preference);
        notify();
      },
    }}>
      {children}
    </ExperiencePreferenceContext.Provider>
  );
}

export function useExperiencePreferences(): ExperiencePreferenceContextValue {
  const value = useContext(ExperiencePreferenceContext);
  if (!value) {
    throw new Error("useExperiencePreferences requires ExperiencePreferencesProvider");
  }
  return value;
}

export function useOptionalExperiencePreferences():
  ExperiencePreferenceContextValue | null {
  return useContext(ExperiencePreferenceContext);
}
