# =========================================================
# CONFIGURAÇÃO DO BOT DE VAGAS
# Copie este arquivo para config.py e preencha os campos abaixo
# com os seus dados. config.py não é versionado (está no .gitignore).
# =========================================================

# Token do seu bot no Telegram (você recebe do @BotFather)
TELEGRAM_BOT_TOKEN = "SEU_TOKEN_AQUI"

# ID do chat para onde as vagas serão enviadas
# (pode ser o seu chat pessoal com o bot, ou um grupo/canal)
TELEGRAM_CHAT_ID = "SEU_CHAT_ID_AQUI"

# Palavras-chave que devem aparecer no título ou na descrição da vaga
# para ela ser considerada um "match" com o seu perfil.
# Dica: use termos específicos (cargo, tecnologias, área) para reduzir ruído.
KEYWORDS = [
    "Python",
    "Analista de Dados",
    "Marketing Digital",
]

# (opcional) Se quiser, pode adicionar um segundo filtro por localização.
# Deixe a lista vazia [] para não filtrar por local.
LOCATION_KEYWORDS = [
    "Remoto",
    "Brasil",
]
