# Security

New Haven holds other people's API keys, so this document is explicit about what the server does with them and what an attacker can and cannot do.

## Visitors' keys

- A key is held **in server memory only**, attached to the sponsored citizen's brain, with an expiry the visitor chooses (1–72 h). It is never logged, never written to disk, never included in any snapshot or event. On expiry or restart it is gone; the citizen falls back to the rules brain.
- Storing the key is **opt-in** and only possible when the host has set `APP_SECRET`. Stored keys are Fernet-encrypted (key derived from `APP_SECRET`); they are decrypted only inside the server process when a village restores.
- "Forget my key" wipes it from memory and clears any stored copy immediately.
- Error messages from providers are scrubbed of anything that looks like a credential before being shown or logged.
- Visitors are told to use a separate, spend-capped key. Please repeat that in your own copy.

## What is protected how

| Threat | Mitigation |
|---|---|
| Stored XSS via names, backstories, sponsor names, movement names, model output | All user- and model-derived strings are HTML-escaped at every `unsafe_allow_html` site; the 3D scene's tooltips use `textContent`; adoption strips control characters and caps lengths |
| SSRF via a custom provider URL | `custom` and `ollama` providers are disabled unless `ALLOW_CUSTOM_PROVIDERS=1`; when enabled, base URLs must be https and must not resolve to loopback, private, link-local or reserved addresses; other providers cannot override their base URL |
| Brute-forcing the god password or claim tokens | `hmac.compare_digest`; per-session limiter (5 attempts / 15 min for the password with a delay, 10 for tokens); claim tokens are 144-bit random and stored as SHA-256 hashes |
| An unlocked production village | With no `ADMIN_PASSWORD` on a production server (`RAILWAY_ENVIRONMENT`/`PRODUCTION` set) nobody is god; locally everyone is, with a warning |
| Snapshot tampering → pickle RCE | Snapshots are HMAC-signed with `APP_SECRET`; unsigned or mismatched blobs are refused when a secret is set. Treat `APP_SECRET` and the Supabase service key as equally sensitive |
| Database exposure | The SQLite fallback lives in `data/` (not the publicly served `static/`); Supabase tables have RLS enabled with no policies, so only the service-role key can read them, and that key exists only in the server environment |
| Abuse of the host's LLM key | Decrees are god-only; host reactions are capped by `LLM_MAX_CALLS`; stewards' instructions run on their own keys with an 8-second cooldown; `MAX_RESIDENTS` caps the village |
| Container | Runs as an unprivileged user; TLS is terminated by the platform (Railway) |

## What is *not* protected

- There are no user accounts. A claim token is bearer authentication: whoever has it is the steward. Tokens are shown once; the app advises against putting them in URLs.
- Streamlit's websocket carries form fields (including keys) in plaintext *inside* TLS; do not run this over plain HTTP.
- The public village is a shared sandbox: a steward's actions (courting, confronting, founding movements) affect other people's citizens by design.
- A compromised server process can read any key currently in memory. This is inherent to server-side inference; the alternative is browser-held keys where the visitor's own tab makes the model calls — not implemented.

## Reporting

Open an issue or contact the host. Please don't test SSRF or brute-force paths against someone else's deployment.
