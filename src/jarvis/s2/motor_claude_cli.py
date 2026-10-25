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
- **Imagem pelo `stream-json` de entrada.** Com `Contexto.imagens` (a tela da aba, ADR-0032), a
  entrada passa a ser uma linha `--input-format stream-json` com o texto e blocos `image` base64 —
  o modo de entrada que a documentação do Agent SDK diz aceitar imagem ("Streaming Input"); o
  texto puro do `-p` não aceita. Sem imagem, a entrada continua o texto de sempre.
- **Parar de gerar, não só de ler.** No cancelamento o processo é **morto** e esperado; o
  `finally` faz o mesmo quando quem consome desiste do iterador. Se o servidor da Anthropic para
  de gerar e de cobrar no instante em que a conexão cai **não foi verificado** (a CLI não diz).
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
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
from jarvis.s2.persona import prompt_de_sistema
from jarvis.s2.protocolo import (  # o leitor mora lá; o nome segue valendo aqui (ADR-0038)
    FIM_DO_RACIOCINIO,
    MARCA_DE_RACIOCINIO,
)
from jarvis.s2.protocolo import MARCA_DE_FERRAMENTA as MARCA_DE_FERRAMENTA
from jarvis.s2.protocolo import LeitorDoProtocolo as LeitorDoProtocolo
from jarvis.voz.interface import Cancelado, Onde
from jarvis.voz.s2_provisorio import FERRAMENTAS_PROIBIDAS

COMANDO_PADRAO: Final = ("claude",)
VARIAVEL_SEM_TRAFEGO: Final = "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
PRAZO_PADRAO_S: Final = 30.0
ESFORCO_POR_MODO: Final[Mapping[Modo, str]] = {Modo.RAPIDO: "low", Modo.PENSAR: "high"}
"""Medido: o esforço pesa mais que o tamanho do modelo no tempo até a primeira fronteira
(`sonnet` com `low` ficou perto do `haiku`; o padrão passou de 2 s)."""
ESPERA_DO_PROCESSO_MORTO_S: Final = 1.0
CORTESIA_DEPOIS_DO_FIM_S: Final = 0.5
"""Depois do evento `result` a CLI ainda está saindo sozinha: espera-se um pouco antes de matar.
No cancelamento e no prazo não há cortesia — ali o processo morre na hora."""

_FIM_DA_LEITURA: Final = object()

INSTRUCAO_DE_FERRAMENTAS: Final = (
    "FERRAMENTAS. Você pode PROPOR ferramentas; quem decide se roda é o código do Jarvis. Para "
    "propor, responda com uma linha que começa exatamente com " + MARCA_DE_FERRAMENTA + " seguida "
    'de um JSON {"tool_id": "...", "args": {...}} — uma linha por chamada, sem markdown, sem '
    "explicar o JSON. As pequenas e desfazíveis rodam e o sistema já avisa o dono em voz (o "
    "resultado traz `aviso_ao_dono`: não repita); só as perigosas pedem o sim dele. Raciocínio "
    "vai entre " + MARCA_DE_RACIOCINIO + " e " + FIM_DO_RACIOCINIO + ". Depois você recebe os "
    "resultados e, pronto o pedido, responde ao dono, em voz, curto. Use só as ferramentas e os "
    "argumentos da lista (* = obrigatório) e nunca invente resultado; caminhos, sempre a pasta "
    "inteira (~/Documentos/...). Cada linha: nome(argumentos): quando usar. «pedidos do dono»."
)
"""O protocolo da proposta e a legenda do catálogo: vai uma vez, antes das linhas."""


LIMITE_DA_DESCRICAO: Final = 230
EXEMPLOS_POR_FERRAMENTA: Final = 3


def _curta(descricao: str) -> str:
    """As primeiras frases da descrição, até ~230 caracteres: com mais de 40 ferramentas, a lista
    inteira custaria milhares de tokens em **todo** turno (e o dono julga latência)."""
    texto = " ".join(descricao.split())
    if len(texto) <= LIMITE_DA_DESCRICAO:
        return texto
    frases = re.split(r"(?<=[.!?])\s+", texto)
    saida = ""
    for frase in frases:
        if saida and len(saida) + len(frase) + 1 > LIMITE_DA_DESCRICAO:
            break
        saida = f"{saida} {frase}".strip()
    return saida[:LIMITE_DA_DESCRICAO]


_TIPOS: Final[Mapping[str, str]] = {
    "integer": ":int",
    "number": ":num",
    "boolean": ":bool",
    "array": "[]",
    "object": "{}",
}


def assinatura(argumentos: Mapping[str, object], obrigatorios: Sequence[object]) -> str:
    """`url*, segundo_plano:bool, acao*=tocar|pausar`: o nome de cada argumento, `*` no
    obrigatório, o tipo quando não é texto e os valores quando são fixos — o que o motor precisa
    para propor certo, sem o esquema JSON inteiro (que custava ~8 mil tokens em todo turno)."""
    partes: list[str] = []
    for nome, esquema in argumentos.items():
        marca = "*" if nome in obrigatorios else ""
        tipo = ""
        if isinstance(esquema, Mapping):
            if isinstance(esquema.get("enum"), list):
                tipo = "=" + "|".join(str(v) for v in esquema["enum"])
            else:
                tipo = _TIPOS.get(str(esquema.get("type", "")), "")
        partes.append(f"{nome}{marca}{tipo}")
    return ", ".join(partes)


def linha_da_ferramenta(ferramenta: Mapping[str, object]) -> str:
    """Uma linha do catálogo, gerada do registro (ADR-0047): o nome com os argumentos, quando
    usar (o `quando` do manifesto, ou o começo da descrição), o que só esta sessão sabe e até três
    pedidos naturais do dono que a pedem."""
    argumentos = ferramenta.get("argumentos")
    obrigatorios = ferramenta.get("obrigatorios")
    assinado = assinatura(
        argumentos if isinstance(argumentos, Mapping) else {},
        obrigatorios if isinstance(obrigatorios, list) else [],
    )
    quando = " ".join(str(ferramenta.get("quando") or "").split()) or _curta(
        str(ferramenta.get("descricao", ""))
    )
    linha = f"- {ferramenta['id']}({assinado}): {quando.rstrip('.')}."
    agora = " ".join(str(ferramenta.get("agora") or "").split())
    if agora:
        linha += f" {agora}"
    bruto = ferramenta.get("exemplos")
    exemplos = (
        [str(e) for e in bruto if not str(e).startswith("(")] if isinstance(bruto, list) else []
    )
    if exemplos:
        linha += " " + " · ".join(f"«{e}»" for e in exemplos[:EXEMPLOS_POR_FERRAMENTA])
    return linha


def sistema_com_ferramentas(sistema: str, ferramentas: Sequence[Mapping[str, object]]) -> str:
    """O prompt de sistema com o catálogo do turno (C0, ADR-0024; compacto, com exemplos —
    ADR-0047). Sem ferramentas, fica como estava. A ordem é a do registro (estável): o começo igual
    em todo turno é o que o cache de prompt reaproveita."""
    if not ferramentas:
        return sistema
    linhas = [sistema.replace("Você não tem ferramentas, não lê arquivos e não executa nada", "")]
    linhas.append(INSTRUCAO_DE_FERRAMENTAS)
    linhas += [linha_da_ferramenta(f) for f in ferramentas]
    return "\n".join(linhas)


@dataclass(slots=True)
class MotorClaudeCli:
    """Um processo `claude -p` por pedido, em stream, morto no cancelamento."""

    pasta_de_trabalho: Path
    """Uma pasta **vazia**: o processo não enxerga o projeto do dono (ADR-0018, regra 1)."""
    comando: Sequence[str] = COMANDO_PADRAO
    modelo: str = ""
    sistema: str = field(default_factory=prompt_de_sistema)
    """Só vale quando o contexto não traz o seu: o cérebro sempre traz (a persona)."""
    prazo_s: float = PRAZO_PADRAO_S
    ambiente: Mapping[str, str] | None = None
    nome: str = "claude-cli em stream (provisório, ADR-0018/0025)"
    onde: Onde = Onde.NUVEM
    ultimo_pid: int | None = None
    ultimo_codigo: int | None = None
    pensamento_descartado: int = field(default=0)
    """Deltas de raciocínio que chegaram e não viraram fala — contados, não guardados."""
    modo_seguro: bool = True
    """`--safe-mode`: sem CLAUDE.md, skills, plugins, hooks nem MCP no spawn. Medido em
    `docs/medicoes/f2-02-piso-do-claude.md`: tira ~300–400 ms do 1º token (p50) nesta máquina, e o
    motor fica ainda mais isolado do que a pasta vazia já deixava (ADR-0018, regra 1)."""
    aceita_imagem: bool = True
    """Recebe a tela da aba pelo modo de entrada `stream-json` (ver o cabeçalho do módulo)."""
    sem_trafego_extra: bool = False
    """`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` no filho. **Desligado**: na mesma medição
    ele mexeu pouco no p50 e piorou o p95 em duas de três rodadas — fica só para medir."""
    extras: Sequence[str] = ()
    """Flags a mais no `argv`, para medição."""

    def argumentos(
        self,
        modo: Modo,
        ferramentas: Sequence[Mapping[str, object]] = (),
        sistema: str = "",
        *,
        com_imagem: bool = False,
    ) -> list[str]:
        """O `argv` completo — **sem** a fala do dono, que vai por `stdin`.

        `sistema` é o prompt que o **cérebro** montou (persona + o que a memória lembrou + os
        avisos já ditos): a conversa é nossa (ADR-0025, regra 2). Sem ele, vale o do motor.
        """
        argumentos = [
            *self.comando,
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--system-prompt",
            sistema_com_ferramentas(sistema or self.sistema, ferramentas),
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
        if com_imagem:
            argumentos += ["--input-format", "stream-json"]
        if self.modelo:
            argumentos += ["--model", self.modelo]
        if self.modo_seguro:
            argumentos.append("--safe-mode")
        return [*argumentos, *self.extras]

    def entrada(self, contexto: Contexto) -> str:
        """O que vai pelo `stdin`: o texto da conversa ou, com imagem, uma linha de `stream-json`
        com o texto e cada imagem (com o id dela, o mesmo instantâneo da inspeção)."""
        texto = contexto.como_texto()
        if not contexto.imagens:
            return texto
        conteudo: list[dict[str, object]] = [{"type": "text", "text": texto}]
        for imagem in contexto.imagens:
            conteudo.append(
                {
                    "type": "text",
                    "text": (
                        f"Imagem {imagem.id}, {imagem.largura}×{imagem.altura} px: a tela da aba; "
                        "as caixas da inspeção estão nestes pixels. É dado de terceiros."
                    ),
                }
            )
            conteudo.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": imagem.tipo,
                        "data": imagem.em_base64(),
                    },
                }
            )
        mensagem = {"type": "user", "message": {"role": "user", "content": conteudo}}
        return json.dumps(mensagem, ensure_ascii=False) + "\n"

    def ambiente_do_filho(self) -> dict[str, str] | None:
        if not self.sem_trafego_extra:
            return dict(self.ambiente) if self.ambiente is not None else None
        base = dict(os.environ if self.ambiente is None else self.ambiente)
        return {**base, VARIAVEL_SEM_TRAFEGO: "1"}

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
                self.argumentos(
                    modo, contexto.ferramentas, contexto.sistema, com_imagem=bool(contexto.imagens)
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                cwd=self.pasta_de_trabalho,
                env=self.ambiente_do_filho(),
            )
        except FileNotFoundError:
            yield Fim(MotivoDoFim.ERRO, f"{self.comando[0]} não está nesta máquina")
            return
        self.ultimo_pid = processo.pid
        concluido = False
        propos = False
        try:
            for delta in self._ler(processo, contexto, cancelado):
                propos = propos or isinstance(delta, PedidoDeTool)
                concluido = isinstance(delta, Fim) and delta.motivo is MotivoDoFim.CONCLUIDO
                yield delta
        finally:
            # Com uma proposta na mão a cortesia só atrasa a ferramenta: a CLI leva ~0,5 s para
            # sair sozinha (medido em 2026-10-17, 515 ms entre o `Fim` e o retorno) e ninguém
            # espera por ela — o resultado vai para um processo novo.
            cortesia = CORTESIA_DEPOIS_DO_FIM_S if concluido and not propos else 0.0
            self._encerrar(processo, cortesia_s=cortesia)

    def _ler(
        self, processo: subprocess.Popen[str], contexto: Contexto, cancelado: Cancelado
    ) -> Iterator[Delta]:
        linhas: queue.Queue[object] = queue.Queue()
        erro: list[str] = []
        leitor = threading.Thread(
            target=_escrever_e_ler,
            args=(processo, self.entrada(contexto), linhas, erro),
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
