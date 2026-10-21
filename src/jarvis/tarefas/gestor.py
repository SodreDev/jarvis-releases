"""O gestor de tarefas (ADR-0022, fatia mínima; pedido do dono de 2026-10-18).

Comando longo não prende a conversa: `tarefa.iniciar` cria uma **tarefa** — uma linha de execução
própria —, devolve o id na hora e o Jarvis segue falando. O que a ADR manda, e está aqui:

- **cada passo passa pelo mesmo PDP** (`ExecutorDeFerramentas.executar`): a tarefa não tem caminho
  para uma ferramenta que não seja o da conversa. Passo perigoso pede o "sim" do dono na mesma
  faixa da janela, e a tarefa espera; a conversa segue;
- **a allowlist da tarefa só encolhe**: o que o modo de acesso permite, sem `tarefa.*` (profundidade
  1) nem `acao.desfazer`;
- **cancelável**: o botão "parar" da janela, `tarefa.cancelar` ou o fim da sessão. Resultado que
  chega depois do cancelamento é descartado (fica na auditoria, não no estado);
- **a conclusão entra pela fila de avisos** (ADR-0025) como `Notification`, e a tarefa aparece no
  card `tarefas` (nome, estado, progresso, "parar");
- **o motor é escolha do dono** (`tarefa_motor` na configuração), nunca do modelo: `direto` roda a
  ferramenta pedida; `agente` deixa um motor de conversa planejar os passos, ainda assim cada um
  proposto, nunca executado, por ele;
- **sem ressurreição** (P9): as tarefas vivem na memória do processo. Fechar o Jarvis as cancela, e
  nada é retomado sozinho. Teto de **2** tarefas ao mesmo tempo (ADR-0022, regra 8).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, Protocol

import jsonschema

from jarvis.barramento.envelope import uuid7
from jarvis.executor.desfazer import Contaminacao
from jarvis.politica.objetivo import EstadoDoObjetivo, Objetivo
from jarvis.s2.motor import PedidoDeTool

if TYPE_CHECKING:
    from jarvis.executor.ferramentas import (
        Confirmacao,
        ExecutorDeFerramentas,
        ResultadoDeFerramenta,
    )

MAXIMO_DE_TAREFAS_AO_MESMO_TEMPO: Final = 2
MAXIMO_DE_PASSOS: Final = 6
PRAZO_DA_TAREFA_S: Final = 300.0
TAREFAS_NO_CARD: Final = 8
FORA_DA_ALLOWLIST: Final = ("tarefa.", "acao.desfazer")
"""Profundidade 1: tarefa não cria tarefa. E desfazer é do dono na conversa, não de uma tarefa."""
MOTORES_DE_TAREFA: Final = ("direto", "agente")


class EstadoDaTarefa(StrEnum):
    RODANDO = "rodando"
    ESPERANDO_O_DONO = "esperando_o_dono"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"
    CANCELADA = "cancelada"

    @property
    def final(self) -> bool:
        return self in (EstadoDaTarefa.CONCLUIDA, EstadoDaTarefa.FALHOU, EstadoDaTarefa.CANCELADA)


@dataclass(frozen=True, slots=True)
class FimDaTarefa:
    """O motor não tem mais passo: a tarefa acabou, com este resumo."""

    resumo: str
    de_terceiros: bool = False
    """O resumo foi escrito por um modelo a partir do que a tarefa leu: é dado, não fala própria."""
    aviso: str | None = None
    """O que o dono ouve no fim, escrito pelo **código** do motor: `None` = o aviso de sempre; `""`
    = nenhum (o card mostra o fim) — o foco de um app que abriu na hora (ADR-0037)."""
    resposta: str = ""
    """A resposta ao dono, na tarefa de um pedido dele (ADR-0038): o que o Jarvis diz no fim —
    o resultado conferido ou o erro em frase de gente. Vazio = o aviso de sempre."""
    falhou: bool = False
    """O objetivo não foi cumprido (nenhum passo deu certo): a tarefa acaba `falhou`, com o
    `resumo` como motivo, e a `resposta` diz isso ao dono."""


Passo = PedidoDeTool | FimDaTarefa


class MotorDeTarefa(Protocol):
    """Quem decide o próximo passo. Só **propõe**: executar é do executor, com o PDP."""

    @property
    def nome(self) -> str: ...

    @property
    def na_nuvem(self) -> bool: ...

    def proximo(
        self, tarefa: Tarefa, feitos: Sequence[ResultadoDeFerramenta], cancelado: Callable[[], bool]
    ) -> Passo: ...


@dataclass(slots=True)
class Tarefa:
    id: str
    descricao: str
    tool_id: str
    parametros: Mapping[str, Any]
    motor: str
    na_nuvem: bool = False
    estado: EstadoDaTarefa = EstadoDaTarefa.RODANDO
    passo: int = 0
    passos_previstos: int = 0
    """0 = não se sabe (motor `agente`)."""
    resumo: str = ""
    motivo: str = ""
    de_terceiros: bool = False
    aviso: str | None = None
    prazo_s: float | None = None
    """O prazo desta tarefa, quando o código que a criou escolheu outro; `None` = o do gestor."""
    criada_em: float = field(default_factory=time.monotonic)
    terminou_em: float | None = None
    cancelada: threading.Event = field(default_factory=threading.Event, repr=False)
    contaminacao: Contaminacao = field(default_factory=Contaminacao, repr=False)
    confirmar: Callable[[Confirmacao], bool] | None = field(default=None, repr=False)
    """Quem responde primeiro às perguntas desta tarefa (o "sim" já dado); `None` = a janela."""
    de_objetivo: bool = False
    """A tarefa é um pedido do dono que precisava de ferramenta (ADR-0038): o fim dela é a
    resposta àquele pedido, e não um aviso de segundo plano."""
    resposta: str = ""
    """O que o Jarvis diz ao dono no fim da tarefa de um pedido (`FimDaTarefa.resposta`)."""
    maximo_de_passos: int | None = None
    """O teto de passos desta tarefa, quando o código que a criou escolheu outro."""
    chamar: ChamarNaTarefa | None = field(default=None, repr=False)
    """Por onde cada passo passa até o executor: na tarefa de um pedido, o mesmo portão do turno
    (PDP, Jev, objetivo — `jarvis.s2.fluxo_de_acao`). `None` = direto ao executor (só o PDP)."""

    @property
    def progresso(self) -> int:
        """Em %, para o card. Sem total conhecido, anda devagar até 90 e só fecha ao terminar."""
        if self.estado is EstadoDaTarefa.CONCLUIDA:
            return 100
        if self.passos_previstos:
            return min(99, int(100 * self.passo / self.passos_previstos))
        return min(90, 15 * self.passo)

    def para_o_modelo(self) -> dict[str, Any]:
        corpo: dict[str, Any] = {
            "tarefa_id": self.id,
            "descricao": self.descricao,
            "estado": str(self.estado),
            "progresso_pct": self.progresso,
        }
        objetivo = self.contaminacao.objetivo
        if objetivo is not None:
            corpo["fase"] = str(objetivo.fase)
            corpo["passos_feitos"] = objetivo.total_de_passos
        if self.motivo:
            corpo["motivo"] = self.motivo
        return corpo


@dataclass(slots=True)
class MotorDireto:
    """Roda a ferramenta que foi pedida, num passo só."""

    nome: str = "direto"
    na_nuvem: bool = False

    def proximo(
        self, tarefa: Tarefa, feitos: Sequence[ResultadoDeFerramenta], cancelado: Callable[[], bool]
    ) -> Passo:
        if not feitos:
            return PedidoDeTool(tarefa.tool_id, dict(tarefa.parametros))
        ultimo = feitos[-1]
        if ultimo.status == "ok":
            return FimDaTarefa(f"{tarefa.tool_id} terminou")
        # O motivo vai para o dono em voz: sem o id da ferramenta nem o status cru (ADR-0038).
        raise ErroDeTarefa(ultimo.motivo or "não terminou")


class ErroDeTarefa(RuntimeError):
    """A tarefa não deu certo; a frase diz por quê."""


class TarefaRecusada(ValueError):
    """`tarefa.iniciar` recusou antes de criar: a frase volta ao modelo."""


ChamarNaTarefa = Callable[
    [Tarefa, PedidoDeTool, str, Callable[["Confirmacao"], bool]], "ResultadoDeFerramenta"
]
"""Um passo da tarefa: a tarefa, a proposta, o `call_id` e quem confirma por ela."""
Concluida = Callable[[Tarefa], None]
AvisarDaTarefa = Callable[[Tarefa, str, str, str], None]
"""A tarefa tem algo para o dono **agora** (ADR-0038): `(tarefa, id, tipo, frase)` — a pergunta
que ela espera, o aviso de uma ação moderada. Quem liga aqui põe na fila de avisos."""
ConfirmarDaTarefa = Callable[["Confirmacao", Callable[[], bool]], bool]
FabricaDeMotor = Callable[[], MotorDeTarefa]


@dataclass(slots=True)
class GestorDeTarefas:
    executor: ExecutorDeFerramentas
    confirmar: ConfirmarDaTarefa
    """Pede o "sim" na janela e espera; recebe a pergunta e a função "a tarefa foi cancelada?"."""
    fabrica_de_motor: FabricaDeMotor = MotorDireto
    session_id: str = ""
    ao_mudar: Callable[[], None] = lambda: None
    """O card mudou (estado, passo, fim): a janela o renova. Chamada da linha da tarefa."""
    ao_concluir: Concluida = lambda _t: None
    """A tarefa terminou (de qualquer jeito): quem liga aqui põe o `Notification` na fila."""
    ao_avisar: AvisarDaTarefa = lambda _t, _i, _tipo, _f: None
    """A tarefa tem algo para o dono antes do fim (a pergunta que ela espera, o aviso de uma
    moderada): chamada da linha da tarefa."""
    ao_retirar_aviso: Callable[[Tarefa, str], None] = lambda _t, _i: None
    """O aviso deste id perdeu a vez (a pergunta foi respondida antes de tocar): se ainda não
    saiu, não sai mais."""
    maximo_ao_mesmo_tempo: int = MAXIMO_DE_TAREFAS_AO_MESMO_TEMPO
    prazo_s: float = PRAZO_DA_TAREFA_S
    tarefas: dict[str, Tarefa] = field(default_factory=dict)
    _trava: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _linhas: dict[str, threading.Thread] = field(default_factory=dict, repr=False)

    # --- o que o modelo pede (tarefa.*) ---------------------------------------------------
    def iniciar(
        self,
        descricao: str,
        tool_id: str,
        parametros: Mapping[str, Any],
        *,
        contaminado: bool = False,
        motor: MotorDeTarefa | None = None,
        confirmar: Callable[[Confirmacao], bool] | None = None,
        prazo_s: float | None = None,
    ) -> Tarefa:
        """Cria e põe a tarefa para rodar. `motor`, `confirmar` e `prazo_s` são do **código** (a
        execução que o dono já autorizou na conversa: motor direto, e o "sim" dele valendo só para
        aquela chamada; o foco de um app lento, que espera mais que o prazo de sempre); o modelo,
        por `tarefa.iniciar`, nunca os escolhe."""
        self._conferir(tool_id, parametros)
        motor = motor if motor is not None else self.fabrica_de_motor()
        return self._comecar(
            Tarefa(
                id=f"t-{uuid7()[-8:]}",
                descricao=" ".join(descricao.split())[:120],
                tool_id=tool_id,
                parametros=dict(parametros),
                motor=motor.nome,
                na_nuvem=motor.na_nuvem,
                passos_previstos=1 if motor.nome == "direto" else 0,
                # O objetivo da tarefa é dela (Lote C, C2): ela o segue até cumprir, com o teto de
                # passos e de prazo e o cancelar de sempre — e o PDP o usa nas chamadas dela.
                contaminacao=Contaminacao(contaminado, Objetivo.do_pedido(descricao)),
                confirmar=confirmar,
                prazo_s=prazo_s,
            ),
            motor,
        )

    def iniciar_objetivo(
        self,
        descricao: str,
        motor: MotorDeTarefa,
        *,
        contaminacao: Contaminacao,
        chamar: ChamarNaTarefa | None = None,
        prazo_s: float | None = None,
        maximo_de_passos: int | None = None,
    ) -> Tarefa:
        """A tarefa de um **pedido do dono** que precisa de ferramenta (ADR-0038): quem a cria é o
        cérebro, nunca o modelo; o motor já traz a primeira proposta, e a `contaminacao` traz o
        objetivo e o método daquele pedido. Cada passo vai por `chamar` (o portão do turno); o
        teto de tarefas, o cancelar e o prazo são os de sempre."""
        return self._comecar(
            Tarefa(
                id=f"t-{uuid7()[-8:]}",
                descricao=" ".join(descricao.split())[:120],
                tool_id="",
                parametros={},
                motor=motor.nome,
                na_nuvem=motor.na_nuvem,
                contaminacao=contaminacao,
                prazo_s=prazo_s,
                de_objetivo=True,
                maximo_de_passos=maximo_de_passos,
                chamar=chamar,
            ),
            motor,
        )

    def _comecar(self, tarefa: Tarefa, motor: MotorDeTarefa) -> Tarefa:
        with self._trava:
            rodando = [t for t in self.tarefas.values() if not t.estado.final]
            if len(rodando) >= self.maximo_ao_mesmo_tempo:
                raise TarefaRecusada(
                    f"já há {len(rodando)} tarefas rodando (o teto é "
                    f"{self.maximo_ao_mesmo_tempo}): espere uma terminar ou cancele uma"
                )
            self.tarefas[tarefa.id] = tarefa
            linha = threading.Thread(
                target=self._correr, args=(tarefa, motor), name=f"jarvis-{tarefa.id}", daemon=True
            )
            self._linhas[tarefa.id] = linha
        linha.start()
        self.ao_mudar()
        return tarefa

    def esperando_o_dono(self, tarefa: Tarefa, esperando: bool) -> None:
        """A tarefa parou numa pergunta ao dono (ou voltou dela): o card diz isso."""
        if tarefa.estado.final:
            return
        novo = EstadoDaTarefa.ESPERANDO_O_DONO if esperando else EstadoDaTarefa.RODANDO
        if tarefa.estado is not novo:
            tarefa.estado = novo
            self.ao_mudar()

    def avisar(self, tarefa: Tarefa, identificador: str, tipo: str, frase: str) -> None:
        """Algo da tarefa para o dono agora; aviso que falha não derruba a linha da tarefa."""
        try:
            self.ao_avisar(tarefa, identificador, tipo, frase)
        except Exception:
            return

    def retirar_aviso(self, tarefa: Tarefa, identificador: str) -> None:
        try:
            self.ao_retirar_aviso(tarefa, identificador)
        except Exception:
            return

    def cancelar(self, tarefa_id: str) -> Tarefa:
        tarefa = self.tarefas.get(tarefa_id)
        if tarefa is None:
            raise TarefaRecusada(f"não existe a tarefa {tarefa_id!r}")
        if not tarefa.estado.final:
            tarefa.cancelada.set()
        return tarefa

    def cancelar_todas(self) -> int:
        """O fim da sessão e o botão de privacidade: nada fica rodando sem o dono saber."""
        vivas = [t for t in self.tarefas.values() if not t.estado.final]
        for tarefa in vivas:
            tarefa.cancelada.set()
        return len(vivas)

    def estado(self, tarefa_id: str = "") -> list[Tarefa]:
        if tarefa_id:
            achada = self.tarefas.get(tarefa_id)
            if achada is None:
                raise TarefaRecusada(f"não existe a tarefa {tarefa_id!r}")
            return [achada]
        return sorted(self.tarefas.values(), key=lambda t: t.criada_em, reverse=True)

    def encerrar(self, segundos: float = 5.0) -> None:
        """Cancela tudo e espera as linhas acabarem — antes de fechar o que elas usam."""
        self.cancelar_todas()
        for linha in list(self._linhas.values()):
            linha.join(timeout=segundos)

    def esperar(self, tarefa_id: str, segundos: float = 5.0) -> bool:
        """Para o teste e para o fim da sessão: a linha da tarefa terminou?"""
        linha = self._linhas.get(tarefa_id)
        if linha is not None:
            linha.join(timeout=segundos)
        return linha is None or not linha.is_alive()

    # --- o card -----------------------------------------------------------------------------
    def dados_do_card(self) -> dict[str, list[dict[str, str]]]:
        """Os itens do card `tarefas` (nome, estado, progresso e o id do botão "parar")."""
        itens: list[dict[str, str]] = []
        for tarefa in self.estado()[:TAREFAS_NO_CARD]:
            itens.append(
                {
                    "id": tarefa.id,
                    "titulo": tarefa.descricao,
                    "detalhe": _detalhe(tarefa),
                    "estado": _ESTADO_DO_CARD[tarefa.estado],
                    "progresso": str(tarefa.progresso),
                }
            )
        return {"itens": itens}

    # --- a linha da tarefa --------------------------------------------------------------------
    def _conferir(self, tool_id: str, parametros: Mapping[str, Any]) -> None:
        """Recusa na porta o que a tarefa nunca poderia rodar: o modelo ouve o porquê na hora."""
        if tool_id.startswith(FORA_DA_ALLOWLIST):
            raise TarefaRecusada(
                f"{tool_id} não roda dentro de tarefa (tarefa não cria tarefa nem desfaz ação)"
            )
        if not self.executor.disponivel(tool_id):
            raise TarefaRecusada(f"{tool_id} não existe nesta sessão ou o modo atual não a permite")
        try:
            jsonschema.validate(dict(parametros), self.executor.manifestos[tool_id]["input_schema"])
        except jsonschema.ValidationError as erro:
            raise TarefaRecusada(
                f"parâmetros fora do contrato de {tool_id}: {erro.message}"
            ) from None

    def _correr(self, tarefa: Tarefa, motor: MotorDeTarefa) -> None:
        feitos: list[ResultadoDeFerramenta] = []
        limite = time.monotonic() + (tarefa.prazo_s or self.prazo_s)
        try:
            self._passos(tarefa, motor, feitos, limite)
        except ErroDeTarefa as erro:
            self._terminar(tarefa, EstadoDaTarefa.FALHOU, motivo=str(erro))
        except Exception as erro:  # a tarefa cai com a frase; a conversa não
            self._terminar(tarefa, EstadoDaTarefa.FALHOU, motivo=f"{type(erro).__name__}: {erro}")

    def _passos(
        self,
        tarefa: Tarefa,
        motor: MotorDeTarefa,
        feitos: list[ResultadoDeFerramenta],
        limite: float,
    ) -> None:
        maximo = tarefa.maximo_de_passos or MAXIMO_DE_PASSOS
        for numero in range(1, maximo + 1):
            if tarefa.cancelada.is_set():
                return self._terminar(tarefa, EstadoDaTarefa.CANCELADA)
            if time.monotonic() > limite:
                prazo = tarefa.prazo_s or self.prazo_s
                raise ErroDeTarefa(f"passou de {prazo:.0f} s: o prazo é nosso")
            passo = motor.proximo(tarefa, feitos, tarefa.cancelada.is_set)
            if tarefa.cancelada.is_set():
                return self._terminar(tarefa, EstadoDaTarefa.CANCELADA)
            if isinstance(passo, FimDaTarefa):
                tarefa.resumo, tarefa.de_terceiros = passo.resumo, passo.de_terceiros
                tarefa.aviso, tarefa.resposta = passo.aviso, passo.resposta
                if passo.falhou:
                    return self._terminar(tarefa, EstadoDaTarefa.FALHOU, motivo=passo.resumo)
                return self._terminar(tarefa, EstadoDaTarefa.CONCLUIDA)
            if passo.tool_id.startswith(FORA_DA_ALLOWLIST):
                # O motor propôs fora da allowlist da tarefa: nem chega ao PDP (e fica registrado).
                feitos.append(_negado(passo.tool_id, "tarefa não roda isto (allowlist da tarefa)"))
                continue
            tarefa.passo = numero
            self.ao_mudar()
            if tarefa.chamar is not None:
                resultado = tarefa.chamar(
                    tarefa, passo, f"{tarefa.id}-{numero}", self._confirmar_da(tarefa)
                )
            else:
                resultado = self.executor.executar(
                    passo.tool_id,
                    passo.args,
                    cancelado=tarefa.cancelada.is_set,
                    confirmar=self._confirmar_da(tarefa),
                    session_id=self.session_id,
                    call_id=f"{tarefa.id}-{numero}",
                    contaminacao=tarefa.contaminacao,
                )
            if tarefa.cancelada.is_set():
                # Chegou depois do cancelamento: vai para a auditoria, não para o estado.
                return self._terminar(tarefa, EstadoDaTarefa.CANCELADA)
            feitos.append(resultado)
        raise ErroDeTarefa(f"passei de {maximo} passos sem terminar")

    def _confirmar_da(self, tarefa: Tarefa) -> Callable[[Confirmacao], bool]:
        def perguntar(pergunta: Confirmacao) -> bool:
            tarefa.estado = EstadoDaTarefa.ESPERANDO_O_DONO
            self.ao_mudar()
            try:
                if tarefa.confirmar is not None and tarefa.confirmar(pergunta):
                    return not tarefa.cancelada.is_set()
                return self.confirmar(pergunta, tarefa.cancelada.is_set)
            finally:
                if not tarefa.estado.final:
                    tarefa.estado = EstadoDaTarefa.RODANDO
                self.ao_mudar()

        return perguntar

    def _terminar(self, tarefa: Tarefa, estado: EstadoDaTarefa, *, motivo: str = "") -> None:
        objetivo = tarefa.contaminacao.objetivo
        if objetivo is not None:
            objetivo.concluir(_ESTADO_DO_OBJETIVO.get(estado, EstadoDoObjetivo.FALHOU))
        with self._trava:
            tarefa.estado = estado
            tarefa.motivo = motivo or tarefa.motivo
            tarefa.terminou_em = time.monotonic()
        self.ao_mudar()
        try:
            self.ao_concluir(tarefa)
        except Exception:  # aviso que falha não derruba a linha: o card já mostra o fim
            return


def _negado(tool_id: str, motivo: str) -> ResultadoDeFerramenta:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta

    return ResultadoDeFerramenta(tool_id, "negado", motivo=motivo)


_ESTADO_DO_OBJETIVO: Final = {
    EstadoDaTarefa.CONCLUIDA: EstadoDoObjetivo.CONCLUIDO,
    EstadoDaTarefa.CANCELADA: EstadoDoObjetivo.CANCELADO,
    EstadoDaTarefa.FALHOU: EstadoDoObjetivo.FALHOU,
}

_ESTADO_DO_CARD: Final = {
    EstadoDaTarefa.RODANDO: "executando",
    EstadoDaTarefa.ESPERANDO_O_DONO: "espera",
    EstadoDaTarefa.CONCLUIDA: "resultado",
    EstadoDaTarefa.FALHOU: "falhou",
    EstadoDaTarefa.CANCELADA: "cancelada",
}


def _detalhe(tarefa: Tarefa) -> str:
    quando = {
        EstadoDaTarefa.RODANDO: "rodando",
        EstadoDaTarefa.ESPERANDO_O_DONO: "esperando o seu sim",
        EstadoDaTarefa.CONCLUIDA: "pronta",
        EstadoDaTarefa.FALHOU: f"falhou: {tarefa.motivo}"[:80],
        EstadoDaTarefa.CANCELADA: "cancelada",
    }[tarefa.estado]
    onde = " · nuvem" if tarefa.na_nuvem else ""
    passos = f" · passo {tarefa.passo}" + (
        f"/{tarefa.passos_previstos}" if tarefa.passos_previstos else ""
    )
    return f"{quando}{passos if not tarefa.estado.final else ''} · motor {tarefa.motor}{onde}"
