"""Catálogo fonético local para transformar uma fala aproximada em aplicativo conhecido.

O Whisper continua sendo quem escuta; este módulo recebe apenas o texto já transcrito. Não há
modelo, rede, shell nem uma lista de apelidos embutida: as formas vêm dos metadados do aplicativo
e de uma correção explícita do dono. A chave fonética é deliberadamente pequena e portável. Ela
remove vogais, aproxima grafias comuns de inglês e pt-BR e gera abreviações de nomes compostos.
Isso é suficiente para recuperar candidatos como ``discórdi``/Discord e ``vi esse côdi``/Visual
Studio Code; a decisão ainda combina a chave com similaridade textual e exige margem.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Final, Literal, Protocol

LIMIAR_PADRAO: Final = 0.74
"""Abaixo disto o Jarvis recusa em vez de abrir um app por palpite."""
MARGEM_PADRAO: Final = 0.08
"""Diferença mínima entre primeiro e segundo para uma escolha automática."""
LIMITE_DE_ALIASES: Final = 128
LIMITE_DE_CARACTERES: Final = 160


class AppDoCatalogo(Protocol):
    """A parte de ``executor.lancador.App`` que o resolvedor precisa.

    O protocolo evita dependência circular: o executor pode importar o resolvedor, e o resolvedor
    não sabe como um ``Exec`` será lançado.
    """

    @property
    def id(self) -> str: ...

    @property
    def nome(self) -> str: ...

    @property
    def nomes(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class Candidato:
    app: AppDoCatalogo
    score: float


@dataclass(frozen=True, slots=True)
class Resolucao:
    estado: Literal["encontrado", "ambiguo", "nao_encontrado"]
    app: AppDoCatalogo | None
    candidatos: tuple[Candidato, ...]

    @property
    def pergunta(self) -> str:
        """Frase pronta para o Jarvis apresentar, sem fingir certeza."""
        opcoes = ", ".join(c.app.nome for c in self.candidatos[:3])
        return f"você quis dizer {opcoes}?" if opcoes else "não encontrei um aplicativo parecido"


@dataclass(frozen=True, slots=True)
class _Forma:
    app: AppDoCatalogo
    texto: str
    chave: str
    peso: float


def normalizar(texto: str) -> str:
    """Texto sem acento, caixa ou pontuação; nunca executa nem interpreta o texto."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if unicodedata.category(c) != "Mn"
    ).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", sem_acento))


def chave_fonetica(texto: str) -> str:
    """Uma aproximação estável de consoantes compartilhadas entre pt-BR e inglês.

    Soundex/Metaphone tradicionais foram desenhados para nomes ingleses. Aqui eles só inspiram a
    redução; preservar ``k``/``s`` e remover vogais faz "Spotify" e "espótifai" convergirem sem
    cadastrar o nome do aplicativo como exceção.
    """
    valor = normalizar(texto).replace(" ", "")
    for antes, depois in (
        ("ph", "f"),
        ("th", "t"),
        ("sh", "x"),
        # Em nomes de apps em inglês, ``ch`` é frequentemente /k/ (Chrome), enquanto no
        # português a transcrição normalmente já vem com ``x`` ("xati" para chat). A escolha
        # por /k/ cobre a grafia instalada sem exigir uma tabela de apelidos por aplicativo.
        ("ch", "k"),
        ("ck", "k"),
        ("qu", "k"),
        ("y", "i"),
        ("c", "k"),
        ("q", "k"),
    ):
        valor = valor.replace(antes, depois)
    sem_vogais = "".join(c for c in valor if c not in "aeiou")
    return re.sub(r"(.)\1+", r"\1", sem_vogais).upper()


def _abreviacoes(texto: str) -> tuple[str, ...]:
    """Chaves de nome composto e de sigla+última palavra (Visual Studio Code → VS+code).

    Não combinamos abreviações arbitrárias: uma forma curta como ``GLK`` para Google Chrome
    tende a coincidir por acaso com uma fala longa. Manter o último termo inteiro reduz falsos
    aceites e ainda representa a construção comum ``VS Code``.
    """
    tokens = [chave_fonetica(token) for token in normalizar(texto).split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return ()
    formas = {"".join(tokens)}
    if len(tokens) > 1:
        formas.add("".join(token[0] for token in tokens[:-1]) + tokens[-1])
    return tuple(sorted(formas))


def _termos(app: AppDoCatalogo) -> tuple[tuple[str, float], ...]:
    """Metadados que o desktop entry já declarou; atributos novos continuam opcionais."""
    itens: list[tuple[str, float]] = [(app.nome, 1.0), *((nome, 0.98) for nome in app.nomes)]
    generico = getattr(app, "generico", "")
    if isinstance(generico, str) and generico:
        itens.append((generico, 0.94))
    keywords = getattr(app, "keywords", ())
    if isinstance(keywords, tuple):
        # Keywords são metadados do pacote, não autorização: só entram porque o índice recebe
        # exclusivamente apps já autorizados. Uma keyword exata ainda deve ser resolúvel.
        itens.extend((palavra, 0.92) for palavra in keywords if isinstance(palavra, str))
    executavel = getattr(app, "exec_nome", "")
    if isinstance(executavel, str) and executavel:
        itens.append((executavel, 0.92))
    return tuple((texto, peso) for texto, peso in itens if normalizar(texto))


def _similaridade(esquerda: str, direita: str) -> float:
    if not esquerda or not direita:
        return 0.0
    if esquerda == direita:
        return 1.0
    if min(len(esquerda), len(direita)) >= 3 and (esquerda in direita or direita in esquerda):
        return 1.0
    return SequenceMatcher(None, esquerda, direita).ratio()


class ResolvedorDeApps:
    """Índice em memória e resolvedor de um catálogo já autorizado pelo dono."""

    def __init__(
        self,
        apps: Iterable[AppDoCatalogo],
        *,
        aliases: Mapping[str, tuple[str, ...]] | None = None,
        limiar: float = LIMIAR_PADRAO,
        margem: float = MARGEM_PADRAO,
    ) -> None:
        self.limiar = limiar
        self.margem = margem
        self._apps = {app.id: app for app in apps}
        self._formas: tuple[_Forma, ...] = self._montar_formas(aliases or {})

    def _montar_formas(self, aliases: Mapping[str, tuple[str, ...]]) -> tuple[_Forma, ...]:
        formas: list[_Forma] = []
        vistos: set[tuple[str, str, str]] = set()
        for app in self._apps.values():
            termos = [*_termos(app), *((alias, 1.05) for alias in aliases.get(app.id, ()))]
            for texto, peso in termos:
                normal = normalizar(texto)
                for chave in _abreviacoes(texto):
                    identidade = (app.id, normal, chave)
                    if identidade not in vistos:
                        vistos.add(identidade)
                        formas.append(_Forma(app, normal, chave, peso))
        return tuple(formas)

    def resolver(self, fala: str) -> Resolucao:
        texto = normalizar(fala)
        chave = chave_fonetica(fala)
        if not texto or not chave:
            return Resolucao("nao_encontrado", None, ())
        melhores: dict[str, float] = {}
        for forma in self._formas:
            texto_score = _similaridade(texto, forma.texto)
            fone_score = _similaridade(chave, forma.chave)
            score = min(1.0, forma.peso * (0.72 * fone_score + 0.28 * texto_score))
            melhores[forma.app.id] = max(melhores.get(forma.app.id, 0.0), score)
        candidatos = tuple(
            Candidato(self._apps[identificador], round(score, 4))
            for identificador, score in sorted(
                melhores.items(), key=lambda item: (-item[1], self._apps[item[0]].nome.casefold())
            )[:3]
        )
        if not candidatos or candidatos[0].score < self.limiar:
            return Resolucao("nao_encontrado", None, candidatos)
        if len(candidatos) > 1 and candidatos[0].score - candidatos[1].score < self.margem:
            return Resolucao("ambiguo", None, candidatos)
        return Resolucao("encontrado", candidatos[0].app, candidatos)


@dataclass(frozen=True, slots=True)
class RepositorioDeAliases:
    """Aliases confirmados pelo dono, fora do repositório e sem nenhum dado sensível."""

    caminho: Path

    @classmethod
    def padrao(cls, ambiente: Mapping[str, str] | None = None) -> RepositorioDeAliases:
        fonte = os.environ if ambiente is None else ambiente
        if os.name == "nt":  # pragma: no cover — caminho do Windows
            base = Path(fonte.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        else:
            base = Path(fonte.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
        return cls(base / "jarvis" / "apps" / "aliases.json")

    def carregar(self) -> dict[str, tuple[str, ...]]:
        try:
            bruto = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        aliases = bruto.get("aliases", {}) if isinstance(bruto, dict) else {}
        if not isinstance(aliases, dict):
            return {}
        resultado: dict[str, tuple[str, ...]] = {}
        for identificador, falas in aliases.items():
            if not isinstance(identificador, str) or not isinstance(falas, list):
                continue
            limpas = tuple(
                fala.strip()
                for fala in falas
                if isinstance(fala, str)
                and normalizar(fala)
                and len(fala.strip()) <= LIMITE_DE_CARACTERES
            )
            if limpas:
                resultado[identificador] = tuple(dict.fromkeys(limpas))
        return resultado

    def aprender(self, fala: str, app_id: str) -> None:
        apelido = fala.strip()
        if not normalizar(apelido) or len(apelido) > LIMITE_DE_CARACTERES:
            raise ValueError("a correção precisa ter entre 1 e 160 caracteres pronunciáveis")
        if not app_id or len(app_id) > LIMITE_DE_CARACTERES:
            raise ValueError("identificador de aplicativo inválido")
        aliases = self.carregar()
        atuais = list(aliases.get(app_id, ()))
        if apelido not in atuais:
            atuais.append(apelido)
        aliases[app_id] = tuple(atuais[-LIMITE_DE_ALIASES:])
        corpo = {
            "version": 1,
            "aliases": {
                identificador: list(falas) for identificador, falas in sorted(aliases.items())
            },
        }
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        parcial = self.caminho.with_name(self.caminho.name + ".tmp")
        parcial.write_text(json.dumps(corpo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        parcial.replace(self.caminho)
