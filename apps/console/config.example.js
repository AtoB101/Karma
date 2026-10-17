/** Copy to `config.js` (gitignored in production) and set deploy origins. */
window.KARMA_API_BASE = "http://127.0.0.1:8000";
window.KARMA_BFF_PUBLIC_BASE = "http://127.0.0.1:8820";
/** WalletConnect projectId for Bitpie connect（到 https://cloud.walletconnect.com 创建后替换）。 */
window.KARMA_WC_PROJECT_ID = "REPLACE_WITH_WALLETCONNECT_PROJECT_ID";
/** Show Sepolia testnet beta banner (loads testnet-banner.js on pages that include it). */
window.KARMA_TESTNET_BETA = true;
