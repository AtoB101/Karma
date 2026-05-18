/**
 * Sepolia / public testnet beta banner (P0-5).
 * Enable: window.KARMA_TESTNET_BETA = true before loading this script.
 */
(function () {
  if (!window.KARMA_TESTNET_BETA) return;
  var el = document.createElement("div");
  el.className = "banner testnet-beta";
  el.setAttribute("role", "status");
  el.innerHTML =
    "<strong>Sepolia Testnet Beta</strong> — Not mainnet production. " +
    '<a href="https://github.com/AtoB101/Karma/blob/main/docs/public-testing/PUBLIC_TESTNET_GO_LIVE-zh.md" ' +
    'target="_blank" rel="noopener">Go-live checklist</a>';
  var main = document.querySelector("main");
  if (main) main.insertBefore(el, main.firstChild);
  else document.body.insertBefore(el, document.body.firstChild);
})();
