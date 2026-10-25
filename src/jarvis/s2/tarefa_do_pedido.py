"""O pedido do dono que precisa de ferramenta, cumprido numa tarefa (ADR-0038; dono, 2026-10-21).

O dono ouvia o Jarvis ler a chamada da ferramenta em voz alta, esperava calado enquanto o laço
inteiro rodava dentro do turno e, em "abre um vídeo no YouTube", via o trabalho parar depois da
primeira tentativa. O desenho agora: o pedido vira **objetivo**, o cérebro diz uma frase curta e
o turno acaba; quem segue é uma **tarefa** do `GestorDeTarefas`, conduzida por este motor — o
**mesmo** motor da conversa, com o mesmo contexto (persona, método, memória, a fala do dono) —,
uma rodada por passo, até o objetivo estar cumprido e conferido, precisar do dono, falhar ou ser
cancelado. O fim é a resposta àquele pedido, e chega ao dono pela fila de avisos.

O que vale aqui, por cima do modelo:

- **pensar não é falar** (ADR-0031): o texto antes de uma proposta é narração, o depois é palpite,
  e o `Raciocinio` fica com a tarefa (com teto) — nada disso vira fala;
- **conferir antes de dizer** (critério do objetivo, C2): no navegador e na entrada virtual,
  efeito sem leitura depois não é "pronto"; o motor é cobrado uma vez e, se ainda assim não
  conferir, a resposta diz que não conferiu;
- **nunca fingir sucesso**: sem nenhum passo que tenha dado certo, a resposta é do **código**, com
  o motivo do último erro em frase de gente;
- **a resposta é fala, não protocolo**: passa pelo leitor do protocolo e perde a frase que cita
  uma ferramenta pelo id ou traz argumento em JSON.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from jarvis.imagem import Imagem
from jarvis.s2.motor import (
    Contexto,
    Fim,
    Mensagem,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    PedidoDeTool,
    Raciocinio,
    Texto,
    aceita_imagem,
)
from jarvis.s2.protocolo import LeitorDoProtocolo, sem_protocolo
from jarvis.s2.rascunho import textos_no_contexto
from jarvis.tarefas.gestor import FORA_DA_ALLOWLIST, ErroDeTarefa, FimDaTarefa, Passo, Tarefa
from jarvis.voz.interface import Onde

if TYPE_CHECKING:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta

LIMITE_DO_RACIOCINIO: Final = 2000
"""O mesmo teto do turno (`jarvis.s2.cerebro`): o raciocínio não cresce o prompt sem fim."""
NOTA_DA_TAREFA: Final = (
    "Este pedido do dono está sendo cumprido em segundo plano e a conversa com ele segue. "
    "Continue com as ferramentas, uma por vez, até o objetivo estar cumprido e conferido; entre "
    "um passo e outro, nada em voz. Quando terminar, responda ao dono em uma ou duas frases, sem "
    "markdown, com o resultado que a ferramenta confirmou — ou com o que deu errado e o que dá "
    "para fazer. Não cite o nome das ferramentas nem os argumentos delas."
)
NOTA_DE_CONFERIR: Final = (
    "O que foi feito ainda NÃO foi conferido: antes de responder, leia o resultado (a aba, a "
    "página, o estado) com uma ferramenta de leitura e só diga que ficou pronto se a leitura "
    "confirmar."
)
FERRAMENTAS_DE_LEITURA: Final = frozenset(
    {"browser.read", "browser.tabs", "browser.tela", "browser.inspecionar", "web.ler"}
)
SEM_CONFERIR: Final = "Não consegui conferir se ficou certo."
NAO_CONFIRMADO: Final = "Não fiz, porque você não confirmou."
SEM_JEITO: Final = "não achei um jeito de fazer isso com o que está ligado agora"
CAUSAS_DE_DENTRO: Final = frozenset(
    {"fora_do_contrato", "ferramenta_desligada", "argumento_recusado", "metodo_de_fora"}
)
"""Falhas que são do caminho interno (contrato, catálogo, método): o dono ouve a frase geral."""
_FRASE: Final = r"(?<=[.!?…])\s+"
_CODIGO_ENTRE_PARENTESES: Final = r"\s*\([a-z][a-z_]{2,40}\)"


@dataclass(slots=True)
class MotorDoObjetivo:
    """O `MotorDeTarefa` da tarefa de um pedido: propõe, nunca executa (P1)."""

    motor: MotorDeConversa
    contexto: Contexto
    """O do turno em que o pedido chegou: sistema (persona, método, memória) e a conversa até a
    fala do dono. As ferramentas vêm do `catalogo`, as de agora."""
    catalogo: Callable[[], Sequence[Mapping[str, Any]]]
    primeiro: PedidoDeTool | None
    """A proposta que o motor já fez no turno: é o primeiro passo, sem pedir de novo. `None` = o
    turno já fez o primeiro passo (o objetivo que precisa conferir, ADR-0046): a tarefa pergunta ao
    motor o próximo, com os resultados do turno na mão."""
    feitos_antes: tuple[ResultadoDeFerramenta, ...] = ()
    """O que o turno já tinha rodado antes de delegar (só o que não vai em tarefa)."""
    raciocinio: str = ""
    ja_dito: str = ""
    """O que o dono já ouviu deste pedido (a frase curta): o motor não a repete."""
    ids: frozenset[str] = frozenset()
    """Os ids de todas as ferramentas do catálogo (as fora deste modo também): frase que cita um
    deles é etapa interna e não vai para a voz."""
    limite_do_raciocinio: int = LIMITE_DO_RACIOCINIO
    nome: str = "objetivo"
    raciocinio_descartado: int = 0
    cobrou_conferencia: bool = False

    @property
    def na_nuvem(self) -> bool:
        return self.motor.onde is Onde.NUVEM

    def proximo(
        self, tarefa: Tarefa, feitos: Sequence[ResultadoDeFerramenta], cancelado: Callable[[], bool]
    ) -> Passo:
        if not feitos and self.primeiro is not None:
            return self.primeiro
        if feitos and feitos[-1].causa == "dono_nao_confirmou":
            # O dono disse não (ou cortou a pergunta, ou ela venceu): a tarefa acaba aqui. Chamar o
            # motor de novo era a mesma ação proposta outra vez — a pergunta em laço da trilha do
            # dono (2026-10-24: três perguntas seguidas para o mesmo apps.quit).
            return _recusado(feitos[-1])
        objetivo = tarefa.contaminacao.objetivo
        catalogo = tuple(
            f for f in self.catalogo() if not str(f["id"]).startswith(FORA_DA_ALLOWLIST)
        )
        while True:
            cobrar = self.cobrou_conferencia
            pedido, texto = self._rodada(tarefa, feitos, catalogo, cancelado, conferir=cobrar)
            if pedido is not None:
                return pedido
            ids = self.ids | {str(f["id"]) for f in catalogo}
            pode_ler = any(str(f["id"]) in FERRAMENTAS_DE_LEITURA for f in catalogo)
            if objetivo is not None and objetivo.falta_conferir and pode_ler and not cobrar:
                self.cobrou_conferencia = True  # uma vez: o motor lê, ou a resposta diz que não
                continue
            return self._fim(tarefa, feitos, texto, ids)

    def _rodada(
        self,
        tarefa: Tarefa,
        feitos: Sequence[ResultadoDeFerramenta],
        catalogo: tuple[Mapping[str, Any], ...],
        cancelado: Callable[[], bool],
        *,
        conferir: bool,
    ) -> tuple[PedidoDeTool | None, str]:
        todos = (*self.feitos_antes, *feitos)
        textos, _podados = textos_no_contexto(todos)
        notas = [NOTA_DA_TAREFA]
        objetivo = tarefa.contaminacao.objetivo
        if objetivo is not None:
            # Lote C, C2: o critério de pronto, a fase e o que já foi feito (só ferramenta e
            # status) — na nuvem sem o texto do pedido de novo (D20: ele já está na conversa).
            dados = objetivo.para_o_classificador(na_nuvem=self.na_nuvem)
            notas.append(
                f"Critério de pronto: {dados['criterio_de_pronto']}. Fase: {dados['fase']}. "
                f"Passos feitos: {', '.join(dados['passos_feitos']) or 'nenhum'}."
            )
        if conferir:
            notas.append(NOTA_DE_CONFERIR)
        contexto = Contexto(
            sistema=f"{self.contexto.sistema}\n\n" + " ".join(notas),
            mensagens=(*self.contexto.mensagens, *(Mensagem("ferramenta", t) for t in textos)),
            ferramentas=catalogo,
            raciocinio=self.raciocinio,
            ja_dito=self.ja_dito,
            imagens=_imagens(todos) if aceita_imagem(self.motor) else (),
        )
        # Todo texto passa pelo leitor (o motor que esqueceu de separar o protocolo não fala JSON
        # por isso); o que vem antes da proposta é narração e o depois, palpite: raciocínio.
        leitor = LeitorDoProtocolo()
        pedido: PedidoDeTool | None = None
        texto: list[str] = []
        deltas = self.motor.gerar(contexto, Modo.RAPIDO, cancelado)
        try:
            for delta in deltas:
                if isinstance(delta, Fim):
                    if delta.motivo in (MotivoDoFim.ERRO, MotivoDoFim.PRAZO):
                        raise ErroDeTarefa(
                            "o motor da conversa não respondeu a tempo para o próximo passo"
                        )
                    break
                partes = (
                    list(leitor.alimentar(delta.texto)) if isinstance(delta, Texto) else [delta]
                )
                for parte in partes:
                    if isinstance(parte, PedidoDeTool):
                        if pedido is None:
                            pedido = parte
                            self._pensou(" ".join(texto))
                            texto = []
                    elif isinstance(parte, Raciocinio):
                        self._pensou(parte.texto)
                    elif isinstance(parte, Texto):
                        if pedido is None:
                            texto.append(parte.texto)
                        else:
                            self._pensou(parte.texto)
        finally:
            deltas.close()  # o `finally` do motor para a geração
        for parte in leitor.fechar():
            if isinstance(parte, PedidoDeTool) and pedido is None:
                pedido = parte
            elif isinstance(parte, Texto) and pedido is None:
                texto.append(parte.texto)
        return pedido, "".join(texto)

    def _pensou(self, trecho: str) -> None:
        trecho = trecho.strip()
        if not trecho:
            return
        guardado = trecho[: max(0, self.limite_do_raciocinio - len(self.raciocinio) - 1)]
        if guardado:
            self.raciocinio = f"{self.raciocinio}\n{guardado}" if self.raciocinio else guardado
        self.raciocinio_descartado += len(trecho) - len(guardado)

    def _fim(
        self,
        tarefa: Tarefa,
        feitos: Sequence[ResultadoDeFerramenta],
        texto: str,
        ids: frozenset[str],
    ) -> FimDaTarefa:
        todos = (*self.feitos_antes, *feitos)
        objetivo = tarefa.contaminacao.objetivo
        nada_feito = (
            objetivo is not None and objetivo.efeitos_tentados and not objetivo.efeito_feito
        )
        if nada_feito or not any(r.status == "ok" for r in todos):
            # Nada deu certo — nenhum passo, ou nenhum dos que mudam algo (ler a página não é abrir
            # o vídeo): quem diz é o código, com o motivo do último erro, nunca "abri".
            ultimo = next((r for r in reversed(todos) if r.status != "ok"), todos[-1])
            if ultimo.causa == "dono_nao_confirmou" or ultimo.motivo == "o dono disse não":
                return FimDaTarefa(ultimo.motivo, resposta=NAO_CONFIRMADO, falhou=True)
            motivo = motivo_para_ouvir(ultimo, ids)
            return FimDaTarefa(motivo, resposta=f"Não consegui: {motivo}.", falhou=True)
        resposta = sem_etapas_internas(texto, ids) or "Terminei o que você pediu."
        if objetivo is not None and objetivo.falta_conferir:
            resposta = f"{resposta} {SEM_CONFERIR}"
        return FimDaTarefa(resposta, resposta=resposta)


def _recusado(resultado: ResultadoDeFerramenta) -> FimDaTarefa:
    """O fim da tarefa cuja pergunta o dono não confirmou. Ele disse não, clicou não ou cortou a
    pergunta com outro assunto: já ouviu (ou disse) o que importa, e o fim é calado — só o card
    muda. O prazo que venceu sem resposta é o único "não" que ele não viu acontecer: esse é dito."""
    origem = str(resultado.dados.get("resposta_do_dono", "prazo"))
    if origem == "prazo":
        return FimDaTarefa(resultado.motivo, resposta=NAO_CONFIRMADO, falhou=True)
    return FimDaTarefa(resultado.motivo, resposta="", falhou=True, aviso="")


def _imagens(feitos: Sequence[ResultadoDeFerramenta]) -> tuple[Imagem, ...]:
    """A tela mais nova que um passo capturou (ADR-0032): só ela vai ao motor."""
    for resultado in reversed(feitos):
        if resultado.anexos:
            return resultado.anexos
    return ()


def motivo_para_ouvir(resultado: ResultadoDeFerramenta, ids: frozenset[str]) -> str:
    """O motivo de uma falha em frase de gente: sem o código entre parênteses, sem o id de
    ferramenta, sem JSON. Falha do caminho interno vira a frase geral."""
    if resultado.causa in CAUSAS_DE_DENTRO or resultado.tool_id == "(malformado)":
        return SEM_JEITO
    limpo = re.sub(_CODIGO_ENTRE_PARENTESES, "", sem_protocolo(resultado.motivo))
    limpo = limpo.strip().rstrip(".!?…").strip()
    if not limpo or _cita_ferramenta(limpo, ids) or "{" in limpo:
        return SEM_JEITO
    return limpo


def sem_etapas_internas(texto: str, ids: frozenset[str]) -> str:
    """O texto do motor como fala: sem protocolo, e sem a frase que cita uma ferramenta pelo id
    ou traz argumento em JSON (é etapa interna, não resultado)."""
    frases = re.split(_FRASE, sem_protocolo(texto))
    return " ".join(
        f for f in frases if f.strip() and not _cita_ferramenta(f, ids) and "{" not in f
    ).strip()


def _cita_ferramenta(texto: str, ids: frozenset[str]) -> bool:
    return any(re.search(rf"(?<![\w.]){re.escape(i)}(?![\w])", texto) for i in ids)
