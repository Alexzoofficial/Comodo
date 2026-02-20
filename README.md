# Comodo (Website + JS API)

This project is prepared for static hosting and Vercel serverless APIs (JavaScript), so Python backend dependency is not required on Vercel.

## What changed for permanent fix

- Frontend website is served from `index.html`.
- Vercel rewrites map old Flask-style routes (like `/ask`, `/new_chat`, `/get_history`) to JS serverless API files under `/api/*`.
- SPA fallback is still enabled so unknown paths open `index.html`.

## Vercel deploy (step-by-step)

1. Import this repo in Vercel.
2. Framework Preset: **Other**
3. Build Command: **(empty)**
4. Output Directory: **.**
5. Environment Variables:
   - `OPENROUTER_API_KEY`
   - `ALEXZO_SEARCH_API_KEY`
6. Deploy.

## Cloudflare / Netlify static deploy

If you only deploy static hosting (without serverless API), UI loads but chat/file APIs need backend support.

- Cloudflare Pages: Framework `None`, Build command empty, Output `/`
- Netlify: Publish `.` (already in `netlify.toml`)

## Files

- `api/*.js` → JS backend routes for Vercel.
- `vercel.json` → rewrites old endpoints to JS APIs + SPA fallback.
- `codeeditorcode.py` → legacy/local Flask version (optional, not required for Vercel).
