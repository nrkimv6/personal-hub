import type { ExpoDraftBooth } from '$lib/types';

export const EXPO_DRAFT_STORAGE_NAMESPACE = 'expo';

export function buildExpoDraftStorageKey(slug: string) {
  return `${EXPO_DRAFT_STORAGE_NAMESPACE}:${slug}:draft`;
}

export function serializeExpoDraftsForExport(drafts: ExpoDraftBooth[]) {
  return JSON.stringify(
    drafts.map((draft) => ({
      id: draft.name,
      name: draft.name,
      pin: draft.pin
    })),
    null,
    2
  );
}
