# comandos/file_ctrl.py
# -*- coding: utf-8 -*-
"""Controle de arquivos e pastas via comandos de voz."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

# ── Atalhos de pastas comuns ──────────────────────────────────────────────────
_HOME = Path.home()

_ALIAS: list[tuple[str, Path]] = sorted([
    ("área de trabalho",     _HOME / "Desktop"),
    ("area de trabalho",     _HOME / "Desktop"),
    ("desktop",              _HOME / "Desktop"),
    ("downloads",            _HOME / "Downloads"),
    ("documentos",           _HOME / "Documents"),
    ("documents",            _HOME / "Documents"),
    ("musica",               _HOME / "Music"),
    ("musicas",              _HOME / "Music"),
    ("música",               _HOME / "Music"),
    ("imagens",              _HOME / "Pictures"),
    ("fotos",                _HOME / "Pictures"),
    ("pictures",             _HOME / "Pictures"),
    ("videos",               _HOME / "Videos"),
    ("vídeos",               _HOME / "Videos"),
    ("temp",                 Path(os.environ.get("TEMP", str(_HOME / "AppData" / "Local" / "Temp")))),
], key=lambda kv: -len(kv[0]))


def _resolver_caminho(texto: str) -> Path | None:
    """
    Extrai um caminho de uma frase em linguagem natural.
    Aceita caminhos absolutos (C:\\...), aliases de pastas comuns ou
    nomes previamente aprendidos (learned_locations + quick_scan).
    """
    t = texto.strip()

    # 1. Caminho absoluto com drive letter — C:\..., D:\...  (com ou sem aspas)
    m = re.search(r'["\']?([A-Za-z]:[\\\/][^"\']+?)["\']?(?:\s|$|,|;)', t)
    if m:
        raw = m.group(1).rstrip('\\/.,;!? ')
        return Path(raw)

    # 2. Caminho Unix — /home/..., /mnt/...
    m = re.search(r'(\/[^\s,;.!?"\']+)', t)
    if m:
        raw = m.group(1).rstrip('\\/.,;!? ')
        return Path(raw)

    # 3. Alias (procura o mais longo que bater)
    tl = t.lower()
    for alias, caminho in _ALIAS:
        if alias in tl:
            return caminho

    # 4. Nomes aprendidos / quick scan no FS
    try:
        from core import filesystem_indexer as _fsi
        # Extrai o "alvo" — palavras após "pasta/projeto/jogo X"
        m2 = re.search(
            r"(?:pasta|projeto|jogo|diret[oó]rio|folder)\s+(?:do\s+|da\s+|de\s+)?(.+?)(?:\s+(?:no|na|em|do|da)\b|$)",
            t, re.I,
        )
        candidato = (m2.group(1) if m2 else t).strip(" .,;!?\"'")
        if candidato and len(candidato) >= 2:
            hit = _fsi.find_path(candidato)
            if hit and Path(hit["path"]).exists():
                return Path(hit["path"])
    except Exception:
        pass

    return None


def _extrair_nome(texto: str) -> str:
    """Extrai o nome de pasta/arquivo de uma frase."""
    patterns = [
        r'chamad[ao]\s+["\']?([^\s,;.!?"\']+(?:\s+[^\s,;.!?"\']+)*?)["\']?(?:\s+(?:em|na?|no|do|da)\b|$)',
        r'(?:com\s+)?nome\s+["\']?([^\s,;.!?"\']+(?:\s+[^\s,;.!?"\']+)*?)["\']?(?:\s+(?:em|na?|no|do|da)\b|$)',
        r'nomeada?\s+["\']?([^\s,;.!?"\']+)["\']?(?:\s|$)',
        r'^["\'](.+?)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, texto, re.I)
        if m:
            nome = m.group(1).strip().rstrip('.,;!? ')
            if nome:
                return nome
    return ""


def _fmt_size(bytes_: int | float) -> str:
    """Formata tamanho em bytes para leitura humana."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes_ < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} PB"


def _tam_pasta(path: Path, limit: int = 5000) -> int:
    """Retorna tamanho total de uma pasta em bytes (recursivo, limitado a `limit` arquivos)."""
    total = 0
    count = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
                count += 1
                if count >= limit:
                    break
    except Exception:
        pass
    return total


# ── Operações ─────────────────────────────────────────────────────────────────

def criar_pasta(texto_cmd: str) -> str:
    """Cria uma pasta a partir de um comando em linguagem natural."""
    # 1. Extrai o nome
    nome = _extrair_nome(texto_cmd)
    if not nome:
        # fallback: primeira palavra após "pasta/diretório/folder"
        m = re.search(
            r'\b(?:pasta|diret[oó]rio|folder)\s+["\']?([^\s,;.!?"\']+)["\']?',
            texto_cmd, re.I,
        )
        if m:
            nome = m.group(1).strip().rstrip('.,;!?')
    if not nome:
        return ("Não entendi o nome da pasta, Senhor. "
                "Tente: 'cria uma pasta chamada Projetos na área de trabalho'.")

    # 2. Extrai localização (padrão: Desktop)
    destino_base = _resolver_caminho(texto_cmd) or (_HOME / "Desktop")
    full_path = destino_base / nome

    try:
        full_path.mkdir(parents=True, exist_ok=True)
        return f"Pasta '{nome}' criada em {full_path.parent}, Senhor."
    except PermissionError:
        return f"Sem permissão para criar em {full_path.parent}, Senhor."
    except Exception as e:
        return f"Não foi possível criar a pasta: {e}"


def listar_arquivos(texto_cmd: str) -> str:
    """Lista arquivos e pastas de um diretório."""
    pasta = _resolver_caminho(texto_cmd) or (_HOME / "Desktop")

    if not pasta.exists():
        return f"Pasta não encontrada: {pasta}"
    if not pasta.is_dir():
        return f"'{pasta.name}' não é uma pasta, Senhor."

    try:
        itens = sorted(pasta.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return f"Sem permissão para acessar {pasta}, Senhor."

    if not itens:
        return f"A pasta '{pasta.name}' está vazia, Senhor."

    pastas_sub = [i for i in itens if i.is_dir()]
    arquivos    = [i for i in itens if i.is_file()]
    linhas = [f"📂 {pasta}  —  {len(itens)} itens:"]
    if pastas_sub:
        linhas.append(f"  🗂 Pastas ({len(pastas_sub)}): " +
                      ", ".join(p.name for p in pastas_sub[:10]) +
                      ("..." if len(pastas_sub) > 10 else ""))
    if arquivos:
        linhas.append(f"  📄 Arquivos ({len(arquivos)}): " +
                      ", ".join(a.name for a in arquivos[:15]) +
                      ("..." if len(arquivos) > 15 else ""))
    return "\n".join(linhas)


def buscar_arquivos(texto_cmd: str) -> str:
    """Busca arquivos por extensão ou nome em uma pasta."""
    tl = texto_cmd.lower()

    # Extensão: ".py", ".pdf", "python", "pdf"
    m_ext = re.search(r'\.([a-z0-9]{1,6})\b', tl)
    ext = ("." + m_ext.group(1)) if m_ext else ""

    # Pasta raiz da busca
    pasta = _resolver_caminho(texto_cmd) or _HOME

    # Filtro de data (modificados hoje)
    hoje          = datetime.now().date()
    filtrar_hoje  = bool(re.search(r'\bhoje\b|\brecent[es]*\b', tl, re.I))

    try:
        padrao = f"*{ext}" if ext else "*"
        encontrados: list[Path] = []
        for arq in pasta.rglob(padrao):
            if arq.is_file():
                if filtrar_hoje:
                    if datetime.fromtimestamp(arq.stat().st_mtime).date() != hoje:
                        continue
                encontrados.append(arq)
                if len(encontrados) >= 20:
                    break

        if not encontrados:
            sufixo = " modificados hoje" if filtrar_hoje else ""
            return f"Nenhum arquivo{' ' + ext if ext else ''}{sufixo} encontrado em {pasta}, Senhor."

        linhas = [f"Encontrei {len(encontrados)} arquivo(s):"]
        for arq in encontrados:
            data = datetime.fromtimestamp(arq.stat().st_mtime).strftime("%d/%m %H:%M")
            linhas.append(f"  {arq.name}  ({data})  ← {arq.parent}")
        return "\n".join(linhas)
    except PermissionError:
        return f"Sem permissão para buscar em {pasta}, Senhor."


def info_pasta(texto_cmd: str) -> str:
    """Retorna tamanho e informações de uma pasta ou arquivo."""
    alvo = _resolver_caminho(texto_cmd)
    if alvo is None:
        alvo = _HOME / "Downloads"

    if not alvo.exists():
        return f"Pasta/arquivo não encontrado: {alvo}"

    if alvo.is_file():
        try:
            st   = alvo.stat()
            data = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")
            return (f"Arquivo: {alvo.name}\n"
                    f"  Tamanho: {_fmt_size(st.st_size)}\n"
                    f"  Modificado: {data}")
        except Exception as e:
            return f"Erro ao obter info: {e}"

    try:
        n_arqs = 0
        n_dirs = sum(1 for _ in alvo.iterdir() if _.is_dir())
        for _ in alvo.rglob("*"):
            if _.is_file():
                n_arqs += 1
                if n_arqs >= 5000:  # cap para pastas grandes
                    break
        tam    = _tam_pasta(alvo)
        aprox  = "+" if n_arqs >= 5000 else ""
        return (f"Pasta: {alvo}\n"
                f"  Tamanho total: {_fmt_size(tam)}\n"
                f"  Arquivos: {n_arqs}{aprox}  |  Subpastas: {n_dirs}")
    except PermissionError:
        return f"Sem permissão para acessar {alvo}, Senhor."


def renomear(texto_cmd: str) -> str:
    """Renomeia um arquivo ou pasta."""
    # Remove prefixos descritivos antes do nome de origem:
    # "renomeie o projeto X para Y", "renomeie a pasta X como Y", "renomeia X para Y"
    texto_limpo = re.sub(
        r'\b(?:renomei[ae]r?|renomear?|muda[r]?\s+(?:o\s+)?nome\s+d[eo])\s+'
        r'(?:o\s+|a\s+|os\s+|as\s+)?'
        r'(?:arquivo|pasta|diret[oó]rio|projeto|folder|chamad[oa]\s+)?\s*',
        '', texto_cmd, count=1, flags=re.I,
    ).strip()

    m = re.search(
        r'["\']?([\w\s.\-]+?)["\']?\s+'
        r'(?:para|como|pra)\s+'
        r'["\']?([\w\s.\-]+?)["\']?\s*$',
        texto_limpo, re.I,
    )
    if not m:
        return ("Não entendi. Use: 'renomeia X para Y', Senhor.")

    origem_nome = m.group(1).strip()
    novo_nome   = m.group(2).strip().rstrip('.,;!? ')

    # Procura o arquivo em locais comuns
    candidatos: list[Path] = []
    for pasta in (_HOME / "Desktop", _HOME / "Downloads", _HOME / "Documents", _HOME):
        c = pasta / origem_nome
        if c.exists():
            candidatos.append(c)
    if not candidatos:
        return f"Arquivo/pasta '{origem_nome}' não encontrado, Senhor."

    origem  = candidatos[0]
    destino = origem.parent / novo_nome
    try:
        origem.rename(destino)
        return f"Renomeado '{origem_nome}' → '{novo_nome}', Senhor."
    except Exception as e:
        return f"Erro ao renomear: {e}"


def mover(texto_cmd: str) -> str:
    """Move ou copia um arquivo/pasta para outra localização."""
    tl = texto_cmd.lower()
    copiar = bool(re.search(r'\bcopiar?\b|\bcopi[ae]', tl, re.I))

    # "move arquivo X para [destino]"
    m = re.search(
        r'(?:arquivo|pasta|pdf|video|foto|imagem|diret[oó]rio\s+)?'
        r'["\']?([\w\s.\-]+?)["\']?\s+'
        r'(?:para|pra|até|pra\s+dentro\s+de)\s+'
        r'(.+?)\s*$',
        texto_cmd, re.I,
    )
    if not m:
        return ("Não entendi o destino, Senhor. "
                "Use: 'move arquivo X para a área de trabalho'.")

    nome_origem   = m.group(1).strip()
    destino_texto = m.group(2).strip()
    destino       = _resolver_caminho(destino_texto)
    if destino is None:
        return f"Destino '{destino_texto}' não reconhecido, Senhor."

    candidatos: list[Path] = []
    for pasta in (_HOME / "Desktop", _HOME / "Downloads", _HOME / "Documents", _HOME):
        c = pasta / nome_origem
        if c.exists():
            candidatos.append(c)
    if not candidatos:
        return f"Arquivo/pasta '{nome_origem}' não encontrado, Senhor."

    origem = candidatos[0]
    try:
        destino.mkdir(parents=True, exist_ok=True)
        alvo = destino / origem.name
        if copiar:
            if origem.is_dir():
                shutil.copytree(str(origem), str(alvo))
            else:
                shutil.copy2(str(origem), str(alvo))
            return f"'{origem.name}' copiado para {destino}, Senhor."
        else:
            shutil.move(str(origem), str(alvo))
            return f"'{origem.name}' movido para {destino}, Senhor."
    except PermissionError:
        return f"Sem permissão para mover para {destino}, Senhor."
    except Exception as e:
        return f"Erro ao mover: {e}"


def abrir_vscode(texto_cmd: str) -> str:
    """Abre uma pasta/arquivo no VSCode como workspace."""
    alvo = _resolver_caminho(texto_cmd)

    # Se nenhum caminho foi especificado, abre o VS Code sem workspace (última sessão)
    args = ["code", str(alvo)] if alvo and alvo.exists() else ["code"]
    nome_exib = alvo.name if alvo and alvo.exists() else None

    if alvo and not alvo.exists():
        return f"Caminho não encontrado: {alvo}"

    try:
        subprocess.Popen(args, shell=True)
        if nome_exib:
            return f"Abrindo '{nome_exib}' no VSCode, Senhor."
        return "Abrindo o VSCode, Senhor."
    except FileNotFoundError:
        return ("Comando 'code' não encontrado. "
                "Certifique-se de que o VSCode está instalado e adicionado ao PATH, Senhor.")
    except Exception as e:
        return f"Erro ao abrir no VSCode: {e}"
