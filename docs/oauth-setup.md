# SSO / OAuth setup (Google + LinkedIn)

The backend runs the OpenID Connect (OIDC) **authorization-code + PKCE** flow as the relying
party and mints its own short-lived session JWT (§7.1). Registering the OAuth apps is a
one-time **manual** step in each provider's console (it needs an external account this repo
cannot create for you). This is a copy-paste checklist.

You need, per provider, a **client id** and **client secret**, plus a **redirect URI** that
matches exactly what the backend derives from config.

## Redirect URI (both providers)

The backend derives the callback URI from `OAUTH_REDIRECT_BASE_URL` — it is **never**
hard-coded per provider:

```
<OAUTH_REDIRECT_BASE_URL>/api/auth/callback/{provider}
```

Set `OAUTH_REDIRECT_BASE_URL` to the public base URL of the **backend** (scheme + host, no
trailing slash), then register these exact URIs:

| Environment | `OAUTH_REDIRECT_BASE_URL` | Google redirect URI | LinkedIn redirect URI |
|-------------|---------------------------|---------------------|------------------------|
| Local dev   | `http://localhost:8000`   | `http://localhost:8000/api/auth/callback/google` | `http://localhost:8000/api/auth/callback/linkedin` |
| HF Space    | `https://<owner>-<space>.hf.space` | `https://<owner>-<space>.hf.space/api/auth/callback/google` | `https://<owner>-<space>.hf.space/api/auth/callback/linkedin` |

The redirect URI in the console must match **character-for-character** (scheme, host, path).

## Scopes (both providers)

Request **minimal scopes only**: `openid email profile` (config key `OAUTH_SCOPES`). Do not
add more. LinkedIn *profile import* (extra scopes + a stored provider token) is a separate,
opt-in feature — not part of login.

## 1. Google

1. Go to <https://console.cloud.google.com/> → select/create a project.
2. **APIs & Services → OAuth consent screen**: configure it (External), add the
   `openid`, `email`, `profile` scopes, and your account as a test user (until published).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
4. Application type: **Web application**.
5. Under **Authorized redirect URIs**, add the Google redirect URI from the table above (add
   both localhost and the Space URI if you use both).
6. Save. Copy the **Client ID** → `GOOGLE_CLIENT_ID` and **Client secret** →
   `GOOGLE_CLIENT_SECRET`.

Google's discovery document (already the default in `OAUTH_METADATA_URLS`):
`https://accounts.google.com/.well-known/openid-configuration`.

## 2. LinkedIn

1. Go to <https://www.linkedin.com/developers/apps> → **Create app** (needs a LinkedIn Page).
2. In the app's **Products** tab, add **Sign In with LinkedIn using OpenID Connect**.
3. In the **Auth** tab, under **OAuth 2.0 settings → Authorized redirect URLs**, add the
   LinkedIn redirect URI from the table above.
4. Confirm the OpenID Connect scopes `openid`, `email`, `profile` are granted.
5. Copy the **Client ID** → `LINKEDIN_CLIENT_ID` and **Client Secret** →
   `LINKEDIN_CLIENT_SECRET`.

LinkedIn's discovery document (already the default in `OAUTH_METADATA_URLS`):
`https://www.linkedin.com/oauth/.well-known/openid-configuration`.

## 3. Secrets — where they go

Never commit real values. Set them as environment variables:

- **Local:** in `backend/.env` / repo-root `.env` (git-ignored). See `.env.example`.
- **HF Spaces:** in the **Space Secrets** panel (injected as env vars at container start):
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`,
  `JWT_SECRET_KEY`, and `OAUTH_REDIRECT_BASE_URL` (= the Space domain).

Generate the JWT signing key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 4. Verify

1. Start the backend with the vars set.
2. Open `<OAUTH_REDIRECT_BASE_URL>/api/auth/login/google` in a browser → you should be
   redirected to Google's consent screen (URL contains `code_challenge` + `state`).
3. After consent you land on `OAUTH_POST_LOGIN_REDIRECT` with `#access_token=...` in the URL
   fragment. That token is the backend session JWT — send it as `Authorization: Bearer
   <token>` on API calls.
4. `POST /api/auth/logout` (with the bearer token) ends the session.
