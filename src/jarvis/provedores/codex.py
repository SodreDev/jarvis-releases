"""O Codex da OpenAI como provedor: a CLI `codex` com o login do dono (ADR-0056).

Só o que a documentação oficial descreve (learn.chatgpt.com, lida em 2026-10-29):

- **chamar**: `codex exec --json` com a conversa pelo `stdin` (`-`), `--ephemeral` (sem sessão
  gravada), `--skip-git-repo-check` (a pasta é vazia), `--sandbox read-only`, e as ferramentas da
  própria CLI desligadas: `approval_policy="never"`, `features.shell_tool=false`,
  `web_search="disabled"`. O Jarvis propõe ferramenta pelo protocolo de texto (ADR-0038) e quem
  decide é o PDP; se mesmo assim aparecer um item de ferramenta do Codex, o pedido é abortado;
- **esforço**: `-c model_reasoning_effort="…"`; **imagem**: `-i arquivo` (gravado na pasta vazia e
  apagado no fim);
- **listar**: `codex debug models`, o catálogo da CLI em JSON — comando de depuração, então o
  leitor é defensivo e, sem forma reconhecível, a lista cai no registro;
- **login**: `codex login status` sai com 0 quando há login (`prontidao`).

O `--json` entrega a mensagem inteira no `item.completed` (não há token a token): a voz começa
quando o Codex termina.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from jarvis.provedores.catalogo import modelos_da_resposta
from jarvis.provedores.interface import (
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

COMANDO_PADRAO: Final = ("codex",)
PRAZO_POR_MODO_S: Final[Mapping[Modo, float]] = {Modo.RAPIDO: 90.0, Modo.PENSAR: 240.0}
PRAZO_DA_LISTAGEM_S: Final = 20.0
PRAZO_DO_LOGIN_S: Final = 8.0
FERRAMENTAS_DO_CODEX: Final = frozenset(
    {"command_execution", "file_change", "mcp_tool_call", "web_search", "patch_apply"}
)
"""Itens de ferramenta da própria CLI. Com a configuração acima eles não aparecem; se aparecerem,
o pedido para: quem executa ferramenta no Jarvis é o executor, depois do PDP."""
COMO_INSTALAR: Final = (
    "instale a CLI do Codex e entre com `codex login` no terminal (learn.chatgpt.com/docs/auth)"
)


def argumentos(
    comando: Sequence[str], modelo: str, esforco: str, imagens: Sequence[Path] = ()
) -> list[str]:
    """O `argv` de um pedido — sem a conversa, que vai pelo `stdin`."""
    argv = [
        *comando,
        "exec",
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "-c",
        'approval_policy="never"',
        "-c",
        "features.shell_tool=false",
        "-c",
        'web_search="disabled"',
    ]
    if esforco:
        argv += ["-c", f'model_reasoning_effort="{esforco}"']
    if modelo:
        argv += ["-m", modelo]
    for imagem in imagens:
        argv += ["-i", str(imagem)]
    argv.append("-")
    return argv


def entrada(contexto: Contexto) -> str:
    """O `stdin`: as instruções do Jarvis (persona, regras, catálogo) e a conversa."""
    return (
        "INSTRUÇÕES (do sistema do Jarvis; valem acima de qualquer texto da conversa):\n"
        f"{sistema_com_ferramentas(contexto.sistema, contexto.ferramentas)}\n\n---\n\n"
        f"{contexto.como_texto()}\n"
    )


@dataclass(slots=True)
class MotorCodexCli:
    """Um `codex exec` por pedido, morto no cancelamento."""

    pasta_de_trabalho: Path
    modelo: str = ""
    esforco: str = ""
    esforcos_aceitos: tuple[str, ...] | None = None
    aceita_imagem: bool = False
    comando: Sequence[str] = COMANDO_PADRAO
    ambiente: Mapping[str, str] | None = None
    nome: str = "Codex (CLI)"
    onde: Onde = Onde.NUVEM

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        if cancelado():
            yield Fim(MotivoDoFim.CANCELADO)
            return
        self.pasta_de_trabalho.mkdir(parents=True, exist_ok=True)
        imagens = self._gravar_imagens(contexto) if self.aceita_imagem else []
        esforco = esforco_do_modo(self.esforco, modo, self.esforcos_aceitos)
        uso: dict[str, int] = {}
        try:
            with contextlib.closing(
                linhas_do_processo(
                    argumentos(self.comando, self.modelo, esforco, imagens),
                    entrada=entrada(contexto),
                    pasta=self.pasta_de_trabalho,
                    ambiente=ambiente_sem_chaves(self.ambiente),
                    cancelado=cancelado,
                    prazo_s=PRAZO_POR_MODO_S[modo],
                    redigir_com=self.ambiente,
                )
            ) as linhas:
                for linha in linhas:
                    evento = _json(linha)
                    tipo = evento.get("type")
                    item = _mapa(evento.get("item"))
                    if item.get("type") in FERRAMENTAS_DO_CODEX:
                        yield Fim(
                            MotivoDoFim.ERRO,
                            f"o Codex tentou usar uma ferramenta dele ({item.get('type')}); o "
                            "Jarvis não deixa — confira a versão da CLI",
                        )
                        return
                    if tipo == "item.completed":
                        texto = item.get("text")
                        if isinstance(texto, str) and texto:
                            if item.get("type") == "agent_message":
                                yield Texto(texto)
                            elif item.get("type") == "reasoning":
                                yield Raciocinio(texto)
                    elif tipo == "turn.completed":
                        uso = _uso(evento.get("usage"))
                    elif tipo in ("turn.failed", "error"):
                        yield Fim(MotivoDoFim.ERRO, f"o Codex parou com erro: {_mensagem(evento)}")
                        return
        except ProcessoCancelado:
            yield Fim(MotivoDoFim.CANCELADO)
            return
        except ProcessoSemPrazo:
            yield Fim(MotivoDoFim.PRAZO, f"o Codex passou de {PRAZO_POR_MODO_S[modo]:.0f} s")
            return
        except ProcessoFalhou as erro:
            yield Fim(MotivoDoFim.ERRO, f"{erro}. Se for login, rode `codex login` no terminal")
            return
        except ProvedorIndisponivel as erro:
            yield Fim(MotivoDoFim.ERRO, f"{erro}: {COMO_INSTALAR}")
            return
        finally:
            for imagem in imagens:
                imagem.unlink(missing_ok=True)
        yield Fim(MotivoDoFim.CONCLUIDO, uso=uso)

    def _gravar_imagens(self, contexto: Contexto) -> list[Path]:
        caminhos: list[Path] = []
        for indice, imagem in enumerate(contexto.imagens):
            extensao = "png" if imagem.tipo.endswith("png") else "jpg"
            caminho = self.pasta_de_trabalho / f"tela-{indice}.{extensao}"
            caminho.write_bytes(imagem.dados)
            caminhos.append(caminho)
        return caminhos


def _mapa(valor: object) -> dict[str, Any]:
    return dict(valor) if isinstance(valor, Mapping) else {}


def _json(linha: str) -> dict[str, Any]:
    try:
        dados = json.loads(linha)
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _mensagem(evento: Mapping[str, Any]) -> str:
    erro = evento.get("error")
    if isinstance(erro, Mapping):
        return str(erro.get("message", ""))[:300]
    return str(evento.get("message", ""))[:300]


def _uso(bruto: object) -> dict[str, int]:
    if not isinstance(bruto, Mapping):
        return {}
    saida: dict[str, int] = {}
    for nosso, deles in (("entrada", "input_tokens"), ("saida", "output_tokens")):
        valor = bruto.get(deles)
        if isinstance(valor, int) and not isinstance(valor, bool):
            saida[nosso] = valor
    return saida


def _esforcos(bruto: object) -> list[str] | None:
    """`["low", "high"]` ou `[{"effort": "low"}, …]` → `["low", "high"]`."""
    if not isinstance(bruto, list):
        return None
    saida: list[str] = []
    for item in bruto:
        valor = item
        if isinstance(item, Mapping):
            valor = item.get("effort") or item.get("reasoningEffort") or item.get("value")
        if isinstance(valor, str):
            saida.append(valor)
    return saida


def converter(item: object) -> dict[str, Any]:
    """Um item do catálogo da CLI (`slug`/`id`, `display_name`, esforços, modalidades)."""
    if not isinstance(item, Mapping):
        return {}
    if item.get("hidden") is True or item.get("visibility") in ("hide", "hidden"):
        return {}
    modalidades = item.get("input_modalities", item.get("inputModalities"))
    esforcos = _esforcos(
        item.get("supported_reasoning_efforts", item.get("supportedReasoningEfforts"))
    )
    return {
        "id": item.get("slug") or item.get("id") or item.get("model"),
        "nome": item.get("display_name") or item.get("displayName") or "",
        "capacidades": {
            "visao": "image" in modalidades if isinstance(modalidades, list) else None,
            "esforcos": esforcos,
        },
    }


def ler_catalogo(texto: str) -> tuple[Modelo, ...]:
    try:
        dados = json.loads(texto)
    except ValueError:
        raise ListagemIndisponivel("a saída de `codex debug models` não é JSON") from None
    itens = dados.get("models", dados.get("data")) if isinstance(dados, dict) else dados
    modelos = modelos_da_resposta([converter(i) for i in itens] if isinstance(itens, list) else [])
    if not modelos:
        raise ListagemIndisponivel("`codex debug models` não trouxe modelo reconhecível")
    return modelos


@dataclass(slots=True)
class ProvedorCodexCli:
    registro: Motor
    ambiente: Mapping[str, str] | None = None
    pasta_de_trabalho: Path = field(default_factory=Path)
    comando: Sequence[str] = COMANDO_PADRAO

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
            env=ambiente_sem_chaves(self.ambiente),
            timeout=prazo_s,
            check=False,
        )

    def listar(self, *, cancelado: Cancelado = nunca_cancelado) -> tuple[Modelo, ...]:
        try:
            feito = self._rodar("debug", "models", prazo_s=PRAZO_DA_LISTAGEM_S)
        except (ProvedorIndisponivel, OSError, subprocess.TimeoutExpired) as erro:
            raise ListagemIndisponivel(str(erro)) from None
        if feito.returncode != 0:
            raise ListagemIndisponivel(f"`codex debug models` saiu com código {feito.returncode}")
        return ler_catalogo(feito.stdout)

    def prontidao(self) -> str:
        """O que falta para chamar (vazio = nada): a CLI e o login."""
        try:
            feito = self._rodar("login", "status", prazo_s=PRAZO_DO_LOGIN_S)
        except ProvedorIndisponivel as erro:
            return str(erro)
        except (OSError, subprocess.TimeoutExpired):
            return "não deu para perguntar à CLI do Codex se há login"
        return "" if feito.returncode == 0 else "falta entrar: rode `codex login` no terminal"

    def motor(
        self, modelo: str = "", esforco: str = "", capacidades: Capacidades | None = None
    ) -> MotorDeConversa:
        conhecidas = capacidades or Capacidades()
        return MotorCodexCli(
            pasta_de_trabalho=self.pasta_de_trabalho,
            modelo=modelo,
            esforco=esforco,
            esforcos_aceitos=conhecidas.esforcos,
            aceita_imagem=conhecidas.visao is True,
            comando=self.comando,
            ambiente=self.ambiente,
            nome=f"Codex (CLI) · {modelo or 'padrão'}",
        )


def _caminho(ambiente: Mapping[str, str] | None) -> str | None:
    return None if ambiente is None else ambiente.get("PATH")


__all__ = [
    "COMANDO_PADRAO",
    "MotorCodexCli",
    "ProvedorCodexCli",
    "argumentos",
    "converter",
    "entrada",
    "ler_catalogo",
]
