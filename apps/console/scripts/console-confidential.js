/**
 * Karma Console — Enterprise confidentiality view (P2, enterprise 默认私有).
 *
 * When the active identity role profile has `visibility === "private"` (enterprise),
 * this module:
 *   - adds a `confidential` class to <body> (CSS masks amount summaries), and
 *   - injects a "涉密 · CONFIDENTIAL" badge.
 *
 * Reacts to `karma-profiles-loaded` (initial + wallet reconnect) and
 * `karma-profile-switched` (user change) so the state stays correct after
 * console-sync.js polling rewrites the amount elements.
 */
(function (global) {
  var BADGE_ID = "karma-confidential-badge";

  function activeProfile() {
    var s = global.KarmaIdentitySwitcher;
    return s && s.getActiveProfile ? s.getActiveProfile() : null;
  }

  function apply() {
    var p = activeProfile();
    var confidential = !!p && p.visibility === "private";
    document.body.classList.toggle("confidential", confidential);

    var badge = document.getElementById(BADGE_ID);
    if (confidential) {
      if (!badge) {
        badge = document.createElement("div");
        badge.id = BADGE_ID;
        badge.className = "confidential-badge";
        badge.textContent = "🔒 涉密 · CONFIDENTIAL";
        document.body.appendChild(badge);
      }
    } else if (badge) {
      badge.remove();
    }
  }

  global.KarmaConfidential = {
    apply: apply,
    isConfidential: function () {
      return document.body.classList.contains("confidential");
    },
  };

  function init() {
    apply();
    document.addEventListener("karma-profiles-loaded", apply);
    document.addEventListener("karma-profile-switched", apply);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
