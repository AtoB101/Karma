/**
 * BFF public origin for read-only GET /public/status (no secrets).
 * Deploy: set before app.js, or inject via server-side template.
 */
window.KARMA_BFF_PUBLIC_BASE =
  typeof window.KARMA_BFF_PUBLIC_BASE === "string" ? window.KARMA_BFF_PUBLIC_BASE : "";
