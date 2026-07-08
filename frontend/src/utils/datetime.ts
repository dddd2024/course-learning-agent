/** Unified datetime formatting so every page shows the same local time.

The backend now returns timezone-aware ISO 8601 strings (e.g.
``2026-07-08T07:26:00+00:00``). Pages must not call
``new Date(...).toLocaleString()`` ad-hoc — use these helpers instead so the
"8-hour skew" bug (UTC naive datetime + local formatting) cannot recur.
 */

/** Format an ISO timestamp as a local string (24h, no AM/PM). Returns '-' for empty. */
export function formatLocalDateTime(value?: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString(undefined, { hour12: false })
}

/** Format an ISO timestamp as a local date only (YYYY-MM-DD). Returns '-' for empty. */
export function formatLocalDate(value?: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString(undefined)
}

/** Seconds elapsed since an ISO timestamp, floored to 0. Used for "已耗时 N 秒". */
export function secondsSince(value?: string | null): number {
  if (!value) return 0
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return 0
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000))
}
