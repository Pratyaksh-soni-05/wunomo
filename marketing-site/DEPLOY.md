# Deploying marketing-site to wunomo.in

`PLACEHOLDERS.md` is fully checked off as of this writing — Cal.com,
Formspree, and both WhatsApp contacts are real values, verified live (see
that file and this session's deploy-readiness verdict for the detail).

**Two stages, do them in order:**
- **Stage 1 (sections 1-2 below): deploy to the free `*.vercel.app` URL
  and test everything live there first.** This is the recommended starting
  point — confirms the real Vercel build/runtime behaves like the local one
  before any DNS is touched.
- **Stage 2 (sections 3-4): point `wunomo.in` at it via Cloudflare DNS.**
  Only do this once Stage 1 is confirmed working on the `.vercel.app` URL.

## 1. Push the branch

```
git push -u origin marketing-site
```

## 2. Create the Vercel project

1. Vercel dashboard → **Add New… → Project** → import the same GitHub repo
   this branch lives in (connect the repo if it isn't connected yet).
2. **Production Branch: `marketing-site`** — not `main`/`master`. This is
   the setting that keeps the product app (which lives on `master`) out of
   this deployment entirely; Vercel will only ever build what's on this
   branch.
3. **Root Directory: `marketing-site`** — this repo is a monorepo; without
   this, Vercel will try to build the repo root and fail (there's no
   `package.json` there).
4. Framework Preset should auto-detect as **Next.js**. Leave Build Command /
   Output Directory on their defaults (`next build --turbopack`, from this
   project's own `package.json`).
5. No environment variables are required — this app has no backend, no API
   URL, nothing to configure. If you added the real Formspree ID directly
   into `src/lib/config.ts` (as this project does, rather than via an env
   var), there's nothing else to set here.
6. Deploy. Vercel gives you a `*.vercel.app` preview URL — confirm the site
   loads there correctly before touching DNS.

## 3. Add the custom domain in Vercel

1. In the Vercel project → **Settings → Domains** → add `wunomo.in`.
2. Also add `www.wunomo.in` and set it to **redirect to `wunomo.in`** (Vercel
   offers this as a one-click option when you add the second domain) — not
   required, but avoids a dead `www.` if anyone types it.
3. Vercel will show you the **exact DNS records it wants** for `wunomo.in`.
   Use what it shows you over the reference values below if they ever
   differ — Vercel's own edge IPs are the source of truth, not this file.
   As of writing, for an apex domain like `wunomo.in` it's typically one of:
   - `A` record: `@` → `76.76.21.21`, **or**
   - `CNAME` (flattened) record: `@` → `cname.vercel-dns.com`
   Cloudflare supports CNAME flattening at the apex, so the CNAME form works
   there even though CNAME isn't normally legal at a root domain — prefer it
   if Vercel offers it, since it auto-follows Vercel's IP if that ever
   changes, where a bare `A` record wouldn't.

## 4. Add the records in Cloudflare DNS

In the Cloudflare dashboard for `wunomo.in` → **DNS → Records**:

| Type | Name | Value | Proxy status |
|---|---|---|---|
| `A` (or `CNAME`, per what Vercel showed you) | `@` | `76.76.21.21` (or `cname.vercel-dns.com`) | **DNS only** (grey cloud) — see note below |
| `CNAME` | `www` | `cname.vercel-dns.com` | **DNS only** (grey cloud) — see note below |

**Proxy status — start with DNS only (grey cloud), not Proxied (orange
cloud).** Vercel needs to issue and validate a Let's Encrypt certificate for
the domain, which is more reliable when Cloudflare isn't sitting in front of
it yet. Once you've confirmed `https://wunomo.in` loads correctly with a
valid cert (a few minutes after adding the records), you can switch both
records to **Proxied** if you want Cloudflare's CDN/DDoS protection in
front — just make sure Cloudflare's **SSL/TLS mode is set to "Full" or
"Full (strict)"**, never "Flexible" (Flexible causes a redirect loop against
Vercel, which always forces HTTPS on its own end).

## 5. Verify

- `https://wunomo.in` loads over HTTPS with a valid certificate (no browser
  warning).
- `https://www.wunomo.in` redirects to `https://wunomo.in`.
- DNS propagation can take anywhere from a few minutes to ~24h depending on
  the previous record's TTL at your registrar — if it's not resolving yet,
  wait and recheck rather than re-editing records repeatedly.

## Not part of this task

The product app (`dataops-agent/`) is not deployed by any of this — this
Vercel project only ever builds the `marketing-site/` folder on the
`marketing-site` branch. `master` and the product app are untouched.
