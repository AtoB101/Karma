/**
 * Karma Console — nav cleanup (P2): 下线旧页 + 折叠二级入口。
 *
 * - Removes the legacy MVVS dashboard link (下线).
 * - Folds Evidence / Disputes / Verifier Network into an "高级 ▾" dropdown,
 *   matching by href so it works across pages whose nav text may differ.
 */
(function (global) {
  var REMOVE_HREFS = ["mvvs-dashboard"];
  var FOLD_HREFS = ["evidence", "disputes", "verifier-explorer"];

  function matches(a, patterns) {
    var href = a.getAttribute("href") || "";
    return patterns.some(function (p) {
      return href.indexOf(p) >= 0;
    });
  }

  function init() {
    var nav = document.querySelector("header.top nav");
    if (!nav) return;

    // 1. 下线旧页
    Array.prototype.slice.call(nav.querySelectorAll("a")).forEach(function (a) {
      if (matches(a, REMOVE_HREFS)) a.remove();
    });

    // 2. 折叠 evidence / disputes / verifier-explorer 到「高级」
    var folded = Array.prototype.slice
      .call(nav.querySelectorAll("a"))
      .filter(function (a) {
        return matches(a, FOLD_HREFS);
      });
    if (!folded.length) return;

    var dd = document.createElement("span");
    dd.className = "nav-fold";
    var toggle = document.createElement("span");
    toggle.className = "nav-fold-toggle";
    toggle.textContent = "高级 ▾";
    var menu = document.createElement("span");
    menu.className = "nav-fold-menu";
    folded.forEach(function (a) {
      a.classList.add("nav-fold-item");
      menu.appendChild(a);
    });
    dd.appendChild(toggle);
    dd.appendChild(menu);

    var first = folded[0];
    first.parentNode.insertBefore(dd, first);

    toggle.addEventListener("click", function (e) {
      e.stopPropagation();
      dd.classList.toggle("open");
    });
    document.addEventListener("click", function () {
      dd.classList.remove("open");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
