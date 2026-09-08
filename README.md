# LinkedIn Bot

Automações para apoiar a busca de vagas e a presença no LinkedIn, respeitando
os Termos de Uso da plataforma (sem scraping nem automação de ações na conta).

## Módulos

### 1. Bot de vagas para Telegram — ✅ pronto

Fica em [`telegram-jobs-bot/`](telegram-jobs-bot/). Busca vagas nas APIs
públicas do **RemoteOK**, **Arbeitnow** e **Remotive** (esta última já marca
o tipo de contrato de cada vaga — CLT, freelance, contrato — permitindo
filtrar trabalhos freelancer), filtra pelas palavras-chave do seu perfil e
envia as novidades para o seu Telegram, evitando repetir vagas já enviadas.
Veja o [README do módulo](telegram-jobs-bot/README.md) para instruções de
configuração e uso.

**Workana, 99Freelas e Upwork ficaram de fora**: nenhuma das três oferece
API pública de busca de vagas sem autenticação, e fazer scraping violaria os
Termos de Uso — a mesma razão pela qual este projeto não faz scraping do
LinkedIn.

Para vagas específicas do LinkedIn, a alternativa recomendada é usar o
alerta de vaga nativo por e-mail do LinkedIn e encaminhar esses e-mails para
o Telegram via Zapier/Make.com — sem violar os termos de uso.

### 2. Agendador de postagem semanal — 🚧 próximo passo

Ainda não iniciado. Direções possíveis: usar a API oficial do LinkedIn
(`w_member_social`, via app registrado no LinkedIn Developer Portal) ou,
como alternativa mais simples, uma ferramenta de agendamento pronta
(Buffer, Hootsuite, Publer) ou o agendamento nativo do próprio LinkedIn.

### Curtidas automáticas — ❌ descartado

O LinkedIn não tem API pública para curtir posts em nome do usuário, e
simular isso via automação de navegador (Selenium/Puppeteer) viola os
Termos de Uso da plataforma, com risco real de suspensão de conta. Por
isso esse recurso não faz parte do projeto.

## Estrutura

```
LinkendIn-Bot/
├── README.md                        # este arquivo
├── .gitignore
└── telegram-jobs-bot/
    ├── bot.py                       # script principal
    ├── config.example.py            # modelo de configuração (sem segredos)
    ├── requirements.txt
    └── README.md                    # instruções de uso detalhadas
```
