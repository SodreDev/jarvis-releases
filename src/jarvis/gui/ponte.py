"""A ponte entre o Python e o QML (ADR-0019): fina de propósito, e sem regra de negócio.

Tudo o que decide alguma coisa mora atrás desta classe — o laço de voz (`jarvis.voz.app`), o
gerente de workspace (`jarvis.gui.workspace`), o catálogo (`jarvis.gui.componentes`), o
chaveiro (`jarvis.gui.chaveiro`). A ponte só **publica estado** para o QML e **repassa**
cliques. É isso que deixa a tela ser trocada sem que nada do resto se mexa, e é isso que deixa
a lógica ser testada sem abrir janela.

Duas coisas importam na implementação, e as duas são sobre thread:

1. **nada pesado na thread da interface.** O laço roda na thread da `SessaoDeVoz`; o
   diagnóstico, o teste de microfone e o de voz rodam em threads próprias. O que chega de lá
   vira **sinal**, e o Qt entrega o sinal na thread da janela;
2. **o modelo de módulos preserva identidade.** Mover um módulo é `dataChanged` na linha dele,
   não refazer a lista — é o que permite ao QML animar a posição em vez de piscar.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    QTimer,
    Signal,
    Slot,
)

from jarvis.gui import chaveiro, recursos, sistema
from jarvis.gui.acoes import Acao, Area, Modo, Tipo
from jarvis.gui.componentes import CATALOGO
from jarvis.gui.controlador import Controlador, RoteiroDeDemonstracao
from jarvis.gui.nucleo import SessaoDeVoz
from jarvis.gui.workspace import Workspace
from jarvis.rede import ErroDeRede
from jarvis.ui.atalhos import AtalhoIndisponivel
from jarvis.ui.portal import AtalhoPortal, portal_disponivel
from jarvis.voz import aferir
from jarvis.voz.app import Aplicativo
from jarvis.voz.chaves import VARIAVEIS
from jarvis.voz.cli import diagnosticar
from jarvis.voz.config import Configuracao, caminho_padrao, escrever, ler, validar
from jarvis.voz.escuta import CombinacaoInvalida, Escuta, exigir_combinacao, modo_de
from jarvis.voz.estado import Estado
from jarvis.voz.interface import Onde
from jarvis.voz.modelos import ModeloRecusado, baixar, descarga_da_voz
from jarvis.voz.nuvem import ServicoRecusou
from jarvis.voz.palavra import PalavraInvalida, exigir_limiar
from jarvis.voz.provedores import provedores, vozes_da_elevenlabs
from jarvis.voz.registro import motor_registrado, motores_de
from jarvis.voz.s2_provisorio import nomes_de_gerador

PAPEIS: Final = ("asr", "tts")
AREA_DOS_PAINEIS: Final[dict[str, Area]] = {
    "configuracao": Area(coluna=1, linha=0, colunas=10, linhas=8),
    "diagnostico": Area(coluna=1, linha=0, colunas=10, linhas=7),
}
"""Onde cada painel do dono abre. O de provedores ocupa a altura toda desde que o provedor
escolhido abre o que se escolhe dentro dele (modelo, aviso, voz da conta) — e rola quando
nem assim cabe; o de diagnóstico é texto corrido do `--diagnostico`."""
MAXIMO_DE_LINHAS: Final = 400
COMPONENTE_DE_AVISOS: Final = "notificacoes"
PREFIXO_DA_RESPOSTA: Final = "Jarvis: "
PREFIXO_DO_DIGITADO: Final = "Você (digitado): "
"""Como o laço ecoa uma linha digitada no meio do laço de voz (`Aplicativo._turno_digitado`)."""
"""Como o laço escreve a resposta na tela — o mesmo prefixo do terminal."""
RENOVAR_O_CARD_A_CADA: Final = 30
"""Tiques de 1 s entre duas renovações do card: o "há 3 min" de cada aviso envelhece."""


class ModeloDeModulos(QAbstractListModel):
    """Os módulos na tela, como lista com papéis — um por campo que o QML desenha."""

    PAPEL_BASE: Final = int(Qt.ItemDataRole.UserRole) + 1
    CAMPOS: Final[tuple[str, ...]] = (
        "widgetId",
        "componente",
        "vista",
        "titulo",
        "coluna",
        "linha",
        "colunas",
        "linhas",
        "estado",
        "minimizado",
        "fixado",
        "foco",
        "maximizado",
        "demonstracao",
        "dados",
    )

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._linhas: list[dict[str, Any]] = []

    # --- API do Qt -----------------------------------------------------------------------
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex | None = None) -> int:
        _ = parent
        return len(self._linhas)

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.PAPEL_BASE + indice: QByteArray(campo.encode())
            for indice, campo in enumerate(self.CAMPOS)
        }

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._linhas):
            return None
        campo = self.CAMPOS[role - self.PAPEL_BASE] if role >= self.PAPEL_BASE else ""
        return self._linhas[index.row()].get(campo)

    # --- sincronização -------------------------------------------------------------------
    def sincronizar(self, modulos: Sequence[Mapping[str, Any]]) -> None:
        """Casa a lista nova com a que está na tela, mexendo só no que mudou.

        Refazer a lista inteira seria mais simples e destruiria a animação: o QML recriaria
        cada delegate, e um módulo que apenas se moveu apareceria piscando no lugar novo.
        """
        novos = {str(modulo["id"]): dict(modulo) for modulo in modulos}
        for posicao in range(len(self._linhas) - 1, -1, -1):
            if self._linhas[posicao]["widgetId"] not in novos:
                self.beginRemoveRows(QModelIndex(), posicao, posicao)
                self._linhas.pop(posicao)
                self.endRemoveRows()
        presentes = {linha["widgetId"] for linha in self._linhas}
        for identificador, modulo in novos.items():
            if identificador in presentes:
                continue
            posicao = len(self._linhas)
            self.beginInsertRows(QModelIndex(), posicao, posicao)
            self._linhas.append(self._linha(modulo))
            self.endInsertRows()
        for posicao, linha in enumerate(self._linhas):
            atualizada = self._linha(novos[linha["widgetId"]])
            if atualizada != linha:
                self._linhas[posicao] = atualizada
                indice = self.index(posicao, 0)
                self.dataChanged.emit(indice, indice)

    def _linha(self, modulo: Mapping[str, Any]) -> dict[str, Any]:
        catalogo = CATALOGO.get(str(modulo["componente"]))
        return {
            "widgetId": str(modulo["id"]),
            "componente": str(modulo["componente"]),
            "vista": str(catalogo.vista) if catalogo else "texto",
            "titulo": str(modulo["titulo"]),
            "coluna": int(modulo["coluna"]),
            "linha": int(modulo["linha"]),
            "colunas": int(modulo["colunas"]),
            "linhas": int(modulo["linhas"]),
            "estado": str(modulo["estado"]),
            "minimizado": bool(modulo["minimizado"]),
            "fixado": bool(modulo["fixado"]),
            "foco": bool(modulo["foco"]),
            "maximizado": bool(modulo["maximizado"]),
            "demonstracao": bool(modulo["demonstracao"]),
            "dados": dict(modulo["dados"]),
        }


class Ponte(QObject):
    """O objeto que o QML enxerga. Sem lógica própria: estado para fora, clique para dentro."""

    mudou = Signal()
    """Qualquer mudança de estado publicado. O QML liga as propriedades nele."""
    linhaNova = Signal(str, str)
    conversaMudou = Signal()
    diagnosticoMudou = Signal()
    vozesMudaram = Signal()
    escutaMudou = Signal()
    dedoGlobal = Signal(bool)
    avisosMudaram = Signal()
    respostaParcial = Signal(str)
    """O texto acumulado da resposta em curso, vindo do laço a cada pedaço (ADR-0025)."""
    """A fila de avisos do laço mudou: o card é renovado na thread da janela."""
    """Apertar/soltar do atalho global. Vem da thread do portal; o Qt entrega na da janela."""

    def __init__(
        self,
        *,
        raiz: Path,
        configuracao: Configuracao | None = None,
        caminho_da_configuracao: Path | None = None,
        controlador: Controlador | None = None,
        ambiente: Mapping[str, str] | None = None,
        aplicativo: Aplicativo | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._raiz = raiz
        self._caminho = caminho_da_configuracao or caminho_padrao()
        self._configuracao = configuracao or ler(self._caminho)
        self._controlador = controlador or RoteiroDeDemonstracao()
        self._ambiente_base = dict(ambiente) if ambiente is not None else None
        self._aplicativo = aplicativo
        """Um laço já montado (teste, medição). `None` monta um na hora de conversar."""
        self._espaco = Workspace()
        self._espaco.ao_mudar = self._publicar
        # O modo de escuta vivo (ADR-0021): o mesmo objeto para o laço, para o gerente (que
        # julga o `definirModoDeEscuta` do modelo) e para a tela.
        self._escuta = Escuta.de(
            self._configuracao.escuta,
            palavra=self._configuracao.palavra,
            limiar=self._configuracao.limiar_palavra,
            atalho=self._configuracao.atalho,
        )
        self._escuta.ao_mudar = self._escuta_mudou
        self._espaco.escuta = self._escuta
        self._espaco.asr_na_nuvem = self._asr_na_nuvem
        self._portal: AtalhoPortal | None = None
        self._portal_ok, self._portal_frase = portal_disponivel(ambiente=self._ambiente_base)
        self.dedoGlobal.connect(self._aplicar_dedo)
        self.avisosMudaram.connect(self._ligar_card_de_avisos)
        self.respostaParcial.connect(self._guardar_parcial)
        self._tiques = 0
        self._modelo = ModeloDeModulos(self)
        self._sessao: SessaoDeVoz | None = None
        self._estado = Estado.PARADO
        self._transcricao: list[dict[str, str]] = []
        self._diagnostico = ""
        self._nivel = 0.0
        self._aviso = ""
        self._consulta = ""
        self._relogio = ""
        self._medidas: list[dict[str, Any]] = []
        self._historico_visto = 0
        """Quantos resultados do gerente já eram da composição do modo: o que o roteiro monta
        ao trocar de modo não é novidade para o dono, e não vira frase na tela."""
        self._vozes: list[dict[str, Any]] = []
        self._vozes_frase = ""
        self._tique = QTimer(self)
        self._tique.setInterval(1000)
        self._tique.timeout.connect(self._bater_o_relogio)
        self._tique.start()
        self._bater_o_relogio()
        self.linhaNova.connect(self._guardar_linha)
        self.demonstrar(str(Modo.ASSISTENTE))

    # --- o que o QML lê -------------------------------------------------------------------
    @Property(QObject, constant=True)
    def modulos(self) -> ModeloDeModulos:
        return self._modelo

    @Property(str, notify=mudou)
    def modo(self) -> str:
        return str(self._espaco.modo)

    @Property(str, notify=mudou)
    def modoFrase(self) -> str:
        return self._espaco.modo.frase

    @Property(dict, notify=mudou)
    def nucleo(self) -> dict[str, int]:
        return self._espaco.nucleo.para_dict()

    @Property(str, notify=conversaMudou)
    def estado(self) -> str:
        return str(self._estado)

    @Property(str, notify=conversaMudou)
    def estadoFrase(self) -> str:
        return self._estado.frase

    @Property(bool, notify=conversaMudou)
    def processando(self) -> bool:
        """Os anéis giram só aqui: pensando ou falando. Fora disso, a tela fica parada."""
        return self._estado in {Estado.PENSANDO, Estado.FALANDO}

    @Property(bool, notify=conversaMudou)
    def conversaViva(self) -> bool:
        return self._sessao is not None and self._sessao.viva

    @Property(list, notify=conversaMudou)
    def transcricao(self) -> list[dict[str, str]]:
        return self._transcricao[-MAXIMO_DE_LINHAS:]

    @Property(dict, notify=conversaMudou)
    def microfone(self) -> dict[str, Any]:
        """A fonte como ela **está** (F1-13) e, ao lado, **quando** o que ela ouve vira pedido.

        As duas coisas vêm de quem as sabe: `aberta` do arquivo que o laço escreve, o modo do
        estado vivo da escuta. "Microfone aberto" sozinho não diz ao dono se o Jarvis está
        esperando o nome dele ou transformando tudo em pedido — e é isso que ele cobrou.
        """
        estado = self._sessao.estado_do_microfone() if self._sessao else None
        aberta = bool(estado and estado.aberta)
        return {
            "aberta": aberta,
            "modo": str(self._escuta.modo),
            "modoFrase": self._escuta.modo.frase,
            "escuta": self._escuta.frase(time.monotonic_ns()),
            "armado": self._escuta.armado(time.monotonic_ns()),
            "amostras": int(estado.amostras) if estado else 0,
            "frase": (
                "microfone aberto"
                if aberta
                else (
                    estado.indisponivel if estado and estado.indisponivel else "microfone fechado"
                )
            ),
        }

    @Property(str, notify=mudou)
    def relogio(self) -> str:
        return self._relogio

    @Property(str, notify=mudou)
    def data(self) -> str:
        agora = datetime.now()
        dias = ("SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM")
        meses = (
            "JAN",
            "FEV",
            "MAR",
            "ABR",
            "MAI",
            "JUN",
            "JUL",
            "AGO",
            "SET",
            "OUT",
            "NOV",
            "DEZ",
        )
        return f"{dias[agora.weekday()]}, {agora.day:02d} {meses[agora.month - 1]} {agora.year}"

    @Property(list, notify=mudou)
    def medidas(self) -> list[dict[str, Any]]:
        return self._medidas

    def pendencias_abertas(self) -> list[dict[str, str]]:
        """As confirmações esperando o dono. Método normal, para quem não é QML (a captura)."""
        return [dict(p) for p in self._espaco.para_dict()["pendentes"]]

    @Property(list, notify=mudou)
    def pendentes(self) -> list[dict[str, str]]:
        return self.pendencias_abertas()

    @Property(list, notify=mudou)
    def fechados(self) -> list[dict[str, str]]:
        return [dict(f) for f in self._espaco.para_dict()["fechados"]]

    @Property(list, notify=mudou)
    def historico(self) -> list[str]:
        """O rastro **técnico** (`createWidget: feito`): serve a log e a teste, não à tela."""
        return [resultado.frase() for resultado in self._espaco.historico[-12:]]

    @Property(str, notify=mudou)
    def ultimaMudanca(self) -> str:
        """A última coisa que aconteceu na tela, **em português**, ou vazio.

        É o que a janela mostra — discreto, e some sozinho. Nome de ação interna na cara do
        dono é informação de quem escreveu o código, não de quem está usando o Jarvis.
        """
        for resultado in reversed(self._espaco.historico[self._historico_visto :]):
            frase = resultado.frase_do_dono()
            if frase:
                return frase
        return ""

    @Property(str, notify=mudou)
    def aviso(self) -> str:
        return self._aviso

    @Property(str, notify=mudou)
    def consulta(self) -> str:
        """O que está sendo pesquisado — é o que a faixa do modo de pesquisa mostra."""
        return self._consulta

    # --- configuração e chaves ------------------------------------------------------------
    @Property(dict, notify=mudou)
    def configuracao(self) -> dict[str, Any]:
        dados = self._configuracao.para_dict()
        dados["caminho"] = str(self._caminho)
        return dados

    @Property(list, notify=mudou)
    def motores(self) -> list[dict[str, Any]]:
        escolhidos = {"asr": self._configuracao.asr, "tts": self._configuracao.tts}
        return [
            {
                "id": motor.id,
                "papel": motor.papel,
                "onde": "nuvem" if motor.onde is Onde.NUVEM else "local",
                "ligado": motor.id in self._configuracao.nuvem_ligada,
                "escolhido": escolhidos.get(motor.papel) == motor.id,
                "aviso": motor.frase_de_aviso,
            }
            for papel in PAPEIS
            for motor in motores_de(papel)
        ]

    def estado_da_escuta(self) -> dict[str, Any]:
        """Modo, palavra, limiar, atalho e se ele é global — tudo do estado vivo. Método
        normal, para quem não é QML (a captura, o teste)."""
        dados = self._escuta.para_dict(time.monotonic_ns())
        dados["asrNaNuvem"] = self._asr_na_nuvem()
        return dados

    @Property(dict, notify=escutaMudou)
    def escuta(self) -> dict[str, Any]:
        return self.estado_da_escuta()

    @Property(bool, notify=escutaMudou)
    def portalDisponivel(self) -> bool:
        return self._portal_ok

    @Property(str, notify=escutaMudou)
    def portalFrase(self) -> str:
        return self._portal_frase

    @Property(int, notify=escutaMudou)
    def atalhoTecla(self) -> int:
        """A tecla da combinação, como `Qt.Key` — a janela compara no `Keys.onPressed`. 0 =
        barra de espaço (o padrão de antes)."""
        return self._combinacao()[0]

    @Property(int, notify=escutaMudou)
    def atalhoModificadores(self) -> int:
        return self._combinacao()[1]

    @Property(list, notify=mudou)
    def provedoresAsr(self) -> list[dict[str, Any]]:
        """Quem ouve, por provedor — com os modelos de cada um (`jarvis.voz.provedores`)."""
        return [p.para_dict() for p in provedores(self._configuracao, "asr")]

    @Property(list, notify=mudou)
    def provedoresTts(self) -> list[dict[str, Any]]:
        return [p.para_dict() for p in provedores(self._configuracao, "tts")]

    @Property(list, notify=vozesMudaram)
    def vozesDaConta(self) -> list[dict[str, Any]]:
        """As vozes que a conta da ElevenLabs enxerga, depois que o dono pediu a lista."""
        return self._vozes

    @Property(str, notify=vozesMudaram)
    def vozesFrase(self) -> str:
        return self._vozes_frase

    @Property(list, notify=mudou)
    def geradores(self) -> list[str]:
        return list(nomes_de_gerador())

    @Property(list, notify=mudou)
    def chaves(self) -> list[dict[str, str]]:
        """Só "de onde vem" — o valor não é lido nem para montar esta lista."""
        return [
            {
                "variavel": variavel,
                "estado": chaveiro.fonte_da_chave(variavel, ambiente=self._ambiente_base).frase,
            }
            for variavel in VARIAVEIS
        ]

    @Property(str, notify=mudou)
    def chaveiroFrase(self) -> str:
        return chaveiro.disponivel()[1]

    @Property(str, notify=diagnosticoMudou)
    def diagnostico(self) -> str:
        return self._diagnostico

    @Property(float, notify=diagnosticoMudou)
    def nivel(self) -> float:
        return self._nivel

    @Property(str, notify=diagnosticoMudou)
    def vozFaltando(self) -> str:
        """A frase do que falta baixar, ou vazio. O peso não vem no pacote (ADR-0020)."""
        descarga = descarga_da_voz(self._configuracao.voz)
        if descarga is None or descarga.completa:
            return ""
        return descarga.frase()

    # --- o que o QML manda fazer ------------------------------------------------------------
    @Slot(str)
    def encenar_estado(self, estado: str) -> None:
        """Põe o núcleo num estado **para o retrato** (`--capturar`), sem laço nenhum rodando.

        Existe por um motivo só: o dono precisa ver como fica o núcleo **pensando** e
        **falando** sem ter um microfone na frente. Fora da captura ninguém chama isto — quem
        muda o estado de verdade é o laço, e é por isso que o nome diz "encenar".
        """
        self._mudar_estado(Estado(estado))

    @Slot(str)
    def demonstrar(self, modo: str) -> None:
        """Pede ao controlador as propostas deste modo e passa cada uma pelo gerente."""
        alvo = Modo(modo)
        for identificador in list(self._espaco.widgets):
            self._espaco.fechar_pelo_dono(identificador)
        self._espaco.fechados.clear()
        self._espaco.pendentes.clear()
        propostas = self._controlador.propor(alvo)
        self._consulta = next(
            (str(p.get("motivo", "")) for p in propostas if p.get("tipo") == "setWorkspaceMode"),
            "",
        )
        for bruta in propostas:
            self._espaco.propor(bruta)
        self._ligar_card_de_avisos()
        self._historico_visto = len(self._espaco.historico)
        self._publicar()

    @Slot(str)
    def definirModo(self, modo: str) -> None:
        self.demonstrar(modo)

    @Slot(str)
    def abrirPainel(self, componente: str) -> None:
        """Provedores e diagnóstico são **módulos do workspace**, não abas de formulário.

        Entram pelo mesmo caminho de qualquer outro módulo — proposta, validação, encaixe —,
        então valem para eles as mesmas regras: o dono move, fixa, maximiza e fecha.
        """
        for identificador, widget in self._espaco.widgets.items():
            if widget.componente == componente:
                if not widget.maximizado:
                    self._espaco.maximizar(identificador)
                self._publicar()
                return
        dados: dict[str, Any] = {}
        if componente == "diagnostico":
            dados["licenca"] = recursos.frase_de_licenca()
        # O layout de antes é guardado para o dono poder voltar, e o que está na tela é
        # **minimizado**, não fechado: painel do dono tem precedência, sem destruir nada.
        self._espaco.guardar_layout("antes-do-painel")
        for identificador in list(self._espaco.widgets):
            self._espaco.minimizar_pelo_dono(identificador)
        resultado = self._espaco.propor(
            {
                "tipo": "createWidget",
                "componente": componente,
                "motivo": "o dono abriu pela barra lateral",
                "dados": dados,
            }
        )
        if resultado.widget:
            # Grande, mas **do tamanho do conteúdo**: um painel esticado até o rodapé deixa
            # dois terços de moldura vazia, que é o oposto de "espaço livre de propósito".
            self._espaco.colocar_em(resultado.widget, AREA_DOS_PAINEIS[componente])
        # Quem abriu foi o dono, pela barra lateral: dizer a ele que abriu não acrescenta nada.
        self._historico_visto = len(self._espaco.historico)
        self._publicar()

    @Slot()
    def iniciarConversa(self) -> None:
        if self._sessao is not None and self._sessao.viva:
            return
        self._sessao = SessaoDeVoz(
            configuracao=self._configuracao,
            raiz=self._raiz,
            ambiente=chaveiro.ambiente_com_chaves(self._ambiente_base),
            ao_linha=lambda linha: self.linhaNova.emit("jarvis", linha),
            ao_estado=self._mudar_estado,
            ao_terminar=self._fim_da_conversa,
            ao_mudar_avisos=self.avisosMudaram.emit,
            ao_pedaco=self.respostaParcial.emit,
            escuta=self._escuta,
        )
        self._sessao.iniciar(self._aplicativo)
        self.conversaMudou.emit()

    @Slot()
    def pararConversa(self) -> None:
        if self._sessao is not None:
            self._sessao.parar()
        self.conversaMudou.emit()

    @Slot()
    def segurar(self) -> None:
        if self._sessao is not None:
            self._sessao.segurar()

    @Slot()
    def soltar(self) -> None:
        if self._sessao is not None:
            self._sessao.soltar()

    @Slot()
    def interromper(self) -> None:
        if self._sessao is not None:
            self._sessao.interromper()

    @Slot(str)
    def enviarTexto(self, texto: str) -> None:
        linha = texto.strip()
        if not linha:
            return
        self.linhaNova.emit("dono", linha)
        if self._sessao is None or not self._sessao.viva:
            self.iniciarConversa()
        assert self._sessao is not None
        self._sessao.digitar(linha)

    @Slot(str)
    def fecharModulo(self, identificador: str) -> None:
        self._espaco.fechar_pelo_dono(identificador)

    @Slot(str, bool)
    def fixarModulo(self, identificador: str, fixado: bool) -> None:
        self._espaco.fixar(identificador, fixado)
        self._publicar()

    @Slot(str)
    def maximizarModulo(self, identificador: str) -> None:
        self._espaco.maximizar(identificador)

    @Slot(str, int, int)
    def moverModulo(self, identificador: str, coluna: int, linha: int) -> None:
        self._espaco.mover_pelo_dono(identificador, coluna, linha)

    @Slot(str)
    def recuperarModulo(self, identificador: str) -> None:
        self._espaco.recuperar(identificador)

    @Slot(str, bool)
    def responderPendencia(self, pendencia: str, sim: bool) -> None:
        self._espaco.confirmar(pendencia, sim)
        self._publicar()

    @Slot(str, str)
    def escolherMotor(self, papel: str, identificador: str) -> None:
        self._configuracao = self._configuracao.com(**{papel: identificador})
        self._publicar()

    @Slot(str, str)
    def escolherProvedor(self, papel: str, chave: str) -> None:
        """Escolher o provedor escolhe o motor vigente dele — e não liga nuvem nenhuma."""
        for provedor in provedores(self._configuracao, papel):
            if provedor.chave == chave:
                self.escolherMotor(papel, provedor.motor)
                return

    @Slot()
    def buscarVozes(self) -> None:
        """Lista as vozes da conta da ElevenLabs, numa thread (é rede).

        A chave vem pelo mesmo caminho do laço — o ambiente mais o chaveiro, em memória — e
        não volta para a tela: o que volta é id, nome, categoria e idioma de cada voz.
        """
        self._vozes_frase = "consultando a ElevenLabs…"
        self.vozesMudaram.emit()

        def trabalhar() -> None:
            try:
                achadas = vozes_da_elevenlabs(chaveiro.ambiente_com_chaves(self._ambiente_base))
            except (chaveiro.SegredoAusente, ServicoRecusou, ErroDeRede) as erro:
                self._vozes_frase = f"não deu para listar: {erro}"
            else:
                self._vozes = achadas
                em_pt = sum(1 for voz in achadas if voz["portugues"])
                self._vozes_frase = (
                    f"{len(achadas)} voz(es) na conta, {em_pt} com português declarado"
                )
            self.vozesMudaram.emit()

        threading.Thread(target=trabalhar, name="jarvis-vozes", daemon=True).start()

    @Slot(str, bool)
    def ligarNuvem(self, identificador: str, ligado: bool) -> None:
        """Ligar nuvem é escolha do dono, e a tela mostra o aviso antes de chamar isto."""
        atuais = [m for m in self._configuracao.nuvem_ligada if m != identificador]
        if ligado:
            atuais.append(identificador)
        self._configuracao = self._configuracao.com(nuvem_ligada=tuple(atuais))
        self._publicar()

    @Slot(str, str)
    def definirCampo(self, campo: str, valor: str) -> None:
        if campo in self._configuracao.para_dict():
            self._configuracao = self._configuracao.com(**{campo: valor})
            self._publicar()

    # --- modos de ativação (ADR-0021) -----------------------------------------------------
    @Slot(str)
    def definirEscuta(self, modo: str) -> None:
        """O dono troca o modo. Escolha dele, com o dedo: não passa pela política do modelo,
        e vale no próximo tique do laço, com a conversa aberta ou não."""
        try:
            alvo = modo_de(modo)
        except ValueError as erro:
            self._aviso = str(erro)
        else:
            self._escuta.trocar(alvo)
            self._configuracao = self._configuracao.com(escuta=alvo.value)
        self._publicar()

    @Slot(str, str)
    def definirPalavra(self, palavra: str, limiar: str) -> None:
        try:
            valor = (
                exigir_limiar(float(limiar.replace(",", ".")))
                if limiar.strip()
                else self._escuta.detector.limiar
            )
            self._escuta.trocar_palavra(palavra or self._escuta.detector.palavra, valor)
        except (PalavraInvalida, ValueError) as erro:
            self._aviso = f"palavra recusada: {erro}"
        else:
            detector = self._escuta.detector
            self._configuracao = self._configuracao.com(
                palavra=detector.palavra, limiar_palavra=detector.limiar
            )
            self._aviso = (
                f"palavra de ativação: “{detector.palavra}” (limiar {detector.limiar:.2f})"
            )
        self._publicar()

    @Slot(int, int)
    def capturarAtalho(self, tecla: int, modificadores: int) -> None:
        """A combinação apertada na janela vira texto do Qt e passa pela mesma validação."""
        from PySide6.QtGui import QKeySequence

        sequencia = QKeySequence(int(modificadores) | int(tecla))
        bruto = sequencia.toString(QKeySequence.SequenceFormat.PortableText)
        try:
            atalho = exigir_combinacao(bruto)
        except CombinacaoInvalida as erro:
            self._aviso = f"atalho recusado: {erro}"
            self._publicar()
            return
        self._trocar_atalho(atalho)

    @Slot()
    def limparAtalho(self) -> None:
        self._trocar_atalho("")

    @Slot()
    def ativarAtalhoGlobal(self) -> None:
        """Pede ao sistema o atalho global. **Abre um diálogo do compositor** — por isso só
        roda no clique do dono, nunca sozinho, e numa thread (o diálogo espera por ele)."""
        if self._portal is not None:
            self._portal.fechar()
            self._portal = None
        combinacao = self._escuta.atalho or "Ctrl+Space"
        self._portal_frase = "pedindo o atalho ao sistema — responda ao diálogo dele…"
        self.escutaMudou.emit()

        def trabalhar() -> None:
            portal = AtalhoPortal(
                combinacao=combinacao, ambiente=self._ambiente_base, ao_mudar=self.dedoGlobal.emit
            )
            try:
                portal.abrir()
            except AtalhoIndisponivel as erro:
                self._portal_frase = f"sem atalho global ({erro}): vale só com a janela em foco"
                self._escuta.trocar_atalho(self._escuta.atalho, global_=False)
            else:
                self._portal = portal
                self._portal_frase = f"atalho global ligado pelo sistema: {portal.gatilho}"
                self._escuta.trocar_atalho(combinacao, global_=True)
            self.escutaMudou.emit()

        threading.Thread(target=trabalhar, name="jarvis-portal-ligar", daemon=True).start()

    @Slot(result=str)
    def salvarConfiguracao(self) -> str:
        try:
            escrever(validar(self._configuracao), self._caminho)
        except (ValueError, OSError) as erro:
            self._aviso = f"não deu para salvar: {erro}"
        else:
            self._aviso = f"configuração salva em {self._caminho}"
        self._publicar()
        return self._aviso

    @Slot(str, str, result=str)
    def guardarChave(self, variavel: str, valor: str) -> str:
        """Guarda no chaveiro do sistema. O valor não volta para a tela nem para o log."""
        try:
            chaveiro.guardar(variavel, valor)
        except (chaveiro.ChaveiroIndisponivel, chaveiro.SegredoAusente) as erro:
            self._aviso = str(erro)
        else:
            self._aviso = f"{variavel} guardada no chaveiro do sistema"
        self._publicar()
        return self._aviso

    @Slot(str)
    def esquecerChave(self, variavel: str) -> None:
        try:
            chaveiro.esquecer(variavel)
            self._aviso = f"{variavel} apagada do chaveiro"
        except chaveiro.ChaveiroIndisponivel as erro:
            self._aviso = str(erro)
        self._publicar()

    @Slot()
    def rodarDiagnostico(self) -> None:
        def trabalhar() -> None:
            linhas: list[str] = []
            diagnosticar(linhas.append, caminho=self._caminho, ambiente=self._ambiente_base)
            self._diagnostico = "\n".join(linhas)
            self.diagnosticoMudou.emit()

        threading.Thread(target=trabalhar, name="jarvis-diagnostico", daemon=True).start()

    @Slot()
    def testarMicrofone(self) -> None:
        def trabalhar() -> None:
            def ao_quadro(db: float) -> None:
                self._nivel = min(max((db + 60.0) / 60.0, 0.0), 1.0)
                self.diagnosticoMudou.emit()

            nivel = aferir.medir_microfone(
                self._configuracao, ambiente=self._ambiente_base, ao_quadro=ao_quadro
            )
            self._nivel = 0.0
            self._diagnostico = f"teste de microfone: {nivel.frase()}\n\n{self._diagnostico}"
            self.diagnosticoMudou.emit()

        threading.Thread(target=trabalhar, name="jarvis-microfone", daemon=True).start()

    @Slot()
    def baixarVoz(self) -> None:
        """Baixa a voz local, com o tamanho dito antes e o sha256 conferido depois."""

        def trabalhar() -> None:
            descarga = descarga_da_voz(self._configuracao.voz)
            if descarga is None:
                self._diagnostico = f"a voz {self._configuracao.voz!r} não está no registro"
                self.diagnosticoMudou.emit()
                return

            def progresso(nome: str, lidos: int, total: int) -> None:
                self._nivel = lidos / total if total else 1.0
                self.diagnosticoMudou.emit()

            try:
                escritos = baixar(descarga, ao_progresso=progresso)
            except (ModeloRecusado, ErroDeRede) as erro:
                self._diagnostico = f"não deu para baixar a voz: {erro}\n\n{self._diagnostico}"
            else:
                self._diagnostico = (
                    f"voz baixada e conferida: {', '.join(c.name for c in escritos)}"
                    f"\n\n{self._diagnostico}"
                )
            self._nivel = 0.0
            self.diagnosticoMudou.emit()

        threading.Thread(target=trabalhar, name="jarvis-baixar-voz", daemon=True).start()

    @Slot()
    def testarVoz(self) -> None:
        def trabalhar() -> None:
            prova = aferir.provar_voz(
                self._configuracao, raiz=self._raiz, ambiente=self._ambiente_base
            )
            self._diagnostico = f"teste de voz: {prova.frase()}\n\n{self._diagnostico}"
            self.diagnosticoMudou.emit()

        threading.Thread(target=trabalhar, name="jarvis-voz-teste", daemon=True).start()

    # --- encanamento -----------------------------------------------------------------------
    def _trocar_atalho(self, atalho: str) -> None:
        # Combinação nova invalida o registro no sistema: o que estava ligado era a outra.
        if self._portal is not None:
            self._portal.fechar()
            self._portal = None
        self._escuta.trocar_atalho(atalho, global_=False)
        self._configuracao = self._configuracao.com(atalho=atalho)
        self._aviso = f"atalho: {atalho or 'barra de espaço'}"
        self._publicar()

    def _combinacao(self) -> tuple[int, int]:
        if not self._escuta.atalho:
            return 0, 0
        from PySide6.QtGui import QKeySequence

        sequencia = QKeySequence(self._escuta.atalho, QKeySequence.SequenceFormat.PortableText)
        if sequencia.isEmpty():
            return 0, 0
        combinacao = sequencia[0]  # type: ignore[index]  # o stub não declara, o Qt tem
        return int(combinacao.key().value), int(combinacao.keyboardModifiers().value)

    def _asr_na_nuvem(self) -> bool:
        motor = motor_registrado(self._configuracao.asr)
        return motor is not None and motor.onde is Onde.NUVEM

    def _escuta_mudou(self) -> None:
        """Chamada de qualquer thread (o laço arma e desarma): só emite sinal."""
        self.escutaMudou.emit()
        self.conversaMudou.emit()

    def _aplicar_dedo(self, apertado: bool) -> None:
        if not apertado:
            self.soltar()
            return
        if self._sessao is None or not self._sessao.viva:
            self.iniciarConversa()
        self.segurar()

    def _mudar_estado(self, estado: Estado) -> None:
        self._estado = estado
        self.conversaMudou.emit()

    def _fim_da_conversa(self, erro: str) -> None:
        if erro:
            self.linhaNova.emit("jarvis", f"a conversa parou: {erro}")
        self._estado = Estado.PARADO
        self.conversaMudou.emit()

    def _guardar_linha(self, quem: str, texto: str) -> None:
        if not texto.strip():
            return
        digitado = texto.removeprefix(PREFIXO_DO_DIGITADO)
        if (
            digitado != texto
            and self._transcricao
            and self._transcricao[-1] == {"quem": "dono", "texto": digitado}
        ):
            return  # o eco do laço repete a linha que a janela já pôs: a mesma fala, uma vez
        parcial = self._parcial_em_curso()
        if quem == "jarvis" and texto.startswith(PREFIXO_DA_RESPOSTA) and parcial is not None:
            # A linha final do turno substitui a que veio crescendo em stream: a mesma resposta
            # não aparece duas vezes na conversa.
            self._transcricao[parcial] = {"quem": quem, "texto": texto}
        else:
            self._transcricao.append({"quem": quem, "texto": texto})
        del self._transcricao[:-MAXIMO_DE_LINHAS]
        self.conversaMudou.emit()

    def _guardar_parcial(self, acumulado: str) -> None:
        """Um pedaço novo da resposta: a linha do Jarvis cresce no lugar, enquanto ele gera."""
        linha = {"quem": "jarvis", "texto": f"{PREFIXO_DA_RESPOSTA}{acumulado}", "parcial": "1"}
        parcial = self._parcial_em_curso()
        if parcial is None:
            self._transcricao.append(linha)
        else:
            self._transcricao[parcial] = linha
        del self._transcricao[:-MAXIMO_DE_LINHAS]
        self.conversaMudou.emit()

    def _parcial_em_curso(self) -> int | None:
        """A linha parcial do turno corrente, se houver — perto do fim, porque a interrupção e
        o resumo do turno podem ter entrado depois dela."""
        for indice in range(len(self._transcricao) - 1, max(-1, len(self._transcricao) - 5), -1):
            if self._transcricao[indice].get("parcial"):
                return indice
        return None

    def _bater_o_relogio(self) -> None:
        self._relogio = datetime.now().strftime("%H:%M")
        self._medidas = sistema.medidas()
        self._tiques += 1
        if self._tiques % RENOVAR_O_CARD_A_CADA == 0:
            self._ligar_card_de_avisos()
        self.mudou.emit()

    def _ligar_card_de_avisos(self) -> None:
        """Os dados reais da fila do laço em todo card `notificacoes`, pelo `updateWidget`.

        Quem diz que os dados são reais é este código, que lê a fila — por isso o selo de
        demonstração sai aqui e nunca por proposta da IA (ADR-0019, emenda de 2026-10-17).
        Antes de haver laço, a fila é vazia, e vazio é real: o card diz o que vai aparecer.
        """
        dados = self._sessao.dados_dos_avisos() if self._sessao else {"avisos": []}
        visto = len(self._espaco.historico) == self._historico_visto
        for identificador, widget in list(self._espaco.widgets.items()):
            if widget.componente == COMPONENTE_DE_AVISOS:
                self._espaco.aplicar(
                    Acao(tipo=Tipo.ATUALIZAR, widget=identificador, dados=dados),
                    dados_reais=True,
                )
        if visto:
            # Renovar o card não é novidade para o dono: não vira frase na tela.
            self._historico_visto = len(self._espaco.historico)

    def _publicar(self) -> None:
        self._modelo.sincronizar(self._espaco.para_dict()["widgets"])
        self.mudou.emit()
