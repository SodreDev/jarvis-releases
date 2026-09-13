# code_gen_ctrl.py — Geração de código e scaffold de projetos pela IA
# Comandos:
#   "cria um projeto FastAPI chamado minha-api em C:\Dev"
#   "gera o código de uma classe Python para gerenciar clientes"
#   "faz a base de um bot Discord em C:\Projetos\meu-bot"
#   "cria um script Python que lê um CSV e gera um gráfico"
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path

_HOME = Path.home()

# ── Templates de scaffold conhecidos ─────────────────────────────────────────
# Cada template gera a estrutura de arquivos sem precisar da IA.
# Para projetos mais complexos / sem template → usa IA para gerar o código.

_TEMPLATES: dict[str, dict[str, str]] = {
    "fastapi": {
        "main.py": (
            'from fastapi import FastAPI\n\napp = FastAPI()\n\n\n'
            '@app.get("/")\ndef root():\n    return {"message": "Hello World"}\n'
        ),
        "requirements.txt": "fastapi\nuvicorn[standard]\n",
        "README.md": "# {nome}\n\nProjeto FastAPI gerado pelo J.A.R.V.I.S.\n\n## Executar\n\n```bash\npip install -r requirements.txt\nuvicorn main:app --reload\n```\n",
    },
    "flask": {
        "app.py": (
            'from flask import Flask\n\napp = Flask(__name__)\n\n\n'
            '@app.route("/")\ndef index():\n    return "Hello World!"\n\n\n'
            'if __name__ == "__main__":\n    app.run(debug=True)\n'
        ),
        "requirements.txt": "flask\n",
        "README.md": "# {nome}\n\nProjeto Flask gerado pelo J.A.R.V.I.S.\n\n## Executar\n\n```bash\npip install -r requirements.txt\npython app.py\n```\n",
    },
    "discord": {
        "bot.py": (
            'import discord\nfrom discord.ext import commands\nimport os\n\n'
            'intents = discord.Intents.default()\nintents.message_content = True\n'
            'bot = commands.Bot(command_prefix="!", intents=intents)\n\n\n'
            '@bot.event\nasync def on_ready():\n    print(f"Bot conectado como {bot.user}")\n\n\n'
            '@bot.command()\nasync def ping(ctx):\n    await ctx.send("Pong!")\n\n\n'
            'bot.run(os.getenv("DISCORD_TOKEN", "SEU_TOKEN_AQUI"))\n'
        ),
        "requirements.txt": "discord.py\npython-dotenv\n",
        ".env": "DISCORD_TOKEN=seu_token_aqui\n",
        "README.md": "# {nome}\n\nBot Discord gerado pelo J.A.R.V.I.S.\n\n## Executar\n\n```bash\npip install -r requirements.txt\n# Coloque seu token no .env\npython bot.py\n```\n",
    },
    "django": {
        "requirements.txt": "django\n",
        "README.md": "# {nome}\n\nProjeto Django gerado pelo J.A.R.V.I.S.\n\n## Configurar\n\n```bash\npip install -r requirements.txt\ndjango-admin startproject {nome} .\npython manage.py migrate\npython manage.py runserver\n```\n",
    },
    "script": {
        "script.py": (
            '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n"""Script gerado pelo J.A.R.V.I.S."""\n\n\n'
            'def main():\n    pass\n\n\nif __name__ == "__main__":\n    main()\n'
        ),
        "requirements.txt": "# Adicione suas dependências aqui\n",
    },
    "react": {
        "README.md": "# {nome}\n\nProjeto React gerado pelo J.A.R.V.I.S.\n\n## Criar\n\n```bash\nnpx create-react-app {nome}\ncd {nome}\nnpm start\n```\n",
        "package.json": '{{\n  "name": "{nome}",\n  "version": "1.0.0",\n  "scripts": {{\n    "start": "react-scripts start"\n  }}\n}}\n',
    },
    "node": {
        "index.js": (
            '"use strict";\n\nconst express = require("express");\nconst app = express();\nconst PORT = process.env.PORT || 3000;\n\n'
            'app.get("/", (req, res) => res.json({ message: "Hello World" }));\n\n'
            'app.listen(PORT, () => console.log(`Servidor rodando na porta ${PORT}`));\n'
        ),
        "package.json": '{{\n  "name": "{nome}",\n  "version": "1.0.0",\n  "main": "index.js",\n  "scripts": {{\n    "start": "node index.js"\n  }},\n  "dependencies": {{\n    "express": "^4.18.0"\n  }}\n}}\n',
        "README.md": "# {nome}\n\nProjeto Node.js/Express gerado pelo J.A.R.V.I.S.\n\n## Executar\n\n```bash\nnpm install\nnpm start\n```\n",
    },
}

# Mapeamento de palavras-chave → template
_KEYWORD_MAP: list[tuple[str, str]] = [
    (r"fastapi|fast\s+api",          "fastapi"),
    (r"flask",                        "flask"),
    (r"discord",                       "discord"),
    (r"django",                       "django"),
    (r"react\b",                      "react"),
    (r"node(?:\.?js)?|express",       "node"),
    (r"script\s+python|script\b",     "script"),
]


def _detectar_template(texto: str) -> str:
    """Retorna o nome do template detectado ou 'generico'."""
    tl = texto.lower()
    for pat, nome in _KEYWORD_MAP:
        if re.search(pat, tl, re.I):
            return nome
    return "generico"


def _extrair_nome_projeto(texto: str) -> str:
    """Extrai nome do projeto do texto do comando."""
    # "chamado X" | "chamada X" | "nome X" | "projeto X" | "app X" — ignora a palavra-chave
    patterns = [
        # "chamado minha-api" ou "chamada loja-virtual"
        r'chamad[ao]\s+["\']?([a-zA-Z0-9][a-zA-Z0-9_\-\s]{0,30}?)["\']?'
        r'(?:\s+(?:em|n[ao]|do|da|para)\b|$|,|\.)',
        # "nome de X"
        r'nome\s+(?:de\s+)?["\']?([a-zA-Z0-9][a-zA-Z0-9_\-\s]{0,30}?)["\']?'
        r'(?:\s+(?:em|n[ao]|do|da|para)\b|$|,|\.)',
    ]
    for pat in patterns:
        m = re.search(pat, texto, re.I)
        if m:
            nome = m.group(1).strip().rstrip(' .,;').replace(" ", "-").lower()
            if nome and nome not in ("meu", "um", "uma", "o", "a", "de"):
                return nome
    return "meu-projeto"


def _extrair_destino(texto: str) -> Path:
    """Extrai pasta de destino do comando (padrão: Desktop)."""
    # Caminhos absolutos: C:\..., D:\..., /home/...
    m = re.search(r'[A-Za-z]:[\\\/][^\s,;.!?]*|(?:\/[^\s,;.!?]+){2,}', texto)
    if m:
        raw = m.group(0).rstrip('\\/.,;!? ')
        return Path(raw)
    # Aliases
    tl = texto.lower()
    _ALIAS = [
        ("área de trabalho", _HOME / "Desktop"),
        ("area de trabalho", _HOME / "Desktop"),
        ("desktop",          _HOME / "Desktop"),
        ("documentos",       _HOME / "Documents"),
        ("documents",        _HOME / "Documents"),
        ("downloads",        _HOME / "Downloads"),
    ]
    for alias, path in _ALIAS:
        if alias in tl:
            return path
    return _HOME / "Desktop"


def scaffold_projeto(texto_cmd: str, abrir_vscode: bool = True) -> str:
    """Cria a estrutura de um projeto a partir de um template.

    Retorna mensagem de status (sem usar IA — geração instantânea).
    """
    template_key = _detectar_template(texto_cmd)
    nome         = _extrair_nome_projeto(texto_cmd)
    destino_base = _extrair_destino(texto_cmd)
    pasta_proj   = destino_base / nome

    # Se não tem template específico → só cria a pasta e informa
    if template_key == "generico":
        try:
            pasta_proj.mkdir(parents=True, exist_ok=True)
            if abrir_vscode:
                subprocess.Popen(["code", str(pasta_proj)], shell=True)
            return (f"Pasta do projeto '{nome}' criada em {destino_base}, Senhor. "
                    f"Não reconheci um template específico — abri a pasta no VSCode.")
        except Exception as e:
            return f"Erro ao criar pasta do projeto: {e}"

    template = _TEMPLATES[template_key]
    try:
        pasta_proj.mkdir(parents=True, exist_ok=True)
        for nome_arq, conteudo in template.items():
            # Substitui {nome} pelo nome do projeto
            conteudo_final = conteudo.replace("{nome}", nome)
            arq_path = pasta_proj / nome_arq
            arq_path.parent.mkdir(parents=True, exist_ok=True)
            arq_path.write_text(conteudo_final, encoding="utf-8")
    except PermissionError:
        return f"Sem permissão para criar em {destino_base}, Senhor."
    except Exception as e:
        return f"Erro ao criar estrutura do projeto: {e}"

    arquivos_criados = ", ".join(template.keys())
    msg = (f"Projeto '{nome}' ({template_key}) criado em {pasta_proj}, Senhor. "
           f"Arquivos: {arquivos_criados}.")

    if abrir_vscode:
        try:
            subprocess.Popen(["code", str(pasta_proj)], shell=True)
            msg += " Abrindo no VSCode."
        except Exception:
            pass

    return msg


def gerar_codigo_ia(texto_cmd: str, resumir_cb=None) -> str:
    """Pede para a IA gerar um trecho de código com base no comando.

    Args:
        texto_cmd: descrição do código desejado
        resumir_cb: callable(prompt) → str  (mesmo callback de _resumir_com_ia)
    """
    if not resumir_cb:
        return ("Preciso do modelo de IA ativo para gerar código, Senhor. "
                "Verifique se o LM Studio está rodando.")

    prompt = (
        "Você é um programador senior expert. O usuário pediu:\n"
        f'"{texto_cmd}"\n\n'
        "Gere o código completo e funcional conforme solicitado. "
        "Use boas práticas, adicione comentários relevantes. "
        "Responda APENAS com o código (use blocos markdown ``` com a linguagem). "
        "Sem explicações antes ou depois do código — direto ao ponto."
    )
    try:
        resultado = resumir_cb(prompt)
        return resultado or "A IA não retornou código, Senhor."
    except Exception as e:
        return f"Erro ao gerar código: {e}"
