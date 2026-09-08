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
    # React / Front-end
    "React",
    "React.js",
    "ReactJS",
    "Front-end React",
    "Frontend React",
    # React Native / Mobile
    "React Native",
    "Mobile Developer",
    # .NET
    ".NET",
    "C#",
    "ASP.NET",
    "Dotnet",
    # Python / automações
    "Python",
    "Automação Python",
    "Python Developer",
    "RPA",
]

# (opcional) Se quiser, pode adicionar um segundo filtro por localização.
# Deixe a lista vazia [] para não filtrar por local.
LOCATION_KEYWORDS = [
    "Remoto",
    "Brasil",
]

# (opcional) Funil de senioridade: a vaga só passa se o título ou a
# descrição citarem um destes termos. Deixe a lista vazia [] para não
# filtrar por nível (por exemplo, quando você não for mais júnior).
SENIORITY_KEYWORDS = [
    "Júnior",
    "Junior",
    "Jr",
    "Trainee",
    "Estágio",
    "Entry level",
    "Entry-level",
]
