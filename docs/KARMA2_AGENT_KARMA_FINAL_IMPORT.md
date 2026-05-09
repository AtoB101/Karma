# Karma2 private repo — Import `karma-private/` from `karma-final.zip`

This document is for a **human or agent** working in the **private** repository  
**https://github.com/AtoB101/Karma2** on branch **`main`**.

The archive **`karma-final.zip`** layout is assumed:

```text
karma-final.zip
├── karma-public/     → already applied to **AtoB101/Karma** only (Do NOT duplicate here)
└── karma-private/    → apply to **Karma2** below
```

**Never paste `karma-public/` into Karma2.** Only use `karma-private/`.

---

## 0. Preconditions

- Clone `Karma2` with push rights.
- `karma-final.zip` available locally (same file the public side used).

```bash
git clone git@github.com:AtoB101/Karma2.git
cd Karma2
```

---

## 1. Inspect the archive (sanity check)

```bash
unzip -l karma-final.zip | head -50
```

Confirm you see **`karma-private/`** (or **`karma-final/karma-private/`**).

Quick tree after extract:

```bash
STAGE="$(mktemp -d)"
unzip -q karma-final.zip -d "$STAGE"
find "$STAGE" -maxdepth 3 -type d | head -40
```

Resolve the private folder path:

- If `$STAGE/karma-private` exists → `PRIVATE="$STAGE/karma-private"`
- Else if `$STAGE/karma-final/karma-private` exists → `PRIVATE="$STAGE/karma-final/karma-private"`
- Else **stop** — structure unexpected.

---

## 2. Use `main`

```bash
git checkout main
git pull origin main
```

If you intend a PR instead of direct `main`, create `chore/import-karma-final-private` from `main` and push that branch instead of step 7’s `main`.

---

## 3. Merge `karma-private/` into Karma2 repo root (**default: additive**)

Replace `PRIVATE` below with your resolved absolute path inside `$STAGE`.

```bash
# Default: additive + overwrite same paths — does NOT delete extra files already in Karma2
sudo apt-get install -y rsync   # omit if rsync exists
rsync -a \
  --exclude ".git/" \
  --exclude ".cursor/" \
  --exclude ".DS_Store" \
  "$PRIVATE"/ ./

# ONLY if Karma2 should become an EXACT mirror of karma-private (deletes stray files — dangerous):
#   KARMA_IMPORT_RSYNC_DELETE=1 rsync -a --delete --exclude ".git/" "$PRIVATE"/ ./
```

---

## 4. Review diff (mandatory before commit)

```bash
git status
git diff --stat
git diff
```

Reject any accidental **`karma-public`** paths:

```bash
git diff --name-only | rg -n 'karma-public' && echo "STOP: public paths leaked" && exit 1
```

Reject obvious secrets (.env non-example, raw keys):

```bash
git diff --name-only | rg -n '\.env$|id_rsa|\.pem$' && echo "Review carefully"
```

---

## 5. Commit

```bash
git add -A
git commit -m "chore: import karma-private from karma-final.zip

Source: karma-final.zip karma-private subtree only.
Public subtree already applied on AtoB101/Karma (feat/karma-runtime)."
```

---

## 6. Push

Direct to `main` (only if allowed):

```bash
git push origin main
```

Or feature branch:

```bash
git checkout -b chore/karma-final-private-import
git push -u origin chore/karma-final-private-import
# then open PR → main on GitHub
```

---

## 7. Post-check

- Karma2 **`main`** (or merged PR) contains only expected internal assets.
- No duplicate/conflict resolution needed with Karma public repo paths (maintain separation per `VISIBILITY_MAP.md` conventions in the public Karma repo).

---

## Reference — public side (already scripted in Karma repo)

Public import is automated by:

```text
scripts/import-karma-final-public.sh
```

Target branch: **`feat/karma-runtime`**, remote must be **`AtoB101/Karma`** (verify `git remote -v`).
