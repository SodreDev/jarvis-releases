"""O `claude -p` como motor de conversa em stream — **provisório e de teste** (ADR-0018, ADR-0025).

Decisão do diretor de 2026-10-16 (D18): o motor do cérebro sai da medição de um motor local e de
um de API; este adaptador existe para o dono ouvir o stream hoje e para o harness ter um motor
real a medir. Ele herda as cinco regras da ADR-0018 — sem ferramenta, a fala por `stdin`, saída
`untrusted`, prazo nosso, cancelável — e acrescenta as da ADR-0025:

- **Avulso, sem estado.** Um processo por pedido, com `--no-session-persistence`, recebendo a
  conversa montada pelo cérebro. O modo contínuo da CLI é ~400 ms mais rápido, mas a sessão
  dela guarda o texto **gerado** até o corte, e não o tocado (medido): viola o P4.
- **Stream.** `--output-format stream-json --include-partial-messages`: cada `text_delta` vira
  um `Texto`. `thinking_delta` é **descartado** aqui — raciocínio não vai para o TTS (P10).
- **Parar de gerar, não só de ler.** No cancelamento o processo é **morto** e esperado; o
  `finally` faz o mesmo quando quem consome desiste do iterador. Se o servidor da Anthropic para
  de gerar e de cobrar no instante em que a conexão cai **não foi verificado** (a CLI não diz).
"""

from __future__ import annotations

import contextlib
import json
import queue
import subprocess
import threading
import time
from collections.abc import Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.s2.motor import (
    INTERVALO_DE_CONSULTA_S,
    Contexto,
    Delta,
    Fim,
    Modo,
    MotivoDoFim,
    PedidoDeTool,
    Texto,
)
from jarvis.voz.interface import Cancelado, Onde
from jarvis.voz.s2_provisorio import FERRAMENTAS_PROIBIDAS, PROMPT_DE_SISTEMA

COMANDO_PADRAO: Final = ("claude",)
PRAZO_PADRAO_S: Final = 30.0
ESFORCO_POR_MODO: Final[Mapping[Modo, str]] = {Modo.RAPIDO: "low", Modo.PENSAR: "high"}
"""Medido: o esforço pesa mais que o tamanho do modelo no tempo até a primeira fronteira
(`sonnet` com `low` ficou perto do `haiku`; o padrão passou de 2 s)."""
ESPERA_DO_PROCESSO_MORTO_S: Final = 1.0
CORTESIA_DEPOIS_DO_FIM_S: Final = 0.5
"""Depois do evento `result` a CLI ainda está saindo sozinha: espera-se um pouco antes de matar.
No cancelamento e no prazo não há cortesia — ali o processo morre na hora."""

_FIM_DA_LEITURA: Final = object()

MARCA_DE_FERRAMENTA: Final = "<<ferramenta>>"
"""O protocolo de texto do provisório (ADR-0028): a CLI roda **sem** ferramenta nenhuma (ADR-0018),
então a proposta de chamada chega como uma linha que começa com esta marca e traz um JSON."""

INSTRUCAO_DE_FERRAMENTAS: Final = (
    "Você pode PROPOR ferramentas; quem decide se roda é o código do Jarvis, e coisas como "
    "gravar ou abrir site podem pedir a confirmação do dono. Para propor, responda com uma "
    "linha que começa exatamente com " + MARCA_DE_FERRAMENTA + " seguida de um JSON "
    '{"tool_id": "...", "args": {...}} — uma linha por chamada, sem markdown, sem explicar o '
    'JSON. Pode dizer uma frase curta antes ("deixa eu ver"). Depois você recebe os '
    "resultados e responde ao dono, em voz, curto. Use só as ferramentas da lista, só com os "
    "argumentos dela, e nunca invente resultado. Caminhos: sempre a pasta inteira (~/Documentos/"
    "...). Ferramentas disponíveis agora:"
)


def sistema_com_ferramentas(sistema: str, ferramentas: Sequence[Mapping[str, object]]) -> str:
    """O prompt de sistema com o catálogo fixo do modo (C0). Sem ferramentas, fica como estava."""
    if not ferramentas:
        return sistema
    linhas = [sistema.replace("Você não tem ferramentas, não lê arquivos e não executa nada", "")]
    linhas.append(INSTRUCAO_DE_FERRAMENTAS)
    for ferramenta in ferramentas:
        argumentos = json.dumps(ferramenta.get("argumentos", {}), ensure_ascii=False)
        pedidos = ferramenta.get("obrigatorios")
        obrigatorios = ", ".join(str(o) for o in pedidos) if isinstance(pedidos, list) else ""
        linhas.append(
            f"- {ferramenta['id']}: {ferramenta['descricao']} Argumentos: {argumentos}. "
            f"Obrigatórios: {obrigatorios or 'nenhum'}."
        )
    return "\n".join(linhas)


@dataclass(slots=True)
class LeitorDoProtocolo:
    """Separa, ainda no stream, o texto falado das linhas de proposta de ferramenta.

    Cada linha é segurada só enquanto ainda **pode** ser uma proposta (é prefixo da marca); assim
    que diverge, sai como texto — a fala não espera o fim da resposta. Linha de proposta com JSON
    inválido vira um pedido malformado, que o executor recusa e o motor fica sabendo."""

    _linha: str = ""
    _decidida: bool = False

    def alimentar(self, texto: str) -> Iterator[Delta]:
        while texto:
            fim, quebra, resto = texto.partition("\n")
            if self._decidida:
                if fim:
                    yield Texto(fim)
            else:
                self._linha += fim
                inicio = self._linha.lstrip()
                if inicio and not (
                    MARCA_DE_FERRAMENTA.startswith(inicio) or inicio.startswith(MARCA_DE_FERRAMENTA)
                ):
                    self._decidida = True
                    yield Texto(self._linha)
                    self._linha = ""
            if not quebra:
                return
            if self._decidida:
                yield Texto("\n")
                self._decidida = False
            else:
                yield from self._fim_de_linha()
            texto = resto

    def fechar(self) -> Iterator[Delta]:
        yield from self._fim_de_linha()

    def _fim_de_linha(self) -> Iterator[Delta]:
        linha, self._linha = self._linha.strip(), ""
        if not linha:
            return
        if not linha.startswith(MARCA_DE_FERRAMENTA):
            yield Texto(linha)
            return
        bruto = linha[len(MARCA_DE_FERRAMENTA) :].strip()
        try:
            pedido = json.loads(bruto)
            tool_id, args = str(pedido["tool_id"]), pedido.get("args", {})
            if not isinstance(args, dict):
                raise TypeError("args não é objeto")
        except (ValueError, KeyError, TypeError):
            yield PedidoDeTool("(malformado)", {"bruto": bruto[:200]})
            return
        yield PedidoDeTool(tool_id, args)


@dataclass(slots=True)
class MotorClaudeCli:
    """Um processo `claude -p` por pedido, em stream, morto no cancelamento."""

    pasta_de_trabalho: Path
    """Uma pasta **vazia**: o processo não enxerga o projeto do dono (ADR-0018, regra 1)."""
    comando: Sequence[str] = COMANDO_PADRAO
    modelo: str = ""
    sistema: str = PROMPT_DE_SISTEMA
    prazo_s: float = PRAZO_PADRAO_S
    ambiente: Mapping[str, str] | None = None
    nome: str = "claude-cli em stream (provisório, ADR-0018/0025)"
    onde: Onde = Onde.NUVEM
    ultimo_pid: int | None = None
    ultimo_codigo: int | None = None
    pensamento_descartado: int = field(default=0)
    """Deltas de raciocínio que chegaram e não viraram fala — contados, não guardados."""

    def argumentos(self, modo: Modo, ferramentas: Sequence[Mapping[str, object]] = ()) -> list[str]:
        """O `argv` completo — **sem** a fala do dono, que vai por `stdin`."""
        argumentos = [
            *self.comando,
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--system-prompt",
            sistema_com_ferramentas(self.sistema, ferramentas),
            "--tools",
            "",
            "--disallowed-tools",
            " ".join(FERRAMENTAS_PROIBIDAS),
            "--permission-mode",
            "manual",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--effort",
            ESFORCO_POR_MODO[modo],
        ]
        if self.modelo:
            argumentos += ["--model", self.modelo]
        return argumentos

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        if cancelado():
            yield Fim(MotivoDoFim.CANCELADO)
            return
        if not self.pasta_de_trabalho.is_dir():
            yield Fim(
                MotivoDoFim.ERRO,
                f"{self.pasta_de_trabalho} não existe: o motor roda numa pasta vazia, fora do "
                "repositório (ADR-0018, regra 1)",
            )
            return
        try:
            processo = subprocess.Popen(  # noqa: S603 — argv explícito, sem shell
                self.argumentos(modo, contexto.ferramentas),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=self.pasta_de_trabalho,
                env=dict(self.ambiente) if self.ambiente is not None else None,
            )
        except FileNotFoundError:
            yield Fim(MotivoDoFim.ERRO, f"{self.comando[0]} não está nesta máquina")
            return
        self.ultimo_pid = processo.pid
        concluido = False
        try:
            for delta in self._ler(processo, contexto, cancelado):
                concluido = isinstance(delta, Fim) and delta.motivo is MotivoDoFim.CONCLUIDO
                yield delta
        finally:
            self._encerrar(processo, cortesia_s=CORTESIA_DEPOIS_DO_FIM_S if concluido else 0.0)

    def _ler(
        self, processo: subprocess.Popen[str], contexto: Contexto, cancelado: Cancelado
    ) -> Iterator[Delta]:
        linhas: queue.Queue[object] = queue.Queue()
        erro: list[str] = []
        leitor = threading.Thread(
            target=_escrever_e_ler,
            args=(processo, contexto.como_texto(), linhas, erro),
            daemon=True,
        )
        leitor.start()
        threading.Thread(target=_ler_erro, args=(processo, erro), daemon=True).start()
        limite = time.monotonic() + self.prazo_s
        protocolo = LeitorDoProtocolo()
        while True:
            if cancelado():
                yield Fim(MotivoDoFim.CANCELADO)
                return
            if time.monotonic() > limite:
                yield Fim(MotivoDoFim.PRAZO, f"passou de {self.prazo_s:.0f}s: o prazo é nosso")
                return
            try:
                linha = linhas.get(timeout=INTERVALO_DE_CONSULTA_S)
            except queue.Empty:
                continue
            if linha is _FIM_DA_LEITURA:
                processo.wait(timeout=ESPERA_DO_PROCESSO_MORTO_S)
                detalhe = "".join(erro).strip()[:200] or "saiu sem o evento de fim"
                yield Fim(MotivoDoFim.ERRO, f"código {processo.returncode}: {detalhe}")
                return
            delta = self._traduzir(str(linha))
            if delta is None:
                continue
            if cancelado():
                # Chegou junto com o cancelamento: não é entregue.
                yield Fim(MotivoDoFim.CANCELADO)
                return
            if isinstance(delta, Texto):
                yield from protocolo.alimentar(delta.texto)
                continue
            if isinstance(delta, Fim):
                yield from protocolo.fechar()
            yield delta
            if isinstance(delta, Fim):
                return

    def _traduzir(self, linha: str) -> Delta | None:
        """Uma linha do stream-json da CLI → um delta, ou nada."""
        try:
            evento = json.loads(linha)
        except json.JSONDecodeError:
            return None
        if not isinstance(evento, dict):
            return None
        tipo = evento.get("type")
        if tipo == "stream_event":
            interno = evento.get("event") or {}
            if interno.get("type") != "content_block_delta":
                return None
            delta = interno.get("delta") or {}
            if delta.get("type") == "text_delta":
                return Texto(str(delta.get("text", "")))
            if delta.get("type") == "thinking_delta":
                self.pensamento_descartado += 1
            return None
        if tipo == "result":
            uso = evento.get("usage") or {}
            tokens = {
                chave: int(valor)
                for chave, valor in uso.items()
                if chave.endswith("tokens") and isinstance(valor, int)
            }
            if evento.get("is_error"):
                return Fim(MotivoDoFim.ERRO, str(evento.get("result", ""))[:200], tokens)
            return Fim(MotivoDoFim.CONCLUIDO, uso=tokens)
        return None

    def _encerrar(self, processo: subprocess.Popen[str], *, cortesia_s: float) -> None:
        """Mata e espera. Processo que fica vivo continua gerando para ninguém."""
        if cortesia_s > 0:
            with contextlib.suppress(subprocess.TimeoutExpired):
                processo.wait(timeout=cortesia_s)
        if processo.poll() is None:
            processo.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            processo.wait(timeout=ESPERA_DO_PROCESSO_MORTO_S)
        self.ultimo_codigo = processo.returncode
        for fluxo in (processo.stdin, processo.stdout, processo.stderr):
            if fluxo is not None:
                with contextlib.suppress(OSError):
                    fluxo.close()


def _escrever_e_ler(
    processo: subprocess.Popen[str], texto: str, linhas: queue.Queue[object], erro: list[str]
) -> None:
    """Fio à parte: escrever no `stdin` e ler o `stdout` bloqueiam, e o cancelamento não pode
    esperar por eles (é o mesmo motivo do `_esperar` da ADR-0018)."""
    assert processo.stdin is not None and processo.stdout is not None
    try:
        processo.stdin.write(texto)
        processo.stdin.close()
        for linha in processo.stdout:
            linhas.put(linha)
    except (OSError, ValueError):
        pass  # processo morto no meio: o cancelamento já foi tratado do outro lado
    finally:
        linhas.put(_FIM_DA_LEITURA)


def _ler_erro(processo: subprocess.Popen[str], erro: list[str]) -> None:
    """O `stderr` em fio próprio: lido só no fim, um `stderr` cheio travaria o processo."""
    if processo.stderr is None:
        return
    try:
        for linha in processo.stderr:
            erro.append(linha)
    except (OSError, ValueError):
        pass
