# Comodo (Static Website)

This project is now prepared to behave like a **website** (not backend app) on common static hosts.

## Permanent 404 fix strategy

The repo includes host-specific fallback files so route/path requests resolve to `index.html`:

- Cloudflare Pages: `_redirects`
- Netlify: `netlify.toml`
- Vercel: `vercel.json`
- Generic static hosts: `404.html` redirect fallback

## Deploy settings (step-by-step)

### 1) Cloudflare Pages
- Framework preset: **None**
- Build command: **(leave empty)**
- Build output directory: **/**
- Root directory: **/**

### 2) Netlify
- Build command: **(leave empty)**
- Publish directory: **.**
- `netlify.toml` is already configured for SPA-style fallback.

### 3) Vercel
- Framework preset: **Other**
- Build command: **(leave empty)**
- Output directory: **.**
- `vercel.json` rewrite is already configured.

### 4) GitHub Pages / simple static server
- Ensure `index.html` exists in root (it does).
- `404.html` is added to redirect unknown routes back to home.

## Notes
- If a platform still shows 404, confirm it is publishing the **repository root**.
- This repo also contains `codeeditorcode.py` (Flask), but static hosts will only serve website files unless you deploy Python backend separately.
