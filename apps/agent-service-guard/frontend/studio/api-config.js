/**
 * Optional: set API root for Agent Guard backend (same-origin recommended).
 * Nginx example: proxy /services /orders /dashboard -> upstream.
 * Empty string = relative URLs from current host.
 */
window.KARMAPAY_STUDIO_API_BASE =
  typeof window.KARMAPAY_STUDIO_API_BASE === "string" ? window.KARMAPAY_STUDIO_API_BASE : "";
