export type CopyMode = "simple" | "professional";
export type PageGuidancePreference = "on" | "off";
export type ExperiencePreferences = {
  copyMode: CopyMode;
  pageGuidance: PageGuidancePreference;
};

export const DEFAULT_EXPERIENCE_PREFERENCES: ExperiencePreferences = {
  copyMode: "simple",
  pageGuidance: "on",
};

const copyModeKey = (memberId: string) =>
  `operations-ai:copy-mode:${memberId}`;
const guidanceKey = (memberId: string) =>
  `operations-ai:page-guidance:${memberId}`;

export function readExperiencePreferences(
  storage: Pick<Storage, "getItem">,
  memberId: string,
): ExperiencePreferences {
  try {
    const copyMode = storage.getItem(copyModeKey(memberId));
    const pageGuidance = storage.getItem(guidanceKey(memberId));
    return {
      copyMode: copyMode === "professional" ? "professional" : "simple",
      pageGuidance: pageGuidance === "off" ? "off" : "on",
    };
  } catch {
    return DEFAULT_EXPERIENCE_PREFERENCES;
  }
}

export function writeCopyMode(
  storage: Pick<Storage, "setItem">,
  memberId: string,
  mode: CopyMode,
): void {
  try {
    storage.setItem(copyModeKey(memberId), mode);
  } catch {
    // Display preferences are optional; business workflows continue.
  }
}

export function writePageGuidance(
  storage: Pick<Storage, "setItem">,
  memberId: string,
  preference: PageGuidancePreference,
): void {
  try {
    storage.setItem(guidanceKey(memberId), preference);
  } catch {
    // Display preferences are optional; business workflows continue.
  }
}

export function clearExperiencePreferences(
  storage: Pick<Storage, "key" | "length" | "removeItem">,
): void {
  const keys: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (
      key?.startsWith("operations-ai:copy-mode:")
      || key?.startsWith("operations-ai:page-guidance:")
    ) {
      keys.push(key);
    }
  }
  for (const key of keys) storage.removeItem(key);
}
