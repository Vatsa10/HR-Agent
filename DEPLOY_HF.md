# Deploy the backend on Hugging Face Spaces (free, Docker)

The FastAPI backend runs as a Docker Space (16 GB RAM free, enough for the
headless Chromium). The Next.js frontend stays on Vercel and proxies `/api/*`
to the Space.

## 1. Push the repo to your Space

Your Space: `https://huggingface.co/spaces/Vatsajoshi/do-appy-backend`

From the project root, add the Space as a git remote and push. Use a Hugging
Face access token (Settings -> Access Tokens, write scope) as the password.

```bash
git remote add hf https://huggingface.co/spaces/Vatsajoshi/do-appy-backend
git push hf main
```

HF sees the `Dockerfile` and builds it. The `README.md` frontmatter sets
`sdk: docker` and `app_port: 7860`. First build is slow (Chromium download).

The frontend (`web/`) is uploaded too but never built or run (the Dockerfile
ignores it via `.dockerignore`). Harmless.

## 2. Set Space secrets

Space -> Settings -> Variables and secrets -> New secret. Add:

| Name | Value |
|---|---|
| `DATABASE_URL` | your Neon pooled connection string |
| `OPENAI_API_KEY` | your OpenAI key |
| `GITHUB_TOKEN` | a GitHub PAT (raises rate limits) |
| `LINKEDIN_SESSION_JSON` | the entire contents of your local `linkedin_session.json` (paste the whole JSON) |

`LLM_PROVIDER`, `DEFAULT_MODEL`, `COOKIE_SECURE`, `COOKIE_SAMESITE`, `PORT`,
`HOME`, `TEMP` are already baked into the Dockerfile. The app writes
`LINKEDIN_SESSION_JSON` to a file on startup, so no secret-file mount is needed.

Save; the Space restarts. Health check: open `https://<space-host>/api/healthz`
-> `{"ok": true}`. The public Space URL looks like
`https://vatsajoshi-do-appy-backend.hf.space`.

## 3. Point the frontend at the Space

Vercel -> your project -> Settings -> Environment Variables:

```
API_ORIGIN = https://vatsajoshi-do-appy-backend.hf.space
```

Redeploy the frontend. `next.config.ts` proxies `/api/*` there, so the browser
stays same-origin with your Vercel domain and the session cookie flows.

## Notes

- The Space sleeps after ~48h idle and wakes on the next request; sessions live
  in Neon and jobs persist to disk, so a restart is harmless.
- LinkedIn scrapes from a datacenter IP hit captcha/limits more than a home IP.
  If scraping degrades, that is why.
- Rotate your LinkedIn `li_at` cookie if it was ever exposed: log out/in, re-run
  `create_session_from_cookie.py`, and update the `LINKEDIN_SESSION_JSON` secret.
- Latency: put your Neon DB in a region near HF's (HF runs in the US); the code
  already caches sessions and batches queries, so most calls are one round-trip.
