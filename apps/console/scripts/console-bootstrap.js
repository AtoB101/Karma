/**
 * Hydrate Karma console globals from localStorage (after optional config.js).
 */
(function (global) {
  var LS_BASE = "karma_cyber_api_base";
  var LS_KEY = "karma_cyber_api_key";
  var LS_ID = "karma_cyber_identity_id";

  function hydrateFromStorage() {
    try {
      if (global.KARMA_API_BASE === undefined || global.KARMA_API_BASE === null) {
        var b = localStorage.getItem(LS_BASE);
        if (b && !isForeignLocalhost(b)) global.KARMA_API_BASE = b;
      }
      if (!global.KARMA_API_KEY) {
        var k = sessionStorage.getItem(LS_KEY) || localStorage.getItem(LS_KEY);
        if (k) global.KARMA_API_KEY = k;
      }
      if (!global.KARMA_IDENTITY_ID) {
        var i = sessionStorage.getItem(LS_ID) || localStorage.getItem(LS_ID);
        if (i) global.KARMA_IDENTITY_ID = i;
      }
    } catch (_) {}
    if (global.KARMA_API_BASE === undefined || global.KARMA_API_BASE === null) {
      global.KARMA_API_BASE = "http://127.0.0.1:8000";
    }
  }

  /**
   * A base persisted during local development must not be reused once the console is
   * served from a real host, otherwise every API call hits the visitor's own machine.
   */
  function isForeignLocalhost(base) {
    try {
      var pageHost = global.location.hostname;
      if (pageHost === "localhost" || pageHost === "127.0.0.1" || pageHost === "::1") return false;
      var host = new URL(base, global.location.href).hostname;
      return host === "localhost" || host === "127.0.0.1" || host === "::1" || host === "0.0.0.0";
    } catch (_) {
      return false;
    }
  }

  hydrateFromStorage();
  global.KarmaConsoleBootstrap = { hydrateFromStorage: hydrateFromStorage };
})(window);
