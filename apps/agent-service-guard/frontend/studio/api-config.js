/**
 * Optional: set API root for Agent Guard backend (same-origin recommended).
 * Nginx example: proxy /services /orders /dashboard -> upstream.
 * Empty string = relative URLs from current host.
 *
 * Cross-origin API (discouraged): set `KARMAPAY_STUDIO_API_ORIGIN_ALLOWLIST` to a
 * comma-separated list of exact origins (e.g. "https://api.example.com") that must
 * match the API base URL origin. Otherwise requests are blocked in the client.
 */
window.KARMAPAY_STUDIO_API_BASE =
  typeof window.KARMAPAY_STUDIO_API_BASE === "string" ? window.KARMAPAY_STUDIO_API_BASE : "";
