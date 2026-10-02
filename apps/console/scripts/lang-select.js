/* Karma Console — custom language selector.
 *
 * Native <select> popups are rendered by the OS, so their white background
 * cannot be styled reliably. This small component keeps the original select as
 * the source of truth, replaces its visible presentation with a dark button
 * and menu, and dispatches the same "change" event when an option is chosen.
 * Existing i18n bindings therefore keep working unchanged.
 */
(function () {
  "use strict";

  function selectedLabel(select) {
    return select.options[select.selectedIndex]
      ? select.options[select.selectedIndex].textContent
      : "";
  }

  function buildMenu(select, menu) {
    menu.innerHTML = "";
    Array.prototype.forEach.call(select.options, function (option) {
      var item = document.createElement("button");
      item.type = "button";
      item.className = "lang-select-option";
      item.textContent = option.textContent;
      item.setAttribute("data-value", option.value);
      if (select.value === option.value) item.classList.add("active");
      menu.appendChild(item);
    });
  }

  function sync(select, wrap, button, menu) {
    buildMenu(select, menu);
    button.querySelector(".lang-select-value").textContent = selectedLabel(select);
    Array.prototype.forEach.call(menu.children, function (item) {
      item.classList.toggle("active", item.getAttribute("data-value") === select.value);
    });
  }

  function closeAll() {
    Array.prototype.forEach.call(
      document.querySelectorAll(".lang-select-wrap.open"),
      function (wrap) {
        wrap.classList.remove("open");
      }
    );
  }

  function init(select) {
    if (select.getAttribute("data-lang-select")) return;
    select.setAttribute("data-lang-select", "1");

    var wrap = document.createElement("div");
    wrap.className = "lang-select-wrap";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);

    var button = document.createElement("button");
    button.type = "button";
    button.className = "lang-select-button";
    button.setAttribute("aria-haspopup", "listbox");

    var value = document.createElement("span");
    value.className = "lang-select-value";
    var caret = document.createElement("span");
    caret.className = "lang-select-caret";
    caret.textContent = "▾";
    button.appendChild(value);
    button.appendChild(caret);
    wrap.insertBefore(button, select);

    var menu = document.createElement("div");
    menu.className = "lang-select-menu";
    menu.setAttribute("role", "listbox");
    wrap.appendChild(menu);

    function refresh() {
      sync(select, wrap, button, menu);
    }

    menu.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      var item = event.target.closest(".lang-select-option");
      if (!item) return;
      select.value = item.getAttribute("data-value");
      select.dispatchEvent(new Event("change", { bubbles: true }));
      wrap.classList.remove("open");
    });

    button.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      var wasOpen = wrap.classList.contains("open");
      closeAll();
      if (!wasOpen) wrap.classList.add("open");
    });

    select.addEventListener("change", refresh);

    var observer = new MutationObserver(refresh);
    observer.observe(select, {
      attributes: true,
      childList: true,
      subtree: false,
    });

    document.addEventListener("click", function (event) {
      if (!wrap.contains(event.target)) wrap.classList.remove("open");
    });

    refresh();
  }

  function initAll() {
    Array.prototype.forEach.call(
      document.querySelectorAll("select.lang-select"),
      init
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();
