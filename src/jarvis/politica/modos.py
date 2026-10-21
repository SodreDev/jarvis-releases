"""Os quatro modos de acesso e a lista de negação (SPEC §5.5, ADR-0009).

Ordem real de amplitude: `jarvis ⊂ padrao ⊂ concedido ⊂ total`. A numeração do dono ("nível
2" é a pasta do Jarvis) é preservada como nome, porque é como ele fala; a UI lista por
amplitude.

A lista de negação **vence até no `total`**: "PC inteiro" não é "credenciais".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from jarvis.politica.canonicalizacao import CaminhoCanonico, Sistema, canonicalizar


class Modo(StrEnum):
    """Modo de acesso, do mais estreito para o mais amplo."""

    JARVIS = "jarvis"
    PADRAO = "padrao"
    CONCEDIDO = "concedido"
    TOTAL = "total"

    @property
    def amplitude(self) -> int:
        return AMPLITUDE[self]

    @property
    def nome_do_dono(self) -> str:
        return NOME_DO_DONO[self]


AMPLITUDE: Final[dict[Modo, int]] = {
    Modo.JARVIS: 0,
    Modo.PADRAO: 1,
    Modo.CONCEDIDO: 2,
    Modo.TOTAL: 3,
}
NOME_DO_DONO: Final[dict[Modo, str]] = {
    Modo.JARVIS: "nível 2 — só a pasta do Jarvis",
    Modo.PADRAO: "nível 1 — só pastas padrão",
    Modo.CONCEDIDO: "nível 3 — pastas específicas concedidas",
    Modo.TOTAL: "nível 4 — PC inteiro, menos a lista de negação",
}

PASTAS_PADRAO: Final[tuple[str, ...]] = (
    "Documentos",
    "Downloads",
    "Imagens",
    "Música",
    "Vídeos",
    "Área de Trabalho",
)
"""Nomes em pt-BR; o mapeamento para XDG (`xdg-user-dirs`) e para as pastas conhecidas do
Windows é do cartão F0-07 — aqui a forma importa, não a descoberta."""


@dataclass(frozen=True, slots=True)
class Raiz:
    """Uma raiz autorizada, com permissão própria (§5.5: "permissão por raiz")."""

    nome: str
    caminho: CaminhoCanonico
    pode_ler: bool = True
    pode_escrever: bool = False


NEGADOS_RELATIVOS_AO_LAR: Final[tuple[str, ...]] = (
    ".ssh",
    ".gnupg",
    ".pki",
    ".password-store",
    ".local/share/keyrings",
    ".config/google-chrome",
    ".config/chromium",
    ".config/BraveSoftware",
    ".mozilla",
    ".thunderbird",
    ".aws",
    ".kube",
    ".docker/config.json",
    ".netrc",
    ".git-credentials",
    ".cache/keyring",
    ".local/share/jarvis/cofre",
    ".local/share/jarvis/vozes",
    ".local/share/jarvis/omnivoice",
    ".electrum",
    ".bitcoin",
    ".ethereum",
    "AppData/Local/Microsoft/Credentials",
    "AppData/Roaming/Microsoft/Credentials",
    "AppData/Local/Microsoft/Vault",
    "AppData/Local/Google/Chrome/User Data",
    "AppData/Roaming/Mozilla/Firefox",
    "AppData/Local/Packages/Microsoft.Windows.Cortana_cw5n1h2txyewy",
    "AppData/Local/jarvis/vozes",
    "AppData/Local/jarvis/omnivoice",
)
"""Chaves, chaveiros, perfis de navegador, carteiras e o cofre do próprio Jarvis — e as vozes de
referência do dono e o motor de uso pessoal (ADR-0039): voz é dado biométrico, e nenhuma
ferramenta de arquivo lê uma voz para fora nem põe áudio de terceiro lá para ser clonado."""

NEGADOS_ABSOLUTOS_POSIX: Final[tuple[str, ...]] = (
    "/etc/shadow",
    "/etc/gshadow",
    "/etc/sudoers",
    "/etc/sudoers.d",
    "/etc/ssh",
    "/proc/kcore",
    "/sys/kernel",
    "/dev/mem",
    "/var/lib/sss/secrets",
)
NEGADOS_ABSOLUTOS_WINDOWS: Final[tuple[str, ...]] = (
    "C:\\Windows\\System32\\config",
    "C:\\Windows\\System32\\lsass.exe",
    "C:\\Windows\\System32\\winevt",
    "C:\\ProgramData\\Microsoft\\Crypto",
)
NOMES_NEGADOS: Final[tuple[str, ...]] = (".env", ".envrc", "id_rsa", "id_ed25519", "credentials")
"""Negados onde estiverem, por nome: `.env` dentro de um projeto é segredo igual."""


def lista_de_negacao(lar: Path, sistema: Sistema) -> tuple[CaminhoCanonico, ...]:
    """Caminhos negados, já canônicos. Vale em todos os modos, inclusive no `total` (P13)."""
    lar_canonico = canonicalizar(str(lar), sistema)
    separador = "\\" if sistema is Sistema.WINDOWS else "/"
    negados = [
        canonicalizar(lar_canonico.texto + separador + alvo.replace("/", separador), sistema)
        for alvo in NEGADOS_RELATIVOS_AO_LAR
    ]
    absolutos = NEGADOS_ABSOLUTOS_WINDOWS if sistema is Sistema.WINDOWS else NEGADOS_ABSOLUTOS_POSIX
    negados += [canonicalizar(alvo, sistema) for alvo in absolutos]
    return tuple(negados)


def motivo_de_negacao(caminho: CaminhoCanonico, lar: Path, sistema: Sistema) -> str | None:
    """Motivo pelo qual este caminho é negado, ou `None`. Nunca "confirmável" (§5.5)."""
    for negado in lista_de_negacao(lar, sistema):
        if caminho.dentro_de(negado) or caminho.partes == negado.partes:
            return f"lista de negação: {negado.texto}"
    alvo = caminho.partes[-1] if caminho.partes else ""
    comparavel = alvo if sistema is Sistema.WINDOWS else alvo.casefold()
    if comparavel in NOMES_NEGADOS:
        return f"lista de negação por nome: {alvo}"
    return None


def raizes_do_modo(
    modo: Modo,
    *,
    lar: Path,
    pasta_do_jarvis: Path | None = None,
    concedidas: tuple[Raiz, ...] = (),
    sistema: Sistema = Sistema.POSIX,
) -> tuple[Raiz, ...]:
    """Raízes que o modo materializa, na ordem de amplitude da §5.5."""
    separador = "\\" if sistema is Sistema.WINDOWS else "/"
    jarvis = pasta_do_jarvis or (lar / ".local" / "share" / "jarvis")
    raiz_jarvis = Raiz(
        nome="jarvis_root",
        caminho=canonicalizar(str(jarvis), sistema),
        pode_ler=True,
        pode_escrever=True,
    )
    if modo is Modo.JARVIS:
        return (raiz_jarvis,)

    padrao = tuple(
        Raiz(
            nome=nome,
            caminho=canonicalizar(
                canonicalizar(str(lar), sistema).texto + separador + nome, sistema
            ),
            pode_ler=True,
            pode_escrever=True,
        )
        for nome in PASTAS_PADRAO
    )
    if modo is Modo.PADRAO:
        return (raiz_jarvis, *padrao)
    if modo is Modo.CONCEDIDO:
        return (raiz_jarvis, *padrao, *concedidas)

    tudo = Raiz(
        nome="arvore_do_dono",
        caminho=canonicalizar(str(lar), sistema),
        pode_ler=True,
        pode_escrever=True,
    )
    sistema_todo = Raiz(
        nome="sistema",
        caminho=canonicalizar("C:\\" if sistema is Sistema.WINDOWS else "/", sistema),
        pode_ler=True,
        pode_escrever=False,
    )
    return (raiz_jarvis, *padrao, *concedidas, tudo, sistema_todo)
