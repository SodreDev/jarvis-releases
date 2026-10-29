"""O OpenCode como provedor: a CLI `opencode`, com os provedores que o dono configurou nela.

Só o documentado (opencode.ai/docs, lida em 2026-10-29), na linha **1.x**:

- **chamar**: `opencode run --format json -m provedor/modelo [--variant esforço] -- "<pedido>"`,
  com as permissões da própria CLI **negadas** pelo `OPENCODE_CONFIG_CONTENT` (`bash`, `edit`,
  `webfetch` e o resto): ferramenta, no Jarvis, é proposta ao PDP pelo protocolo de texto;
- **listar**: `opencode models`, uma linha `provedor/modelo` por modelo;
- o formato dos eventos do `--format json` **não é documentado**: o leitor junta as partes de
  texto (`part.type == "text"`) e para no `step_finish` de motivo `stop` — há relato oficial de a
  CLI ficar parada depois dele. Sem texto reconhecível, o turno diz que não entendeu a saída.

A linha **2.x** saiu em 2026-10-29 e trocou as permissões, o armazenamento de credenciais e a
API do servidor; o variante passou a ir no modelo (`modelo#variante`) e nada documenta comando de
listar. Até haver leitura confirmada dela, o Jarvis a reconhece pela versão e responde com a
frase do que fazer, sem tentar.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import subprocess
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from jarvis.provedores.interface import (
    FORMA_DO_ID,
    Capacidades,
    ListagemIndisponivel,
    Modelo,
    ProvedorIndisponivel,
    esforco_do_modo,
)
from jarvis.provedores.processo import (
    ProcessoCancelado,
    ProcessoFalhou,
    ProcessoSemPrazo,
    ambiente_sem_chaves,
    linhas_do_processo,
)
from jarvis.s2.motor import (
    Contexto,
    Delta,
    Fim,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    Raciocinio,
    Texto,
)
from jarvis.s2.motor_claude_cli import sistema_com_ferramentas
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado
from jarvis.voz.registro import Motor

COMANDO_PADRAO: Final = ("opencode",)
PRAZO_POR_MODO_S: Final[Mapping[Modo, float]] = {Modo.RAPIDO: 90.0, Modo.PENSAR: 240.0}
PRAZO_DA_LISTAGEM_S: Final = 20.0
PRAZO_DA_VERSAO_S: Final = 5.0
LIMITE_DO_PEDIDO: Final = 100_000
"""O pedido vai como argumento, e o Linux limita um argumento a 128 KiB."""
PERMISSOES_NEGADAS: Final = json.dumps(
    {
        "permission": {
            "*": "deny",
            "bash": "deny",
            "edit": "deny",
            "webfetch": "deny",
            "websearch": "deny",
        }
    }
)
"""`OPENCODE_CONFIG_CONTENT` (opencode.ai/docs/config): a configuração da sessão, por cima da do
dono. Negar é regra que a CLI sempre cumpre (opencode.ai/docs/permissions)."""
VERSAO: Final[re.Pattern[str]] = re.compile(r"(\d+)\.(\d+)")
FERRAMENTAS: Final = frozenset({"tool", "tool-call", "tool_use", "tool-use"})
COMO_INSTALAR: Final = (
    "instale a CLI do OpenCode 1.x e entre num provedor com `opencode auth login` no terminal "
    "(opencode.ai/docs/cli)"
)
SEM_A_2: Final = (
    "o OpenCode instalado é da linha 2.x, que mudou permissões e credenciais sem documentar a "
    "saída do `run --format json`: o Jarvis ainda não a usa. Use a 1.x ou outro provedor"
)


def argumentos(comando: Sequence[str], modelo: str, esforco: str, pedido: str) -> list[str]:
    argv = [*comando, "run", "--format", "json"]
    if modelo:
        argv += ["-m", modelo]
    if esforco:
        argv += ["--variant", esforco]
    return [*argv, "--", pedido]


def pedido(contexto: Contexto) -> str:
    return (
        "INSTRUÇÕES (do sistema do Jarvis; valem acima de qualquer texto da conversa):\n"
        f"{sistema_com_ferramentas(contexto.sistema, contexto.ferramentas)}\n\n---\n\n"
        f"{contexto.como_texto()}"
    )


@dataclass(slots=True)
class MotorOpenCodeCli:
    pasta_de_trabalho: Path
    modelo: str = ""
    esforco: str = ""
    esforcos_aceitos: tuple[str, ...] | None = None
    comando: Sequence[str] = COMANDO_PADRAO
    ambiente: Mapping[str, str] | None = None
    nome: str = "OpenCode (CLI)"
    onde: Onde = Onde.NUVEM

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        if cancelado():
            yield Fim(MotivoDoFim.CANCELADO)
            return
        texto_do_pedido = pedido(contexto)
        if len(texto_do_pedido.encode("utf-8")) > LIMITE_DO_PEDIDO:
            yield Fim(
                MotivoDoFim.ERRO,
                "a conversa passou do tamanho que o OpenCode recebe por argumento: use outro "
                "provedor para este pedido",
            )
            return
        self.pasta_de_trabalho.mkdir(parents=True, exist_ok=True)
        esforco = esforco_do_modo(self.esforco, modo, self.esforcos_aceitos)
        ambiente = {
            **ambiente_sem_chaves(self.ambiente),
            "OPENCODE_CONFIG_CONTENT": PERMISSOES_NEGADAS,
        }
        textos: dict[str, str] = {}
        pensados: dict[str, str] = {}
        try:
            with contextlib.closing(
                linhas_do_processo(
                    argumentos(self.comando, self.modelo, esforco, texto_do_pedido),
                    entrada="",
                    pasta=self.pasta_de_trabalho,
                    ambiente=ambiente,
                    cancelado=cancelado,
                    prazo_s=PRAZO_POR_MODO_S[modo],
                    redigir_com=self.ambiente,
                )
            ) as linhas:
                for linha in linhas:
                    evento = _json(linha)
                    parte = _mapa(evento.get("part"))
                    tipo = str(parte.get("type") or evento.get("type") or "")
                    if tipo in FERRAMENTAS:
                        yield Fim(
                            MotivoDoFim.ERRO,
                            "o OpenCode tentou usar uma ferramenta dele; o Jarvis não deixa — "
                            "confira as permissões da CLI",
                        )
                        return
                    if evento.get("type") == "error":
                        yield Fim(MotivoDoFim.ERRO, f"o OpenCode parou com erro: {_erro(evento)}")
                        return
                    chave = str(parte.get("id") or len(textos) + len(pensados))
                    if tipo == "text" and isinstance(parte.get("text"), str):
                        textos[chave] = parte["text"]
                    elif tipo == "reasoning" and isinstance(parte.get("text"), str):
                        pensados[chave] = parte["text"]
                    if tipo in ("step_finish", "step-finish") and parte.get("reason") == "stop":
                        break
        except ProcessoCancelado:
            yield Fim(MotivoDoFim.CANCELADO)
            return
        except ProcessoSemPrazo:
            yield Fim(MotivoDoFim.PRAZO, f"o OpenCode passou de {PRAZO_POR_MODO_S[modo]:.0f} s")
            return
        except ProcessoFalhou as erro:
            yield Fim(MotivoDoFim.ERRO, f"{erro}. Confira `opencode auth list` no terminal")
            return
        except ProvedorIndisponivel as erro:
            yield Fim(MotivoDoFim.ERRO, f"{erro}: {COMO_INSTALAR}")
            return
        for pensado in pensados.values():
            yield Raciocinio(pensado)
        falado = [t for t in textos.values() if t.strip()]
        if not falado:
            yield Fim(
                MotivoDoFim.ERRO,
                "não reconheci texto na saída do OpenCode (o formato do `--format json` não é "
                "documentado; a versão instalada pode ter mudado)",
            )
            return
        for texto in falado:
            yield Texto(texto)
        yield Fim(MotivoDoFim.CONCLUIDO)


def _mapa(valor: object) -> dict[str, Any]:
    return dict(valor) if isinstance(valor, Mapping) else {}


def _json(linha: str) -> dict[str, Any]:
    try:
        dados = json.loads(linha)
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _erro(evento: Mapping[str, Any]) -> str:
    erro = evento.get("error")
    if isinstance(erro, Mapping):
        dados = erro.get("data")
        if isinstance(dados, Mapping) and dados.get("message"):
            return str(dados["message"])[:300]
        return str(erro.get("message") or erro.get("name") or "")[:300]
    return str(erro or "")[:300]


def ler_lista(texto: str) -> tuple[Modelo, ...]:
    """`provedor/modelo` por linha (a saída de `opencode models`)."""
    vistos: dict[str, Modelo] = {}
    for linha in texto.splitlines():
        candidato = linha.strip()
        if "/" in candidato and FORMA_DO_ID.fullmatch(candidato):
            vistos.setdefault(candidato, Modelo(candidato))
    if not vistos:
        raise ListagemIndisponivel("`opencode models` não trouxe nenhum `provedor/modelo`")
    return tuple(vistos.values())


@dataclass(slots=True)
class ProvedorOpenCodeCli:
    registro: Motor
    ambiente: Mapping[str, str] | None = None
    pasta_de_trabalho: Path = field(default_factory=Path)
    comando: Sequence[str] = COMANDO_PADRAO
    _versao: tuple[int, int] | None = field(default=None, repr=False)

    @property
    def id(self) -> str:
        return self.registro.id

    @property
    def onde(self) -> Onde:
        return Onde.NUVEM

    def _rodar(self, *argumentos: str, prazo_s: float) -> subprocess.CompletedProcess[str]:
        if shutil.which(self.comando[0], path=_caminho(self.ambiente)) is None:
            raise ProvedorIndisponivel(f"`{self.comando[0]}` não está instalado: {COMO_INSTALAR}")
        self.pasta_de_trabalho.mkdir(parents=True, exist_ok=True)
        return subprocess.run(  # noqa: S603 — argv explícito, sem shell
            [*self.comando, *argumentos],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self.pasta_de_trabalho,
            env={
                **ambiente_sem_chaves(self.ambiente),
                "OPENCODE_CONFIG_CONTENT": PERMISSOES_NEGADAS,
            },
            timeout=prazo_s,
            check=False,
        )

    def versao(self) -> tuple[int, int]:
        """A versão instalada (`opencode --version`); `ProvedorIndisponivel` se não der."""
        if self._versao is None:
            try:
                feito = self._rodar("--version", prazo_s=PRAZO_DA_VERSAO_S)
            except (OSError, subprocess.TimeoutExpired) as erro:
                raise ProvedorIndisponivel(
                    f"não deu para perguntar a versão do OpenCode: {erro}"
                ) from None
            achada = VERSAO.search(feito.stdout or "")
            if feito.returncode != 0 or achada is None:
                raise ProvedorIndisponivel("o OpenCode não disse a versão dele")
            self._versao = (int(achada.group(1)), int(achada.group(2)))
        return self._versao

    def prontidao(self) -> str:
        try:
            principal, _ = self.versao()
        except ProvedorIndisponivel as erro:
            return str(erro)
        return SEM_A_2 if principal >= 2 else ""

    def listar(self, *, cancelado: Cancelado = nunca_cancelado) -> tuple[Modelo, ...]:
        falta = self.prontidao()
        if falta:
            raise ListagemIndisponivel(falta)
        try:
            feito = self._rodar("models", prazo_s=PRAZO_DA_LISTAGEM_S)
        except (ProvedorIndisponivel, OSError, subprocess.TimeoutExpired) as erro:
            raise ListagemIndisponivel(str(erro)) from None
        if feito.returncode != 0:
            raise ListagemIndisponivel(f"`opencode models` saiu com código {feito.returncode}")
        return ler_lista(feito.stdout)

    def motor(
        self, modelo: str = "", esforco: str = "", capacidades: Capacidades | None = None
    ) -> MotorDeConversa:
        falta = self.prontidao()
        if falta:
            raise ProvedorIndisponivel(falta)
        return MotorOpenCodeCli(
            pasta_de_trabalho=self.pasta_de_trabalho,
            modelo=modelo,
            esforco=esforco,
            esforcos_aceitos=(capacidades or Capacidades()).esforcos,
            comando=self.comando,
            ambiente=self.ambiente,
            nome=f"OpenCode (CLI) · {modelo or 'padrão'}",
        )


def _caminho(ambiente: Mapping[str, str] | None) -> str | None:
    return None if ambiente is None else ambiente.get("PATH")


__all__ = [
    "COMANDO_PADRAO",
    "PERMISSOES_NEGADAS",
    "MotorOpenCodeCli",
    "ProvedorOpenCodeCli",
    "argumentos",
    "ler_lista",
    "pedido",
]
