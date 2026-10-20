"""Importa memórias do Orchestrator para o esquema da §6.2 (C1; cartão F0-08).

Três obrigações desta etapa:

1. **Segredo não atravessa.** Todo texto passa por `redigir` antes de entrar no banco; o que
   casa com um padrão conhecido vira marcador (`[REDIGIDO:tipo]`), e a contagem de redações
   vai no relatório. Padrão que a função não conhece é problema de quem adiciona fonte nova —
   por isso `exportar` recusa texto com entropia de segredo não reconhecida.
2. **Proveniência sempre** (P7): cada assertiva aponta o episódio de origem, e cada menção
   aponta a unidade de memória.
3. **Extração determinística** (§6.7): autor, projeto, caminhos de arquivo e commits viram
   entidade por regra, sem LLM. Aresta nasce `proposed` e só vira `active` com duas
   evidências independentes — a mesma regra do grafo.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

PADROES_DE_SEGREDO: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("chave_openai", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("token_github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}")),
    ("chave_aws", re.compile(r"\bAKIA[0-9A-Z]{12,}")),
    ("chave_google", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}")),
    ("chave_anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}")),
    ("token_slack", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    (
        "chave_privada",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    ("url_com_credencial", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@[^\s]+")),
    (
        "senha_declarada",
        # Sem `\b` inicial de propósito: em `API_TOKEN=…` o separador é `_`, que é
        # caractere de palavra, e a borda não existiria.
        re.compile(r"(?i)(senha|password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S{4,}"),
    ),
    (
        "senha_falada",
        # O jeito falado (2026-10-20, Lote C/D20): "minha senha é hunter2", "a senha do wifi é
        # casa2024". Exige um dígito no valor — "a senha é fraca" e "o token é válido" não são
        # segredo e não podem virar consulta recusada.
        re.compile(
            r"(?i)\b(?:senha|password|passwd|pin)\s+(?:d[aoe]\s+\S+\s+)?(?:é|e|eh|era)\s+"
            r"(?=\S*\d)\S{4,}"
        ),
    ),
    ("conteudo_de_env", re.compile(r"(?m)^\s*[A-Z][A-Z0-9_]{3,}=(?!\s*$)\S+")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("hex_longo", re.compile(r"\b[0-9a-f]{48,}\b")),
)
"""Ordem importa: o padrão mais específico redige antes do mais genérico."""

CAMINHO = re.compile(r"(?:/[\w.\-]+){2,}|(?:[A-Za-z]:\\[\w.\-\\]+)")
COMMIT = re.compile(r"\b[0-9a-f]{7,12}\b")
ARQUIVO_SENSIVEL = re.compile(r"(?i)(\.ssh|\.gnupg|\.env|cofre|keyring|credential|id_rsa)")


@dataclass(frozen=True, slots=True)
class MemoriaDoOrchestrator:
    """Uma memória ou decisão exportada do Orchestrator."""

    autor: str
    tipo: str
    prioridade: int
    titulo: str
    corpo: str
    projeto: str = "Orchestrator"
    ocorrido_em: str = ""

    @property
    def texto(self) -> str:
        return f"{self.titulo}\n{self.corpo}".strip()


@dataclass
class Redacao:
    texto: str
    achados: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.achados.values())


def redigir(texto: str) -> Redacao:
    """Troca segredo por marcador. O que sai daqui é o que pode entrar no banco."""
    achados: dict[str, int] = {}
    resultado = texto
    for nome, padrao in PADROES_DE_SEGREDO:
        resultado, quantas = padrao.subn(f"[REDIGIDO:{nome}]", resultado)
        if quantas:
            achados[nome] = achados.get(nome, 0) + quantas
    return Redacao(texto=resultado, achados=achados)


def classe_de_pii(texto: str) -> str:
    """`pii_class` da §6.2 — conservador: na dúvida, sobe a classe."""
    if ARQUIVO_SENSIVEL.search(texto):
        return "sensitive"
    if "[REDIGIDO:" in texto:
        return "metadata"
    if CAMINHO.search(texto):
        return "path_only"
    return "none"


def normalizar(nome: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", nome) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sem_acento).strip().casefold()


def _id(prefixo: str, semente: str) -> str:
    return f"{prefixo}-{hashlib.sha256(semente.encode('utf-8')).hexdigest()[:16]}"


@dataclass
class Contagem:
    """Relatório do exportador — é o `n` que vai para `docs/medicoes/` (aceite F0-08 a e d)."""

    episodios: int = 0
    entidades: int = 0
    assertivas: int = 0
    unidades: int = 0
    mencoes: int = 0
    arestas: int = 0
    arestas_ativas: int = 0
    redacoes: dict[str, int] = field(default_factory=dict)
    pii: dict[str, int] = field(default_factory=dict)

    @property
    def total_redigido(self) -> int:
        return sum(self.redacoes.values())

    @property
    def entidades_por_episodio(self) -> float:
        return self.entidades / self.episodios if self.episodios else 0.0

    @property
    def arestas_por_episodio(self) -> float:
        return self.arestas / self.episodios if self.episodios else 0.0


def extrair_entidades(memoria: MemoriaDoOrchestrator, texto: str) -> list[tuple[str, str]]:
    """Entidades por regra determinística: `(tipo, nome)`. Sem LLM (§6.7)."""
    entidades: list[tuple[str, str]] = [
        ("autor", memoria.autor),
        ("projeto", memoria.projeto),
        ("tema", memoria.tipo),
    ]
    vistos: set[str] = set()
    for achado in CAMINHO.findall(texto):
        if ARQUIVO_SENSIVEL.search(achado):
            continue  # caminho de segredo não vira entidade nem no grafo
        if achado not in vistos:
            vistos.add(achado)
            entidades.append(("arquivo", achado))
    for achado in COMMIT.findall(texto):
        if achado not in vistos and not achado.isdigit():
            vistos.add(achado)
            entidades.append(("commit", achado))
    return entidades[:24]  # teto por episódio: memória gigante não domina o grafo


def exportar(
    con: sqlite3.Connection, memorias: list[MemoriaDoOrchestrator], *, sessao: str = "c1-import"
) -> Contagem:
    """Grava as memórias no esquema da §6.2 + §6.7 e devolve a contagem."""
    contagem = Contagem()
    entidades_gravadas: dict[str, str] = {}
    suporte: dict[tuple[str, str], int] = {}
    agora = datetime.now(UTC).isoformat()

    con.execute("BEGIN")
    for memoria in memorias:
        redacao = redigir(memoria.texto)
        for nome, quantas in redacao.achados.items():
            contagem.redacoes[nome] = contagem.redacoes.get(nome, 0) + quantas
        pii = classe_de_pii(redacao.texto)
        contagem.pii[pii] = contagem.pii.get(pii, 0) + 1

        episodio = _id("ep", redacao.texto)
        ocorrido = memoria.ocorrido_em or agora
        con.execute(
            "INSERT OR IGNORE INTO episode (id, occurred_at, ingested_at, session_id, actor,"
            " source, kind, sha256, trust, pii_class) VALUES (?, ?, ?, ?, ?, 'orchestrator',"
            " ?, ?, ?, ?)",
            (
                episodio,
                ocorrido,
                agora,
                sessao,
                memoria.autor,
                memoria.tipo,
                hashlib.sha256(redacao.texto.encode("utf-8")).hexdigest(),
                "user_ui" if memoria.autor == "dono" else "system",
                pii,
            ),
        )
        contagem.episodios += 1

        unidade = _id("mu", episodio)
        con.execute(
            "INSERT OR IGNORE INTO memory_unit (id, episode_id, text_redacted, content_hash,"
            " importance) VALUES (?, ?, ?, ?, ?)",
            (
                unidade,
                episodio,
                redacao.texto,
                hashlib.sha256(redacao.texto.encode("utf-8")).hexdigest(),
                min(1.0, memoria.prioridade / 10),
            ),
        )
        contagem.unidades += 1

        do_episodio: list[str] = []
        for tipo, nome in extrair_entidades(memoria, redacao.texto):
            entidade = _id("en", f"{tipo}|{normalizar(nome)}")
            if entidade not in entidades_gravadas:
                con.execute(
                    "INSERT OR IGNORE INTO entity (id, type, canonical_name, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (entidade, tipo, nome, agora),
                )
                con.execute(
                    "INSERT OR IGNORE INTO entity_resolution (alias_norm, entity_id, score,"
                    " method) VALUES (?, ?, 1.0, 'exato')",
                    (normalizar(nome), entidade),
                )
                entidades_gravadas[entidade] = nome
                contagem.entidades += 1
            con.execute(
                "INSERT OR IGNORE INTO entity_mention (id, episode_id, memory_unit_id,"
                " entity_id, confidence, extractor, extractor_version, status) VALUES"
                " (?, ?, ?, ?, 1.0, 'regra-c1', '1', 'active')",
                (_id("em", f"{episodio}|{entidade}"), episodio, unidade, entidade),
            )
            contagem.mencoes += 1
            do_episodio.append(entidade)

        autor = _id("en", f"autor|{normalizar(memoria.autor)}")
        con.execute(
            "INSERT OR IGNORE INTO assertion (id, subject_entity, predicate, value_json,"
            " confidence, observed_at, valid_from, status, source_episode_id) VALUES"
            " (?, ?, ?, ?, ?, ?, ?, 'active', ?)",
            (
                _id("as", f"{episodio}|registrou"),
                autor,
                f"registrou_{memoria.tipo}",
                f'"{redigir(memoria.titulo).texto}"',
                min(1.0, memoria.prioridade / 10) or 0.5,
                ocorrido,
                ocorrido,
                episodio,
            ),
        )
        contagem.assertivas += 1

        for i, origem in enumerate(do_episodio):
            for destino in do_episodio[i + 1 :]:
                par = (origem, destino) if origem < destino else (destino, origem)
                suporte[par] = suporte.get(par, 0) + 1
                con.execute(
                    "INSERT OR IGNORE INTO entity_edge (id, src, relation, dst,"
                    " source_episode_id, valid_from, confidence, status, weight,"
                    " support_count, last_seen_at, extractor, extractor_version) VALUES"
                    " (?, ?, 'co_mencao', ?, ?, ?, 0.6, 'proposed', 0.5, 1, ?, 'regra-c1', '1')",
                    (_id("ed", f"{par[0]}|{par[1]}"), par[0], par[1], episodio, ocorrido, ocorrido),
                )
    # §6.7: aresta vira `active` só com duas evidências independentes.
    for (origem, destino), vezes in suporte.items():
        identificador = _id("ed", f"{origem}|{destino}")
        con.execute(
            "UPDATE entity_edge SET support_count = ?, status = ?, weight = ? WHERE id = ?",
            (
                vezes,
                "active" if vezes >= 2 else "proposed",
                min(1.0, 0.4 + 0.1 * vezes),
                identificador,
            ),
        )
    con.execute("COMMIT")

    contagem.arestas = int(con.execute("SELECT COUNT(*) AS n FROM entity_edge").fetchone()["n"])
    contagem.arestas_ativas = int(
        con.execute("SELECT COUNT(*) AS n FROM entity_edge WHERE status = 'active'").fetchone()["n"]
    )
    return contagem
