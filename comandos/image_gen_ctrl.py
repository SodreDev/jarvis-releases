# comandos/image_gen_ctrl.py — Geração de imagens via Pollinations.ai
# -*- coding: utf-8 -*-
"""
Gera imagens usando Pollinations.ai (gratuito, sem API key).

API:  GET https://image.pollinations.ai/prompt/{encoded_prompt}
      Parâmetros: width, height, model, nologo, enhance, seed
      Retorna: bytes da imagem (JPEG/PNG)

Modelos disponíveis:
  flux          → padrão, alta qualidade geral
  flux-realism  → hiper-realista, fotográfico
  turbo         → rápido (< 5s), qualidade um pouco menor
  flux-anime    → estilo anime / ilustração
  flux-3d       → renderizado 3D

O prompt é automaticamente traduzido e enriquecido para inglês via Groq
para obter melhores resultados. Se Groq falhar, envia o prompt original.
"""

from __future__ import annotations

import os
import re
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote_plus

# ─── Mapeamento de estilo → modelo Pollinations ───────────────────────────────
_STYLE_MODEL: dict[str, str] = {
    "realista":   "flux-realism",
    "realismo":   "flux-realism",
    "foto":       "flux-realism",
    "fotográfico":"flux-realism",
    "anime":      "flux-anime",
    "mangá":      "flux-anime",
    "cartoon":    "flux-anime",
    "3d":         "flux-3d",
    "três d":     "flux-3d",
    "rápido":     "turbo",
    "rapido":     "turbo",
}

_DEFAULT_MODEL = "flux"
_WIDTH  = 1024
_HEIGHT = 1024
_TIMEOUT_SECONDS = 90


def _detectar_estilo(descricao: str) -> tuple[str, str]:
    """Extrai estilo do prompt e retorna (modelo, descricao_sem_estilo)."""
    tl = descricao.lower()
    for kw, model in _STYLE_MODEL.items():
        if re.search(rf"\b{re.escape(kw)}\b", tl):
            return model, descricao
    return _DEFAULT_MODEL, descricao


def _melhorar_prompt(descricao: str, groq_client=None) -> str:
    """Usa Groq para traduzir e enriquecer o prompt para inglês.

    Se Groq não estiver disponível, retorna o prompt original.
    """
    if not groq_client:
        return descricao
    try:
        from config import GROQ_MODELO_CHAT
        resp = groq_client.chat.completions.create(
            model=GROQ_MODELO_CHAT,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert image prompt engineer. "
                        "Translate the user's description to English and expand it "
                        "into a vivid, detailed image generation prompt (1-2 sentences, max 200 chars). "
                        "Add visual details like lighting, composition, style, mood. "
                        "Output ONLY the final prompt, no explanation, no quotes."
                    ),
                },
                {"role": "user", "content": descricao},
            ],
            max_tokens=120,
            temperature=0.5,
        )
        enhanced = (resp.choices[0].message.content or "").strip().strip('"').strip("'")
        if enhanced and len(enhanced) > 10:
            print(f"[image_gen] Prompt melhorado: {enhanced[:100]}")
            return enhanced
    except Exception as e:
        print(f"[image_gen] Groq prompt-enhance falhou: {e}")
    return descricao


def gerar_imagem(
    descricao: str,
    pasta_destino: str | None = None,
    groq_client=None,
    modelo: str | None = None,
    fundo_transparente: bool = False,
) -> str:
    """Gera uma imagem via Pollinations.ai e salva localmente.

    Args:
        descricao: Descrição em PT ou EN do que gerar.
        pasta_destino: Pasta onde salvar. Default: <raiz_projeto>/temp/imagens/
        groq_client: Cliente Groq para melhorar o prompt (opcional).
        modelo: Modelo Pollinations a usar (None = auto-detectar pelo estilo).
        fundo_transparente: Se True, remove o fundo após gerar (usa rembg).
                           Útil para logos, rótulos e elementos gráficos.

    Returns:
        Caminho absoluto do arquivo PNG salvo.

    Raises:
        RuntimeError: Se o download falhar.
    """
    descricao = (descricao or "").strip()
    if not descricao:
        raise ValueError("Descrição da imagem não pode ser vazia.")

    # Auto-detecta modelo pelo estilo do prompt
    if modelo is None:
        modelo, descricao = _detectar_estilo(descricao)

    # Melhora o prompt via Groq (tradução + enriquecimento)
    prompt_en = _melhorar_prompt(descricao, groq_client)

    # Monta URL da API Pollinations
    seed = int(time.time()) % 99999
    url = (
        f"https://image.pollinations.ai/prompt/{quote_plus(prompt_en)}"
        f"?width={_WIDTH}&height={_HEIGHT}&model={modelo}"
        f"&nologo=true&enhance=true&seed={seed}"
    )

    # Pasta destino
    if pasta_destino is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pasta_destino = os.path.join(base, "temp", "imagens")
    Path(pasta_destino).mkdir(parents=True, exist_ok=True)

    # Nome do arquivo
    slug = re.sub(r"[^\w\s-]", "", descricao[:40]).strip().replace(" ", "_")
    ts   = time.strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(pasta_destino, f"jarvis_{ts}_{slug}.png")

    # Faz o download
    print(f"[image_gen] Gerando via {modelo}: {url[:100]}…")
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            dados = resp.read()
    except Exception as e:
        raise RuntimeError(f"Pollinations.ai falhou: {e}") from e

    if len(dados) < 1000:
        raise RuntimeError(f"Resposta inválida da API ({len(dados)} bytes).")

    with open(caminho, "wb") as fh:
        fh.write(dados)

    print(f"[image_gen] Imagem salva: {caminho} ({len(dados) // 1024} KB)")

    # Remoção de fundo (opcional)
    if fundo_transparente:
        caminho = _remover_fundo(caminho)

    return caminho


def _remover_fundo(caminho: str) -> str:
    """Remove o fundo da imagem usando rembg (retorna caminho do PNG-32 sem fundo).

    Se rembg não estiver instalado, retorna o caminho original sem erro.
    """
    try:
        from rembg import remove
        from PIL import Image
        import io

        with open(caminho, "rb") as fh:
            dados_in = fh.read()

        dados_out = remove(dados_in)

        # Garante que a saída é RGBA
        img = Image.open(io.BytesIO(dados_out)).convert("RGBA")
        caminho_nobg = caminho.replace(".png", "_sem_fundo.png")
        img.save(caminho_nobg, "PNG")
        print(f"[image_gen] Fundo removido: {caminho_nobg}")
        return caminho_nobg

    except ImportError:
        print("[image_gen] rembg não instalado — fundo mantido. Instale: pip install rembg")
        return caminho
    except Exception as e:
        print(f"[image_gen] Falha ao remover fundo: {e}")
        return caminho
