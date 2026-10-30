"""A conversa que sobrevive ao reinício (ADR-0026, dono em 2026-10-18).

O histórico persistente já existia (o livro-razão cifrado); faltava **ligá-lo**: ao abrir a janela,
os últimos turnos voltam à tela e ao contexto do cérebro, e o dono pode começar outra do zero.
Este módulo é essa ligação, sem Qt e sem motor:

- **Uma conversa = um `conversa_id`** guardado em `conversa-atual.json`, ao lado do livro. É um
  identificador de *conversa*, distinto do `session_id` do processo: reabrir o aplicativo continua
  a conversa; "nova conversa" troca o id (e vale já, no disco — fechar logo depois não traz a
  antiga de volta).
- **Só volta o que foi tocado** (P4): o livro só guarda do Jarvis o que o dono ouviu, e a
  interrupção vem marcada.
- **Dois textos por turno:** o original (decifrado) vai para a tela do dono; o redigido (sem
  segredo nem dado pessoal) é o que o modelo lê.
- **Degrada, não cai** (P9): sem chaveiro não há cofre, e sem cofre não há histórico em disco. O
  aplicativo segue sem persistência e a frase do motivo (`aviso`) vai para a tela.
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.barramento.envelope import uuid7
from jarvis.memoryd.cofre import Cofre, CofreIndisponivel, cofre_do_chaveiro
from jarvis.memoryd.embedding import ARQUIVO_DO_MODELO, PASTA_DO_MODELO
from jarvis.memoryd.indice import IndiceEmMemoria, MemoryIndex
from jarvis.memoryd.livro import LivroDeMemoria

PASTA_DA_MEMORIA: Final = "memoria"
ARQUIVO_DO_LIVRO: Final = "livro.sqlite"
ARQUIVO_DA_CONVERSA: Final = "conversa-atual.json"
TURNOS_NA_TELA: Final = 30
"""Quantos turnos voltam à tela ao reabrir; o contexto do cérebro corta nos seus (`Conversa`)."""


@dataclass(frozen=True, slots=True)
class TurnoSalvo:
    papel: str
    """`dono` ou `jarvis`."""
    texto: str
    """O original, para a tela."""
    redigido: str
    """Para o modelo."""
    interrompida: bool = False


@dataclass(slots=True)
class ConversaPersistente:
    """O livro do dono e a conversa corrente nele. Sem livro, tudo vive só na memória."""

    raiz: Path
    livro: LivroDeMemoria | None = None
    conversa_id: str = ""
    aviso: str = ""
    """Por que não há histórico em disco (vazio quando há)."""
    _indexando: threading.Event = field(default_factory=threading.Event, repr=False)
    _linha: threading.Thread | None = field(default=None, repr=False)
    erro_de_indexacao: str = ""

    def __post_init__(self) -> None:
        if not self.conversa_id:
            self.conversa_id = self._ler_id() or self._gravar_id(f"c-{uuid7()}")

    @property
    def ativa(self) -> bool:
        return self.livro is not None

    # --- a conversa corrente -------------------------------------------------------------
    def recentes(self, ultimos: int = TURNOS_NA_TELA) -> list[TurnoSalvo]:
        """Os últimos turnos da conversa corrente; vazio se não há livro ou ele falha (P9)."""
        if self.livro is None:
            return []
        try:
            linhas = self.livro.turnos_da_sessao(self.conversa_id, ultimos=ultimos)
        except Exception as erro:  # histórico ilegível não derruba a abertura
            self.aviso = f"o histórico não abriu ({type(erro).__name__}): começo uma conversa nova"
            return []
        return [
            TurnoSalvo(
                papel=str(linha["papel"]),
                texto=str(linha["texto"]),
                redigido=str(linha["redigido"]),
                interrompida=bool(linha["interrompida"]),
            )
            for linha in linhas
        ]

    def nova(self) -> str:
        """Começa outra conversa. Os turnos antigos continuam no livro (a busca os acha); só
        deixam de voltar à tela e ao contexto."""
        self.conversa_id = self._gravar_id(f"c-{uuid7()}")
        return self.conversa_id

    # --- índice em segundo plano (§6.4) ------------------------------------------------------
    def indexar_depois(self) -> None:
        """Leva a outbox ao índice numa linha à parte: a voz nunca espera por embedding."""
        livro = self.livro
        if livro is None or self._indexando.is_set():
            return
        self._indexando.set()

        def trabalhar() -> None:
            try:
                livro.processar_outbox()
                self.erro_de_indexacao = ""
            except Exception as erro:  # sem modelo ou sem disco: tenta no turno seguinte
                self.erro_de_indexacao = f"{type(erro).__name__}: {erro}"
            finally:
                self._indexando.clear()

        self._linha = threading.Thread(target=trabalhar, name="jarvis-indice", daemon=True)
        self._linha.start()

    def fechar(self) -> None:
        """Espera a indexação em curso e fecha o banco. Fechar com a linha ainda lendo derruba o
        SQLite (segfault medido no teste), então esta é a única forma de largar o livro."""
        if self._linha is not None:
            self._linha.join(timeout=10.0)
        if self.livro is not None:
            with contextlib.suppress(Exception):
                self.livro.con.close()

    # --- o id no disco -----------------------------------------------------------------------
    @property
    def _arquivo(self) -> Path:
        return self.raiz / PASTA_DA_MEMORIA / ARQUIVO_DA_CONVERSA

    def _ler_id(self) -> str:
        try:
            dados = json.loads(self._arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        valor = dados.get("id") if isinstance(dados, dict) else None
        return valor if isinstance(valor, str) else ""

    def _gravar_id(self, identificador: str) -> str:
        with contextlib.suppress(OSError):  # sem disco, a conversa vale só até fechar
            self._arquivo.parent.mkdir(parents=True, exist_ok=True)
            self._arquivo.write_text(json.dumps({"id": identificador}), encoding="utf-8")
        return identificador


def _indice_do_dono(raiz: Path) -> MemoryIndex:
    """LanceDB com o embedding local quando o modelo já está na máquina; senão o índice de
    termos em memória — a busca cai para o léxico (FTS5), que é do livro e não se perde."""
    if not (PASTA_DO_MODELO / ARQUIVO_DO_MODELO).is_file():
        return IndiceEmMemoria()
    try:
        from jarvis.memoryd.embedding import EmbedderE5
        from jarvis.memoryd.indice_vetorial import IndiceLance

        pasta = raiz / PASTA_DA_MEMORIA / "indice"
        pasta.mkdir(parents=True, exist_ok=True)
        embedder = EmbedderE5()
        # O modelo abre ao lado (auditoria de 2026-10-30): o 1º turno não paga os ~0,8 s.
        embedder.aquecer_em_segundo_plano()
        return IndiceLance(pasta=pasta, embedder=embedder)
    except Exception:  # lancedb ou pyarrow ausentes: o grupo opcional não foi instalado
        return IndiceEmMemoria()


def abrir_conversa(
    raiz: Path,
    *,
    cofre: Callable[[], Cofre] = cofre_do_chaveiro,
    indice: MemoryIndex | None = None,
) -> ConversaPersistente:
    """Abre o livro do dono em `raiz/memoria/` (cifrado com a chave do chaveiro do SO).

    Qualquer falha — sem chaveiro, disco só de leitura — vira uma `ConversaPersistente` sem livro
    e com o motivo em `aviso`: o Jarvis conversa do mesmo jeito, só não lembra no reinício."""
    try:
        chave = cofre()
        pasta = raiz / PASTA_DA_MEMORIA
        pasta.mkdir(parents=True, exist_ok=True)
        livro = LivroDeMemoria.abrir(
            pasta / ARQUIVO_DO_LIVRO,
            cofre=chave,
            indice=indice if indice is not None else _indice_do_dono(raiz),
        )
    except CofreIndisponivel as erro:
        return ConversaPersistente(
            raiz=raiz, aviso=f"sem histórico em disco: {erro}. A conversa vale só até fechar."
        )
    except Exception as erro:
        return ConversaPersistente(
            raiz=raiz,
            aviso=f"sem histórico em disco ({type(erro).__name__}). A conversa vale só até fechar.",
        )
    return ConversaPersistente(raiz=raiz, livro=livro)
