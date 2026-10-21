"""O corpo das tools `input.*`: foco, risco, taxa e parada antes de qualquer evento sintético.

Ordem fixa, e nenhuma etapa lê nada que o modelo ou uma página escreveram além dos argumentos
tipados: **parada** → **argumentos** → **foco** → **risco** (recusa ou pede o "sim" do dono, uma vez
por ação) → **foco de novo** (a confirmação acontece na janela do Jarvis, que ganha o foco; o
código o devolve à janela de origem e recusa se ele não voltar) → **taxa** → evento.

Decisões que valem lembrar:

- **Foco desconhecido é recusa.** Sem saber onde o evento cai, um clique pode cair no botão
  "confirmar" do próprio Jarvis — e uma ação confirmada pela janela do Jarvis deixa o foco nela.
- **O próprio Jarvis em foco é recusa**, sempre: a entrada virtual não aperta os botões dele.
- **Senha, código e cartão são do dono**: digitar em gerenciador de senhas ou janela de
  autenticação, ou digitar número de cartão, é recusado sem pergunta.
- **Enter envia**: apertar Enter (ou digitar quebra de linha) pede o "sim", em qualquer janela.
- Turno que leu conteúdo de terceiros pede o "sim" para qualquer ação (a página pode mandar).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.entrada import teclas
from jarvis.entrada.foco import ROTULOS, Foco, FocoDesconhecido, Janela, categoria_da_janela
from jarvis.entrada.limite import Interruptor, LimiteDeTaxa
from jarvis.entrada.porta import (
    BOTOES,
    LIMITE_DE_CLIQUES,
    LIMITE_DO_DESLOCAMENTO,
    BackendDeEntrada,
    EntradaIndisponivel,
)
from jarvis.navegador.risco import parece_cartao

FERRAMENTAS_DE_ENTRADA: Final = frozenset(
    {"input.mouse.move", "input.mouse.click", "input.key.type", "input.key.press"}
)
FERRAMENTA_DE_CONFIRMACAO: Final = "input.acao_sensivel"
"""Manifesto `perigoso` que só o código consulta no PDP; o modelo nunca a vê."""
CATEGORIAS_ONDE_NAO_SE_DIGITA: Final = frozenset({"senha", "autenticacao"})
PAUSA_DEPOIS_DE_ATIVAR_S: Final = 0.3

Exigir = Callable[[str, str, str], None]
"""`(detalhe, motivo, causa)`: a frase da janela e o código que a trilha grava."""


class EntradaRecusada(ValueError):
    """A ação não aconteceu e a frase diz por quê (parada, foco, taxa, tecla fora da lista…)."""


@dataclass(frozen=True, slots=True)
class Avaliacao:
    recusa: str = ""
    motivos: tuple[str, ...] = ()
    causas: tuple[str, ...] = ()
    """Um código por motivo (`jarvis.trilha.CAUSAS`), na mesma ordem: é o que a trilha grava."""


def _mesma_janela(a: Janela | None, b: Janela | None) -> bool:
    if a is None or b is None:
        return a is b
    if a.id and b.id:
        return a.id == b.id
    return a.app == b.app


def avaliar(
    tool_id: str,
    janela: Janela | None,
    *,
    texto: str = "",
    enter: bool = False,
    contaminado: bool = False,
) -> Avaliacao:
    """Pura: o que a janela em foco e a ação pedem. Sem backend, sem relógio, sem janela real."""
    categoria = categoria_da_janela(janela)
    if categoria == "jarvis":
        return Avaliacao(
            recusa="a janela em foco é o próprio Jarvis: a entrada virtual não toca nela"
        )
    if categoria == "desconhecida":
        return Avaliacao(
            recusa=(
                "não consigo saber qual janela está em foco, e o evento cairia nela. No KDE com "
                "Wayland instale o `kdotool`; sem ele a entrada virtual fica desligada"
            )
        )
    if tool_id == "input.key.type":
        if parece_cartao(texto):
            return Avaliacao(recusa="número de cartão o dono digita; o Jarvis não o recebe")
        if categoria in CATEGORIAS_ONDE_NAO_SE_DIGITA:
            return Avaliacao(
                recusa="em gerenciador de senhas ou janela de autenticação quem digita é o dono"
            )
    motivos: list[tuple[str, str]] = []
    if categoria:
        motivos.append((f"a janela em foco é {ROTULOS[categoria]}", "categoria_da_janela"))
    if enter:
        motivos.append(("Enter confirma ou envia o que estiver na janela", "enter_envia"))
    if contaminado:
        motivos.append(
            (
                "o turno leu conteúdo de terceiros, que pode estar pedindo esta ação",
                "turno_contaminado",
            )
        )
    return Avaliacao(
        motivos=tuple(frase for frase, _ in motivos), causas=tuple(causa for _, causa in motivos)
    )


def _inteiro(args: Mapping[str, Any], nome: str) -> int:
    valor: object = args.get(nome, 0)
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise EntradaRecusada(f"{nome} tem de ser um número inteiro")
    if abs(valor) > LIMITE_DO_DESLOCAMENTO:
        raise EntradaRecusada(f"{nome} passa de {LIMITE_DO_DESLOCAMENTO} pixels por chamada")
    return valor


@dataclass(slots=True)
class ControleDeEntrada:
    backend: BackendDeEntrada
    foco: Foco = field(default_factory=FocoDesconhecido)
    limite: LimiteDeTaxa = field(default_factory=LimiteDeTaxa)
    interruptor: Interruptor = field(default_factory=Interruptor)
    dormir: Callable[[float], None] = time.sleep

    def executar(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        *,
        contaminado: bool,
        exigir: Exigir,
        cancelado: Callable[[], bool],
    ) -> dict[str, Any]:
        if self.interruptor.parado:
            raise EntradaRecusada(
                f"a entrada virtual está parada ({self.interruptor.motivo}); só o dono a libera"
            )
        descricao, texto, enter, fazer, resultado = self._preparar(tool_id, args)
        janela = self.foco.atual()
        avaliacao = avaliar(tool_id, janela, texto=texto, enter=enter, contaminado=contaminado)
        if avaliacao.recusa:
            raise EntradaRecusada(avaliacao.recusa)
        if avaliacao.motivos:
            onde = f" na janela «{janela.app}: {janela.titulo[:60]}»" if janela else ""
            exigir(f"{descricao}{onde}", "; ".join(avaliacao.motivos), "+".join(avaliacao.causas))
            if cancelado():
                raise EntradaRecusada("interrompido antes do evento")
            self._conferir_foco_depois_do_sim(janela)
        if self.interruptor.parado:  # o dono pode ter parado enquanto olhava a pergunta
            raise EntradaRecusada("o dono mandou parar a entrada virtual")
        espera = self.limite.tentar()
        if espera > 0:
            raise EntradaRecusada(
                f"limite de taxa da entrada virtual: espere {espera:.0f} s antes da próxima ação"
            )
        try:
            fazer()
        except (EntradaIndisponivel, teclas.TeclaRecusada) as erro:
            raise EntradaRecusada(str(erro)) from None
        return resultado

    def _conferir_foco_depois_do_sim(self, original: Janela | None) -> None:
        """A janela do Jarvis ganhou o foco quando o dono clicou "sim": devolve-o à de origem e só
        segue se o foco estiver mesmo lá. Qualquer outra mudança no meio da pergunta é recusa."""
        agora = self.foco.atual()
        if _mesma_janela(agora, original):
            return
        if (
            original is not None
            and categoria_da_janela(agora) == "jarvis"
            and self.foco.ativar(original)
        ):
            self.dormir(PAUSA_DEPOIS_DE_ATIVAR_S)
            if _mesma_janela(self.foco.atual(), original):
                return
        raise EntradaRecusada(
            "o foco mudou enquanto você decidia, e não consegui devolvê-lo à janela de origem: "
            "peça de novo com a janela certa à frente"
        )

    def _preparar(
        self, tool_id: str, args: Mapping[str, Any]
    ) -> tuple[str, str, bool, Callable[[], None], dict[str, Any]]:
        """Valida os argumentos e monta `(descrição, texto, é_enter, evento, resultado)`."""
        nome = self.backend.nome
        if tool_id == "input.mouse.move":
            dx, dy = _inteiro(args, "dx"), _inteiro(args, "dy")
            if dx == 0 and dy == 0:
                raise EntradaRecusada("dx e dy são zero: não há o que mover")
            return (
                f"mover o mouse ({dx:+d}, {dy:+d})",
                "",
                False,
                lambda: self.backend.mover(dx, dy),
                {"dx": dx, "dy": dy, "backend": nome},
            )
        if tool_id == "input.mouse.click":
            botao = str(args.get("botao", "esquerdo"))
            vezes = args.get("vezes", 1)
            if botao not in BOTOES:
                raise EntradaRecusada(f"botão {botao!r}: use esquerdo, direito ou meio")
            if (
                isinstance(vezes, bool)
                or not isinstance(vezes, int)
                or not 1 <= vezes <= LIMITE_DE_CLIQUES
            ):
                raise EntradaRecusada(f"vezes tem de ir de 1 a {LIMITE_DE_CLIQUES}")
            return (
                f"clicar com o botão {botao} ({vezes}x)",
                "",
                False,
                lambda: self.backend.clicar(botao, vezes),
                {"botao": botao, "vezes": vezes, "backend": nome},
            )
        if tool_id == "input.key.type":
            try:
                texto = teclas.validar_texto(str(args.get("texto", "")))
            except teclas.TeclaRecusada as erro:
                raise EntradaRecusada(str(erro)) from None
            visto = " ".join(texto.split())
            resumo = visto if len(visto) <= 80 else visto[:80] + "…"
            return (
                f"digitar «{resumo}»",
                texto,
                "\n" in texto,
                lambda: self.backend.digitar(texto),
                {"caracteres": len(texto), "backend": nome},
            )
        if tool_id == "input.key.press":
            try:
                combinacao = teclas.interpretar(str(args.get("tecla", "")))
            except teclas.TeclaRecusada as erro:
                raise EntradaRecusada(str(erro)) from None
            return (
                f"apertar {combinacao.texto}",
                "",
                combinacao.e_enter,
                lambda: self.backend.pressionar(combinacao.modificadores, combinacao.tecla),
                {"tecla": combinacao.texto, "backend": nome},
            )
        raise EntradaRecusada(f"{tool_id} sem corpo")  # pragma: no cover — o executor filtra
