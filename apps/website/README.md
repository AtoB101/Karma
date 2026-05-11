# KARMA Website (public)

Static **brand + trust + entry** site. **No wallet connection** on these pages — users operate assets only inside **Console** (`apps/console`).

## Local preview

From repository root:

```bash
python3 -m http.server 8787
```

Open `http://127.0.0.1:8787/apps/website/index.html`.

## Production routing

Map browser paths to static files, for example:

- `/` → `apps/website/index.html`
- `/console` → `apps/console/index.html` (or SPA host)
- `/developers` → `apps/developer-portal/index.html`

The HTML in this folder uses **relative** links (`../console/...`) so it works without URL rewrites when opened under `/apps/website/`.
