/* Karma Console — background globe visual.
 *
 * The globe is a pre-rendered cyberpunk earth image that is centred behind the
 * console shell. It intentionally has no WebGL dependency, which makes the
 * visual deterministic across devices and browsers.
 */
(function () {
  "use strict";

  var container = document.getElementById("bgGlobe");
  if (!container) return;

  var image = document.createElement("img");
  image.className = "globe-image";
  image.setAttribute("aria-hidden", "true");
  image.alt = "";
  image.src =
    container.getAttribute("data-image") ||
    "../../assets/globe-cyber.png?v=0dbea9890ce3";
  container.appendChild(image);
})();
