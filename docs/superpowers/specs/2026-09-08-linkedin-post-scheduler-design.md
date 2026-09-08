# LinkedIn Post Scheduler — Design

**Status:** Approved by user, pending implementation
**Date:** 2026-09-08
**Module:** `linkedin-post-bot/` (new, sibling of `telegram-jobs-bot/`)

## 1. Overview & Goals

Module 2 of the LinkedIn Bot project (see root `README.md`). Every Friday, the
system drafts a LinkedIn post about the user's recent technical learning and
personal projects, sends the draft to the user's Telegram for approval, and —
once approved — publishes it to LinkedIn automatically via the official
LinkedIn API. No third-party scheduling SaaS, no scraping, no unattended
posting without a human approval step.

**Goals:**
- Draft a post automatically from two sources: freeform notes the user jots
  during the week, and their own recent GitHub commits.
- Require explicit human approval (via Telegram) before anything is published.
- Publish through LinkedIn's official API — not a scraper, not a third-party
  tool — consistent with the rest of the project.
- Run entirely via cron-triggered scripts, no long-running process, matching
  `telegram-jobs-bot`'s existing operational model.

**Non-goals (out of scope for this spec):**
- Generating/scheduling more than one post per week.
- A UI beyond Telegram text messages.
- Automatic approval or any posting without a human "aprovar" reply.
- Multi-user support (the whole system is single-user, single Telegram chat,
  single LinkedIn account — same assumption `telegram-jobs-bot` already
  makes).
- Automatic LinkedIn token refresh without any human step. (LinkedIn access
  tokens for this product are not guaranteed to be silently refreshable for
  self-serve apps — see §8. When the token expires, the system asks the user
  to re-run the one-time authorization script.)

## 2. Architecture & Module Structure

```
linkedin-post-bot/
├── generate_post.py        # cron: Friday 17:00 — drafts the post, sends for approval
├── check_approval.py       # cron: every 15 min — publishes once approved (Fridays only)
├── authorize_linkedin.py   # run manually once — OAuth setup, and again after token expiry
├── config.example.py       # template; copy to config.py (gitignored)
├── notes.example.md        # template; copy to notes.md (gitignored)
├── requirements.txt
└── README.md                # setup + usage instructions for this module
```

No long-running server process. `generate_post.py` and `check_approval.py`
are both short-lived scripts invoked by cron/Task Scheduler, following the
same pattern as `telegram-jobs-bot/bot.py`. State is persisted to disk
between invocations (see §7).

## 3. Weekly Data Flow

1. **Friday 17:00** — `generate_post.py` runs:
   a. If `pending_post.json` already exists with `status:
      "aguardando_aprovacao"` (i.e. last week's draft was never approved or
      cancelled), it does **not** generate a new draft. It sends a Telegram
      reminder ("ainda tem um post pendente de aprovação de [data] — aprove,
      edite ou cancele antes de gerar um novo") and exits. This prevents two
      drafts racing for the same approval slot.
   b. Otherwise, it reads `notes.md` and fetches commits from the last 7
      days authored by the configured GitHub user across `GITHUB_REPOS`
      (§6).
   c. If both sources are empty (no notes content and zero commits), it
      sends a Telegram message saying there's nothing to post this week and
      exits — it does not force Claude to invent content from nothing.
   d. Otherwise, it calls the Claude API (§9) to draft the post text.
   e. It sends the draft to Telegram with instructions to reply `aprovar`,
      `cancelar`, or a corrected replacement text (§10).
   f. It writes `pending_post.json` with `status: "aguardando_aprovacao"`.

2. **Every 15 minutes, Fridays only** — `check_approval.py` runs:
   a. First action, before anything else: check the OS date. If
      `datetime.now().weekday() != 4` (Friday), exit immediately — no
      Telegram, GitHub, or LinkedIn calls at all on other days.
   b. If it's Friday but no `pending_post.json` exists, or its status isn't
      `"aguardando_aprovacao"`, exit (nothing to do).
   c. Poll Telegram (`getUpdates`, using the stored offset in
      `telegram_offset.json` to avoid reprocessing) for a message from
      `TELEGRAM_CHAT_ID` sent after the draft was posted.
   d. If a qualifying reply is found, act on it (§10), update
      `pending_post.json` to `status: "publicado"` or `"cancelado"`, and —
      as part of the same step — truncate `notes.md` back to the template
      header (§5), so next week starts with a clean slate regardless of
      the outcome.
   e. If the LinkedIn API call fails (including an expired token), send a
      Telegram error message describing what happened and leave
      `pending_post.json` at `status: "aguardando_aprovacao"` so the next
      15-minute run retries.

   **`--force` flag:** bypasses the weekday check in step (a) so a manual
   invocation works on any day — this is how the "known limitation" below
   is actually resolved.

   **Known limitation (explicitly accepted by the user):** if the user
   approves after Friday (e.g. Saturday), the cron-triggered
   `check_approval.py` will not pick it up automatically — the cron-fired
   runs process only on Fridays. The user runs
   `python check_approval.py --force` manually in that case, which skips
   step (a) and proceeds straight to steps (b)-(e). This is intentional,
   not a bug.

3. **One-time / occasional** — `authorize_linkedin.py`: run manually
   whenever there's no valid token, or the stored one has expired (§8).

## 4. Configuration (`config.example.py`)

```python
# Reused from telegram-jobs-bot (same bot/chat, same secrets file convention)
TELEGRAM_BOT_TOKEN = "SEU_TOKEN_AQUI"
TELEGRAM_CHAT_ID = "SEU_CHAT_ID_AQUI"

# Claude API — drafts the post text
ANTHROPIC_API_KEY = "SUA_CHAVE_AQUI"
CLAUDE_MODEL = "claude-opus-5"               # troque aqui se quiser um modelo mais barato

# LinkedIn API — from the app created in the LinkedIn Developer Portal (§8)
LINKEDIN_CLIENT_ID = "..."
LINKEDIN_CLIENT_SECRET = "..."
LINKEDIN_REDIRECT_URI = "http://localhost:8000/callback"

# GitHub — source of "what I built this week"
GITHUB_USERNAME = "NicolasDamasceno"        # commits by anyone else are excluded
GITHUB_REPOS = ["NicolasDamasceno/LinkendIn-Bot"]   # list of "owner/repo"
GITHUB_TOKEN = ""                            # optional: private repos / higher rate limit

# Local content sources
NOTES_FILE = "notes.md"

# Editable prompt sent to Claude — tune tone/length/topics here without touching code
POST_SYSTEM_PROMPT = """Você escreve posts de LinkedIn em primeira pessoa, tom pessoal \
e direto (não corporativo), para um desenvolvedor focado em React, React Native, \
.NET e automações em Python. Use o material fornecido (anotações da semana e \
commits recentes) para gerar UM post entre 150 e 300 palavras sobre aprendizado \
técnico e/ou projetos pessoais. Sem emojis em excesso, no máximo 3-5 hashtags \
relevantes no final. Responda só com o texto do post, sem comentários extras."""
```

`config.py` stays gitignored, same as today.

## 5. `notes.example.md`

A template showing the expected freeform format — just bullet points the
user jots during the week:

```markdown
<!-- Escreva livremente durante a semana. Cada linha vira contexto pro rascunho de sexta. -->
- terminei o filtro de freelance no bot de vagas
- estudei roteamento avançado no React Native
```

The real `notes.md` is gitignored and starts empty (or copied from the
example). `check_approval.py` truncates it back to the template header the
moment it resolves `pending_post.json` to `"publicado"` or `"cancelado"`
(§3.2.d) — not `generate_post.py` — so old notes don't bleed into next
week's draft, and the truncation happens exactly once per cycle, at
resolution time rather than at the next generation time.

## 6. GitHub Commit Fetching

`generate_post.py` calls the public GitHub REST API (no new dependency,
same `requests` pattern as the rest of the project):

```
GET https://api.github.com/repos/{owner}/{repo}/commits
    ?since={7_days_ago_iso}&author={GITHUB_USERNAME}
```

One call per repo in `GITHUB_REPOS`. If `GITHUB_TOKEN` is set, it's sent as
`Authorization: Bearer {GITHUB_TOKEN}` (needed for private repos; also
raises the unauthenticated 60 req/hour rate limit). A failed call for one
repo is logged and skipped — it doesn't abort the whole run (same
resilience pattern as `fetch_remoteok_jobs`/`fetch_arbeitnow_jobs` in
module 1, which log and continue on a single source's failure).

Only the commit `message` (first line) and repo name are passed to Claude —
not full diffs, to keep the prompt small and avoid leaking code content
into a public-facing post.

**Accepted trade-off:** the lookback window is always a rolling 7 days from
"now," not from the last successful post. If a Friday is skipped (§3.1.a,
prior draft still pending) or `check_approval.py` needs a manual
`--force` run days later, commits older than 7 days at that point can fall
outside the window and never make it into any draft — unlike `notes.md`,
whose content persists untouched until a draft is actually resolved. This
is accepted as-is; the window does not expand to cover skipped weeks.

## 7. State Files (all gitignored, live in `linkedin-post-bot/`)

**`pending_post.json`:**
```json
{
  "status": "aguardando_aprovacao",
  "draft_text": "...",
  "created_at": "2026-09-11T17:00:00-03:00",
  "telegram_message_id": 12345,
  "linkedin_post_urn": null,
  "published_at": null
}
```
`status` is one of `"aguardando_aprovacao"`, `"publicado"`, `"cancelado"`.

**`telegram_offset.json`:**
```json
{"last_update_id": 987654321}
```
Tracks the last processed Telegram `update_id` so `check_approval.py` never
reprocesses an old message (standard Telegram long-polling pattern).

**`linkedin_token.json`** (written by `authorize_linkedin.py`):
```json
{
  "access_token": "...",
  "expires_at": "2026-11-10T17:00:00-03:00",
  "refresh_token": null
}
```
`refresh_token` is `null` unless LinkedIn grants one for this app's product
access (not guaranteed for self-serve "Share on LinkedIn" access — see §8).

`expires_at` is written but checked only reactively (§8: a 401 from the
LinkedIn API is what triggers the re-authorization prompt) — no script
reads `expires_at` proactively to warn before expiry. This is intentional,
not an oversight: it keeps both scripts simpler, and the 401-triggered flow
already surfaces the problem the same day it would first matter (the next
scheduled publish attempt).

## 8. LinkedIn API Setup & Authorization

**One-time manual setup (documented step-by-step in the module's README,
not automated):**
1. Create an app in the LinkedIn Developer Portal, associated with a
   LinkedIn Page (LinkedIn requires every app to have an associated Page,
   even for posting as an individual member afterward — a minimal free
   Page works).
2. Request the "Share on LinkedIn" product (self-serve, grants the
   `w_member_social` scope for posting as the authenticated member).
3. Copy the app's Client ID / Client Secret into `config.py`.

**`authorize_linkedin.py` (run once, and again after token expiry):**
- Builds the LinkedIn OAuth 2.0 authorization URL (`response_type=code`,
  `client_id`, `redirect_uri=http://localhost:8000/callback`,
  `scope=w_member_social ...`) and prints/opens it.
- Starts a temporary local HTTP server (Python stdlib `http.server`, no new
  dependency) bound to `localhost:8000` to catch the OAuth redirect.
- User logs into LinkedIn in their browser and authorizes the app; LinkedIn
  redirects to `localhost:8000/callback?code=...`.
- The script exchanges `code` for an access token
  (`POST https://www.linkedin.com/oauth/v2/accessToken`) and writes
  `linkedin_token.json`.

**Token lifetime:** LinkedIn access tokens for this product are typically
valid ~60 days. Whether a refresh token is issued depends on the app's
approved products; the script stores one if present, but the design does
not assume it will be. When `check_approval.py` gets a 401 from the
LinkedIn API, it treats the token as expired: it sends a Telegram message
asking the user to re-run `authorize_linkedin.py`, and leaves the pending
post as `"aguardando_aprovacao"` so it publishes automatically on the next
successful run.

**Publish call:** LinkedIn's post-creation endpoint and required headers
(e.g. `LinkedIn-Version`) will be confirmed against LinkedIn's current
official API documentation at implementation time — not guessed from
training memory, the same caution already applied to the Remotive
integration in module 1. This spec fixes the *behavior* (one text-only,
`PUBLIC`-visibility post per approval, authored as the token's member); the
exact request/response shape is an implementation detail to be verified,
not a design decision.

## 9. Content Generation (Claude API)

Single, non-streaming Claude API call (see the `claude-api` skill's
Python reference for exact SDK usage at implementation time):

- **Model:** `claude-opus-5` (project default; user may override in
  `config.py` if they want a cheaper model — cost is negligible at this
  volume, one call per week).
- **System prompt:** `POST_SYSTEM_PROMPT` from `config.py` (§4).
- **User message:** the week's `notes.md` content + the fetched commit list
  (repo name + message, per §6), clearly labeled as two separate sources.
- **`max_tokens`:** 2000 (comfortably covers a 150-300 word post; no
  streaming needed at this size).
- Thinking left at the model's default (adaptive) — this is a short
  creative-writing task, not a reasoning-heavy one; no explicit
  `thinking`/`effort` override is needed.
- No tools, no structured output — the response text *is* the draft
  (instructed via the system prompt to return only the post text).

## 10. Telegram Approval Protocol

**Message sent by `generate_post.py`:**
```
📝 Rascunho do post desta semana:

<draft text>

Responda:
• "aprovar" — publica como está
• "cancelar" — pula essa semana
• qualquer outro texto — publica ESSE texto no lugar do rascunho
```

**Interpretation by `check_approval.py`** (first qualifying message from
`TELEGRAM_CHAT_ID` after `pending_post.json.created_at` wins; later
messages that same day are ignored once resolved). Matching rule: trim
whitespace, strip trailing punctuation (`!`, `.`, `,`), fold case — so
`"Aprovar!"` and `"aprovar."` both count as approval, not as replacement
text:
- Matches `"aprovar"` or `"aprovado"` under the rule above → publish
  `draft_text` as-is.
- Matches `"cancelar"` under the rule above → mark `"cancelado"`, no
  LinkedIn call, confirms cancellation back to the user.
- Anything else → treat the message text itself as the replacement post
  text and publish *that* instead of `draft_text`.

**Accepted risk:** because this is a single-user personal tool, there is no
confirmation step before publishing replacement text — if the user's reply
doesn't match the approve/cancel keywords (even a typo, or an unrelated
message sent to the same chat), it gets published to LinkedIn verbatim.
This trade-off is deliberate, the same way the Friday-only check in §3.2 is
— not an oversight.

This reuses the same `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` as
`telegram-jobs-bot`, but as a separate `getUpdates` consumer with its own
offset file (§7) — the two modules don't share polling state, so one
module's message consumption can't cause the other to miss a message type
it doesn't expect (job alerts are one-way sends; this module is the only
one reading replies).

## 11. Error Handling & Notifications

Unlike `telegram-jobs-bot` (which only `print()`s warnings, since a human
reviews cron output when convenient), this module's scripts run unattended
with a real consequence (a scheduled post) — so failures are surfaced
directly to Telegram, not just logged:

| Failure | Behavior |
|---|---|
| GitHub API error for one repo | Log, skip that repo, continue with the rest |
| GitHub API error for all repos + empty notes | Falls into the "nothing to post" case (§3.1.c) |
| Claude API error | Telegram message: draft generation failed, with the error; no `pending_post.json` written; next Friday retries normally |
| Telegram send failure during `generate_post.py` | Logged to stdout (cron log) only — `pending_post.json` is **not** written in this case, so `check_approval.py` never polls for approval of a draft the user never actually saw. There's no fallback channel if Telegram itself is down; next Friday retries normally. |
| LinkedIn publish error (non-auth) | Telegram message with the error; `pending_post.json` stays `"aguardando_aprovacao"`; retried on the next 15-minute run |
| LinkedIn 401 (expired token) | Telegram message asking to re-run `authorize_linkedin.py`; same retry-on-next-run behavior |

**Overlap note:** `generate_post.py` (17:00 Friday) and a `check_approval.py`
tick (`*/15`, including the one at 17:00) can fire in the same minute. This
is not a race worth guarding against: `generate_post.py` only ever writes
`pending_post.json` when none exists in `"aguardando_aprovacao"` state
(§3.1.a), and `check_approval.py` only ever acts on an *existing* one — so
the two either don't touch the same file in that tick, or `check_approval.py`
simply finds nothing to act on yet. No locking is introduced for this.

## 12. Security & Secrets

- `config.py`, `notes.md`, `pending_post.json`, `telegram_offset.json`,
  `linkedin_token.json` are all added to the existing root `.gitignore`.
- `linkedin_token.json` holds a live access token — same gitignore
  discipline as `config.py`'s API keys, called out explicitly in this
  module's README so it's not missed.
- The local OAuth callback server in `authorize_linkedin.py` binds to
  `localhost` only and shuts itself down as soon as it captures the `code`
  (or after a timeout, e.g. 5 minutes, if the user abandons the browser
  flow).

## 13. Testing Approach

No automated test suite — consistent with module 1, which also has none;
this is a personal-scale project validated by manual smoke tests (as was
done for the Remotive integration). Two additions specifically to make
this module safe to validate without spamming LinkedIn or burning Claude
API calls repeatedly:

- **`--dry-run` flag on both scripts:** `generate_post.py --dry-run` runs
  the full flow (GitHub fetch, Claude draft) but prints the draft to stdout
  instead of sending it to Telegram or writing `pending_post.json`.
  `check_approval.py --dry-run` runs its Telegram-polling logic but prints
  what it *would* publish to LinkedIn instead of calling the API.
- **Manual QA checklist in the module's README:** run `authorize_linkedin.py`
  once against a real (throwaway or personal) LinkedIn account, then walk
  the full weekly cycle once end-to-end before relying on cron.

## 14. Cron Schedule (documented in the module's README)

```
# Friday 17:00 — generate and send draft for approval
0 17 * * 5 cd /caminho/para/LinkendIn-Bot/linkedin-post-bot && python3 generate_post.py

# Every 15 minutes — check for approval (script itself no-ops on non-Fridays)
*/15 * * * * cd /caminho/para/LinkendIn-Bot/linkedin-post-bot && python3 check_approval.py
```

## 15. Dependencies (`requirements.txt`)

```
requests>=2.31.0
anthropic>=0.40.0
```

No new dependency for the OAuth callback server (Python stdlib
`http.server`) or for the LinkedIn/GitHub calls (`requests`, already used
throughout the project).
