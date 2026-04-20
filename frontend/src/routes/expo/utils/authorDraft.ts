import type { ExpoDraftBooth, ExpoExportPayload } from '$lib/types';

export const EXPO_DRAFT_STORAGE_NAMESPACE = 'expo';
export const EXPO_EXPORT_VERSION = '2026-04-20';

export function buildExpoDraftStorageKey(slug: string) {
  return `${EXPO_DRAFT_STORAGE_NAMESPACE}:${slug}:draft`;
}

export function buildExpoExportPayload(
  slug: string,
  drafts: ExpoDraftBooth[],
  title: string
): ExpoExportPayload {
  return {
    version: EXPO_EXPORT_VERSION,
    slug,
    title,
    exported_at: new Date().toISOString(),
    booths: drafts.map((draft) => ({
      id: draft.name,
      name: draft.name,
      pin: draft.pin,
    })),
  };
}

export function serializeExpoExportPayload(payload: ExpoExportPayload) {
  return JSON.stringify(payload, null, 2);
}

export async function copyExpoExportPayloadToClipboard(payload: ExpoExportPayload) {
  await navigator.clipboard.writeText(serializeExpoExportPayload(payload));
}

export function serializeExpoDraftsForExport(
  drafts: ExpoDraftBooth[],
  slug = 'expo',
  title = 'Expo Export'
) {
  return serializeExpoExportPayload(buildExpoExportPayload(slug, drafts, title));
}
