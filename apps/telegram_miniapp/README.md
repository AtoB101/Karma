# Telegram MiniApp MVP (Karma main repo)

Aligned with karma8 `integrations/telegram-miniapp/KARMA_MAIN_HANDOFF.md`.

## Run API

```bash
export TELEGRAM_BOT_TOKEN=...          # required in prod
export KARMA8_ECONOMY_HOST=https://economy.example
# optional addresses from karma8 deployments/*.json
export FEE_BRIDGE=0x...
export TREASURY=0x...
export KARMA_BILATERAL=0x...
uvicorn api.app:app --reload --port 8000
```

## Run MiniApp shell

```bash
cd apps/telegram_miniapp
python3 -m http.server 8787
# open http://127.0.0.1:8787
# for local without Telegram client:
# localStorage.DEV_INIT_DATA = <build_dev_init_data()>
# localStorage.KARMA_API = 'http://127.0.0.1:8000'
```

## Hard gates

- initData verified server-side (never trust frontend tg id)
- VerificationEngine PASS required before `/v1/settlement/finalize`
- No treasury fee/split/ContributionNFT mint logic in this repo
- Wallet/Rewards tab embeds `KARMA8_ECONOMY_HOST/?view=miniapp`

## Flow

Chat intent → offers → order → sign → policy → lock → evidence → **verify PASS** → settle → FeeBridge GMV
