# GitHub Pages Portal Setup (Temporary Domain -> Custom Domain)

This guide publishes `trust-chain-core` as a portal website using GitHub Pages.

## 1. Default Test URL

After enabling workflow + Pages, the portal is available at:

- `https://<org-or-user>.github.io/<repo>/`

For this repository example:

- `https://atob101.github.io/Trust-Chain/`

## 2. Publish Path

The workflow publishes static files from:

- `trust-chain-core/`

That means portal entry is:

- `/index.html`

## 3. Enable Pages in Repository Settings

In GitHub repository settings:

1. Open **Settings -> Pages**
2. Build and deployment -> **Source: GitHub Actions**
3. Save

## 4. Temporary Portal Validation Checklist

- [ ] Open default Pages URL
- [ ] Verify dashboard loads
- [ ] Verify buyer/seller/bill interactions render correctly
- [ ] Verify backend API base configuration for environment

## 5. Switch to Purchased Custom Domain Later

When production domain is ready (example `portal.trust-chain.com`):

1. DNS provider: add record pointing to GitHub Pages
   - usually `CNAME portal -> <org-or-user>.github.io`
2. Create real `trust-chain-core/CNAME` file with your domain value
3. Commit and push
4. GitHub Settings -> Pages:
   - set custom domain to `portal.trust-chain.com`
   - enable HTTPS

## 6. CNAME File

Use template:

- `trust-chain-core/CNAME.example`

Create actual file:

- `trust-chain-core/CNAME`

with one line only:

```txt
portal.trust-chain.com
```

## 7. Notes

- You can run on default GitHub Pages domain for testing.
- Replacing with purchased domain later does not require frontend rewrite.
- Keep API endpoint configuration environment-aware when moving to production.
