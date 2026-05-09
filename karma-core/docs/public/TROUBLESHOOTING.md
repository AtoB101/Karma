# Troubleshooting (CN/EN)

## 1) Frontend still shows old UI

- CN: 浏览器缓存导致旧页面残留。请强制刷新（Windows/Linux: `Ctrl+F5`, macOS: `Cmd+Shift+R`）。
- EN: Browser cache is serving stale content. Do a hard refresh.

Recommended URL (cache-busting):
`http://127.0.0.1:8790/examples/v01-metamask-settlement.html?ts=20260428`

---

## 2) MetaMask connection fails

- CN: 必须使用 `http://` 地址，不要用 `file://` 直接打开 HTML。
- EN: Use an `http://` URL, not `file://`.

Checklist:
- MetaMask extension installed and unlocked
- Network matches your deployment chain
- Pop-up requests are not blocked by browser settings

---

## 3) Health Check shows "Blocked"

Common causes:
- token balance is insufficient
- allowance to `NON_CUSTODIAL_ADDRESS` is too low
- wrong token/non-custodial/payee address
- network mismatch

CN 快速建议:
1. 确认当前钱包有足够 Token
2. 确认已给 `NON_CUSTODIAL_ADDRESS` 足够授权
3. 确认地址和网络完全一致

---

## 4) Deploy script fails

Required env vars for deploy:
- `ETH_RPC_URL`
- `DEPLOYER_PRIVATE_KEY`
- `ADMIN_ADDRESS`

If deploy fails:
1. Run `./scripts/preflight.sh --from-env`
2. Validate RPC endpoint is reachable
3. Check private key has enough native gas

---

## 5) Frontend server does not start

Check port conflicts:
```bash
python3 -m http.server 8790
```

If occupied, use another port:
```bash
python3 -m http.server 8791
```

Then update URL accordingly.

