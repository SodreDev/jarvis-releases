# comandos/pdf_ctrl.py — Extração de texto de PDFs para resumo/estudo
# -*- coding: utf-8 -*-
"""
Usa PyMuPDF (fitz) para extrair texto de arquivos PDF.
Suporta:
  - Caminho direto do arquivo
  - Busca do PDF mais recente na pasta Downloads
  - Busca por nome parcial na pasta Downloads
"""

import os
import glob
import re
import unicodedata
import fitz  # PyMuPDF

# Mapa de números por extenso → dígitos
_WORD_TO_NUM: dict[str, int] = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
    "nove": 9, "dez": 10,
}


def _normalizar(s: str) -> str:
    """Remove acentos e converte para minúsculas."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    ).lower()


def palavras_para_numero(texto: str) -> str:
    """Substitui números por extenso por dígitos no texto."""
    resultado = texto
    for palavra, num in _WORD_TO_NUM.items():
        resultado = re.sub(
            rf"\b{palavra}\b", str(num), resultado, flags=re.IGNORECASE
        )
    return resultado


def _pasta_downloads() -> str:
    """Retorna o caminho da pasta Downloads do usuário."""
    # Windows: USERPROFILE\Downloads
    home = os.path.expanduser("~")
    downloads = os.path.join(home, "Downloads")
    if os.path.isdir(downloads):
        return downloads
    # Fallback: pasta do usuário
    return home


def encontrar_pdf(referencia: str = "") -> str | None:
    """Encontra um PDF baseado na referência do usuário.
    
    - Se referencia é um caminho absoluto que existe → retorna ele
    - Se referencia contém nome parcial → busca na Downloads
    - Se referencia está vazia → retorna o PDF mais recente da Downloads
    """
    referencia = referencia.strip().strip('"').strip("'")

    # 1. Caminho absoluto direto
    if referencia and os.path.isfile(referencia) and referencia.lower().endswith(".pdf"):
        return referencia

    # 2. Caminho com extensão implícita
    if referencia and os.path.isfile(referencia + ".pdf"):
        return referencia + ".pdf"

    pasta = _pasta_downloads()

    # 3. Busca por nome parcial na Downloads (com fuzzy/normalização)
    if referencia:
        nome_busca = re.sub(r"\.pdf$", "", referencia, flags=re.IGNORECASE).strip()
        busca_norm = _normalizar(nome_busca)
        # Normaliza variantes: "capítulo" → "cap", espaços → underscores
        busca_alt = re.sub(r"cap[ií]tulo", "cap", busca_norm)
        busca_alt_under = busca_alt.replace(" ", "_")

        pdfs = glob.glob(os.path.join(pasta, "*.pdf"))

        # Tenta match direto, depois normalizado, depois com underscore
        for variante in (busca_norm, busca_alt, busca_alt_under):
            matches = [
                p for p in pdfs
                if variante in _normalizar(os.path.basename(p))
            ]
            if matches:
                matches.sort(key=os.path.getmtime, reverse=True)
                return matches[0]

        # Tenta match por tokens individuais (ex: "2" e "epitelial")
        tokens = [t for t in re.split(r"[\s_]+", busca_alt) if len(t) >= 1]
        if len(tokens) >= 2:
            matches = [
                p for p in pdfs
                if all(tk in _normalizar(os.path.basename(p)) for tk in tokens)
            ]
            if matches:
                matches.sort(key=os.path.getmtime, reverse=True)
                return matches[0]

    # 4. PDF mais recente da Downloads
    pdfs = glob.glob(os.path.join(pasta, "*.pdf"))
    if not pdfs:
        return None
    pdfs.sort(key=os.path.getmtime, reverse=True)
    return pdfs[0]


def extrair_texto(caminho: str, max_paginas: int = 0) -> tuple[str, int, str]:
    """Extrai texto de um PDF.
    
    Args:
        caminho: Caminho completo do arquivo PDF.
        max_paginas: Limite de páginas (0 = todas).
    
    Returns:
        (texto_completo, total_paginas, nome_arquivo)
    """
    if not os.path.isfile(caminho):
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    nome = os.path.basename(caminho)
    doc = fitz.open(caminho)
    total = doc.page_count
    limite = min(total, max_paginas) if max_paginas > 0 else total

    partes = []
    for i in range(limite):
        page = doc[i]
        texto = page.get_text("text")
        if texto.strip():
            partes.append(f"[Página {i+1}]\n{texto.strip()}")

    doc.close()

    texto_completo = "\n\n".join(partes)
    return texto_completo, total, nome


def encontrar_pdfs_recentes(n: int = 3) -> list[str]:
    """Retorna os *n* PDFs mais recentes da pasta Downloads."""
    pasta = _pasta_downloads()
    pdfs = glob.glob(os.path.join(pasta, "*.pdf"))
    if not pdfs:
        return []
    pdfs.sort(key=os.path.getmtime, reverse=True)
    return pdfs[:n]


def encontrar_multiplos(referencias: list[str], n_recentes: int = 3) -> list[str]:
    """
    Resolve uma lista de referências em caminhos de PDF.
    Se a lista estiver vazia, retorna os *n_recentes* mais recentes.
    Cada referência passa por ``encontrar_pdf``; referências não
    encontradas são ignoradas com aviso no stdout.
    """
    if not referencias:
        return encontrar_pdfs_recentes(n_recentes)

    caminhos: list[str] = []
    for ref in referencias:
        ref = ref.strip()
        if not ref:
            continue
        caminho = encontrar_pdf(ref)
        if caminho:
            if caminho not in caminhos:
                caminhos.append(caminho)
        else:
            print(f"[PDF] Não encontrado: '{ref}'")
    return caminhos


def extrair_de_referencia(referencia: str = "", max_paginas: int = 0) -> tuple[str, int, str, str]:
    """Encontra e extrai texto de um PDF.
    
    Returns:
        (texto, total_paginas, nome_arquivo, caminho_completo)
    
    Raises:
        FileNotFoundError se não encontrar nenhum PDF.
    """
    caminho = encontrar_pdf(referencia)
    if not caminho:
        if referencia:
            raise FileNotFoundError(
                f"Não encontrei o PDF '{referencia}' na pasta Downloads."
            )
        raise FileNotFoundError(
            "Não encontrei nenhum PDF na pasta Downloads."
        )

    texto, total, nome = extrair_texto(caminho, max_paginas)
    return texto, total, nome, caminho
