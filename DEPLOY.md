# Deploying Do Apply

Two services: the **Next.js frontend on Vercel** (doapply.online) and the
**FastAPI backend on Render**. The backend cannot run on Vercel: it needs a
long-running process, a persistent headless Chromium (Patchright), and
background job threads that live between requests.

```
Browser  ->  Vercel (Next.js, doapply.online)  --/api/* proxy-->  Render (FastAPI)  ->  Neon Postgres
```

The browser only ever talks to doapply.online. Next.js rewrites `/api/*` to the
Render backend server-side, so the session cookie stays first-party (no CORS).

---

## 1. Database (Neon)

Pick a Neon region, then create the Render service in the **same region** so
backend<->DB latency is single-digit ms (this is what makes the app feel fast;
a far DB is ~750ms per query). Copy the pooled connection string for `DATABASE_URL`.

## 2. Backend on Render

1. Push this repo to GitHub (already done).
2. Render dashboard -> New -> Blueprint -> pick this repo. It reads `render.yaml`
   (Docker, `Dockerfile`). Or New -> Web Service -> Docker, same repo.
3. Set **region = your Neon region** (edit `render.yaml` `region:` or the dashboard).
4. Environment variables (dashboard, marked `sync:false` in the blueprint):
   - `DATABASE_URL` = Neon pooled connection string
   - `OPENAI_API_KEY` = your OpenAI key
   - `GITHUB_TOKEN` = a GitHub PAT (raises rate limits, enables full repo scan)
   - already set by the blueprint: `LLM_PROVIDER=openai`, `DEFAULT_MODEL=gpt-4o-mini`,
     `COOKIE_SECURE=1`, `COOKIE_SAMESITE=lax`, `LINKEDIN_SESSION_PATH=/etc/secrets/linkedin_session.json`
5. **LinkedIn session (optional, for LinkedIn features):** Render dashboard ->
   the service -> Environment -> Secret Files -> add `linkedin_session.json`
   with the contents of your local `linkedin_session.json`. Mount path
   `/etc/secrets/linkedin_session.json` (matches `LINKEDIN_SESSION_PATH`).
   Without it, LinkedIn import / job search / people search fail gracefully; the
   rest of the app works.
6. Deploy. Health check: `GET /api/healthz` -> `{"ok": true}`.
7. Note the service URL, e.g. `https://doapply-api.onrender.com`.

Note: LinkedIn scrapes from a datacenter IP are more likely to hit captcha/rate
limits than a home IP. If scraping degrades, that is the cause.

## 3. Frontend on Vercel

1. Vercel -> New Project -> import this repo.
2. **Root Directory = `web`** (important, the Next.js app lives there).
3. Framework preset: Next.js (auto). Build command / output: defaults.
4. Environment variable:
   - `API_ORIGIN` = your Render URL (e.g. `https://doapply-api.onrender.com`)
   `next.config.ts` reads it to proxy `/api/*` to the backend.
5. Deploy. Add the custom domain **doapply.online** in Vercel -> Domains.

## 4. Verify

- Visit doapply.online -> sign up -> Analyze a resume -> Builder.
- If auth fails: confirm `COOKIE_SECURE=1` on Render (prod is HTTPS) and
  `API_ORIGIN` points at Render on Vercel.
- If loading is slow: confirm Render and Neon are in the same region.

## Local dev (unchanged)

```bash
# backend
python app.py                 # http://127.0.0.1:8000
# frontend
cd web && npm run dev         # http://localhost:3000  (proxies /api to :8000)
```
