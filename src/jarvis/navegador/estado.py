"""O estado verdadeiro da ponte com o navegador (ADR-0027): o que o Jarvis diz quando perguntado.

Antes disto, com o controle desligado, as `browser.*` simplesmente não existiam para o modelo — e
ele respondia, com toda franqueza, que não tinha extensão nenhuma (dono, 2026-10-19). Faltava
ligar? Instalar o host? Abrir o navegador? Ninguém dizia. Aqui o **código** responde, sem pedir
nada à extensão nem à página:

- `desligado` — o dono não ligou `navegador_controlado`: as `browser.*` não existem;
- `sem_conexao` — ligado, mas não há host vivo do navegador principal: o navegador está fechado,
  a extensão não está carregada nele, ou falta o manifesto do host para ele;
- `conectado` — há host vivo: a extensão abriu a porta do Native Messaging e o host escuta.

"Vivo" é o `TransporteUnix.vivos`: conectar no socket e soltar. Os manifestos são lidos nas pastas
que o instalador grava (`instalar.destinos_do_usuario`) e nas do pacote; o `path` de cada um tem de
existir e executar — e, quando é o stub do instalador, o programa que ele chama também.
"""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from jarvis.navegador.cliente import (
    ClienteDoNavegador,
    NavegadorIndisponivel,
    TransporteUnix,
    VersaoDaPonte,
    familia_do_host,
)
from jarvis.navegador.instalar import (
    STUB_NO_USUARIO,
    Destino,
    destinos_do_sistema,
    destinos_do_usuario,
)
from jarvis.navegador.protocolo import NOME_DO_HOST, VERSAO_DA_PONTE

SITUACOES: Final = ("desligado", "sem_conexao", "conectado")
COMO_LIGAR: Final = (
    "ligar na janela do Jarvis: Acesso → Navegadores → «deixar o Jarvis controlar as abas» "
    "(ou navegador_controlado = true no jarvis-voz.toml)"
)
COMO_INSTALAR: Final = (
    "rodar `uv run jarvis-native-host --instalar` no repositório do Jarvis (no pacote ou no "
    "AppImage: `jarvis-native-host --instalar`)"
)
DESTINO_DA_FAMILIA: Final[dict[str, str]] = {
    "firefox": "firefox",
    "chrome": "chrome",
    "chromium": "chromium",
    "brave": "brave",
    "edge": "edge",
    "microsoft": "edge",
    "vivaldi": "vivaldi",
}
"""Família da configuração (`familia_de`: «Microsoft Edge» vira `microsoft`) → pasta de manifesto.
Família fora daqui (Opera, LibreWolf…) não tem pasta conferida: o estado não afirma que falta."""


@dataclass(frozen=True, slots=True)
class Manifesto:
    """Um manifesto do host achado numa pasta onde um navegador procura."""

    navegador: str
    arquivo: Path
    executavel: str
    """O `path` de dentro dele (vazio se o arquivo não se lê)."""
    pronto: bool
    """É o nosso host, o `path` existe e executa (e, sendo o stub, o que ele chama também)."""


def alvo_do_stub(stub: Path) -> str | None:
    """O programa que o stub do instalador chama (`exec <programa> …`), ou `None` se não é ele."""
    try:
        linhas = stub.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for linha in linhas:
        if linha.startswith("exec "):
            try:
                partes = shlex.split(linha)
            except ValueError:
                return None
            return partes[1] if len(partes) > 1 else None
    return None


def _executa(caminho: str) -> bool:
    alvo = Path(caminho)
    return alvo.is_absolute() and alvo.is_file() and os.access(alvo, os.X_OK)


def _ler(destino: Destino, home: Path) -> Manifesto | None:
    nome = "firefox" if destino.navegador == "firefox64" else destino.navegador
    try:
        dados = json.loads(destino.arquivo.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return Manifesto(nome, destino.arquivo, "", False)
    if not isinstance(dados, dict):
        return Manifesto(nome, destino.arquivo, "", False)
    executavel = str(dados.get("path", ""))
    pronto = dados.get("name") == NOME_DO_HOST and _executa(executavel)
    if pronto and Path(executavel) == home / STUB_NO_USUARIO:
        alvo = alvo_do_stub(Path(executavel))
        pronto = alvo is not None and _executa(alvo)
    return Manifesto(nome, destino.arquivo, executavel, pronto)


def manifestos(home: Path, raiz_do_sistema: Path = Path("/")) -> tuple[Manifesto, ...]:
    """Os manifestos do host nas pastas do usuário e nas do pacote (`.deb`/`.rpm`)."""
    achados = (
        _ler(d, home) for d in (*destinos_do_usuario(home), *destinos_do_sistema(raiz_do_sistema))
    )
    return tuple(m for m in achados if m is not None)


@dataclass(frozen=True, slots=True)
class EstadoDaPonte:
    ligado: bool
    """`navegador_controlado` da configuração."""
    principal: str
    """O navegador principal do dono (`brave`), ou vazio."""
    vivos: tuple[str, ...]
    """Famílias de host (`chromium`, `firefox`) que aceitam conexão agora."""
    manifestos: tuple[Manifesto, ...]
    em_flatpak: bool = False
    """O principal configurado é um Flatpak (o Native Messaging não sai da caixa de areia)."""
    versao: VersaoDaPonte | None = None
    """A versão do host e da extensão no ar (`sondar(..., conferir_versao=True)` com a extensão
    conectada); `None` = não conferida."""
    falha_da_versao: str = ""
    """Conectada, mas a pergunta da versão não voltou (a extensão travou, o host caiu)."""

    @property
    def desatualizada(self) -> str:
        """Vazio se a versão está em dia (ou não foi conferida); senão, o que o dono faz."""
        if self.falha_da_versao:
            return (
                f"a extensão está conectada mas não respondeu ({self.falha_da_versao}): recarregue "
                "a extensão do Jarvis na página de extensões do navegador"
            )
        return self.versao.o_que_fazer() if self.versao is not None else ""

    @property
    def familia(self) -> str:
        return familia_do_host(self.principal)

    @property
    def conectado(self) -> bool:
        """Há host vivo da família do principal (sem principal, de qualquer uma) — o mesmo
        filtro que o cliente usa para escolher o socket."""
        return self.familia in self.vivos if self.familia else bool(self.vivos)

    @property
    def situacao(self) -> str:
        if not self.ligado:
            return "desligado"
        return "conectado" if self.conectado else "sem_conexao"

    def manifesto_do_principal(self) -> Manifesto | None:
        nome = DESTINO_DA_FAMILIA.get(self.principal.strip().lower(), "")
        prontos = [m for m in self.manifestos if m.navegador == nome]
        return next((m for m in prontos if m.pronto), prontos[0] if prontos else None)

    def frase(self) -> str:
        onde = self.principal or (self.vivos[0] if self.vivos else "")
        if not self.ligado:
            if self.conectado:
                return (
                    f"O controle do navegador está desligado na configuração do Jarvis. A extensão "
                    f"está conectada no {onde}, mas as ferramentas browser.* só existem depois que "
                    "o dono ligar."
                )
            return (
                "O controle do navegador está desligado na configuração do Jarvis, e nenhuma "
                "extensão do Jarvis está conectada agora."
            )
        if self.conectado and self.desatualizada:
            return (
                f"A extensão do Jarvis está conectada no {onde}, mas precisa de atenção: "
                f"{self.desatualizada}."
            )
        if self.conectado:
            return f"Conectado: a extensão do Jarvis está ativa no {onde} e as browser.* funcionam."
        no_principal = f" no {self.principal}" if self.principal else ""
        return (
            f"O controle do navegador está ligado, mas nenhuma extensão do Jarvis está "
            f"conectada{no_principal} agora."
        )

    def o_que_fazer(self) -> tuple[str, ...]:
        """Em ordem: o primeiro item é o que destrava o próximo."""
        passos: list[str] = []
        if not self.ligado:
            passos.append(COMO_LIGAR)
        if self.conectado:
            if self.desatualizada:
                passos.append(self.desatualizada)
            return tuple(passos)
        if self.em_flatpak:
            passos.append(
                f"o {self.principal} configurado é Flatpak: o Native Messaging não lança o host "
                "fora da caixa de areia; use a versão do pacote do sistema (rpm/deb)"
            )
        manifesto = self.manifesto_do_principal()
        conhecido = self.principal.strip().lower() in DESTINO_DA_FAMILIA
        if conhecido and manifesto is None:
            passos.append(
                f"falta o manifesto do host nativo para o {self.principal}: {COMO_INSTALAR}"
            )
        elif manifesto is not None and not manifesto.pronto:
            passos.append(
                f"o manifesto do {manifesto.navegador} ({manifesto.arquivo}) aponta para um host "
                f"que não existe ou não executa ({manifesto.executavel or 'sem path'}): "
                f"{COMO_INSTALAR}"
            )
        elif not self.principal and not any(m.pronto for m in self.manifestos):
            passos.append(f"nenhum navegador tem o manifesto do host nativo: {COMO_INSTALAR}")
        outras = [f for f in self.vivos if f != self.familia]
        if self.familia and outras:
            passos.append(
                f"há extensão conectada no {', '.join(outras)}, mas o navegador principal é o "
                f"{self.principal}: troque o principal em Acesso → Navegadores ou abra o "
                f"{self.principal}"
            )
        alvo = self.principal or "navegador"
        passos.append(
            f"abrir o {alvo} com a extensão do Jarvis carregada (chrome://extensions ou "
            "about:debugging); se ela já estava carregada antes do host ser instalado, clicar em "
            "«Recarregar» nela uma vez"
        )
        return tuple(passos)

    def para_o_modelo(self) -> dict[str, Any]:
        return {
            "situacao": self.situacao,
            "controle_ligado": self.ligado,
            "extensao_conectada": self.conectado,
            "navegadores_conectados": list(self.vivos),
            "navegador_principal": self.principal,
            "frase": self.frase(),
            "o_que_fazer": list(self.o_que_fazer()),
            **self._versao_para_o_modelo(),
        }

    def _versao_para_o_modelo(self) -> dict[str, Any]:
        if self.versao is None and not self.falha_da_versao:
            return {}
        versao = self.versao
        return {
            "versao_esperada": VERSAO_DA_PONTE,
            "versao_da_extensao": versao.extensao if versao is not None else None,
            "versao_do_host": versao.host if versao is not None else None,
            "versao_em_dia": not self.desatualizada,
        }

    def linhas(self) -> list[str]:
        """O mesmo estado, para o `jarvis-voz --diagnostico`."""
        prontos = sorted({m.navegador for m in self.manifestos if m.pronto})
        quebrados = sorted({m.navegador for m in self.manifestos if not m.pronto} - set(prontos))
        linhas = [
            f"  situação: {self.situacao} — {self.frase()}",
            f"  controle (navegador_controlado): {'ligado' if self.ligado else 'desligado'}",
            f"  navegador principal: {self.principal or 'nenhum'}"
            + (f" (host da família {self.familia})" if self.familia else ""),
            f"  extensões conectadas agora: {', '.join(self.vivos) or 'nenhuma'}",
            f"  host nativo instalado para: {', '.join(prontos) or 'nenhum navegador'}"
            + (f"; quebrado em: {', '.join(quebrados)}" if quebrados else ""),
        ]
        if self.versao is not None or self.falha_da_versao:
            linhas.append(f"  versão da ponte: {self.linha_da_versao()}")
        passos = self.o_que_fazer()
        if passos:
            linhas.append("  o que fazer:")
            linhas.extend(f"    - {passo}" for passo in passos)
        return linhas

    def linha_da_versao(self) -> str:
        if self.falha_da_versao:
            return f"sem resposta ({self.falha_da_versao})"
        versao = self.versao
        if versao is None:
            return "não conferida"

        def numero(valor: int | None) -> str:
            return str(valor) if valor is not None else "de antes da pergunta de versão"

        texto = (
            f"esperada {VERSAO_DA_PONTE}; extensão {numero(versao.extensao)}"
            + (f" (manifesto {versao.manifesto})" if versao.manifesto else "")
            + f"; host {numero(versao.host)}"
            + (f" (pid {versao.pid_do_host})" if versao.pid_do_host is not None else "")
        )
        faltam = [p for p in ("debugger", "scripting") if versao.permissoes.get(p) is False]
        if faltam:
            texto += f"; sem a permissão: {', '.join(faltam)}"
        return texto + (" — em dia" if not self.desatualizada else "")


def sondar(
    *,
    ligado: bool,
    principal: str = "",
    navegadores: Mapping[str, str] | None = None,
    transporte: TransporteUnix | None = None,
    home: Path | None = None,
    raiz_do_sistema: Path = Path("/"),
    conferir_versao: bool = False,
) -> EstadoDaPonte:
    """O estado agora. `navegadores` é a configuração separada (`família → caminho`): é por ela
    que se sabe se o principal é um Flatpak. `conferir_versao` pergunta ao host e à extensão
    conectados qual contrato eles conhecem (`host.versao`, `ponte.versao`) — nenhuma aba nem
    página é tocada, e a pergunta tem o prazo curto do método."""
    entrada = (navegadores or {}).get(principal, "")
    canal = transporte or TransporteUnix()
    estado = EstadoDaPonte(
        ligado=ligado,
        principal=principal,
        vivos=canal.vivos(),
        manifestos=manifestos(home or Path.home(), raiz_do_sistema),
        em_flatpak="/flatpak/" in entrada or entrada.startswith("flatpak"),
    )
    if not conferir_versao or not estado.conectado:
        return estado
    cliente = ClienteDoNavegador(canal)
    cliente.navegador = estado.familia
    try:
        versao = cliente.versao()
    except (NavegadorIndisponivel, RuntimeError) as erro:
        return replace(estado, falha_da_versao=str(erro)[:160] or type(erro).__name__)
    return replace(estado, versao=versao)
