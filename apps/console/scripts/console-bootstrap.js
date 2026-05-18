/**
 * Hydrate Karma console globals from localStorage (after optional config.js).
 */
(function (global) {
  var LS_BASE = "karma_cyber_api_base";
  var LS_KEY = "karma_cyber_api_key";
  var LS_ID = "karma_cyber_identity_id";

  function hydrateFromStorage() {
    try {
      if (!global.KARMA_API_BASE) {
        var b = localStorage.getItem(LS_BASE);
        if (b) global.KARMA_API_BASE = b;
      }
      if (!global.KARMA_API_KEY) {
        var k = localStorage.getItem(LS_KEY);
        if (k) global.KARMA_API_KEY = k;
      }
      if (!global.KARMA_IDENTITY_ID) {
        var i = localStorage.getItem(LS_ID);
        if (i) global.KARMA_IDENTITY_ID = i;
      }
    } catch (_) {}
    if (!global.KARMA_API_BASE) global.KARMA_API_BASE = "http://127.0.0.1:8000";
  }

  hydrateFromStorage();
  global.KarmaConsoleBootstrap = { hydrateFromStorage: hydrateFromStorage };
})(window);
