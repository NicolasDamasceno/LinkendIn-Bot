# Bot de Vagas para Telegram

Busca vagas em fontes públicas (RemoteOK e Arbeitnow), filtra pelo seu perfil
e envia as novidades direto no seu Telegram.

> **Por que não busca direto no LinkedIn?** O LinkedIn não oferece uma API
> pública de vagas para aplicações de terceiros, e raspar (fazer scraping)
> o site viola os Termos de Uso da plataforma, com risco de bloqueio da
> sua conta. Por isso este bot usa fontes abertas e legítimas. Se quiser
> vagas específicas do LinkedIn, veja a seção "Vagas do LinkedIn" no final.

## 1. Criar o bot no Telegram

1. Abra o Telegram e converse com **@BotFather**
2. Envie `/newbot` e siga as instruções (nome + username do bot)
3. O BotFather vai te dar um **token** — copie e cole em `config.py` no
   campo `TELEGRAM_BOT_TOKEN`

## 2. Descobrir o seu chat_id

1. Envie qualquer mensagem para o bot que você acabou de criar
2. Acesse no navegador (trocando SEU_TOKEN):
   `https://api.telegram.org/botSEU_TOKEN/getUpdates`
3. Procure o campo `"chat":{"id":...}` — esse número é o seu `TELEGRAM_CHAT_ID`
4. Cole em `config.py`

## 3. Instalar dependências

```bash
cd telegram-jobs-bot
pip install -r requirements.txt
```

## 4. Configurar seu perfil

Copie `config.example.py` para `config.py`:

```bash
cp config.example.py config.py
```

Depois abra `config.py` e edite:
- `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`: dados obtidos nos passos 1 e 2
- `KEYWORDS`: palavras-chave do seu perfil (cargo, tecnologias, área)
- `LOCATION_KEYWORDS`: filtro de localização (ou `[]` para não filtrar)
- `SENIORITY_KEYWORDS`: funil de senioridade — a vaga só passa se citar um
  desses termos (ex: "Júnior", "Trainee", "Estágio"). Deixe `[]` para não
  filtrar por nível (útil quando você não for mais júnior)

`config.py` não é versionado (está no `.gitignore`), então seus dados
ficam só na sua máquina.

## 5. Rodar

```bash
python bot.py
```

Na primeira vez ele vai varrer as vagas atuais e te mandar as que derem
match. Nas próximas execuções, só manda o que for **novo**.

## 6. Automatizar (rodar sozinho de tempos em tempos)

**Linux/Mac (cron):** edite o crontab com `crontab -e` e adicione, por
exemplo, para rodar a cada 2 horas:

```
0 */2 * * * cd /caminho/para/LinkendIn-Bot/telegram-jobs-bot && /usr/bin/python3 bot.py
```

**Windows:** use o Agendador de Tarefas para rodar `bot.py` no intervalo
desejado.

## Vagas do LinkedIn

O LinkedIn tem alertas de vaga nativos (na busca de vagas, ative "Criar
alerta de vaga" para receber por e-mail). Se quiser que esses e-mails
também caiam no Telegram, dá pra usar uma automação sem código como
Zapier ou Make.com com a regra "novo e-mail com esse assunto → mandar
mensagem no Telegram" — isso não envolve automação ou scraping da conta,
só encaminhar um e-mail que o próprio LinkedIn te manda.
