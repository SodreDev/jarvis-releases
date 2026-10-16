"""A chave de API no chaveiro do sistema — porque o menu de aplicativos não tem shell.

**O problema que isto resolve.** `jarvis.voz.chaves` é categórico, e continua valendo: a chave
vem do ambiente, nunca do repositório, nunca da configuração, nunca de `argv`. Isso funciona
perfeitamente quando o dono roda `jarvis-voz` num terminal onde ele deu `export`. Abrir o
aplicativo **pelo ícone** não passa pelo `~/.bashrc` de ninguém: o processo nasce com o
ambiente da sessão gráfica, e a chave simplesmente não existe ali.

**A saída que não afrouxa nada.** O chaveiro do sistema (Secret Service — libsecret no GNOME,
KWallet no KDE Plasma) guarda o segredo cifrado, destrancado pela sessão do dono, fora do
disco do projeto. A janela guarda e lê por ali, e entrega o valor ao laço **como um mapa de
ambiente em memória** (`ambiente_com_chaves`), que `Aplicativo` já aceita — então a chave:

- não entra no `os.environ` do processo (nada de `/proc/<pid>/environ` para outro processo
  ler), nem em `argv`, nem no TOML, nem em log;
- não aparece na tela: a aba de configuração mostra **de onde** a chave vem (ambiente,
  chaveiro, ausente), nunca o valor, nem truncado;
- não é lida por quem não precisa: `valor()` é o único acesso, tem nome fácil de procurar e é
  chamado em um lugar só.

**Sem chaveiro, diz.** Numa sessão sem Secret Service (um tty, um contêiner, um desktop sem
agente), guardar falha com frase — e a frase manda exportar a variável, que é o caminho que
sempre funcionou. Nada é escrito "em algum outro lugar" por conveniência.

A biblioteca é `keyring` (MIT), com `SecretStorage` (BSD-3) e `jeepney` (MIT) no Linux: três
licenças permissivas, registradas em `licenses/bibliotecas-distribuidas.toml` (ADR-0019).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Final

from jarvis.ambiente import ambiente_ou_os
from jarvis.voz.chaves import VARIAVEIS, Chave, SegredoAusente

SERVICO: Final = "jarvis"
"""O "serviço" no chaveiro. O nome da variável de ambiente é a "conta"."""


class ChaveiroIndisponivel(RuntimeError):
    """Não há Secret Service nesta sessão. A frase diz o que fazer em vez disso."""


class Fonte(StrEnum):
    """De onde a chave vem — é isto que a tela mostra, nunca o valor."""

    AMBIENTE = "ambiente"
    """Exportada no shell: continua tendo precedência, porque é o caminho mais explícito."""

    CHAVEIRO = "chaveiro"
    AUSENTE = "ausente"

    @property
    def frase(self) -> str:
        return {
            Fonte.AMBIENTE: "definida (variável de ambiente)",
            Fonte.CHAVEIRO: "definida (chaveiro do sistema)",
            Fonte.AUSENTE: "AUSENTE",
        }[self]


def _modulo() -> Any:
    try:
        import keyring
    except ImportError as erro:  # pragma: no cover — só sem o grupo `gui` instalado
        raise ChaveiroIndisponivel(
            "a biblioteca `keyring` não está instalada (`uv sync --group gui`). Enquanto "
            "isso, exporte a chave no shell antes de abrir o Jarvis"
        ) from erro
    return keyring


def disponivel() -> tuple[bool, str]:
    """(dá para usar?, frase). A frase é o que a tela mostra quando não dá."""
    try:
        chaveiro = _modulo().get_keyring()
    except ChaveiroIndisponivel as erro:
        return False, str(erro)
    # O `keyring` não levanta quando não há chaveiro: ele devolve o back-end
    # `keyring.backends.fail.Keyring`, que só explode na hora de usar. Olhar o módulo **e** o
    # nome da classe é o que distingue "não há chaveiro" de "há e está trancado".
    nome = type(chaveiro).__name__
    identificacao = f"{type(chaveiro).__module__}.{nome}"
    if "fail" in identificacao.casefold():
        return False, (
            "esta sessão não tem chaveiro (Secret Service): no KDE é o KWallet, no GNOME é o "
            "gnome-keyring. Sem ele, exporte a chave no shell antes de abrir o Jarvis"
        )
    familia = type(chaveiro).__module__.rsplit(".", 1)[-1]
    return True, f"chaveiro do sistema: {familia}"


def guardar(variavel: str, valor: str) -> None:
    """Grava a chave no chaveiro. Valor curto demais é recusado antes de sair daqui.

    A validação é a mesma de `jarvis.voz.chaves.Chave`: guardar meia chave colada por engano
    faria o serviço responder 401 e o dono procurar o problema no lugar errado.
    """
    chave = Chave(variavel=variavel, valor=valor.strip())  # levanta SegredoAusente se não presta
    pode, frase = disponivel()
    if not pode:
        raise ChaveiroIndisponivel(frase)
    try:
        _modulo().set_password(SERVICO, chave.variavel, chave.usar())
    except Exception as erro:  # o keyring levanta exceção própria por back-end
        raise ChaveiroIndisponivel(f"o chaveiro recusou guardar: {erro}") from erro


def esquecer(variavel: str) -> None:
    """Apaga a chave do chaveiro. Não existir ali não é erro."""
    pode, frase = disponivel()
    if not pode:
        raise ChaveiroIndisponivel(frase)
    try:
        _modulo().delete_password(SERVICO, variavel)
    except Exception:  # "não havia nada para apagar" é o resultado desejado, não uma falha
        return


def valor(variavel: str) -> str | None:
    """O segredo guardado, ou `None`. **Único** acesso ao valor — e ele não é impresso aqui."""
    pode, _ = disponivel()
    if not pode:
        return None
    try:
        guardado = _modulo().get_password(SERVICO, variavel)
    except Exception:  # chaveiro trancado, D-Bus caído: para quem chama é "não tem"
        return None
    return guardado or None


def fonte_da_chave(variavel: str, *, ambiente: Mapping[str, str] | None = None) -> Fonte:
    """De onde esta chave viria agora. Lê presença, nunca conteúdo."""
    if Chave.presente(variavel, ambiente=ambiente):
        return Fonte.AMBIENTE
    return Fonte.CHAVEIRO if valor(variavel) else Fonte.AUSENTE


def ambiente_com_chaves(
    ambiente: Mapping[str, str] | None = None, *, variaveis: Sequence[str] = VARIAVEIS
) -> dict[str, str]:
    """O ambiente que a janela entrega ao laço: o do processo **mais** o que está no chaveiro.

    É um mapa em memória, passado por parâmetro (`Aplicativo.ambiente`), e não uma alteração
    de `os.environ`: o segredo não vaza para processo filho nem para `/proc`.

    A variável exportada no shell **ganha** do chaveiro, sempre. É o caminho mais explícito, e
    é o que deixa o dono trocar a chave numa sessão sem mexer no que está guardado.
    """
    fonte = dict(ambiente_ou_os(ambiente))
    for variavel in variaveis:
        if fonte.get(variavel, "").strip():
            continue
        guardado = valor(variavel)
        if guardado:
            fonte[variavel] = guardado
    return fonte


__all__ = [
    "SERVICO",
    "ChaveiroIndisponivel",
    "Fonte",
    "SegredoAusente",
    "ambiente_com_chaves",
    "disponivel",
    "esquecer",
    "fonte_da_chave",
    "guardar",
    "valor",
]
