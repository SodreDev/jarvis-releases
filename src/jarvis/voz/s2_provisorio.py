"""O "S2" do aplicativo de teste: provisório, sem ferramenta e sem acesso a arquivo (ADR-0018).

Isto **não é** o `s2` da SPEC §2. É a peça do meio do laço de voz do `jarvis-voz`, para o dono
poder conversar e julgar voz, latência e barge-in **hoje**; quando a F2 entregar o `s2` de
verdade, este arquivo sai e `GeradorDeResposta` passa a ser implementado por ele.

As cinco regras da ADR-0018, e onde cada uma está no código:

1. **sem ferramenta, sem arquivo** — `--disallowed-tools` nomeia as ferramentas de efeito e de
   leitura, `--permission-mode manual` não aprova nada sozinho, e o processo roda com `cwd`
   numa **pasta vazia**, não na raiz do repositório (nada de `CLAUDE.md`, nada de arquivo do
   projeto). O P1 vale por construção: este gerador não tem como executar nada;
2. **a fala do dono vai por `stdin`** — `argv` é legível por outro processo do usuário e entra
   em histórico de shell; a transcrição é privada, igual à chave de API;
3. **o que volta é `untrusted`** (P6) — texto é dado: não amplia permissão, não vira memória,
   não escolhe capacidade. Aqui ele só vira voz;
4. **o prazo é nosso** — sem resposta no prazo, o turno **degrada e diz**, em vez de pendurar;
5. **cancelável** — com o epoch morto o processo é encerrado e a resposta descartada. Responder
   a um turno que o dono interrompeu é o que o F1-11 proíbe.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from jarvis.voz.interface import Cancelado, nunca_cancelado

EXECUTAVEL: Final = "claude"
PRAZO_PADRAO_S: Final = 30.0
INTERVALO_DE_CONSULTA_S: Final = 0.05
"""De quanto em quanto tempo o cancelamento é consultado enquanto a CLI pensa. 50 ms é um
quadro e meio de áudio: granularidade suficiente para o dono não ouvir a resposta morta."""

PROMPT_DE_SISTEMA: Final = (
    "Você é o Jarvis, um assistente pessoal por voz, falando em português do Brasil. "
    "A sua resposta vai ser LIDA EM VOZ ALTA, então: escreva como se fala, em uma ou duas "
    "frases curtas, sem listas, sem markdown, sem emoji e sem código. "
    "Não invente fato que você não sabe; se não souber, diga que não sabe. "
    "Você não tem ferramentas, não lê arquivos e não executa nada — se pedirem isso, diga que "
    "ainda não consegue fazer e ofereça o que dá para responder com palavras."
)
"""Curto de propósito: prompt comprido custa tempo em todo turno e o dono vai julgar latência.
A instrução "vai ser lida em voz alta" é a que mais muda a resposta — sem ela, o modelo
devolve lista com marcador, e marcador no TTS vira "hífen, hífen, hífen"."""

FERRAMENTAS_PROIBIDAS: Final[tuple[str, ...]] = (
    "Bash",
    "Read",
    "Write",
    "Edit",
    "NotebookEdit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Task",
    "TodoWrite",
)


class RespostaIndisponivel(RuntimeError):
    """A CLI não está instalada, não respondeu no prazo ou falhou. A frase diz qual."""


@runtime_checkable
class GeradorDeResposta(Protocol):
    """Quem decide o que o Jarvis responde. Um método, para a F2 poder substituir."""

    nome: str

    def responder(self, texto: str) -> str: ...


@dataclass(slots=True)
class RespostaDeEco:
    """Repete o que ouviu. É o modo sem nuvem: testa áudio, não testa conversa.

    Existe para o dono poder exercitar microfone, barge-in e indicador **sem** falar com
    serviço nenhum — e para o teste do laço não depender de processo externo.
    """

    nome: str = "eco"
    prefixo: str = "Você disse: "

    def responder(self, texto: str) -> str:
        return f"{self.prefixo}{texto}" if texto.strip() else "Não entendi."


@dataclass(slots=True)
class RespostaPelaCli:
    """Chama a CLI `claude` em modo não interativo, sem ferramenta e fora do repositório."""

    pasta_de_trabalho: Path
    """Uma pasta **vazia**. É o que impede o processo de enxergar o projeto do dono."""
    executavel: str = EXECUTAVEL
    modelo: str = ""
    prompt_de_sistema: str = PROMPT_DE_SISTEMA
    prazo_s: float = PRAZO_PADRAO_S
    cancelado: Cancelado = nunca_cancelado
    ambiente: Mapping[str, str] | None = None

    nome: str = "claude-cli (provisório, ADR-0018)"
    respostas: int = 0
    canceladas: int = 0
    ultimo_ms: float = 0.0
    _erro: str = field(default="", repr=False)

    @property
    def argumentos(self) -> list[str]:
        """O `argv` completo — **sem** a fala do dono, que vai por `stdin`."""
        argumentos = [
            self.executavel,
            "--print",
            "--output-format",
            "text",
            "--system-prompt",
            self.prompt_de_sistema,
            "--permission-mode",
            "manual",
            "--disallowed-tools",
            " ".join(FERRAMENTAS_PROIBIDAS),
        ]
        if self.modelo:
            argumentos += ["--model", self.modelo]
        return argumentos

    def responder(self, texto: str) -> str:
        """A resposta, ou `RespostaIndisponivel` com o motivo em uma frase."""
        import time

        if self.cancelado():
            self.canceladas += 1
            return ""
        if not self.pasta_de_trabalho.is_dir():
            raise RespostaIndisponivel(
                f"{self.pasta_de_trabalho} não existe: o gerador roda numa pasta vazia, fora "
                "do repositório, para não enxergar arquivo do projeto (ADR-0018)"
            )
        comeco = time.monotonic()
        try:
            processo = subprocess.Popen(  # noqa: S603 — argv explícito, sem shell
                self.argumentos,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.pasta_de_trabalho,
                env=dict(self.ambiente) if self.ambiente is not None else None,
            )
        except FileNotFoundError:
            raise RespostaIndisponivel(
                f"{self.executavel} não está nesta máquina: o gerador de resposta do "
                "aplicativo de teste é a CLI do Claude (ADR-0018, provisório até a F2). "
                "Use `--s2 eco` para testar o áudio sem ele"
            ) from None

        saida, erro, cancelado = self._esperar(processo, texto)
        self.ultimo_ms = (time.monotonic() - comeco) * 1000.0
        if cancelado:
            self.canceladas += 1
            return ""
        if processo.returncode != 0:
            raise RespostaIndisponivel(
                f"{self.executavel} saiu com código {processo.returncode}: "
                f"{erro.strip()[:200] or 'sem mensagem'}"
            )
        self.respostas += 1
        return saida.strip()

    def _esperar(self, processo: subprocess.Popen[str], texto: str) -> tuple[str, str, bool]:
        """Espera a CLI, consultando o cancelamento e o prazo — os dois são nossos.

        A escrita de `stdin` e a leitura de `stdout` ficam numa linha de execução à parte
        porque `communicate` **bloqueia**: sem isso, o `Cancel` do dono só seria visto depois
        de a resposta inteira chegar, que é o oposto do contrato do F1-11.
        """
        import time

        resultado: dict[str, str] = {}

        def conversar() -> None:
            saida, erro = processo.communicate(input=texto)
            resultado["saida"] = saida
            resultado["erro"] = erro

        fio = threading.Thread(target=conversar, daemon=True)
        fio.start()
        limite = time.monotonic() + self.prazo_s
        while fio.is_alive():
            if self.cancelado():
                processo.kill()
                fio.join(timeout=1.0)
                return "", "", True
            if time.monotonic() > limite:
                processo.kill()
                fio.join(timeout=1.0)
                raise RespostaIndisponivel(
                    f"{self.executavel} passou de {self.prazo_s:.0f}s sem responder: o prazo é "
                    "nosso, e turno pendurado é defeito (regra 5 da §3.3)"
                )
            time.sleep(INTERVALO_DE_CONSULTA_S)
        fio.join(timeout=1.0)
        return resultado.get("saida", ""), resultado.get("erro", ""), False


def gerador_de(
    nome: str,
    *,
    pasta_de_trabalho: Path,
    modelo: str = "",
    cancelado: Cancelado = nunca_cancelado,
    executavel: str = EXECUTAVEL,
) -> GeradorDeResposta:
    """O gerador que a configuração pediu. Nome desconhecido é erro, não padrão silencioso."""
    if nome == "eco":
        return RespostaDeEco()
    if nome in {"claude", "claude-cli"}:
        return RespostaPelaCli(
            pasta_de_trabalho=pasta_de_trabalho,
            modelo=modelo,
            cancelado=cancelado,
            executavel=executavel,
        )
    validos = ", ".join(("eco", "claude"))
    raise ValueError(f"gerador de resposta {nome!r} não existe; use um de: {validos}")


def nomes_de_gerador() -> Sequence[str]:
    return ("eco", "claude")
