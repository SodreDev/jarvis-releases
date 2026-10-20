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
    Raciocinio,
    Texto,
)
from jarvis.s2.persona import prompt_de_sistema
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

MARCA_DE_FERRAMENTA: Final = "<<ferramenta>>"
"""O protocolo de texto do provisório (ADR-0028): a CLI roda **sem** ferramenta nenhuma (ADR-0018),
então a proposta de chamada chega como uma linha que começa com esta marca e traz um JSON."""
MARCA_DE_RACIOCINIO: Final = "<<pensar>>"
FIM_DO_RACIOCINIO: Final = "<</pensar>>"
"""O canal de raciocínio do protocolo (ADR-0031): o que vem entre as duas marcas é do modelo para
ele mesmo, e sai do leitor como `Raciocinio`. Sem a marca que fecha, vale até a próxima proposta
ou o fim da geração — na dúvida, o texto não vai para a fala."""

INSTRUCAO_DE_FERRAMENTAS: Final = (
    "Você pode PROPOR ferramentas; quem decide se roda é o código do Jarvis. As simples rodam na "
    "hora; as pequenas e desfazíveis rodam e o Jarvis já avisa o dono em voz (o resultado traz "
    "`aviso_ao_dono`: não repita); só as perigosas pedem a confirmação do dono na tela. Para "
    "propor, responda com uma "
    "linha que começa exatamente com " + MARCA_DE_FERRAMENTA + " seguida de um JSON "
    '{"tool_id": "...", "args": {...}} — uma linha por chamada, sem markdown, sem explicar o '
    'JSON. Antes da primeira ferramenta do pedido você pode dizer uma frase curta ("vou ver"), '
    "uma vez só; entre um passo e outro, nada em voz. O que for raciocínio (plano, o que "
    "conferir, o próximo passo) vai entre " + MARCA_DE_RACIOCINIO + " e " + FIM_DO_RACIOCINIO + ": "
    "o dono não ouve nem vê, e ele volta para você no passo seguinte. Depois você recebe os "
    "resultados e, quando o pedido estiver pronto, responde ao dono, em voz, curto. Use só as "
    "ferramentas da lista, só com os argumentos dela, e nunca invente resultado. Caminhos: "
    "sempre a pasta inteira (~/Documentos/...). Ferramentas disponíveis agora:"
)


LIMITE_DA_DESCRICAO: Final = 230


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
            f"- {ferramenta['id']}: {_curta(str(ferramenta['descricao']))} "
            f"Argumentos: {argumentos}. "
            f"Obrigatórios: {obrigatorios or 'nenhum'}."
        )
    return "\n".join(linhas)


_MARCA_RE: Final = re.compile(r"<<\s*ferramenta\s*>>", re.IGNORECASE)
_PENSAR_RE: Final = re.compile(r"<<\s*pensar\s*>>", re.IGNORECASE)
_FIM_DO_PENSAR_RE: Final = re.compile(r"<<\s*/\s*pensar\s*>>", re.IGNORECASE)
_CERCA_NO_FIM: Final = re.compile(r"```(?:json)?\s*$", re.IGNORECASE)
_CERCA_NO_COMECO: Final = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
LIMITE_DA_PROPOSTA: Final = 4000
"""Caracteres que uma proposta pode ocupar antes de virar malformada: JSON que nunca fecha não
pode segurar a fala do resto da resposta para sempre."""


def _malformado(bruto: str) -> PedidoDeTool:
    return PedidoDeTool("(malformado)", {"bruto": bruto.strip()[:200]})


def _pedido_de(objeto: object, bruto: str) -> PedidoDeTool:
    """O JSON já lido → pedido. Aceita os apelidos que o modelo usa por conta própria
    (`tool`/`name`, `arguments`): recusar por nome de chave é falha que o dono sente como erro."""
    if not isinstance(objeto, dict):
        return _malformado(bruto)
    ferramenta = next(
        (objeto[k] for k in ("tool_id", "tool", "id", "name") if isinstance(objeto.get(k), str)),
        None,
    )
    argumentos: object = next(
        (objeto[k] for k in ("args", "arguments", "argumentos") if k in objeto), {}
    )
    if ferramenta is None or not isinstance(argumentos, dict):
        return _malformado(bruto)
    return PedidoDeTool(ferramenta, argumentos)


@dataclass(slots=True)
class LeitorDoProtocolo:
    """Separa, ainda no stream, o texto falado das propostas de ferramenta.

    A marca vale **em qualquer ponto** do texto (não só no começo da linha): o modelo escreve
    "Vou abrir. <<ferramenta>> {...}" e o JSON não pode ir para a fala. O texto sai assim que
    se sabe que não é o começo de uma marca (só um `<` no fim fica retido). Depois da marca, o
    JSON é lido por **balanceamento** — vale em várias linhas, com cerca ``` em volta, com texto
    depois — e a proposta sai no instante em que o objeto fecha, sem esperar a quebra de linha
    nem o fim da geração. JSON que não fecha, ou sem objeto, vira um pedido malformado, que o
    executor recusa e o motor fica sabendo.

    O bloco `<<pensar>>` … `<</pensar>>` (ADR-0031) sai como `Raciocinio`, também no meio do
    texto e partido entre deltas. Uma proposta dentro de um raciocínio aberto fecha o raciocínio
    (o modelo esqueceu a marca de fim), e o que sobra aberto no fim da geração é raciocínio."""

    _texto: str = ""
    _proposta: str | None = None
    _raciocinio: str | None = None

    def alimentar(self, texto: str) -> Iterator[Delta]:
        while True:
            if self._proposta is not None:
                self._proposta += texto
                texto = ""
                lido = self._ler_proposta(final=False)
                if lido is None:
                    return
                pedido, resto = lido
                yield pedido
                self._proposta = None
                texto = resto
                if not texto:
                    return
                continue
            if self._raciocinio is not None:
                self._raciocinio += texto
                texto = ""
                fim = _FIM_DO_PENSAR_RE.search(self._raciocinio)
                proposta = _MARCA_RE.search(self._raciocinio)
                if fim is None and proposta is None:
                    retido = _retencao(self._raciocinio, (FIM_DO_RACIOCINIO, MARCA_DE_FERRAMENTA))
                    saida = self._raciocinio[: len(self._raciocinio) - retido]
                    self._raciocinio = self._raciocinio[len(self._raciocinio) - retido :]
                    if saida:
                        yield Raciocinio(saida)
                    return
                if fim is not None and (proposta is None or fim.start() < proposta.start()):
                    antes, texto = self._raciocinio[: fim.start()], self._raciocinio[fim.end() :]
                else:
                    assert proposta is not None
                    # A marca da proposta fica no texto: é o ramo do texto comum que a lê.
                    antes = self._raciocinio[: proposta.start()]
                    texto = self._raciocinio[proposta.start() :]
                self._raciocinio = None
                if antes:
                    yield Raciocinio(antes)
                if not texto:
                    return
                continue
            self._texto += texto
            texto = ""
            achada = _MARCA_RE.search(self._texto)
            pensar = _PENSAR_RE.search(self._texto)
            if pensar is not None and (achada is None or pensar.start() < achada.start()):
                antes, texto = self._texto[: pensar.start()], self._texto[pensar.end() :]
                self._texto = ""
                self._raciocinio = ""
                if antes.strip():
                    yield Texto(antes)
                if not texto:
                    return
                continue
            if achada is None:
                retido = _retencao(self._texto, (MARCA_DE_FERRAMENTA, MARCA_DE_RACIOCINIO))
                saida = self._texto[: len(self._texto) - retido]
                self._texto = self._texto[len(self._texto) - retido :]
                if saida:
                    yield Texto(saida)
                return
            antes = _CERCA_NO_FIM.sub("", self._texto[: achada.start()])
            self._proposta = self._texto[achada.end() :]
            self._texto = ""
            if antes.strip():
                yield Texto(antes)
            lido = self._ler_proposta(final=False)
            if lido is None:
                return
            pedido, resto = lido
            yield pedido
            self._proposta = None
            texto = resto
            if not texto:
                return

    def fechar(self) -> Iterator[Delta]:
        if self._proposta is not None:
            lido = self._ler_proposta(final=True)
            self._proposta = None
            if lido is not None:
                yield lido[0]
        if self._raciocinio is not None:
            # Sem a marca que fecha: na dúvida, não é fala.
            resto, self._raciocinio = self._raciocinio, None
            if resto:
                yield Raciocinio(resto)
        if self._texto:
            texto, self._texto = self._texto, ""
            yield Texto(texto)

    def _ler_proposta(self, *, final: bool) -> tuple[PedidoDeTool, str] | None:
        """O pedido e o que sobrou depois dele; `None` enquanto o JSON ainda pode fechar."""
        assert self._proposta is not None
        corpo = _CERCA_NO_COMECO.sub("", self._proposta).lstrip()
        if not corpo.startswith("{"):
            linha, quebra, resto = corpo.partition("\n")
            if not quebra and not final:
                return None
            return _malformado(linha), resto
        try:
            objeto, fim = json.JSONDecoder().raw_decode(corpo)
        except ValueError:
            if final or len(corpo) > LIMITE_DA_PROPOSTA:
                return _malformado(corpo), ""
            return None
        resto = corpo[fim:]
        if resto.lstrip().startswith("```"):  # a cerca que fecha o bloco não é fala
            resto = resto.lstrip()[3:]
        return _pedido_de(objeto, corpo[:fim]), resto


def _retencao(texto: str, marcas: Sequence[str]) -> int:
    """Quantos caracteres do fim ainda podem ser o começo de uma das marcas (e por isso esperam)."""
    for tamanho in range(min(len(texto), max(len(m) for m in marcas) + 2), 0, -1):
        cauda = texto[-tamanho:]
        compacta = cauda.lower().replace(" ", "")
        if cauda[0] == "<" and any(marca.startswith(compacta) for marca in marcas):
            return tamanho
    return 0


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
