# LinkedIn Post Scheduler Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `linkedin-post-bot/` module: every Friday it drafts a LinkedIn post from the user's notes + recent GitHub commits via the Claude API, sends it to Telegram for approval, and publishes it via the official LinkedIn API once approved.

**Architecture:** Three cron-triggered scripts (`generate_post.py`, `check_approval.py`, plus the one-time `authorize_linkedin.py`) sharing state through small JSON files on disk — no long-running process, matching `telegram-jobs-bot`'s existing operational model. Two small shared client modules (`telegram_client.py`, `linkedin_client.py`) avoid duplicating HTTP-call logic between the scripts that need them.

**Tech Stack:** Python 3, `requests`, `anthropic` (Claude API SDK), Python stdlib only for the OAuth callback server (`http.server`) — no new runtime dependencies beyond those two packages.

**Spec:** `docs/superpowers/specs/2026-09-08-linkedin-post-scheduler-design.md` — read it for full rationale; this plan implements it as written, with two additive (non-contradictory) implementation-level decisions called out below.

**A note on testing:** the spec explicitly rejects an automated test suite (§13) — this is a personal-scale project validated by manual smoke tests, same as `telegram-jobs-bot`. This plan follows that: pure functions with no external dependency (`classify_reply`, `find_reply`, `build_authorization_url`) get a real inline assertion-based check (no pytest — none is installed in this project, consistent with module 1); functions that call a public, unauthenticated API (GitHub) get a live smoke test the same way `fetch_remotive_jobs` was verified earlier in this project; functions that require secrets we don't have (Telegram bot token, LinkedIn OAuth app, Claude API key) are verified for *plumbing* only (they raise/fail the right way against the real endpoint with garbage credentials, proving the URL and request shape are right) — full functional verification of those is the user's manual QA pass from spec §13, not something this plan can complete unattended.

**Implementation-level decisions not fixed by the spec** (the spec explicitly leaves file-level decomposition and a couple of request/response details to implementation time — see spec §8, §9):
- `linkedin_client.py` and `telegram_client.py` are new shared modules not listed in spec §2's directory tree. They exist because `check_approval.py` and `authorize_linkedin.py` both need LinkedIn HTTP calls, and `generate_post.py` and `check_approval.py` both need Telegram HTTP calls — splitting them out avoids duplicating that logic (DRY), and each has one clear responsibility.
- `linkedin_token.json` gets one field beyond spec §7's schema: `author_urn` (the LinkedIn member's own URN, `urn:li:person:{id}`), fetched once during authorization via `GET /v2/userinfo` and cached so `check_approval.py` doesn't need an extra API call on every publish. This is additive, not a contradiction of the documented schema.
- The exact LinkedIn Posts API shape (confirmed via Microsoft Learn's LinkedIn API docs, current as of this plan): `POST https://api.linkedin.com/rest/posts` with headers `Authorization: Bearer {token}`, `X-Restli-Protocol-Version: 2.0.0`, `LinkedIn-Version: {YYYYMM}`; body `{"author": "urn:li:person:{id}", "commentary": "...", "visibility": "PUBLIC", "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []}, "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": false}`. Success is `201` with the new post's URN in the `x-restli-id` response header. The member's own URN requires the `openid` and `profile` scopes (in addition to `w_member_social`) and a call to `GET https://api.linkedin.com/v2/userinfo` (returns a `sub` claim → `urn:li:person:{sub}`). `LinkedIn-Version` is pinned to `"202608"` as a constant in `linkedin_client.py`, with a comment noting it may need bumping if LinkedIn rejects it later — LinkedIn ships new versions periodically and there's no way to make this self-updating without an extra API call on every run, which isn't worth it at one post/week.
- Timestamps (`created_at`, `expires_at`, `published_at`) are written with naive `datetime.now().isoformat()` throughout this module, matching `telegram-jobs-bot/bot.py`'s existing convention — not the timezone-aware `-03:00`-suffixed example shown in spec §7's illustrative JSON. Harmless: spec §7/§8 confirm nothing ever parses these fields back programmatically for comparison: `expires_at` is checked reactively via a 401, not by parsing the timestamp (spec §7), and `created_at` is only ever echoed back into a Telegram reminder message as a string (spec §3.1.a).
- OAuth endpoints (also confirmed live): authorize at `GET https://www.linkedin.com/oauth/v2/authorization` (`response_type=code`, `client_id`, `redirect_uri`, `state`, `scope`), exchange at `POST https://www.linkedin.com/oauth/v2/accessToken` (form-encoded: `grant_type=authorization_code`, `code`, `client_id`, `client_secret`, `redirect_uri`). Access tokens are confirmed 60-day lifespan; refresh tokens are confirmed "available for a limited set of partners" (i.e. not guaranteed for a self-serve app) — matches spec §8's assumption exactly. `http://localhost:PORT/callback` is a documented-acceptable redirect URI for this flow.

---

## Chunk 1: Scaffolding + shared clients + one-time LinkedIn authorization

### Task 1: Module scaffolding

**Files:**
- Create: `linkedin-post-bot/requirements.txt`
- Create: `linkedin-post-bot/config.example.py`
- Create: `linkedin-post-bot/notes.example.md`
- Modify: `.gitignore`

- [ ] **Step 1: Create the module directory and `requirements.txt`**

```
requests>=2.31.0
anthropic>=0.40.0
```

- [ ] **Step 2: Create `config.example.py`**

```python
# =========================================================
# CONFIGURAÇÃO DO AGENDADOR DE POSTS DO LINKEDIN
# Copie este arquivo para config.py e preencha os campos abaixo.
# config.py não é versionado (está no .gitignore).
# =========================================================

# Reaproveita o mesmo bot/chat do telegram-jobs-bot (pode ser o mesmo token)
TELEGRAM_BOT_TOKEN = "SEU_TOKEN_AQUI"
TELEGRAM_CHAT_ID = "SEU_CHAT_ID_AQUI"

# Claude API — gera o texto do rascunho
ANTHROPIC_API_KEY = "SUA_CHAVE_AQUI"
CLAUDE_MODEL = "claude-opus-5"               # troque aqui se quiser um modelo mais barato

# LinkedIn API — do app criado no LinkedIn Developer Portal (veja o README)
LINKEDIN_CLIENT_ID = "..."
LINKEDIN_CLIENT_SECRET = "..."
LINKEDIN_REDIRECT_URI = "http://localhost:8000/callback"

# GitHub — fonte de "o que eu construí essa semana"
GITHUB_USERNAME = "NicolasDamasceno"        # commits de outras pessoas são ignorados
GITHUB_REPOS = ["NicolasDamasceno/LinkendIn-Bot"]   # lista de "owner/repo"
GITHUB_TOKEN = ""                            # opcional: repos privados / mais rate limit

# Fonte de conteúdo local
NOTES_FILE = "notes.md"

# Prompt enviado à Claude — ajuste tom/tamanho/temas aqui sem tocar no código
POST_SYSTEM_PROMPT = """Você escreve posts de LinkedIn em primeira pessoa, tom pessoal \
e direto (não corporativo), para um desenvolvedor focado em React, React Native, \
.NET e automações em Python. Use o material fornecido (anotações da semana e \
commits recentes) para gerar UM post entre 150 e 300 palavras sobre aprendizado \
técnico e/ou projetos pessoais. Sem emojis em excesso, no máximo 3-5 hashtags \
relevantes no final. Responda só com o texto do post, sem comentários extras."""
```

- [ ] **Step 3: Create `notes.example.md`**

```markdown
<!-- Escreva livremente durante a semana. Cada linha vira contexto pro rascunho de sexta. -->
- terminei o filtro de freelance no bot de vagas
- estudei roteamento avançado no React Native
```

- [ ] **Step 4: Add the new gitignored files to `.gitignore`**

Open `.gitignore` (repo root) and add, under the existing "Segredos e dados locais do bot de vagas" section:

```
notes.md
pending_post.json
telegram_offset.json
linkedin_token.json
```

(`config.py` is already covered by the existing unscoped `config.py` line — it applies to any directory.)

- [ ] **Step 5: Verify**

Run: `ls linkedin-post-bot/` — expect `requirements.txt`, `config.example.py`, `notes.example.md`.

Run: `git status` — expect the three new files plus modified `.gitignore`, nothing else.

- [ ] **Step 6: Commit**

```bash
git add linkedin-post-bot/requirements.txt linkedin-post-bot/config.example.py linkedin-post-bot/notes.example.md .gitignore
git commit -m "feat: scaffold linkedin-post-bot module"
```

---

### Task 2: `telegram_client.py` (shared Telegram helper)

**Files:**
- Create: `linkedin-post-bot/telegram_client.py`

- [ ] **Step 1: Write the file**

```python
"""Cliente Telegram compartilhado entre generate_post.py e check_approval.py."""

import requests

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def send_message(token, chat_id, text):
    """Envia uma mensagem de texto. Levanta requests.HTTPError em falha."""
    url = TELEGRAM_API.format(token=token, method="sendMessage")
    resp = requests.post(
        url,
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["result"]


def get_updates(token, offset=None, timeout=10):
    """Busca atualizações novas via long polling. Levanta requests.HTTPError em falha."""
    url = TELEGRAM_API.format(token=token, method="getUpdates")
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(url, params=params, timeout=timeout + 15)
    resp.raise_for_status()
    return resp.json()["result"]
```

- [ ] **Step 2: Verify — syntax**

Run: `python -m py_compile linkedin-post-bot/telegram_client.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Verify — plumbing, against the real Telegram API with a deliberately invalid token**

This confirms the URL construction and error handling are correct without needing a real bot token.

Run:
```bash
cd linkedin-post-bot && python -c "
import telegram_client
import requests
try:
    telegram_client.send_message('invalid_token_smoke_test', '123', 'hi')
    print('FAIL: should have raised')
except requests.HTTPError as e:
    print('OK: raised HTTPError as expected —', e.response.status_code)
"
```
Expected: `OK: raised HTTPError as expected — 404` (Telegram returns 404 for an unrecognized bot token in the URL path).

- [ ] **Step 4: Verify — plumbing of `get_updates`, same technique**

Run:
```bash
cd linkedin-post-bot && python -c "
import telegram_client
import requests
try:
    telegram_client.get_updates('invalid_token_smoke_test')
    print('FAIL: should have raised')
except requests.HTTPError as e:
    print('OK: raised HTTPError as expected —', e.response.status_code)
"
```
Expected: `OK: raised HTTPError as expected — 404`.

- [ ] **Step 5: Commit**

```bash
git add linkedin-post-bot/telegram_client.py
git commit -m "feat: add shared Telegram client for linkedin-post-bot"
```

---

### Task 3: `linkedin_client.py` (shared LinkedIn helper)

**Files:**
- Create: `linkedin-post-bot/linkedin_client.py`

- [ ] **Step 1: Write the file**

```python
"""Cliente LinkedIn compartilhado entre authorize_linkedin.py e check_approval.py."""

from urllib.parse import quote

import requests

AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
POSTS_URL = "https://api.linkedin.com/rest/posts"

# Versão da API do LinkedIn (formato YYYYMM). A LinkedIn publica novas
# versões periodicamente; se as chamadas começarem a falhar com erro de
# versão, confira a atual em
# https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
# e atualize esta constante.
LINKEDIN_API_VERSION = "202608"

SCOPES = "openid profile w_member_social"


def build_authorization_url(client_id, redirect_uri, state):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": SCOPES,
    }
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    return f"{AUTHORIZATION_URL}?{query}"


def exchange_code_for_token(client_id, client_secret, redirect_uri, code):
    """Troca o código de autorização por um access token. Levanta requests.HTTPError em falha."""
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def get_member_urn(access_token):
    """Descobre o URN (urn:li:person:{id}) do membro autenticado."""
    resp = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return f"urn:li:person:{resp.json()['sub']}"


def publish_post(access_token, author_urn, text):
    """Publica um post de texto público. Levanta requests.HTTPError (incluindo 401) em falha."""
    resp = requests.post(
        POSTS_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": LINKEDIN_API_VERSION,
            "Content-Type": "application/json",
        },
        json={
            "author": author_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.headers["x-restli-id"]
```

- [ ] **Step 2: Verify — syntax**

Run: `python -m py_compile linkedin-post-bot/linkedin_client.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Verify — `build_authorization_url` is pure, assert its output directly**

Run:
```bash
cd linkedin-post-bot && python -c "
import linkedin_client
url = linkedin_client.build_authorization_url('CID', 'http://localhost:8000/callback', 'STATE123')
assert url.startswith('https://www.linkedin.com/oauth/v2/authorization?')
assert 'client_id=CID' in url
assert 'state=STATE123' in url
assert 'redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fcallback' in url
assert 'scope=openid%20profile%20w_member_social' in url
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 4: Verify — plumbing of `exchange_code_for_token` against the real LinkedIn endpoint with garbage credentials**

A `400` (not a connection error or `404`) proves the URL and request shape are accepted by LinkedIn even though the credentials are fake.

Run:
```bash
cd linkedin-post-bot && python -c "
import linkedin_client
import requests
try:
    linkedin_client.exchange_code_for_token('x', 'x', 'http://localhost:8000/callback', 'x')
    print('FAIL: should have raised')
except requests.HTTPError as e:
    print('OK: raised HTTPError as expected —', e.response.status_code)
"
```
Expected: `OK: raised HTTPError as expected — 400`.

- [ ] **Step 5: Verify — plumbing of `get_member_urn` against the real LinkedIn endpoint with a garbage token**

Run:
```bash
cd linkedin-post-bot && python -c "
import linkedin_client
import requests
try:
    linkedin_client.get_member_urn('garbage_token')
    print('FAIL: should have raised')
except requests.HTTPError as e:
    print('OK: raised HTTPError as expected —', e.response.status_code)
"
```
Expected: `OK: raised HTTPError as expected — 401`.

- [ ] **Step 6: Verify — plumbing of `publish_post` against the real LinkedIn endpoint with a garbage token**

Run:
```bash
cd linkedin-post-bot && python -c "
import linkedin_client
import requests
try:
    linkedin_client.publish_post('garbage_token', 'urn:li:person:x', 'test')
    print('FAIL: should have raised')
except requests.HTTPError as e:
    print('OK: raised HTTPError as expected —', e.response.status_code)
"
```
Expected: `OK: raised HTTPError as expected — 401`. (If LinkedIn instead returns `400`/`403` for this specific combination of a malformed-but-present token, that's still a pass — the point of this check is confirming the request reaches LinkedIn and is rejected for an auth/authorization reason, not a 404/connection error, proving the endpoint URL and request shape are correct.)

- [ ] **Step 7: Commit**

```bash
git add linkedin-post-bot/linkedin_client.py
git commit -m "feat: add shared LinkedIn API client for linkedin-post-bot"
```

---

### Task 4: `authorize_linkedin.py` (one-time OAuth setup script)

**Files:**
- Create: `linkedin-post-bot/authorize_linkedin.py`

- [ ] **Step 1: Write the file**

```python
"""Setup único (e reautorização após o token expirar) do acesso à API do LinkedIn.

Uso:
    python authorize_linkedin.py
"""

import json
import os
import secrets
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import linkedin_client

TOKEN_FILE = os.path.join(os.path.dirname(__file__), "linkedin_token.json")
CALLBACK_TIMEOUT = 300  # segundos


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        self.server.captured_code = query.get("code", [None])[0]
        self.server.captured_state = query.get("state", [None])[0]
        self.server.captured_error = query.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<html><body><h1>Pode fechar esta aba.</h1></body></html>".encode("utf-8"))

    def log_message(self, format, *args):
        pass  # silencia o log padrão do http.server


def _capture_callback(port):
    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.timeout = CALLBACK_TIMEOUT
    server.captured_code = None
    server.captured_state = None
    server.captured_error = None
    server.handle_request()  # bloqueia até 1 request ou o timeout
    server.server_close()
    return server.captured_code, server.captured_state, server.captured_error


def main():
    # Importado aqui (não no topo do módulo) para que authorize_linkedin.py
    # continue importável — e testável — sem exigir um config.py real.
    from config import LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, LINKEDIN_REDIRECT_URI

    parsed = urlparse(LINKEDIN_REDIRECT_URI)
    port = parsed.port or 8000

    state = secrets.token_urlsafe(16)
    auth_url = linkedin_client.build_authorization_url(LINKEDIN_CLIENT_ID, LINKEDIN_REDIRECT_URI, state)
    print(f"Abrindo o navegador para autorizar o app:\n{auth_url}\n")
    webbrowser.open(auth_url)

    code, returned_state, error = _capture_callback(port)

    if error:
        print(f"[erro] LinkedIn recusou a autorização: {error}")
        return
    if code is None:
        print(f"[erro] Nenhum retorno recebido em {CALLBACK_TIMEOUT}s. Tente de novo.")
        return
    if returned_state != state:
        print("[erro] state não bate com o esperado — possível ataque CSRF. Abortando.")
        return

    token_data = linkedin_client.exchange_code_for_token(
        LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET, LINKEDIN_REDIRECT_URI, code
    )
    access_token = token_data["access_token"]
    author_urn = linkedin_client.get_member_urn(access_token)
    expires_at = (datetime.now() + timedelta(seconds=token_data["expires_in"])).isoformat()

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "access_token": access_token,
                "expires_at": expires_at,
                "refresh_token": token_data.get("refresh_token"),
                "author_urn": author_urn,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Autorizado como {author_urn}. Token salvo em {TOKEN_FILE}.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify — syntax**

Run: `python -m py_compile linkedin-post-bot/authorize_linkedin.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Verify — the local callback server actually captures `code`/`state` correctly**

This tests our own server logic end-to-end without touching LinkedIn at all: start `_capture_callback` in a background thread, hit its `/callback` URL ourselves with `requests.get`, and check what it captured.

Run:
```bash
cd linkedin-post-bot && python -c "
import threading
import time
import requests
import authorize_linkedin as al

result = {}

def run():
    result['value'] = al._capture_callback(8000)

t = threading.Thread(target=run)
t.start()
time.sleep(0.3)
requests.get('http://localhost:8000/callback', params={'code': 'abc123', 'state': 'xyz789'})
t.join(timeout=5)

code, state, error = result['value']
assert code == 'abc123', code
assert state == 'xyz789', state
assert error is None, error
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add linkedin-post-bot/authorize_linkedin.py
git commit -m "feat: add one-time LinkedIn OAuth authorization script"
```

---

**End of Chunk 1.** Dispatch the plan-document-reviewer subagent for this chunk before continuing to Chunk 2.
