/**
 * Axios already prefixes requests with `/api/v1`. Reader contracts expose
 * browser-facing asset URLs with that prefix, so passing them through as-is
 * would request `/api/v1/api/v1/...` and create a 404/reporting storm.
 */
export function normalizeApiAssetUrl(fileUrl: string): string {
  return fileUrl.startsWith('/api/v1/')
    ? fileUrl.slice('/api/v1'.length)
    : fileUrl
}
