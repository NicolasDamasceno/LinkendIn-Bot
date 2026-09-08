"""
Bot de vagas para Telegram.

Busca vagas em fontes públicas (RemoteOK, Arbeitnow e Remotive), filtra
pelas palavras-chave definidas em config.py e envia as vagas novas para
o seu Telegram. Vagas já enviadas ficam registradas em sent_jobs.json
para não serem repetidas.

Workana, 99Freelas e Upwork ficaram de fora: nenhum dos três oferece uma
API pública de busca de vagas sem autenticação (a da Upwork exige OAuth
e só enxerga dados da sua própria conta), então buscar vagas ali exigiria
scraping — o que viola os Termos de Uso dessas plataformas. O Remotive
entrou no lugar por marcar explicitamente o tipo de contrato de cada vaga
("freelance", "contract", "full_time"...), o que ajuda a filtrar trabalhos
freelancer mesmo quando a palavra não aparece no título/descrição.

Uso:
    python bot.py

Para rodar automaticamente de tempos em tempos, agende este script
via cron (Linux/Mac) ou Agendador de Tarefas (Windows). Veja o
README.md para instruções.
"""

import json
import os
from datetime import datetime

import requests

from config import (
    KEYWORDS,
    LOCATION_KEYWORDS,
    SENIORITY_KEYWORDS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

SENT_JOBS_FILE = os.path.join(os.path.dirname(__file__), "sent_jobs.json")


def load_sent_jobs():
    if os.path.exists(SENT_JOBS_FILE):
        with open(SENT_JOBS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_sent_jobs(sent_jobs):
    with open(SENT_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(sent_jobs), f, ensure_ascii=False, indent=2)


def matches_keywords(text, keywords):
    if not keywords:
        return True
    text = text.lower()
    return any(k.lower() in text for k in keywords)


def fetch_remoteok_jobs():
    """Busca vagas na API pública do RemoteOK."""
    jobs = []
    try:
        resp = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "Mozilla/5.0 (compatible; JobsBot/1.0)"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        # O primeiro item da lista costuma ser metadado, não vaga
        for item in data:
            if not isinstance(item, dict) or "id" not in item:
                continue
            jobs.append(
                {
                    "id": f"remoteok_{item.get('id')}",
                    "title": item.get("position", "Vaga sem título"),
                    "company": item.get("company", "Empresa não informada"),
                    "location": item.get("location") or "Remoto",
                    "url": item.get("url", "https://remoteok.com"),
                    "description": item.get("description", "") or "",
                    "employment_type": "",
                    "source": "RemoteOK",
                }
            )
    except Exception as e:
        print(f"[aviso] Erro ao buscar vagas no RemoteOK: {e}")
    return jobs


def fetch_arbeitnow_jobs():
    """Busca vagas na API pública do Arbeitnow."""
    jobs = []
    try:
        resp = requests.get(
            "https://www.arbeitnow.com/api/job-board-api", timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data", []):
            jobs.append(
                {
                    "id": f"arbeitnow_{item.get('slug')}",
                    "title": item.get("title", "Vaga sem título"),
                    "company": item.get("company_name", "Empresa não informada"),
                    "location": item.get("location") or "Remoto",
                    "url": item.get("url", "https://arbeitnow.com"),
                    "description": item.get("description", "") or "",
                    "employment_type": "",
                    "source": "Arbeitnow",
                }
            )
    except Exception as e:
        print(f"[aviso] Erro ao buscar vagas no Arbeitnow: {e}")
    return jobs


def fetch_remotive_jobs():
    """Busca vagas na API pública do Remotive (inclui vagas freelance/contrato).

    A Remotive pede, nos termos da própria API, no máximo ~4 chamadas por
    dia e que os links apontem de volta para remotive.com — por isso não
    reduza demais o intervalo do cron abaixo do sugerido no README.
    """
    jobs = []
    try:
        resp = requests.get("https://remotive.com/api/remote-jobs", timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("jobs", []):
            jobs.append(
                {
                    "id": f"remotive_{item.get('id')}",
                    "title": item.get("title", "Vaga sem título"),
                    "company": item.get("company_name", "Empresa não informada"),
                    "location": item.get("candidate_required_location") or "Remoto",
                    "url": item.get("url", "https://remotive.com"),
                    "description": item.get("description", "") or "",
                    "employment_type": item.get("job_type", ""),
                    "source": "Remotive",
                }
            )
    except Exception as e:
        print(f"[aviso] Erro ao buscar vagas no Remotive: {e}")
    return jobs


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, json=payload, timeout=15)
    if not resp.ok:
        print(f"[erro] Falha ao enviar mensagem no Telegram: {resp.text}")


def format_job_message(job):
    tipo = job.get("employment_type", "")
    linha_tipo = f"🧾 Tipo: {tipo}\n" if tipo else ""
    return (
        f"💼 <b>{job['title']}</b>\n"
        f"🏢 {job['company']}\n"
        f"📍 {job['location']}\n"
        f"{linha_tipo}"
        f"📡 Fonte: {job['source']}\n"
        f"🔗 <a href=\"{job['url']}\">Ver vaga</a>"
    )


def main():
    if TELEGRAM_BOT_TOKEN == "SEU_TOKEN_AQUI":
        print(
            "[erro] Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID em config.py "
            "antes de rodar o bot."
        )
        return

    sent_jobs = load_sent_jobs()
    all_jobs = fetch_remoteok_jobs() + fetch_arbeitnow_jobs() + fetch_remotive_jobs()

    new_matches = []
    for job in all_jobs:
        if job["id"] in sent_jobs:
            continue
        title_and_description = (
            f"{job['title']} {job['description']} {job.get('employment_type', '')}"
        )
        if (
            matches_keywords(title_and_description, KEYWORDS)
            and (not LOCATION_KEYWORDS or matches_keywords(job["location"], LOCATION_KEYWORDS))
            and (not SENIORITY_KEYWORDS or matches_keywords(title_and_description, SENIORITY_KEYWORDS))
        ):
            new_matches.append(job)

    print(f"[{datetime.now()}] {len(new_matches)} vaga(s) nova(s) encontrada(s).")

    for job in new_matches:
        send_telegram_message(format_job_message(job))
        sent_jobs.add(job["id"])

    save_sent_jobs(sent_jobs)


if __name__ == "__main__":
    main()
