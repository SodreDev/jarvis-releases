"""Como o Jarvis decide que é com ele: atalho, palavra de ativação ou escuta contínua (ADR-0021).

**Três modos, e os valores antigos continuam valendo.** `ATALHO` é `"ptt"` e `CONTINUA` é
`"vad"` — os mesmos textos que o `jarvis-voz.toml` do dono já tem no campo `escuta` e que o
indicador de microfone (`jarvis.microfone.Modo`) já entende. `PALAVRA` é o novo.

**Trocável com a sessão aberta.** `Escuta` é o estado **vivo**: o laço de voz o lê a cada
tique (`jarvis.voz.app`), a janela e o controlador o trocam de outra thread. Não há trava, e
não precisa: cada troca é **uma** atribuição de atributo (o modo, ou um detector inteiro já
montado), e atribuição de atributo é atômica em CPython. O laço vê o modo antigo ou o novo,
nunca metade de um.

**A política mora aqui, não na tela.** `confirmacao_necessaria` diz quando uma troca pedida
**pelo modelo** precisa do sim do dono na tela — e a resposta não depende de quem desenha o
botão. O que o dono troca com o próprio dedo não passa por ela: escolher é dele.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from jarvis.voz.palavra import (
    LIMIAR_PADRAO,
    PALAVRA_PADRAO,
    DetectorDePalavra,
)

ARMADO_POR_S: Final = 8.0
"""Quanto tempo a escuta fica armada depois de o dono dizer **só** o nome ("Jarvis?"). Oito
segundos cabem a pausa de quem pensa no que vai pedir e não deixam o microfone virando pedido
pelo resto da tarde."""


class ModoDeEscuta(StrEnum):
    """Quem decide que um trecho de fala é um pedido."""

    ATALHO = "ptt"
    """O dedo do dono: só vira pedido o que ele fala segurando a combinação de teclas."""

    PALAVRA = "palavra"
    """O VAD abre o trecho, o ASR local transcreve, e só vira pedido o que traz a palavra."""

    CONTINUA = "vad"
    """Todo trecho que o VAD abrir vira pedido. É o modo que mais escuta."""

    @property
    def frase(self) -> str:
        return {
            ModoDeEscuta.ATALHO: "atalho de teclas",
            ModoDeEscuta.PALAVRA: "palavra de ativação",
            ModoDeEscuta.CONTINUA: "escuta contínua",
        }[self]

    @property
    def abre_sozinho(self) -> bool:
        """O microfone vira transcrição sem o dono apertar nada?

        No `PALAVRA` sim: para saber se ele chamou, cada trecho que o VAD abrir é transcrito.
        É isso que faz a palavra de ativação com ASR de **nuvem** mandar fala para fora.
        """
        return self is not ModoDeEscuta.ATALHO


MODOS: Final[tuple[str, ...]] = tuple(m.value for m in ModoDeEscuta)


def modo_de(bruto: str) -> ModoDeEscuta:
    """O modo pelo valor do arquivo (`ptt`, `palavra`, `vad`), ou a recusa com os válidos."""
    try:
        return ModoDeEscuta(bruto)
    except ValueError:
        raise ValueError(
            f"modo de escuta {bruto!r} não existe. Válidos: {', '.join(MODOS)}"
        ) from None


# --- a combinação de teclas -------------------------------------------------------------------
#
# A grafia guardada é a do Qt (`QKeySequence.toString()`, "Ctrl+Shift+A"), que é a que a janela
# captura e mostra. O portal de atalhos globais quer outra (spec freedesktop de atalhos:
# `CTRL+SHIFT+a`), e `gatilho_do_portal` traduz — uma grafia guardada, uma traduzida na borda.
MODIFICADORES: Final[dict[str, str]] = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "meta": "Meta",
    "super": "Meta",
    "logo": "Meta",
}
_NO_PORTAL: Final[dict[str, str]] = {"Ctrl": "CTRL", "Alt": "ALT", "Shift": "SHIFT", "Meta": "LOGO"}
TECLAS_COM_NOME: Final[dict[str, str]] = {
    "space": "space",
    "espaço": "space",
    "espaco": "space",
    "return": "Return",
    "enter": "Return",
    "tab": "Tab",
    "esc": "Escape",
    "escape": "Escape",
    "backspace": "BackSpace",
    "pause": "Pause",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
}
"""Teclas com nome, na grafia do keysym (é a que o portal recebe). Fora disto: letra, dígito
ou F1–F24."""
_ORDEM: Final = ("Ctrl", "Alt", "Shift", "Meta")
_TECLA_DO_QT: Final[dict[str, str]] = {"space": "Space", "BackSpace": "Backspace", "Escape": "Esc"}
"""Onde o Qt escreve diferente do keysym (`XKB_KEY_space`, `XKB_KEY_BackSpace`)."""


class CombinacaoInvalida(ValueError):
    """A combinação de teclas não serve. A frase diz por quê."""


def _tecla(bruta: str) -> str:
    """A tecla na grafia do keysym, ou a recusa."""
    minuscula = bruta.lower()
    if minuscula in TECLAS_COM_NOME:
        return TECLAS_COM_NOME[minuscula]
    if len(bruta) == 1 and bruta.isascii() and bruta.isalnum():
        return bruta.lower()
    if minuscula.startswith("f") and minuscula[1:].isdigit() and 1 <= int(minuscula[1:]) <= 24:
        return f"F{int(minuscula[1:])}"
    raise CombinacaoInvalida(
        f"tecla {bruta!r} não é uma que o atalho aceita: use letra, dígito, F1–F24 ou "
        f"{', '.join(sorted(set(TECLAS_COM_NOME.values())))}"
    )


def exigir_combinacao(bruta: str) -> str:
    """A combinação normalizada na grafia do Qt ("Ctrl+Space"), vazia, ou a recusa.

    Vazio é válido: é a barra de espaço com a janela em foco, como era antes. Fora isso, tem de
    haver **um modificador** — a não ser em F1–F24 —, porque uma letra sozinha como atalho
    global tomaria a letra de todo programa aberto.
    """
    limpa = bruta.strip()
    if not limpa:
        return ""
    partes = [p.strip() for p in limpa.replace(" ", "").split("+")]
    if any(not p for p in partes):
        raise CombinacaoInvalida(f"{bruta!r} tem um '+' sem tecla")
    *mods_brutos, tecla_bruta = partes
    mods: list[str] = []
    for mod in mods_brutos:
        nome = MODIFICADORES.get(mod.lower())
        if nome is None:
            raise CombinacaoInvalida(f"{mod!r} não é modificador: use {', '.join(_ORDEM)}")
        if nome not in mods:
            mods.append(nome)
    tecla = _tecla(tecla_bruta)
    if not mods and not tecla.startswith("F"):
        raise CombinacaoInvalida(
            f"{bruta!r} sem Ctrl, Alt, Shift ou Meta tomaria essa tecla de todo programa: "
            "junte um modificador (ex.: Ctrl+Space)"
        )
    ordenados = [m for m in _ORDEM if m in mods]
    no_qt = _TECLA_DO_QT.get(tecla, tecla.upper() if len(tecla) == 1 else tecla)
    return "+".join([*ordenados, no_qt])


def gatilho_do_portal(combinacao: str) -> str:
    """A grafia da spec freedesktop de atalhos, que vai em `preferred_trigger` do portal."""
    normal = exigir_combinacao(combinacao)
    if not normal:
        return ""
    *mods, tecla = normal.split("+")
    return "+".join([*(_NO_PORTAL[m] for m in mods), _tecla(tecla)])


def confirmacao_necessaria(alvo: ModoDeEscuta, *, atual: ModoDeEscuta, asr_na_nuvem: bool) -> str:
    """Por que uma troca **pedida pelo modelo** precisa do sim do dono — ou vazio.

    Duas regras, e só duas, porque são as duas que ampliam alcance (SPEC §5.5, P12):

    1. **ligar a escuta contínua**: todo trecho de fala vira pedido, sem chamada nem dedo;
    2. **ligar um modo que abre sozinho com ASR de nuvem**: cada trecho que o VAD abrir é
       transcrito fora da máquina — é "ligar nuvem" por outro nome.

    Reduzir alcance (contínua → palavra → atalho, com ASR local) passa direto: pedir para
    escutar **menos** não precisa de permissão. Pedir o que já está ligado também não.
    """
    if alvo is atual:
        return ""
    if alvo is ModoDeEscuta.CONTINUA:
        motivo = (
            "escuta contínua faz todo trecho de fala virar pedido, sem você chamar nem apertar nada"
        )
        if asr_na_nuvem:
            motivo += "; e com o ASR na nuvem, cada trecho sai da máquina"
        return motivo
    if asr_na_nuvem and alvo.abre_sozinho and not atual.abre_sozinho:
        return (
            f"{alvo.frase} com o ASR na nuvem transcreve fora da máquina cada trecho que o "
            "microfone abrir, para saber se você chamou"
        )
    return ""


@dataclass(slots=True)
class Escuta:
    """O modo vivo, a palavra e o atalho. Lido pelo laço a cada tique."""

    modo: ModoDeEscuta = ModoDeEscuta.ATALHO
    detector: DetectorDePalavra = field(default_factory=DetectorDePalavra)
    atalho: str = ""
    """A combinação que o dono escolheu, como a tela mostra ("Ctrl+Espaço"). Vazio = a barra
    de espaço com a janela focada, que é o que existia antes."""
    atalho_global: bool = False
    """Se o atalho vale com a janela fora de foco (portal registrado). Quem escreve é quem
    registrou — nunca a tela supondo."""
    armado_ate_ns: int = 0
    descartados: int = 0
    """Trechos ouvidos sem a palavra, nesta sessão. O texto deles não fica em lugar nenhum."""
    ruidos: int = 0
    """Trechos de ruído que não viraram pedido nesta sessão (ADR-0043): estalo, tecla, respiração,
    o texto que o ASR inventou no silêncio. Nada deles fica — nem o áudio, nem o texto."""
    ao_mudar: Callable[[], None] | None = None

    @classmethod
    def de(
        cls,
        modo: str,
        *,
        palavra: str = PALAVRA_PADRAO,
        limiar: float = LIMIAR_PADRAO,
        atalho: str = "",
    ) -> Escuta:
        return cls(
            modo=modo_de(modo),
            detector=DetectorDePalavra(palavra=palavra or PALAVRA_PADRAO, limiar=limiar),
            atalho=atalho,
        )

    # --- trocas (qualquer thread) --------------------------------------------------------
    def trocar(self, modo: ModoDeEscuta) -> None:
        self.modo = modo
        self.armado_ate_ns = 0
        self._avisar()

    def trocar_palavra(self, palavra: str, limiar: float | None = None) -> None:
        """Monta o detector novo **antes** de trocar: palavra inválida não derruba a antiga."""
        novo = DetectorDePalavra(
            palavra=palavra, limiar=self.detector.limiar if limiar is None else limiar
        )
        self.detector = novo
        self.armado_ate_ns = 0
        self._avisar()

    def trocar_atalho(self, atalho: str, *, global_: bool) -> None:
        self.atalho = atalho
        self.atalho_global = global_
        self._avisar()

    # --- armar (thread do laço) ----------------------------------------------------------
    def armar(self, agora_ns: int, segundos: float = ARMADO_POR_S) -> None:
        self.armado_ate_ns = agora_ns + int(segundos * 1e9)
        self._avisar()

    def armado(self, agora_ns: int) -> bool:
        return self.modo is ModoDeEscuta.PALAVRA and agora_ns < self.armado_ate_ns

    def descartar(self) -> None:
        self.descartados += 1
        self._avisar()

    def descartar_ruido(self) -> None:
        self.ruidos += 1
        self._avisar()

    def desarmar(self) -> None:
        if self.armado_ate_ns:
            self.armado_ate_ns = 0
            self._avisar()

    # --- o que a tela mostra -------------------------------------------------------------
    def frase(self, agora_ns: int) -> str:
        """Quando o Jarvis está ouvindo, em uma frase. É o que o indicador diz ao lado do mic."""
        if self.modo is ModoDeEscuta.ATALHO:
            tecla = self.atalho or "a barra de espaço"
            onde = "" if self.atalho_global else " (com a janela em foco)"
            return f"só ouve enquanto você segura {tecla}{onde}"
        if self.modo is ModoDeEscuta.PALAVRA:
            if self.armado(agora_ns):
                return "chamado: pode falar o pedido"
            return f"só responde quando ouvir “{self.detector.palavra}”"
        return "todo trecho de fala vira pedido"

    def para_dict(self, agora_ns: int) -> dict[str, Any]:
        return {
            "modo": str(self.modo),
            "modoFrase": self.modo.frase,
            "palavra": self.detector.palavra,
            "limiar": self.detector.limiar,
            "atalho": self.atalho,
            "atalhoGlobal": self.atalho_global,
            "armado": self.armado(agora_ns),
            "descartados": self.descartados,
            "ruidos": self.ruidos,
            "frase": self.frase(agora_ns),
        }

    def _avisar(self) -> None:
        if self.ao_mudar is not None:
            self.ao_mudar()
