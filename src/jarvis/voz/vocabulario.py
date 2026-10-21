"""O vocabulário do dono: como ouvir e como falar os nomes que importam para ele (ADR-0044).

Pedido do dono (2026-10-21): termos populares, nomes de pessoas e apps pouco famosos saem errados
nos dois sentidos. A mesma lista resolve os dois:

- **ouvir (ASR)**: os termos vão na dica do ASR (`jarvis.voz.dica`, curta — ADR-0043) e, depois
  dele, a **pós-correção** troca o que ele costuma errar (`ouvido`, os apelidos) pela grafia certa
  (`escrita`), e acha pela fonética o nome composto escrito de outro jeito ("Tiago Negro" →
  "Thiago Nigro"). A fonética só vale para termo de duas palavras ou mais: palavra solta casaria
  com palavra comum ("discórdia" não é o Discord) — para ela, o apelido explícito.
- **falar (TTS)**: antes de sintetizar, a grafia vira a pronúncia que o dono escreveu (`fala`), em
  grafia pt-BR ("Steam" → "Stím"). A troca é na camada que todo motor atravessa
  (`SintetizadorEmStreaming.pronunciar`), não em cada motor; a tela e a conversa ficam com a
  grafia certa. `motores` restringe a troca: a ElevenLabs já fala "Spotify" certo, a piper não.

**Onde mora: fora do repositório**, ao lado do `jarvis-voz.toml` (`~/.config/jarvis/`):
`vocabulario.toml` é do dono — o Jarvis só lê, nunca reescreve, e os comentários dele ficam —, e
`vocabulario-aprendido.toml` é o que o Jarvis anota quando o dono corrige ("o certo é X"), pela
tool `vocabulario.aprender`, com o PDP (ADR-0044). O exemplo está em `docs/exemplos/`.

**Leitura tolerante:** arquivo que não abre, TOML quebrado ou entrada torta não derrubam a voz —
o que não serve fica de fora e vira um aviso (pela posição, sem o texto).
"""

from __future__ import annotations

import os
import re
import tomllib
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

from jarvis.ambiente import ambiente_ou_os
from jarvis.apps.resolvedor import chave_fonetica
from jarvis.barramento.envelope import uuid7

ARQUIVO_DO_DONO: Final = "vocabulario.toml"
ARQUIVO_APRENDIDO: Final = "vocabulario-aprendido.toml"
PASTA: Final = "jarvis"
TIPOS: Final[tuple[str, ...]] = ("app", "pessoa", "termo")
LIMITE_DE_CARACTERES: Final = 80
LIMITE_DE_APELIDOS: Final = 8
LIMITE_DE_TERMOS: Final = 500
LIMITE_DE_APRENDIDOS: Final = 200
LIMITE_DO_ARQUIVO: Final = 256 * 1024
FORMA_DO_TEXTO: Final = re.compile(r"[^\x00-\x1f\x7f\"\\\[\]{}<>=#]{1,80}")
"""Letras, números, espaço e pontuação comum. Fora: controle, aspas, colchetes, chaves, `<>`, `=`
e `#` — o que mudaria o TOML, viraria marcação ou não é nome de ninguém."""
SEM_PESO: Final[frozenset[str]] = frozenset(
    {"o", "a", "os", "as", "e", "de", "do", "da", "dos", "das", "um", "uma", "no", "na", "em"}
)
SIMILARIDADE_FONETICA: Final = 0.9
SIMILARIDADE_DO_TEXTO: Final = 0.75
"""Os dois limiares da correção por fonética: chave fonética quase igual **e** texto parecido.
Alto de propósito: corrigir o que o dono disse para outra coisa é pior do que não corrigir."""
_PALAVRA: Final = re.compile(r"\w+", re.UNICODE)
_ENTRE_PALAVRAS: Final = re.compile(r"[\s-]*")


class VocabularioInvalido(ValueError):
    """A correção pedida não serve. A frase diz por quê."""


def dobrar(texto: str) -> str:
    """Sem acento, sem caixa — a forma em que dois textos são comparados."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if unicodedata.category(c) != "Mn"
    )
    return sem_acento.casefold()


def _tokens(texto: str) -> list[re.Match[str]]:
    return list(_PALAVRA.finditer(texto))


@dataclass(frozen=True, slots=True)
class Termo:
    """Um nome do dono: como se escreve, como o ASR o erra e como se fala."""

    escrita: str
    ouvido: tuple[str, ...] = ()
    fala: str = ""
    motores: tuple[str, ...] = ()
    """Os motores de TTS em que a `fala` vale (ids do registro). Vazio = todos."""
    tipo: str = "termo"
    id: str = ""
    """Só nos aprendidos: é por ele que o "desfaz" tira a correção."""

    @property
    def palavras(self) -> list[str]:
        return dobrar(self.escrita).split()

    def fala_para(self, motor: str) -> str:
        if not self.fala or (self.motores and motor not in self.motores):
            return ""
        return self.fala


def _trocar_sequencia(texto: str, alvo: str, por: str) -> str:
    """Troca no texto cada ocorrência de `alvo` como palavras inteiras — sem caixa e sem acento,
    com espaço ou hífen entre elas — por `por`. O que está em volta (pontuação) fica."""
    procurado = dobrar(alvo).split()
    if not procurado:
        return texto
    tokens = _tokens(texto)
    saida: list[str] = []
    ultimo = 0
    i = 0
    while i <= len(tokens) - len(procurado):
        janela = tokens[i : i + len(procurado)]
        casa = [dobrar(t.group()) for t in janela] == procurado and all(
            _ENTRE_PALAVRAS.fullmatch(texto[a.end() : b.start()]) for a, b in pairwise(janela)
        )
        if casa:
            saida.append(texto[ultimo : janela[0].start()])
            saida.append(por)
            ultimo = janela[-1].end()
            i += len(procurado)
        else:
            i += 1
    saida.append(texto[ultimo:])
    return "".join(saida)


def _similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


@dataclass(frozen=True, slots=True)
class Vocabulario:
    """O vocabulário lido (o do dono e o aprendido, nessa ordem)."""

    termos: tuple[Termo, ...] = ()
    ignorar: tuple[str, ...] = ()
    """Frases que o ASR inventa e o dono quer descartadas sempre (o filtro de ruído as usa)."""
    avisos: tuple[str, ...] = ()
    """O que ficou de fora na leitura, pela posição — para o `--diagnostico`, nunca o texto."""

    def termos_da_dica(self) -> list[str]:
        """As grafias, sem repetir, para a dica do ASR: as correções aprendidas, da mais recente
        para a mais antiga (foram as que o ASR errou), e depois as do dono, na ordem do arquivo —
        a dica tem orçamento (`jarvis.voz.dica`), e o que passa dele fica só na pós-correção."""
        aprendidos = [t for t in self.termos if t.id]
        do_dono = [t for t in self.termos if not t.id]
        vistas: dict[str, str] = {}
        for termo in (*reversed(aprendidos), *do_dono):
            vistas.setdefault(dobrar(termo.escrita), termo.escrita)
        return list(vistas.values())

    def corrigir(self, texto: str) -> str:
        """A transcrição com os nomes do dono escritos certo: primeiro os apelidos (o que o ASR
        costuma errar), depois a fonética dos nomes compostos."""
        if not texto or not self.termos:
            return texto
        corrigido = texto
        apelidos = sorted(
            ((apelido, termo.escrita) for termo in self.termos for apelido in termo.ouvido),
            key=lambda par: -len(dobrar(par[0]).split()),
        )
        for apelido, escrita in apelidos:
            corrigido = _trocar_sequencia(corrigido, apelido, escrita)
        for termo in sorted(self.termos, key=lambda t: -len(t.palavras)):
            if len(termo.palavras) >= 2:
                corrigido = self._pela_fonetica(corrigido, termo)
        return corrigido

    def _pela_fonetica(self, texto: str, termo: Termo) -> str:
        """O nome composto que o ASR escreveu de outro jeito, achado pela chave fonética."""
        tamanho = len(termo.palavras)
        alvo_texto = " ".join(termo.palavras)
        alvo_chave = chave_fonetica(termo.escrita)
        tokens = _tokens(texto)
        for i in range(len(tokens) - tamanho + 1):
            janela = tokens[i : i + tamanho]
            if not all(
                _ENTRE_PALAVRAS.fullmatch(texto[a.end() : b.start()]) for a, b in pairwise(janela)
            ):
                continue
            ouvido = " ".join(dobrar(t.group()) for t in janela)
            if ouvido == alvo_texto or any(p in SEM_PESO for p in ouvido.split()):
                continue
            if (
                _similaridade(chave_fonetica(ouvido), alvo_chave) >= SIMILARIDADE_FONETICA
                and _similaridade(ouvido, alvo_texto) >= SIMILARIDADE_DO_TEXTO
            ):
                return (
                    texto[: janela[0].start()]
                    + termo.escrita
                    + self._pela_fonetica(texto[janela[-1].end() :], termo)
                )
        return texto

    def pronunciar(self, texto: str, motor: str = "") -> str:
        """O texto para o TTS: cada grafia com `fala` trocada pela pronúncia — a mais recente vale,
        o nome composto antes do simples ("Visual Studio Code" antes de "Code")."""
        if not texto or not self.termos:
            return texto
        falas: dict[str, tuple[str, str]] = {}
        for termo in self.termos:
            fala = termo.fala_para(motor)
            if fala:
                falas[dobrar(termo.escrita)] = (termo.escrita, fala)
        dito = texto
        for escrita, fala in sorted(falas.values(), key=lambda par: -len(par[0].split())):
            dito = _trocar_sequencia(dito, escrita, fala)
        return dito


VAZIO: Final = Vocabulario()


# --- leitura ----------------------------------------------------------------------------------
def pasta_do_vocabulario(ambiente: Mapping[str, str] | None = None) -> Path | None:
    """A mesma pasta do `jarvis-voz.toml` (`$XDG_CONFIG_HOME/jarvis/`, `~/.config/jarvis/`,
    `%APPDATA%\\jarvis\\`). Um ambiente **explícito** sem nenhuma dessas (o da suíte) não tem
    vocabulário: cair na casa do processo seria ler a pasta do dono num teste."""
    fonte = ambiente_ou_os(ambiente)
    if os.name == "nt":  # pragma: no cover — caminho do Windows, sem CI aqui
        base = fonte.get("APPDATA") or ""
        if not base and ambiente is None:
            base = str(Path.home() / "AppData" / "Roaming")
    else:
        base = fonte.get("XDG_CONFIG_HOME") or ""
        if not base and fonte.get("HOME"):
            base = str(Path(fonte["HOME"]) / ".config")
        if not base and ambiente is None:
            base = str(Path.home() / ".config")
    return Path(base) / PASTA if base else None


def _texto(valor: object) -> str | None:
    if not isinstance(valor, str):
        return None
    limpo = " ".join(valor.split())
    return limpo if limpo and FORMA_DO_TEXTO.fullmatch(limpo) else None


def _lista(valor: object, limite: int) -> tuple[str, ...] | None:
    if valor is None:
        return ()
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        return None
    itens = [_texto(v) for v in valor]
    if any(item is None for item in itens):
        return None
    return tuple(dict.fromkeys(item for item in itens if item))[:limite]


def termo_de(bruto: Mapping[str, Any]) -> Termo | None:
    """Uma entrada `[[termo]]`, ou `None` se ela não serve."""
    escrita = _texto(bruto.get("escrita"))
    ouvido = _lista(bruto.get("ouvido"), LIMITE_DE_APELIDOS)
    motores = _lista(bruto.get("motores"), 16)
    fala = bruto.get("fala", "")
    tipo = bruto.get("tipo", "termo")
    identificador = bruto.get("id", "")
    if escrita is None or ouvido is None or motores is None:
        return None
    if (fala and _texto(fala) is None) or tipo not in TIPOS or not isinstance(identificador, str):
        return None
    return Termo(
        escrita=escrita,
        ouvido=tuple(o for o in ouvido if dobrar(o) != dobrar(escrita)),
        fala=_texto(fala) or "",
        motores=motores,
        tipo=str(tipo),
        id=identificador if re.fullmatch(r"v-[0-9a-f]{8}", identificador) else "",
    )


def _ler(caminho: Path, nome: str) -> tuple[list[Termo], list[str], list[str]]:
    """Termos, frases a ignorar e avisos de um arquivo. Ausente = vazio, sem aviso."""
    try:
        if not caminho.exists():
            return [], [], []
        if caminho.stat().st_size > LIMITE_DO_ARQUIVO:
            return [], [], [f"{nome}: maior que {LIMITE_DO_ARQUIVO // 1024} KiB, ignorado"]
        dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as erro:
        return [], [], [f"{nome}: não deu para ler ({type(erro).__name__}), ignorado"]
    termos: list[Termo] = []
    avisos: list[str] = []
    brutos = dados.get("termo", [])
    if not isinstance(brutos, list):
        return [], [], [f"{nome}: `termo` tem de ser [[termo]], ignorado"]
    for posicao, bruto in enumerate(brutos, start=1):
        termo = termo_de(bruto) if isinstance(bruto, dict) else None
        if termo is None:
            avisos.append(f"{nome}: o {posicao}º [[termo]] não serve e ficou de fora")
        elif len(termos) < LIMITE_DE_TERMOS:
            termos.append(termo)
    ignorar = _lista(dados.get("ignorar"), 64)
    if ignorar is None:
        avisos.append(f"{nome}: `ignorar` tem de ser uma lista de frases, ignorado")
    return termos, list(ignorar or ()), avisos


def ler_vocabulario(pasta: Path) -> Vocabulario:
    """O vocabulário do dono e o aprendido, juntos. Nunca levanta: o que não serve vira aviso."""
    dono, ignorar_dono, avisos_dono = _ler(pasta / ARQUIVO_DO_DONO, ARQUIVO_DO_DONO)
    aprendido, ignorar_aprendido, avisos_aprendido = _ler(
        pasta / ARQUIVO_APRENDIDO, ARQUIVO_APRENDIDO
    )
    return Vocabulario(
        termos=(*dono, *aprendido),
        ignorar=tuple(dict.fromkeys((*ignorar_dono, *ignorar_aprendido))),
        avisos=(*avisos_dono, *avisos_aprendido),
    )


# --- o que o Jarvis aprende --------------------------------------------------------------------
def exigir_texto(valor: object, campo: str) -> str:
    texto = _texto(valor)
    if texto is None:
        raise VocabularioInvalido(
            f"{campo}: de 1 a {LIMITE_DE_CARACTERES} caracteres, sem aspas, colchetes, chaves, "
            "<, >, = ou #"
        )
    return texto


def _aspas(valor: str) -> str:
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _bloco(termo: Termo) -> str:
    linhas = ["[[termo]]", f"id = {_aspas(termo.id)}", f"escrita = {_aspas(termo.escrita)}"]
    if termo.ouvido:
        linhas.append(f"ouvido = [{', '.join(_aspas(o) for o in termo.ouvido)}]")
    if termo.fala:
        linhas.append(f"fala = {_aspas(termo.fala)}")
    if termo.motores:
        linhas.append(f"motores = [{', '.join(_aspas(m) for m in termo.motores)}]")
    linhas.append(f"tipo = {_aspas(termo.tipo)}")
    return "\n".join(linhas)


CABECALHO_DO_APRENDIDO: Final = """\
# Vocabulário que o Jarvis aprendeu quando você corrigiu um nome ("o certo é …"), pela ferramenta
# vocabulario.aprender (ADR-0044). O Jarvis reescreve este arquivo inteiro a cada correção: o que
# você quiser que fique como está, ponha no vocabulario.toml, que é só seu. Para desfazer a última
# correção, diga "desfaz"; para tirar uma antiga, apague o bloco [[termo]] dela aqui.
"""


@dataclass(slots=True)
class RepositorioDoVocabulario:
    """O vocabulário do dono (só leitura) e o aprendido (escrito aqui, inteiro, atômico)."""

    pasta: Path

    @classmethod
    def padrao(cls, ambiente: Mapping[str, str] | None = None) -> RepositorioDoVocabulario | None:
        """O repositório na pasta de configuração do dono, ou `None` sem pasta (ver acima)."""
        pasta = pasta_do_vocabulario(ambiente)
        return cls(pasta) if pasta is not None else None

    @property
    def arquivo_do_dono(self) -> Path:
        return self.pasta / ARQUIVO_DO_DONO

    @property
    def arquivo_aprendido(self) -> Path:
        return self.pasta / ARQUIVO_APRENDIDO

    def carregar(self) -> Vocabulario:
        return ler_vocabulario(self.pasta)

    def _aprendidos(self) -> list[Termo]:
        termos, _ignorar, _avisos = _ler(self.arquivo_aprendido, ARQUIVO_APRENDIDO)
        return termos

    def aprender(
        self,
        escrita: str,
        *,
        ouvido: Sequence[str] = (),
        fala: str = "",
        motores: Sequence[str] = (),
        tipo: str = "termo",
    ) -> Termo:
        """Anota uma correção do dono. Recusa o que não serve, dizendo por quê."""
        certo = exigir_texto(escrita, "escrita")
        apelidos = tuple(
            dict.fromkeys(
                apelido
                for apelido in (exigir_texto(o, "ouvido") for o in ouvido)
                if dobrar(apelido) != dobrar(certo)
            )
        )
        for apelido in apelidos:
            if all(p in SEM_PESO for p in dobrar(apelido).split()) or len(dobrar(apelido)) < 2:
                raise VocabularioInvalido(
                    f"ouvido: {apelido!r} é curto ou comum demais — trocaria palavra de toda frase"
                )
        pronuncia = exigir_texto(fala, "fala") if fala else ""
        if not apelidos and not pronuncia:
            raise VocabularioInvalido(
                "diga o que o Jarvis ouviu errado (ouvido) ou como se fala (fala)"
            )
        if tipo not in TIPOS:
            raise VocabularioInvalido(f"tipo {tipo!r} não existe: {', '.join(TIPOS)}")
        termo = Termo(
            escrita=certo,
            ouvido=apelidos[:LIMITE_DE_APELIDOS],
            fala=pronuncia,
            motores=tuple(exigir_texto(m, "motores") for m in motores)[:16],
            tipo=tipo,
            id=f"v-{uuid7()[-8:]}",
        )
        aprendidos = self._aprendidos()
        if len(aprendidos) >= LIMITE_DE_APRENDIDOS:
            raise VocabularioInvalido(
                f"já são {LIMITE_DE_APRENDIDOS} correções aprendidas: apague as antigas em "
                f"{self.arquivo_aprendido}"
            )
        self._gravar([*aprendidos, termo])
        return termo

    def esquecer(self, identificador: str) -> Termo | None:
        """Tira uma correção aprendida (o "desfaz"). `None` = não havia."""
        aprendidos = self._aprendidos()
        restantes = [t for t in aprendidos if t.id != identificador]
        if len(restantes) == len(aprendidos):
            return None
        self._gravar(restantes)
        return next(t for t in aprendidos if t.id == identificador)

    def _gravar(self, termos: Iterable[Termo]) -> None:
        corpo = CABECALHO_DO_APRENDIDO + "".join(f"\n{_bloco(t)}\n" for t in termos)
        tomllib.loads(corpo)  # o que vai para o disco tem de voltar inteiro na leitura
        self.pasta.mkdir(parents=True, exist_ok=True)
        parcial = self.arquivo_aprendido.with_name(self.arquivo_aprendido.name + ".tmp")
        descritor = os.open(parcial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descritor, "w", encoding="utf-8") as saida:
            saida.write(corpo)
        parcial.replace(self.arquivo_aprendido)


__all__ = [
    "ARQUIVO_APRENDIDO",
    "ARQUIVO_DO_DONO",
    "VAZIO",
    "RepositorioDoVocabulario",
    "Termo",
    "Vocabulario",
    "VocabularioInvalido",
    "dobrar",
    "ler_vocabulario",
    "pasta_do_vocabulario",
    "termo_de",
]
