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

---

## Chunk 2: Weekly scripts, documentation, integration

**Design note carried over from Chunk 1:** both scripts below defer `from config import (...)` to inside `main()`, and as late as possible within `main()` — after any check that doesn't actually need a config value (the "already-pending" check in `generate_post.py`, the weekday gate and the "no pending post" check in `check_approval.py`). This keeps every module importable, and several real code paths live-runnable, without a `config.py` present — same reasoning Chunk 1 applied to `authorize_linkedin.py` after review. It also means `read_notes`, `fetch_recent_commits`, `write_pending_post`, `classify_reply`, and `find_reply` all take their inputs as plain parameters instead of reading config globals directly — easier to test in isolation, and the config values only get threaded through once, in `main()`.

**Correction to spec §8 found while writing this chunk:** `get_member_urn()` (Chunk 1, `linkedin_client.py`) calls `GET /v2/userinfo`, which requires the `openid` and `profile` scopes. Those come from a **second, separate** LinkedIn Developer Portal product — "Sign In with LinkedIn using OpenID Connect" — distinct from "Share on LinkedIn" (which grants `w_member_social`, used for §8's original step 2). Spec §8 only mentioned requesting "Share on LinkedIn". This is a correction, not a new decision: without both products requested, `authorize_linkedin.py` runs but `get_member_urn()` fails with a 403 during setup. Task 7 documents both.

### Task 5: `generate_post.py`

**Files:**
- Create: `linkedin-post-bot/generate_post.py`

- [ ] **Step 1: Write the file**

```python
"""Gera o rascunho semanal de post do LinkedIn e envia para aprovação no Telegram.

Uso:
    python generate_post.py            # fluxo normal (roda via cron às sextas 17h)
    python generate_post.py --dry-run  # gera e imprime o rascunho, sem enviar nem salvar estado
"""

import argparse
import json
import os
from datetime import datetime, timedelta

import anthropic
import requests

import telegram_client

BASE_DIR = os.path.dirname(__file__)
PENDING_POST_FILE = os.path.join(BASE_DIR, "pending_post.json")
# Mantenha idêntico ao NOTES_TEMPLATE_HEADER em check_approval.py — read_notes()
# aqui só remove o cabeçalho se o texto bater exatamente com o que
# truncate_notes() (no outro script) escreve.
NOTES_TEMPLATE_HEADER = (
    "<!-- Escreva livremente durante a semana. "
    "Cada linha vira contexto pro rascunho de sexta. -->\n"
)


def load_pending_post(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_notes(notes_path):
    if not os.path.exists(notes_path):
        return ""
    with open(notes_path, "r", encoding="utf-8") as f:
        content = f.read()
    return content.replace(NOTES_TEMPLATE_HEADER, "").strip()


def fetch_recent_commits(repos, username, token):
    """Busca commits dos últimos 7 dias do `username` em cada repo de `repos`."""
    since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    commits = []
    for repo in repos:
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{repo}/commits",
                params={"since": since, "author": username},
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            for item in resp.json():
                message = item.get("commit", {}).get("message", "").splitlines()[0]
                commits.append(f"[{repo}] {message}")
        except Exception as e:
            print(f"[aviso] Erro ao buscar commits de {repo}: {e}")
    return commits


def build_draft(notes_text, commits, api_key, model, system_prompt):
    material = "Anotações da semana:\n"
    material += notes_text if notes_text else "(nenhuma anotação)"
    material += "\n\nCommits recentes:\n"
    material += "\n".join(f"- {c}" for c in commits) if commits else "(nenhum commit)"

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": material}],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


def write_pending_post(path, draft_text, telegram_message_id):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "status": "aguardando_aprovacao",
                "draft_text": draft_text,
                "created_at": datetime.now().isoformat(),
                "telegram_message_id": telegram_message_id,
                "linkedin_post_urn": None,
                "published_at": None,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pending = load_pending_post(PENDING_POST_FILE)
    if pending and pending["status"] == "aguardando_aprovacao":
        msg = (
            f"Ainda tem um post pendente de aprovação de {pending['created_at']} — "
            "aprove, edite ou cancele antes de gerar um novo."
        )
        if args.dry_run:
            print(msg)
        else:
            # Importado só aqui dentro: o caminho --dry-run desse branch não
            # precisa de nenhum valor de config.py.
            from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

            telegram_client.send_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg)
        return

    from config import (
        ANTHROPIC_API_KEY,
        CLAUDE_MODEL,
        GITHUB_REPOS,
        GITHUB_TOKEN,
        GITHUB_USERNAME,
        NOTES_FILE,
        POST_SYSTEM_PROMPT,
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID,
    )

    notes_text = read_notes(os.path.join(BASE_DIR, NOTES_FILE))
    commits = fetch_recent_commits(GITHUB_REPOS, GITHUB_USERNAME, GITHUB_TOKEN)

    if not notes_text and not commits:
        msg = "Sem novidades essa semana — pulando o post."
        if args.dry_run:
            print(msg)
        else:
            telegram_client.send_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg)
        return

    try:
        draft_text = build_draft(notes_text, commits, ANTHROPIC_API_KEY, CLAUDE_MODEL, POST_SYSTEM_PROMPT)
    except Exception as e:
        msg = f"[erro] Falha ao gerar o rascunho com a Claude API: {e}"
        print(msg)
        if not args.dry_run:
            telegram_client.send_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg)
        return

    if args.dry_run:
        print("--- RASCUNHO (dry-run, nada foi enviado ou salvo) ---")
        print(draft_text)
        return

    message_text = (
        f"📝 Rascunho do post desta semana:\n\n{draft_text}\n\n"
        "Responda:\n"
        "• \"aprovar\" — publica como está\n"
        "• \"cancelar\" — pula essa semana\n"
        "• qualquer outro texto — publica ESSE texto no lugar do rascunho"
    )
    try:
        sent = telegram_client.send_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, message_text)
    except Exception as e:
        print(f"[erro] Falha ao enviar o rascunho pro Telegram: {e}")
        return

    write_pending_post(PENDING_POST_FILE, draft_text, sent["message_id"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify — syntax**

Run: `python -m py_compile linkedin-post-bot/generate_post.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Verify — `read_notes` against a real temp file, no config needed**

Run:
```bash
cd linkedin-post-bot && python -c "
import tempfile, os
import generate_post as gp

with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8') as f:
    f.write(gp.NOTES_TEMPLATE_HEADER)
    f.write('- fiz X\n- fiz Y\n')
    path = f.name

result = gp.read_notes(path)
os.unlink(path)
assert result == '- fiz X\n- fiz Y', repr(result)
assert gp.read_notes('/nonexistent/path.md') == ''
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 4: Verify — `fetch_recent_commits` against the real, public GitHub API, using this actual repo**

This hits the real GitHub API (no mock). Note the dependency this has on timing:
this plan's own commits (Chunks 1-2) are only local until Task 8's final
`git push` — they are **not** on GitHub yet at this point in the plan. This
check only sees commits from `NicolasDamasceno` that were pushed to this
repo's remote *before* this step runs, from activity outside this plan. So
don't treat a `0` count as a failure of the function — treat it as "no
matching commits happen to be on the remote right now," and confirm the
function itself behaves correctly either way.

Run:
```bash
cd linkedin-post-bot && python -c "
import generate_post as gp

commits = gp.fetch_recent_commits(['NicolasDamasceno/LinkendIn-Bot'], 'NicolasDamasceno', '')
assert isinstance(commits, list)
print(f'{len(commits)} commit(s) found')
if commits:
    assert commits[0].startswith('[NicolasDamasceno/LinkendIn-Bot]'), commits[0]
    print(commits[0])
print('OK')
"
```
Expected: `OK`, with a commit count of 0 or more — a non-zero count (likely,
since this specific repo has had real pushed activity recently) additionally
confirms parsing of real GitHub response data; a zero count still confirms
the function completes without raising and returns the right type.

- [ ] **Step 5: Verify — pending-post reminder path runs without `config.py`, when a pending post is faked**

`build_draft` (the only function that needs `ANTHROPIC_API_KEY`) is not reachable in this path, so this exercises real control flow with zero secrets.

Run:
```bash
cd linkedin-post-bot && python -c "
import json
import generate_post as gp

with open(gp.PENDING_POST_FILE, 'w', encoding='utf-8') as f:
    json.dump({'status': 'aguardando_aprovacao', 'draft_text': 'x', 'created_at': 'now'}, f)

import sys
sys.argv = ['generate_post.py', '--dry-run']
gp.main()
"
```
Expected: prints the "ainda tem um post pendente" reminder message, no crash.

Note: `build_draft()` itself — the actual Claude API call — requires the user's real `ANTHROPIC_API_KEY` and is not exercised by any step in this plan. It's verified by the user's manual QA pass (spec §13), the same way the LinkedIn OAuth consent screen in Chunk 1 was.

- [ ] **Step 6: Clean up the `pending_post.json` created by Step 5**

Step 5 created a real `linkedin-post-bot/pending_post.json` as a side effect. Remove it now so it doesn't interfere with Task 6's verification (which checks for the *absence* of a pending post).

Run: `rm linkedin-post-bot/pending_post.json`
Expected: no output; `ls linkedin-post-bot/pending_post.json` afterward reports the file doesn't exist.

- [ ] **Step 7: Commit**

```bash
git add linkedin-post-bot/generate_post.py
git commit -m "feat: add weekly draft generation script for linkedin-post-bot"
```

---

### Task 6: `check_approval.py`

**Files:**
- Create: `linkedin-post-bot/check_approval.py`

- [ ] **Step 1: Write the file**

```python
"""Verifica aprovação do post pendente e publica no LinkedIn.

Roda via cron a cada 15 minutos; só faz algo às sextas-feiras (a menos
que --force seja passado).

Uso:
    python check_approval.py             # fluxo normal (cron)
    python check_approval.py --force     # ignora a checagem de dia da semana
    python check_approval.py --dry-run   # mostra o que seria publicado, sem publicar
"""

import argparse
import json
import os
from datetime import datetime

import requests

import linkedin_client
import telegram_client

BASE_DIR = os.path.dirname(__file__)
PENDING_POST_FILE = os.path.join(BASE_DIR, "pending_post.json")
TOKEN_FILE = os.path.join(BASE_DIR, "linkedin_token.json")
OFFSET_FILE = os.path.join(BASE_DIR, "telegram_offset.json")
# Mantenha idêntico ao NOTES_TEMPLATE_HEADER em generate_post.py — é o que
# read_notes() (no outro script) espera encontrar e remover no início do
# arquivo.
NOTES_TEMPLATE_HEADER = (
    "<!-- Escreva livremente durante a semana. "
    "Cada linha vira contexto pro rascunho de sexta. -->\n"
)

FRIDAY = 4


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def truncate_notes(notes_path):
    with open(notes_path, "w", encoding="utf-8") as f:
        f.write(NOTES_TEMPLATE_HEADER)


def classify_reply(text):
    """Interpreta a resposta do usuário: ('aprovar'|'cancelar'|'substituir', texto_substituto|None)."""
    normalized = text.strip().rstrip("!.,").lower()
    if normalized in ("aprovar", "aprovado"):
        return "aprovar", None
    if normalized == "cancelar":
        return "cancelar", None
    return "substituir", text


def find_reply(updates, chat_id):
    """Retorna (texto, next_offset) da 1ª mensagem de texto do chat configurado, ou (None, next_offset)."""
    next_offset = None
    for update in updates:
        next_offset = update["update_id"] + 1
        message = update.get("message")
        if not message or "text" not in message:
            continue
        if str(message["chat"]["id"]) != str(chat_id):
            continue
        return message["text"], next_offset
    return None, next_offset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.force and datetime.now().weekday() != FRIDAY:
        return

    pending = load_json(PENDING_POST_FILE, None)
    if not pending or pending["status"] != "aguardando_aprovacao":
        return

    from config import NOTES_FILE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

    offset_state = load_json(OFFSET_FILE, {"last_update_id": 0})
    try:
        updates = telegram_client.get_updates(TELEGRAM_BOT_TOKEN, offset=offset_state["last_update_id"] + 1)
    except Exception as e:
        print(f"[erro] Falha ao consultar o Telegram: {e}")
        return

    reply_text, next_offset = find_reply(updates, TELEGRAM_CHAT_ID)

    if reply_text is None:
        return  # nada novo ainda; próxima checagem em 15 min

    def advance_offset():
        # Só avança o offset numa resolução terminal (cancelado/publicado).
        # Se ficar sem avançar, a MESMA mensagem do Telegram é relida (e
        # reclassificada) na próxima checagem — é assim que uma falha de
        # publicação "tenta de novo com o mesmo texto" sem precisar
        # persistir o texto de substituição em lugar nenhum.
        if not args.dry_run and next_offset is not None:
            save_json(OFFSET_FILE, {"last_update_id": next_offset - 1})

    action, replacement_text = classify_reply(reply_text)
    notes_path = os.path.join(BASE_DIR, NOTES_FILE)

    if action == "cancelar":
        if args.dry_run:
            print("[dry-run] Cancelaria o post pendente.")
            return
        pending["status"] = "cancelado"
        save_json(PENDING_POST_FILE, pending)
        truncate_notes(notes_path)
        advance_offset()
        telegram_client.send_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "Post cancelado.")
        return

    text_to_publish = replacement_text if action == "substituir" else pending["draft_text"]

    if args.dry_run:
        print(f"[dry-run] Publicaria no LinkedIn:\n{text_to_publish}")
        return

    token_data = load_json(TOKEN_FILE, None)
    if not token_data:
        # Offset NÃO avança: sem token não há como publicar, então a mesma
        # resposta do usuário é relida e reprocessada na próxima checagem,
        # até authorize_linkedin.py ser rodado e o pending ser resolvido.
        telegram_client.send_message(
            TELEGRAM_BOT_TOKEN,
            TELEGRAM_CHAT_ID,
            "Não há token do LinkedIn salvo — rode authorize_linkedin.py.",
        )
        return

    try:
        post_urn = linkedin_client.publish_post(
            token_data["access_token"], token_data["author_urn"], text_to_publish
        )
    except requests.HTTPError as e:
        # Offset NÃO avança nos dois ramos abaixo: pending_post.json continua
        # aguardando_aprovacao, e a mesma resposta do Telegram (com o mesmo
        # texto a publicar) é reprocessada na próxima checagem — exatamente
        # o "retried on the next 15-minute run" da spec §11.
        if e.response is not None and e.response.status_code == 401:
            telegram_client.send_message(
                TELEGRAM_BOT_TOKEN,
                TELEGRAM_CHAT_ID,
                "Token do LinkedIn expirado — rode authorize_linkedin.py de novo. "
                "O post continua pendente e será publicado assim que reautorizar.",
            )
        else:
            telegram_client.send_message(
                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"[erro] Falha ao publicar no LinkedIn: {e}"
            )
        return
    except Exception as e:
        telegram_client.send_message(
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"[erro] Falha ao publicar no LinkedIn: {e}"
        )
        return

    pending["status"] = "publicado"
    pending["linkedin_post_urn"] = post_urn
    pending["published_at"] = datetime.now().isoformat()
    save_json(PENDING_POST_FILE, pending)
    truncate_notes(notes_path)
    advance_offset()
    telegram_client.send_message(
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID,
        f"Publicado! https://www.linkedin.com/feed/update/{post_urn}/",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify — syntax**

Run: `python -m py_compile linkedin-post-bot/check_approval.py`
Expected: no output, exit code 0.

- [ ] **Step 3: Verify — `classify_reply`, pure function, all branches**

Run:
```bash
cd linkedin-post-bot && python -c "
import check_approval as ca

assert ca.classify_reply('aprovar') == ('aprovar', None)
assert ca.classify_reply('Aprovar!') == ('aprovar', None)
assert ca.classify_reply('  aprovado.  ') == ('aprovar', None)
assert ca.classify_reply('cancelar') == ('cancelar', None)
assert ca.classify_reply('CANCELAR,') == ('cancelar', None)
assert ca.classify_reply('na verdade prefiro falar sobre X') == ('substituir', 'na verdade prefiro falar sobre X')
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 4: Verify — `find_reply`, pure function, with fake update payloads**

Run:
```bash
cd linkedin-post-bot && python -c "
import check_approval as ca

updates = [
    {'update_id': 10, 'message': {'chat': {'id': 999}, 'text': 'from another chat'}},
    {'update_id': 11, 'edited_message': {'chat': {'id': 123}, 'text': 'not a plain message'}},
    {'update_id': 12, 'message': {'chat': {'id': 123}, 'text': 'aprovar'}},
    {'update_id': 13, 'message': {'chat': {'id': 123}, 'text': 'ignored, already matched above'}},
]
text, next_offset = ca.find_reply(updates, '123')
assert text == 'aprovar', text
assert next_offset == 13, next_offset   # update_id 12 + 1, stops at the first match

assert ca.find_reply([], '123') == (None, None)
no_match = [{'update_id': 5, 'message': {'chat': {'id': 999}, 'text': 'nope'}}]
assert ca.find_reply(no_match, '123') == (None, 6)
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 5: Verify — real weekday gate, run for real (today is not Friday)**

No mocking: this genuinely exercises `datetime.now().weekday() != FRIDAY` on today's real date. Confirm no `linkedin-post-bot/pending_post.json` or `config.py` exists first (Task 5 Step 6 should already have cleaned up its temp `pending_post.json` — verify it's gone).

Run: `cd linkedin-post-bot && python check_approval.py`
Expected: no output, exit code 0, no files created or modified (the weekday gate returns before anything else runs — no `config.py` is needed for this path to work).

- [ ] **Step 6: Verify — `--force` bypasses the gate but still needs no config, since there's no pending post**

Run: `cd linkedin-post-bot && python check_approval.py --force`
Expected: no output, exit code 0 (the "no pending post" check returns before the `from config import ...` line is ever reached).

- [ ] **Step 7: Commit**

```bash
git add linkedin-post-bot/check_approval.py
git commit -m "feat: add approval-check and LinkedIn publish script for linkedin-post-bot"
```

---

### Task 7: Documentation

**Files:**
- Create: `linkedin-post-bot/README.md`
- Modify: `README.md:8-18` (root)

- [ ] **Step 1: Write `linkedin-post-bot/README.md`**

```markdown
# Agendador de Posts do LinkedIn

Toda sexta-feira, gera um rascunho de post sobre o que você andou construindo
e aprendendo (a partir de `notes.md` + commits recentes no GitHub), manda pra
você aprovar no Telegram, e publica no LinkedIn via API oficial assim que
você aprovar.

## 1. Criar o app no LinkedIn Developer Portal

1. Acesse https://www.linkedin.com/developers/apps e crie um novo app.
   A LinkedIn exige vincular o app a uma Página do LinkedIn — uma página
   simples sua (pode ser pessoal/de projeto) serve.
2. Na aba **Products** do app, solicite os dois produtos abaixo (ambos são
   self-serve, aprovação instantânea):
   - **Share on LinkedIn** — concede o scope `w_member_social` (publicar em
     nome do membro).
   - **Sign In with LinkedIn using OpenID Connect** — concede os scopes
     `openid` e `profile`, necessários pra descobrir o URN do seu próprio
     perfil (`GET /v2/userinfo`). Sem esse segundo produto, a autorização
     roda mas falha ao tentar descobrir quem é o autor do post.
3. Na aba **Auth**, adicione `http://localhost:8000/callback` como Redirect URL
   (ou a porta que você configurar em `LINKEDIN_REDIRECT_URI`).
4. Copie o **Client ID** e o **Client Secret** — vão pro `config.py` (passo 3).

## 2. Instalar dependências

```bash
cd linkedin-post-bot
pip install -r requirements.txt
```

## 3. Configurar

```bash
cp config.example.py config.py
cp notes.example.md notes.md
```

Edite `config.py`:
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — pode reaproveitar os mesmos do
  `telegram-jobs-bot`.
- `ANTHROPIC_API_KEY` — sua chave da API da Claude.
- `LINKEDIN_CLIENT_ID` / `LINKEDIN_CLIENT_SECRET` — do passo 1.
- `GITHUB_USERNAME` / `GITHUB_REPOS` — de onde vêm os commits da semana.
- `POST_SYSTEM_PROMPT` — ajuste o tom/tema se quiser.

`config.py` e `notes.md` não são versionados.

## 4. Autorizar o acesso ao LinkedIn (uma vez)

```bash
python authorize_linkedin.py
```

Abre o navegador, você faz login e autoriza o app. O token fica salvo em
`linkedin_token.json` e vale por ~60 dias. Quando expirar, os scripts
avisam no Telegram pra você rodar esse comando de novo.

## 5. Testar sem publicar de verdade

```bash
python generate_post.py --dry-run    # gera e imprime o rascunho
python check_approval.py --force --dry-run   # mostra o que seria publicado
```

## 6. Automatizar

```
# Sexta 17h — gera o rascunho e manda pra aprovação
0 17 * * 5 cd /caminho/para/LinkendIn-Bot/linkedin-post-bot && python3 generate_post.py

# A cada 15 min — publica assim que você aprovar (só age às sextas)
*/15 * * * * cd /caminho/para/LinkendIn-Bot/linkedin-post-bot && python3 check_approval.py
```

Se você aprovar depois de sexta (ex: sábado), rode manualmente:
```bash
python check_approval.py --force
```

## Checklist de teste manual (antes de confiar no cron)

- [ ] `python authorize_linkedin.py` completa e salva `linkedin_token.json`
- [ ] `python generate_post.py --dry-run` gera um rascunho que faz sentido
- [ ] `python generate_post.py` (sem `--dry-run`) manda o rascunho real pro
      Telegram
- [ ] Responder "aprovar" e rodar `python check_approval.py --force` publica
      de verdade no LinkedIn — confira o link que o bot manda de volta
- [ ] Repetir gerando um novo rascunho e respondendo "cancelar" — confirme
      que nada é publicado
- [ ] Repetir gerando um novo rascunho e respondendo com um texto qualquer —
      confirme que esse texto (não o rascunho original) é o que é publicado

## Manutenção

- Token do LinkedIn expira a cada ~60 dias — reautorize quando avisado.
- `LINKEDIN_API_VERSION` em `linkedin_client.py` pode precisar de atualização
  periódica — se as chamadas começarem a falhar, confira a versão atual em
  https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
```

- [ ] **Step 2: Update the root `README.md`**

Read `README.md:8-18` first, then replace the "Módulo 2" section:

Old:
```markdown
### 2. Agendador de postagem semanal — 🚧 próximo passo

Ainda não iniciado. Direções possíveis: usar a API oficial do LinkedIn
(`w_member_social`, via app registrado no LinkedIn Developer Portal) ou,
como alternativa mais simples, uma ferramenta de agendamento pronta
(Buffer, Hootsuite, Publer) ou o agendamento nativo do próprio LinkedIn.
```

New:
```markdown
### 2. Agendador de posts do LinkedIn — ✅ pronto (requer setup manual do LinkedIn App)

Fica em [`linkedin-post-bot/`](linkedin-post-bot/). Toda sexta, gera um
rascunho de post (a partir de anotações da semana + commits recentes do
GitHub, via API da Claude), manda pra aprovação no Telegram, e publica no
LinkedIn através da API oficial (`w_member_social`) assim que aprovado —
sem SaaS de terceiros, sem scraping. Veja o
[README do módulo](linkedin-post-bot/README.md) para o setup (requer criar
um app no LinkedIn Developer Portal — único passo manual).
```

- [ ] **Step 3: Verify**

Run: `git diff README.md` — confirm only the Módulo 2 section changed.
Run: `python -m py_compile linkedin-post-bot/*.py` (or compile each file
individually if the shell doesn't glob) — expect no output, exit 0, covering
every script written so far including this chunk's two.

- [ ] **Step 4: Commit**

```bash
git add linkedin-post-bot/README.md README.md
git commit -m "docs: add linkedin-post-bot module README and update root README"
```

---

### Task 8: Final integration pass

**Files:** none new — verification only.

- [ ] **Step 1: Compile every file in the module together**

Run:
```bash
cd linkedin-post-bot && python -m py_compile telegram_client.py linkedin_client.py authorize_linkedin.py generate_post.py check_approval.py
```
Expected: no output, exit code 0.

- [ ] **Step 2: Confirm no leftover test artifacts from earlier steps**

Run: `ls linkedin-post-bot/` — expect exactly: `telegram_client.py`,
`linkedin_client.py`, `authorize_linkedin.py`, `generate_post.py`,
`check_approval.py`, `config.example.py`, `notes.example.md`,
`requirements.txt`, `README.md`, plus any `__pycache__/` (gitignored by the
existing root `.gitignore` `__pycache__/` rule). No `config.py`, `notes.md`,
`pending_post.json`, `telegram_offset.json`, or `linkedin_token.json` should
be present — those only get created by a real user setup, and Task 5 Step 6's
temp `pending_post.json` should already have been deleted per its own
instructions. If any of the five gitignored files are present from testing,
delete them now.

- [ ] **Step 3: Confirm `git status` is clean of anything unexpected**

Run: `git status`
Expected: clean working tree (everything from Tasks 5-7 already committed) — if anything unstaged remains from a verification step's side effect, review it before deciding whether to commit or discard it.

- [ ] **Step 4: Push**

```bash
git push origin claude/initial-repo-commit-1fqgx9
```

