"""O gerente do workspace: quem **decide** o que a proposta da IA vira na tela (ADR-0019).

A IA propõe (`jarvis.gui.acoes`), o catálogo diz o que pode existir (`jarvis.gui.componentes`)
e este módulo é o que aceita, ajusta ou recusa — com motivo, sempre. É o "código dispõe" do P1
em forma de gerente de layout, e não tem uma linha de Qt: dá para provar colisão, recusa e
restauração sem abrir janela nenhuma.

Cinco regras do dono, que são as que dão a ele o controle que a SPEC §5.5 promete:

1. **O que o dono fixou é dele.** Módulo fixado não é movido, redimensionado, minimizado nem
   fechado pela IA. A recusa diz isso com todas as letras.
2. **Nada aparece por cima do que já estava.** Em colisão, quem se muda é o **novo**: o mapa
   mental do dono vale mais do que a preferência de posição da proposta. Sem lugar, a ação é
   recusada pedindo para fechar ou minimizar algo — nunca empurrando o que ele já lia.
3. **Nada que encoste na máquina dele entra sem confirmação.** Componente sensível vira
   **pendência**, com o motivo que a IA deu, e espera o sim (SPEC §5.4, P12).
4. **Fechar não é apagar.** O que sai vai para a pilha de recuperáveis, e volta inteiro.
5. **Mudar de modo não perde nada.** Quem não cabe na composição nova é realocado; quem não
   couber em lugar nenhum é **minimizado**, nunca destruído.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Final

from jarvis.gui.acoes import (
    COLUNAS,
    LINHAS,
    Acao,
    AcaoInvalida,
    Area,
    Modo,
    Tipo,
    ler_acao,
)
from jarvis.gui.componentes import (
    CATALOGO,
    Componente,
    ComponenteNaoAutorizado,
    componente,
    validar_dados,
)
from jarvis.voz.escuta import Escuta, confirmacao_necessaria

LAYOUT_ANTERIOR: Final = "anterior"
"""O instantâneo que o gerente guarda sozinho antes de mudar de modo ou maximizar — é o que
dá sentido a `restoreLayout` sem a IA precisar ter guardado nada antes."""


class Origem(StrEnum):
    """Quem pôs isto na tela. Muda o que pode ser feito com o módulo depois."""

    IA = "ia"
    DONO = "dono"


class EstadoDoWidget(StrEnum):
    """Visto × em execução × resultado — a distinção que o dono pediu para enxergar."""

    VISTO = "visto"
    EXECUTANDO = "executando"
    RESULTADO = "resultado"


@dataclass(frozen=True, slots=True)
class Composicao:
    """Como cada modo distribui a tela. O núcleo é zona reservada, não um módulo."""

    nucleo: Area
    limite_de_modulos: int
    frase: str


COMPOSICOES: Final[dict[Modo, Composicao]] = {
    Modo.ASSISTENTE: Composicao(
        nucleo=Area(coluna=4, linha=1, colunas=4, linhas=5),
        limite_de_modulos=4,
        frase="núcleo no centro, poucos indicadores, conversa embaixo",
    ),
    Modo.PESQUISA: Composicao(
        nucleo=Area(coluna=0, linha=0, colunas=2, linhas=2),
        limite_de_modulos=6,
        frase="o núcleo encolhe; o conteúdo manda",
    ),
    Modo.EXECUCAO: Composicao(
        # O núcleo encolhe, mas continua **legível e no alto**, com nome e estado: um aro de
        # uma célula no canto de baixo virava enfeite solto, sem identidade nenhuma.
        nucleo=Area(coluna=0, linha=0, colunas=2, linhas=2),
        limite_de_modulos=8,
        frase="várias visões ao mesmo tempo",
    ),
}


@dataclass(frozen=True, slots=True)
class Widget:
    """Um módulo na tela. Imutável: mudar é trocar o objeto, não mexer num campo por fora."""

    id: str
    componente: str
    titulo: str
    area: Area
    dados: Mapping[str, Any] = field(default_factory=dict)
    estado: EstadoDoWidget = EstadoDoWidget.VISTO
    origem: Origem = Origem.IA
    minimizado: bool = False
    fixado: bool = False
    foco: bool = False
    maximizado: bool = False
    area_guardada: Area | None = None
    demonstracao: bool = False

    def para_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "componente": self.componente,
            "titulo": self.titulo,
            **self.area.para_dict(),
            "dados": dict(self.dados),
            "estado": str(self.estado),
            "origem": str(self.origem),
            "minimizado": self.minimizado,
            "fixado": self.fixado,
            "foco": self.foco,
            "maximizado": self.maximizado,
            "demonstracao": self.demonstracao,
        }


@dataclass(frozen=True, slots=True)
class Resultado:
    """O que aconteceu com uma proposta. Recusa sem motivo não existe aqui."""

    aceita: bool
    acao: Acao
    motivo: str = ""
    ajuste: str = ""
    widget: str = ""
    pendencia: str = ""

    @property
    def pendente(self) -> bool:
        return bool(self.pendencia)

    def frase(self) -> str:
        """A frase **técnica**, com o nome da ação: é o que vai para log e para teste."""
        if self.pendente:
            return f"{self.acao.tipo}: esperando a sua confirmação — {self.motivo}"
        if not self.aceita:
            return f"{self.acao.tipo}: recusada — {self.motivo}"
        return f"{self.acao.tipo}: feito{f' ({self.ajuste})' if self.ajuste else ''}"

    @property
    def titulo_do_alvo(self) -> str:
        """Como o dono chama a coisa: o título que a ação pediu, ou o do catálogo."""
        if self.acao.titulo:
            return self.acao.titulo
        alvo = CATALOGO.get(self.acao.componente)
        return alvo.titulo if alvo is not None else (self.acao.componente or "o módulo")

    def frase_do_dono(self) -> str:
        """A mesma coisa em português, para a tela. Vazio quando não há o que dizer.

        `createWidget: feito` é nome de ação interna — informação de quem escreveu o código,
        não de quem está usando o Jarvis. O que o dono precisa ler é o que **aconteceu com a
        tela dele**, e só quando houve algo digno de nota.
        """
        nome = self.titulo_do_alvo
        if self.pendente:
            return f"{nome} espera a sua confirmação"
        if not self.aceita:
            primeira = self.motivo.split(".")[0].strip()
            return f"não abri {nome}: {primeira}" if self.acao.tipo is Tipo.CRIAR else primeira
        if self.acao.tipo is Tipo.MODO and self.acao.modo is not None:
            return f"modo {self.acao.modo.frase}"
        if self.acao.tipo is Tipo.RESTAURAR:
            return "layout de antes de volta"
        if self.acao.tipo is Tipo.ESCUTA and self.acao.escuta is not None:
            return f"agora: {self.acao.escuta.frase}"
        # "verbo: nome", e não "nome verbo": o título é do dono ou do catálogo ("Notificações",
        # "Contexto ativo"), e concordar particípio com ele erra metade das vezes.
        feito = {
            Tipo.CRIAR: f"na tela: {nome}",
            Tipo.REMOVER: f"fechado: {nome} — dá para recuperar",
            Tipo.MOVER: f"movido: {nome}",
            Tipo.REDIMENSIONAR: f"redimensionado: {nome}",
            Tipo.FOCAR: f"em foco: {nome}",
            Tipo.MINIMIZAR: f"minimizado: {nome}",
        }.get(self.acao.tipo, "")
        if feito and self.ajuste and "ocupado" in self.ajuste:
            return f"{feito}, noutro lugar: o que você pediu estava ocupado"
        return feito


@dataclass(slots=True)
class Workspace:
    """O estado da tela e as regras que o protegem."""

    modo: Modo = Modo.ASSISTENTE
    widgets: dict[str, Widget] = field(default_factory=dict)
    fechados: list[Widget] = field(default_factory=list)
    pendentes: dict[str, Acao] = field(default_factory=dict)
    instantaneos: dict[str, tuple[Modo, tuple[Widget, ...]]] = field(default_factory=dict)
    historico: list[Resultado] = field(default_factory=list)
    ao_mudar: Callable[[], None] | None = None
    escuta: Escuta | None = None
    """O modo de escuta vivo da sessão de voz (ADR-0021). Sem ele, `definirModoDeEscuta` é
    recusada: não há o que trocar."""
    asr_na_nuvem: Callable[[], bool] = lambda: False
    """Se o ASR escolhido é de nuvem — muda o que precisa de confirmação."""
    _proximo: int = 0

    # --- leitura -------------------------------------------------------------------------
    @property
    def composicao(self) -> Composicao:
        return COMPOSICOES[self.modo]

    @property
    def nucleo(self) -> Area:
        return self.composicao.nucleo

    def visiveis(self) -> tuple[Widget, ...]:
        return tuple(w for w in self.widgets.values() if not w.minimizado)

    def para_dict(self) -> dict[str, Any]:
        return {
            "modo": str(self.modo),
            "nucleo": self.nucleo.para_dict(),
            "widgets": [w.para_dict() for w in self.widgets.values()],
            "fechados": [{"id": w.id, "titulo": w.titulo} for w in self.fechados],
            "pendentes": [
                {"id": chave, "titulo": acao.titulo or acao.componente, "motivo": acao.motivo}
                for chave, acao in self.pendentes.items()
            ],
        }

    # --- a porta por onde a IA fala -------------------------------------------------------
    def aplicar(
        self, acao: Acao, *, confirmada: bool = False, dados_reais: bool = False
    ) -> Resultado:
        """Uma proposta. Devolve o que aconteceu, e **nunca** levanta por proposta ruim.

        `confirmada` é **só** de `confirmar` — o sim do dono. Não existe campo da proposta que
        diga "já confirmado": antes, um `widget` começando com `confirmado:` fazia esse papel,
        e a própria IA podia escrevê-lo e pular a confirmação.

        `dados_reais` segue a mesma lógica (ADR-0019, emenda de 2026-10-17): só o **código** que
        tem a fonte real (a fila de avisos, por exemplo) passa verdadeiro, e só então o selo de
        demonstração sai do módulo. A proposta crua (`propor`) nunca chega aqui com ele.
        """
        try:
            resultado = self._aplicar(acao, confirmada=confirmada, dados_reais=dados_reais)
        except (AcaoInvalida, ComponenteNaoAutorizado) as erro:
            resultado = Resultado(aceita=False, acao=acao, motivo=str(erro))
        self.historico.append(resultado)
        if resultado.aceita:
            self._avisar()
        return resultado

    def propor(self, bruto: Mapping[str, Any]) -> Resultado:
        """A porta de verdade: proposta **crua**, como a IA a emite, virando resultado.

        Ler e aplicar ficam juntos aqui porque, para quem propõe, "não entendi a sua ação" e
        "não dá para fazer isso" são a mesma resposta: uma frase dizendo o que houve. É isto
        que a ponte da janela chama, e é isto que o teste de proposta malformada exercita.
        """
        try:
            acao = ler_acao(bruto)
        except AcaoInvalida as erro:
            recusa = Resultado(aceita=False, acao=Acao(tipo=Tipo.CRIAR), motivo=str(erro))
            self.historico.append(recusa)
            return recusa
        return self.aplicar(acao)

    def aplicar_todas(self, acoes: Iterator[Acao] | list[Acao]) -> list[Resultado]:
        return [self.aplicar(acao) for acao in acoes]

    def _aplicar(
        self, acao: Acao, *, confirmada: bool = False, dados_reais: bool = False
    ) -> Resultado:
        if acao.tipo is Tipo.CRIAR:
            return self._criar(acao, confirmada=confirmada, dados_reais=dados_reais)
        if acao.tipo is Tipo.ESCUTA:
            return self._definir_escuta(acao, confirmada=confirmada)
        if acao.tipo is Tipo.MODO:
            return self._mudar_de_modo(acao)
        if acao.tipo is Tipo.RESTAURAR:
            return self._restaurar(acao)
        alvo = self.widgets.get(acao.widget)
        if alvo is None:
            return Resultado(
                aceita=False,
                acao=acao,
                motivo=f"não há módulo {acao.widget!r} na tela (talvez o dono já o tenha fechado)",
            )
        if alvo.fixado and acao.tipo in {
            Tipo.REMOVER,
            Tipo.MOVER,
            Tipo.REDIMENSIONAR,
            Tipo.MINIMIZAR,
        }:
            return Resultado(
                aceita=False,
                acao=acao,
                motivo=f"o dono fixou {alvo.titulo!r}: só ele move, minimiza ou fecha este módulo",
            )
        if acao.tipo is Tipo.ATUALIZAR:
            # Antes da regra do fixado: trocar os dados não tira o módulo do lugar.
            return self._atualizar(acao, alvo, dados_reais=dados_reais)
        if acao.tipo is Tipo.REMOVER:
            return self._remover(acao, alvo)
        if acao.tipo is Tipo.FOCAR:
            return self._focar(acao, alvo)
        if acao.tipo is Tipo.MINIMIZAR:
            self._guardar(replace(alvo, minimizado=True, foco=False))
            return Resultado(aceita=True, acao=acao, widget=alvo.id)
        return self._mover_ou_redimensionar(acao, alvo)

    # --- cada ação -----------------------------------------------------------------------
    def _criar(
        self, acao: Acao, *, confirmada: bool = False, dados_reais: bool = False
    ) -> Resultado:
        alvo = componente(acao.componente)
        dados = validar_dados(alvo, acao.dados)
        if alvo.sensivel and not confirmada:
            pendencia = self._identificador("pendencia")
            self.pendentes[pendencia] = acao
            return Resultado(
                aceita=False,
                acao=acao,
                pendencia=pendencia,
                motivo=(
                    f"{alvo.titulo} encosta na sua máquina (SPEC §5.4). "
                    f"{acao.motivo or 'A IA não disse por que precisa disto.'}"
                ),
            )
        area, ajuste = self._encaixar(acao.area or alvo.area_padrao, alvo)
        if area is None:
            return Resultado(
                aceita=False,
                acao=acao,
                motivo=(
                    f"não há espaço livre de {(acao.area or alvo.area_padrao).colunas}×"
                    f"{(acao.area or alvo.area_padrao).linhas} na grade. Feche ou minimize "
                    "algum módulo e eu ponho"
                ),
            )
        identificador = self._identificador(alvo.id)
        self._guardar(
            Widget(
                id=identificador,
                componente=alvo.id,
                titulo=acao.titulo or alvo.titulo,
                area=area,
                dados=dados,
                demonstracao=alvo.demonstracao and not dados_reais,
                estado=EstadoDoWidget.RESULTADO if dados else EstadoDoWidget.VISTO,
            )
        )
        return Resultado(aceita=True, acao=acao, widget=identificador, ajuste=ajuste)

    def _atualizar(self, acao: Acao, alvo: Widget, *, dados_reais: bool) -> Resultado:
        """`updateWidget`: os campos enviados substituem os de mesmo nome, validados pelo
        registro como na criação; área, foco, título e fixação não mudam."""
        if not acao.dados:
            return Resultado(
                aceita=False,
                acao=acao,
                motivo="updateWidget sem dados: não há o que atualizar",
            )
        limpos = validar_dados(componente(alvo.componente), acao.dados)
        self._guardar(
            replace(
                alvo,
                dados={**alvo.dados, **limpos},
                demonstracao=alvo.demonstracao and not dados_reais,
                estado=EstadoDoWidget.RESULTADO,
            )
        )
        return Resultado(aceita=True, acao=acao, widget=alvo.id)

    def _definir_escuta(self, acao: Acao, *, confirmada: bool = False) -> Resultado:
        """O modelo propõe o modo; a política de `jarvis.voz.escuta` decide se espera o dono."""
        if self.escuta is None or acao.escuta is None:
            return Resultado(
                aceita=False, acao=acao, motivo="não há sessão de voz cujo modo trocar"
            )
        motivo = confirmacao_necessaria(
            acao.escuta, atual=self.escuta.modo, asr_na_nuvem=self.asr_na_nuvem()
        )
        if motivo and not confirmada:
            pendencia = self._identificador("pendencia")
            # A pendência precisa de nome na tela: esta ação não tem componente nem título.
            self.pendentes[pendencia] = replace(
                acao, titulo=acao.titulo or f"escuta: {acao.escuta.frase}"
            )
            return Resultado(
                aceita=False,
                acao=acao,
                pendencia=pendencia,
                motivo=f"{motivo}. {acao.motivo or 'A IA não disse por que precisa disto.'}",
            )
        ajuste = "já estava neste modo" if acao.escuta is self.escuta.modo else ""
        self.escuta.trocar(acao.escuta)
        return Resultado(aceita=True, acao=acao, ajuste=ajuste)

    def _remover(self, acao: Acao, alvo: Widget) -> Resultado:
        del self.widgets[alvo.id]
        self.fechados.append(alvo)
        return Resultado(aceita=True, acao=acao, widget=alvo.id)

    def _focar(self, acao: Acao, alvo: Widget) -> Resultado:
        for identificador, widget in self.widgets.items():
            if widget.foco and identificador != alvo.id:
                self.widgets[identificador] = replace(widget, foco=False)
        self._guardar(replace(alvo, foco=True, minimizado=False))
        return Resultado(aceita=True, acao=acao, widget=alvo.id)

    def _mover_ou_redimensionar(self, acao: Acao, alvo: Widget) -> Resultado:
        if acao.area is None:
            return Resultado(aceita=False, acao=acao, motivo=f"{acao.tipo} sem área")
        alvo_componente = componente(alvo.componente)
        minimo = alvo_componente.minimo
        if acao.tipo is Tipo.REDIMENSIONAR and (
            acao.area.colunas < minimo[0] or acao.area.linhas < minimo[1]
        ):
            return Resultado(
                aceita=False,
                acao=acao,
                motivo=(
                    f"{alvo.titulo} fica ilegível abaixo de {minimo[0]}×{minimo[1]} — o mínimo "
                    "é do componente, não da proposta"
                ),
            )
        area, ajuste = self._encaixar(acao.area, alvo_componente, ignorar=alvo.id)
        if area is None:
            return Resultado(
                aceita=False, acao=acao, motivo="não há espaço livre desse tamanho na grade"
            )
        self._guardar(replace(alvo, area=area, minimizado=False, maximizado=False))
        return Resultado(aceita=True, acao=acao, widget=alvo.id, ajuste=ajuste)

    def _mudar_de_modo(self, acao: Acao) -> Resultado:
        if acao.modo is None:
            return Resultado(aceita=False, acao=acao, motivo="setWorkspaceMode sem modo")
        if acao.modo is self.modo:
            return Resultado(aceita=True, acao=acao, ajuste="já estava neste modo")
        self.guardar_layout(LAYOUT_ANTERIOR)
        self.modo = acao.modo
        recolocados = self._recompor()
        return Resultado(
            aceita=True,
            acao=acao,
            ajuste=(
                f"{self.composicao.frase}"
                + (f"; {recolocados} módulo(s) realocado(s)" if recolocados else "")
            ),
        )

    def _restaurar(self, acao: Acao) -> Resultado:
        nome = acao.layout or LAYOUT_ANTERIOR
        guardado = self.instantaneos.get(nome)
        if guardado is None:
            return Resultado(
                aceita=False,
                acao=acao,
                motivo=(
                    f"não há layout guardado chamado {nome!r}. Guardados: "
                    f"{', '.join(sorted(self.instantaneos)) or 'nenhum'}"
                ),
            )
        modo, widgets = guardado
        self.modo = modo
        self.widgets = {w.id: w for w in widgets}
        return Resultado(aceita=True, acao=acao, ajuste=f"layout {nome!r} de volta")

    # --- o que o dono faz (e que a IA não pode impedir) ------------------------------------
    def fixar(self, identificador: str, fixado: bool = True) -> bool:
        """Fixar é do dono: daqui em diante a IA não mexe mais neste módulo."""
        alvo = self.widgets.get(identificador)
        if alvo is None:
            return False
        self._guardar(replace(alvo, fixado=fixado))
        return True

    def mover_pelo_dono(self, identificador: str, coluna: int, linha: int) -> bool:
        """O dono põe onde quiser. Quem estava lá e é da IA se muda; se não couber, minimiza."""
        alvo = self.widgets.get(identificador)
        if alvo is None:
            return False
        try:
            area = alvo.area.movida(coluna, linha)
        except AcaoInvalida:
            return False
        self._guardar(replace(alvo, area=area, minimizado=False))
        for outro in list(self.widgets.values()):
            if outro.id == identificador or outro.minimizado or not outro.area.colide_com(area):
                continue
            if outro.fixado:
                continue
            livre, _ = self._encaixar(outro.area, componente(outro.componente), ignorar=outro.id)
            self._guardar(
                replace(outro, area=livre, minimizado=False)
                if livre is not None
                else replace(outro, minimizado=True)
            )
        self._avisar()
        return True

    def fechar_pelo_dono(self, identificador: str) -> bool:
        alvo = self.widgets.pop(identificador, None)
        if alvo is None:
            return False
        self.fechados.append(alvo)
        self._avisar()
        return True

    def recuperar(self, identificador: str) -> bool:
        """Fechar não é apagar: o módulo volta inteiro, com os dados que tinha."""
        for indice, widget in enumerate(self.fechados):
            if widget.id != identificador:
                continue
            area, _ = self._encaixar(widget.area, componente(widget.componente))
            self.fechados.pop(indice)
            self._guardar(replace(widget, area=area or widget.area, minimizado=area is None))
            self._avisar()
            return True
        return False

    def maximizar(self, identificador: str) -> bool:
        alvo = self.widgets.get(identificador)
        if alvo is None:
            return False
        if alvo.maximizado:
            return self.restaurar_tamanho(identificador)
        self._guardar(
            replace(
                alvo,
                area_guardada=alvo.area,
                area=Area(coluna=0, linha=0, colunas=COLUNAS, linhas=LINHAS),
                maximizado=True,
                minimizado=False,
                foco=True,
            )
        )
        self._avisar()
        return True

    def colocar_em(self, identificador: str, area: Area) -> bool:
        """Põe o módulo exatamente nesta área, **a pedido do dono**, sem olhar colisão.

        É o caminho dos painéis que ele abre pela barra lateral: quem pediu foi ele, e o que
        estava na frente já foi minimizado. Guardar a área de antes é o que faz o botão de
        restaurar ter o que restaurar.
        """
        alvo = self.widgets.get(identificador)
        if alvo is None:
            return False
        self._guardar(
            replace(
                alvo,
                area_guardada=alvo.area_guardada or alvo.area,
                area=area,
                maximizado=True,
                minimizado=False,
                foco=True,
            )
        )
        self._avisar()
        return True

    def restaurar_tamanho(self, identificador: str) -> bool:
        alvo = self.widgets.get(identificador)
        if alvo is None or not alvo.maximizado:
            return False
        self._guardar(
            replace(
                alvo,
                area=alvo.area_guardada or alvo.area,
                area_guardada=None,
                maximizado=False,
            )
        )
        self._avisar()
        return True

    def minimizar_pelo_dono(self, identificador: str, minimizado: bool = True) -> bool:
        alvo = self.widgets.get(identificador)
        if alvo is None:
            return False
        self._guardar(replace(alvo, minimizado=minimizado))
        self._avisar()
        return True

    def confirmar(self, pendencia: str, sim: bool) -> Resultado | None:
        """O dono responde a uma pendência. "Não" some com ela; "sim" aplica a ação original."""
        acao = self.pendentes.pop(pendencia, None)
        if acao is None:
            return None
        if not sim:
            recusa = Resultado(aceita=False, acao=acao, motivo="o dono não autorizou")
            self.historico.append(recusa)
            self._avisar()
            return recusa
        resultado = self.aplicar(acao, confirmada=True)
        self._avisar()
        return resultado

    def guardar_layout(self, nome: str) -> None:
        self.instantaneos[nome] = (self.modo, tuple(self.widgets.values()))

    def estado_de(self, identificador: str, estado: EstadoDoWidget) -> bool:
        """Visto → em execução → resultado. É o laço quem conta, não a tela quem supõe."""
        alvo = self.widgets.get(identificador)
        if alvo is None:
            return False
        self._guardar(replace(alvo, estado=estado))
        self._avisar()
        return True

    # --- encanamento ----------------------------------------------------------------------
    def _guardar(self, widget: Widget) -> None:
        self.widgets[widget.id] = widget

    def _avisar(self) -> None:
        if self.ao_mudar is not None:
            self.ao_mudar()

    def _identificador(self, prefixo: str) -> str:
        self._proximo += 1
        return f"{prefixo}-{self._proximo}"

    def _livre(self, area: Area, *, ignorar: str = "") -> bool:
        if area.colide_com(self.nucleo):
            return False
        return not any(
            w.area.colide_com(area)
            for w in self.widgets.values()
            if w.id != ignorar and not w.minimizado
        )

    def _encaixar(
        self, area: Area, alvo: Componente, *, ignorar: str = ""
    ) -> tuple[Area | None, str]:
        """A área pedida, ou a primeira livre do mesmo tamanho. `None` quando não cabe nada.

        Quem se muda é sempre o **novo**: o módulo que o dono já estava lendo não sai do lugar
        porque uma proposta preferiu aquele canto.
        """
        if self._livre(area, ignorar=ignorar):
            return area, ""
        for linha in range(LINHAS - area.linhas + 1):
            for coluna in range(COLUNAS - area.colunas + 1):
                candidata = area.movida(coluna, linha)
                if self._livre(candidata, ignorar=ignorar):
                    return candidata, (
                        f"{alvo.titulo} foi para a coluna {coluna}, linha {linha}: o lugar "
                        "pedido estava ocupado"
                    )
        return None, ""

    def _recompor(self) -> int:
        """Depois de trocar de modo: quem colide com o núcleo novo se muda; quem não cabe,
        minimiza — e volta inteiro quando houver espaço."""
        mexidos = 0
        for widget in list(self.widgets.values()):
            if widget.minimizado or self._livre(widget.area, ignorar=widget.id):
                continue
            area, _ = self._encaixar(widget.area, componente(widget.componente), ignorar=widget.id)
            self._guardar(
                replace(widget, area=area) if area is not None else replace(widget, minimizado=True)
            )
            mexidos += 1
        return mexidos
