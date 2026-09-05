/**
 * Karma Console — Identity Role Profile Switcher (P2, one card → many identities).
 *
 * Injects a profile <select> into `header.top` on every console page. Lists the
 * current identity's role profiles via `GET /v1/identity/role-profiles` and keeps
 * the active profile_id in sessionStorage (never in long-lived storage).
 *
 * Other modules read the active profile through `KarmaIdentitySwitcher`:
 *   - getActiveProfileId()  -> string profile_id ("" when none selected)
 *   - getActiveProfile()    -> {profile_id, class, visibility, ...} | null
 *   - refresh()             -> re-fetch + re-render the dropdown
 *
 * Emits `karma-profile-switched` (detail: { profile_id }) so sync/actions code can
 * re-filter payments/receiving by the active profile.
 */
(function (global) {
  var SS_PROFILE = "karma_console_active_profile";
  var SS_PROFILES = "karma_console_profiles";

  function api() {
    return global.cyberKarmaApi;
  }

  function identityId() {
    return String(global.KARMA_IDENTITY_ID || "").trim();
  }

  function getActiveProfileId() {
    try {
      return sessionStorage.getItem(SS_PROFILE) || "";
    } catch (_) {
      return "";
    }
  }

  function setActiveProfileId(id) {
    try {
      if (id) sessionStorage.setItem(SS_PROFILE, id);
      else sessionStorage.removeItem(SS_PROFILE);
    } catch (_) {}
  }

  function getActiveProfile() {
    var id = getActiveProfileId();
    if (!id) return null;
    try {
      var raw = sessionStorage.getItem(SS_PROFILES);
      if (raw) {
        var arr = JSON.parse(raw);
        for (var i = 0; i < arr.length; i++) {
          if (arr[i] && arr[i].profile_id === id) return arr[i];
        }
      }
    } catch (_) {}
    return null;
  }

  function label(p) {
    var cls = p["class"] || "";
    var name = p.display_name || p.profile_id || "";
    var lock = p.visibility === "private" ? " 🔒" : "";
    return (name + " · " + cls + lock).trim();
  }

  function render(profiles) {
    var header = document.querySelector("header.top");
    if (!header) return;
    var existing = header.querySelector("[data-identity-switcher]");
    if (existing) existing.remove();

    var wrap = document.createElement("div");
    wrap.className = "identity-switcher";
    wrap.setAttribute("data-identity-switcher", "");

    var sel = document.createElement("select");
    sel.setAttribute("aria-label", "Identity role profile");
    sel.title = "切换身份角色档案";

    var none = document.createElement("option");
    none.value = "";
    none.textContent = profiles.length ? "— 选择身份档案 —" : "（无档案）";
    sel.appendChild(none);

    var active = getActiveProfileId();
    for (var i = 0; i < profiles.length; i++) {
      var p = profiles[i];
      var opt = document.createElement("option");
      opt.value = p.profile_id;
      opt.textContent = label(p);
      if (p.profile_id === active) opt.selected = true;
      sel.appendChild(opt);
    }

    sel.addEventListener("change", function () {
      setActiveProfileId(sel.value);
      document.dispatchEvent(
        new CustomEvent("karma-profile-switched", { detail: { profile_id: sel.value } })
      );
    });

    wrap.appendChild(sel);
    // Insert before the nav so it sits beside the brand on the left.
    var nav = header.querySelector("nav");
    header.insertBefore(wrap, nav || null);
  }

  async function refresh() {
    try {
      var a = api();
      var profiles = [];
      if (a && a.listRoleProfiles) {
        var body = await a.listRoleProfiles(identityId());
        profiles = (body && body.profiles) || [];
      }
      try {
        sessionStorage.setItem(SS_PROFILES, JSON.stringify(profiles));
      } catch (_) {}
      render(profiles);
    } catch (_) {
      render([]);
    }
  }

  global.KarmaIdentitySwitcher = {
    refresh: refresh,
    getActiveProfileId: getActiveProfileId,
    setActiveProfileId: setActiveProfileId,
    getActiveProfile: getActiveProfile,
  };

  function init() {
    refresh();
    // Re-list profiles after wallet connect (identity may have just resolved).
    document.addEventListener("karma-wallet-connected", refresh);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
