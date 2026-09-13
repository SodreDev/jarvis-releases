# -*- coding: utf-8 -*-
"""
ide.project_planner — Cria scaffold de projetos via LLM ou templates.

Não depende de LLM para funcionar: se nenhum LLM estiver configurado,
cai em templates locais (python, node, web).
"""

from __future__ import annotations

from typing import List, Optional
from ide import workspace


# Templates locais — usados quando LLM não está disponível.
TEMPLATES = {
    "python": [
        ("README.md", "# {name}\n\n{description}\n\n## Instalar\n\n```bash\npython -m venv .venv\n.venv\\Scripts\\activate\npip install -r requirements.txt\n```\n"),
        ("requirements.txt", "# Adicione suas dependências aqui\n"),
        ("src/__init__.py", ""),
        ("src/main.py", '"""Entrypoint do projeto."""\n\n\ndef main() -> None:\n    print("Olá do {name}")\n\n\nif __name__ == "__main__":\n    main()\n'),
        ("tests/__init__.py", ""),
        ("tests/test_smoke.py", "def test_smoke():\n    assert 1 + 1 == 2\n"),
        (".gitignore", ".venv/\n__pycache__/\n*.pyc\n.pytest_cache/\n"),
    ],
    "node": [
        ("README.md", "# {name}\n\n{description}\n\n## Iniciar\n\n```bash\nnpm install\nnpm start\n```\n"),
        ("package.json", '{\n  "name": "{slug}",\n  "version": "0.1.0",\n  "scripts": {\n    "start": "node src/index.js"\n  }\n}\n'),
        ("src/index.js", 'console.log("Olá do {name}");\n'),
        (".gitignore", "node_modules/\n.env\n"),
    ],
    "web": [
        ("index.html", '<!DOCTYPE html>\n<html><head><meta charset="UTF-8"><title>{name}</title>\n<link rel="stylesheet" href="style.css"></head>\n<body><h1>{name}</h1><p>{description}</p>\n<script src="app.js"></script></body></html>\n'),
        ("style.css", "body { font-family: sans-serif; padding: 2rem; background: #0a0e1a; color: #d9e7ff; }\nh1 { color: #00d8ff; }\n"),
        ("app.js", 'console.log("Olá do {name}");\n'),
    ],
}


def detect_kind(description: str) -> str:
    d = (description or "").lower()
    if any(k in d for k in ["python", "django", "flask", "fastapi", "ml ", "scikit", "crawler", "scraping", "data"]):
        return "python"
    if any(k in d for k in ["react", "vue", "node", "express", "next", "typescript", "javascript backend"]):
        return "node"
    if any(k in d for k in ["html", "css", "site", "landing", "frontend", "página", "website"]):
        return "web"
    return "python"  # default


# Palavras ignoradas na geração do nome de projeto a partir de fala
_SLUG_STOPWORDS = {
    "uma", "um", "o", "a", "os", "as", "de", "do", "da", "dos", "das",
    "no", "na", "nos", "nas", "e", "com", "para", "por", "em", "ao",
    "sobre", "entre", "que", "isso", "meu", "minha", "meus", "minhas",
    "vamos", "novo", "nova", "criar", "criar", "iniciar", "comecar",
}


def iniciar_projeto(descricao: str, *, nome: Optional[str] = None, kind: Optional[str] = None) -> dict:
    """Cria scaffold completo para um projeto a partir de descrição livre.

    Retorna {slug, path, files, kind}.
    """
    if not nome:
        # Gera nome a partir das primeiras 3 palavras significativas da descrição.
        # Filtra artigos, preposições e stopwords comuns para evitar slugs como
        # "uma_calculadora_com" (correto seria "calculadora_python_html").
        words = [
            w for w in descricao.split()
            if w.isalnum() and w.lower() not in _SLUG_STOPWORDS
        ][:3]
        nome = "_".join(words).lower() or "novo_projeto"
    info = workspace.create_project(nome, description=descricao)
    slug = info["slug"]
    kind = kind or detect_kind(descricao)
    files = []
    for rel, tpl in TEMPLATES.get(kind, TEMPLATES["python"]):
        desc_safe = descricao or "Projeto criado pelo JARVIS."
        content = (
            tpl
            .replace("{name}", nome)
            .replace("{slug}", slug)
            .replace("{description}", desc_safe)
        )
        workspace.write_file(slug, rel, content)
        files.append(rel)
    return {"slug": slug, "path": info["path"], "files": files, "kind": kind}


__all__ = ["iniciar_projeto", "detect_kind", "TEMPLATES"]
