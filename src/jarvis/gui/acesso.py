"""A tela de acesso (pastas, aplicativos, navegadores) — a ponta Qt de `jarvis.voz.acesso`.

Fina como a ponte (ADR-0019): lê a configuração viva, chama uma função pura de
`jarvis.voz.acesso`, **grava o arquivo na hora** e avisa o laço, que recarrega o alcance sem
reiniciar. Gravar na hora é de propósito: marcar um aplicativo e ter de lembrar de outro botão
para valer era a tela que o dono não conseguia usar (2026-10-17). A frase de estado diz o que
aconteceu — salvo, recusado e por quê.

Os diálogos de pasta e de arquivo são do QML (`QtQuick.Dialogs`, que no KDE vira o seletor nativo
do sistema pelo portal); o que eles escolhem chega aqui como `file:///…` ou como caminho.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from jarvis.voz import acesso
from jarvis.voz.acesso import (
    PASTAS_DE_APLICATIVOS,
    AcessoRecusado,
    App,
    Navegador,
    app_de_caminho,
    detectar,
    listar_apps,
    nome_de_app,
    separar,
)
from jarvis.voz.config import Configuracao


def _caminho_local(texto: str) -> str:
    """Do que o diálogo entrega (`file:///home/x/Pasta`) ou o dono digitou, um caminho."""
    if texto.startswith("file:"):
        return QUrl(texto).toLocalFile()
    return texto


class PonteDeAcesso(QObject):
    """O que o QML lê (`raizes`, `aplicativos`, `navegadores`) e o que ele pede (os slots)."""

    mudou = Signal()

    def __init__(
        self,
        *,
        obter: Callable[[], Configuracao],
        gravar: Callable[[Configuracao], str],
        lar: Path | None = None,
        pastas_de_apps: tuple[str, ...] = PASTAS_DE_APLICATIVOS,
        caminho_dos_binarios: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._obter = obter
        self._gravar = gravar
        self._lar = lar or Path.home()
        self._pastas_de_apps = pastas_de_apps
        self._caminho_dos_binarios = caminho_dos_binarios
        self._frase = ""
        self._apps: tuple[App, ...] | None = None
        self._navegadores: tuple[Navegador, ...] | None = None

    # --- o que a tela lê -----------------------------------------------------------------
    @Property(str, notify=mudou)
    def frase(self) -> str:
        return self._frase

    @Property(str, notify=mudou)
    def modo(self) -> str:
        return self._obter().acesso

    @Property(list, notify=mudou)
    def modos(self) -> list[dict[str, Any]]:
        atual = self._obter().acesso
        return [
            {"id": id_, "nome": nome, "frase": frase, "ativo": id_ == atual}
            for id_, (nome, frase) in acesso.FRASE_DOS_MODOS.items()
        ]

    @Property(bool, notify=mudou)
    def raizesValem(self) -> bool:
        return self._obter().acesso in acesso.MODOS_QUE_USAM_AS_RAIZES

    @Property(list, notify=mudou)
    def raizes(self) -> list[dict[str, Any]]:
        configuracao = self._obter()
        return [
            {
                "caminho": caminho,
                "nome": Path(caminho).name or caminho,
                "nivel": acesso.nivel_da_raiz(configuracao, caminho),
                "existe": Path(caminho).expanduser().is_dir(),
            }
            for caminho in configuracao.raizes
        ]

    @Property(list, constant=True)
    def negadas(self) -> list[str]:
        return list(acesso.negacoes_fixas())

    def _instalados(self) -> tuple[App, ...]:
        if self._apps is None:
            self._apps = listar_apps(pastas=self._pastas_de_apps)
        return self._apps

    @Property(list, notify=mudou)
    def aplicativos(self) -> list[dict[str, Any]]:
        liberados = {nome_de_app(a) for a in self._obter().apps_autorizados}
        return [
            {
                "id": app.id,
                "nome": app.nome,
                "arquivo": str(app.arquivo),
                "autorizado": nome_de_app(app.id) in liberados,
            }
            for app in self._instalados()
        ]

    @Property(list, notify=mudou)
    def aplicativosExtras(self) -> list[dict[str, Any]]:
        saida = []
        for caminho in self._obter().apps_extras:
            app = app_de_caminho(caminho)
            saida.append(
                {
                    "caminho": caminho,
                    "nome": app.nome if app is not None else Path(caminho).name,
                    "existe": app is not None,
                }
            )
        return saida

    def _detectados(self) -> tuple[Navegador, ...]:
        if self._navegadores is None:
            self._navegadores = detectar(
                pastas=self._pastas_de_apps, caminho_dos_binarios=self._caminho_dos_binarios
            )
        return self._navegadores

    @Property(list, notify=mudou)
    def navegadores(self) -> list[dict[str, Any]]:
        """Os detectados, e os que o dono pôs à mão, cada um com as opções de binário."""
        configuracao = self._obter()
        escolhidos = separar(configuracao.navegadores)
        linhas: list[dict[str, Any]] = []
        vistas: set[str] = set()
        for navegador in self._detectados():
            vistas.add(navegador.familia)
            escolhido = escolhidos.get(navegador.familia, "")
            opcoes = [
                {"entrada": o.entrada, "rotulo": o.rotulo, "escolhida": o.entrada == escolhido}
                for o in navegador.opcoes
            ]
            fora_da_lista = escolhido and all(o["entrada"] != escolhido for o in opcoes)
            if fora_da_lista:
                opcoes.append({"entrada": escolhido, "rotulo": escolhido, "escolhida": True})
            linhas.append(
                {
                    "familia": navegador.familia,
                    "nome": navegador.nome,
                    "opcoes": opcoes,
                    "escolhido": escolhido,
                    "usado": bool(escolhido),
                    "principal": configuracao.navegador_principal == navegador.familia,
                    "manual": False,
                    "existe": True,
                }
            )
        for familia, entrada in escolhidos.items():
            if familia in vistas:
                continue
            linhas.append(
                {
                    "familia": familia,
                    "nome": familia.capitalize(),
                    "opcoes": [{"entrada": entrada, "rotulo": entrada, "escolhida": True}],
                    "escolhido": entrada,
                    "usado": True,
                    "principal": configuracao.navegador_principal == familia,
                    "manual": True,
                    "existe": Path(entrada).expanduser().exists(),
                }
            )
        return linhas

    # --- o que a tela pede ---------------------------------------------------------------
    def _aplicar(self, mudar: Callable[[Configuracao], Configuracao], ok: str) -> bool:
        try:
            nova = mudar(self._obter())
            self._frase = f"{ok} — {self._gravar(nova)}"
            retorno = True
        except AcessoRecusado as erro:
            self._frase = f"não deu: {erro}"
            retorno = False
        self.mudou.emit()
        return retorno

    @Slot(str, result=bool)
    def definirModo(self, modo: str) -> bool:
        return self._aplicar(lambda c: acesso.com_modo(c, modo), "nível de acesso trocado")

    @Slot(str, result=bool)
    def adicionarRaiz(self, pasta: str) -> bool:
        caminho = _caminho_local(pasta)
        return self._aplicar(
            lambda c: acesso.com_raiz(c, caminho, lar=self._lar), f"pasta concedida: {caminho}"
        )

    @Slot(str)
    def removerRaiz(self, caminho: str) -> None:
        self._aplicar(lambda c: acesso.sem_raiz(c, caminho), f"pasta retirada: {caminho}")

    @Slot(str, str, result=bool)
    def definirNivelDaRaiz(self, caminho: str, nivel: str) -> bool:
        return self._aplicar(
            lambda c: acesso.com_nivel_da_raiz(c, caminho, nivel), f"{caminho}: {nivel}"
        )

    @Slot(str, bool)
    def marcarApp(self, identificador: str, marcado: bool) -> None:
        self._aplicar(
            lambda c: acesso.com_app(c, identificador, marcado),
            f"{identificador} {'liberado' if marcado else 'retirado'}",
        )

    @Slot(str, result=bool)
    def adicionarApp(self, arquivo: str) -> bool:
        caminho = _caminho_local(arquivo)
        return self._aplicar(
            lambda c: acesso.com_app_extra(c, caminho), f"aplicativo liberado: {caminho}"
        )

    @Slot(str)
    def removerApp(self, caminho: str) -> None:
        self._aplicar(lambda c: acesso.sem_app_extra(c, caminho), f"aplicativo retirado: {caminho}")

    @Slot(str, str, result=bool)
    def escolherBinario(self, familia: str, entrada: str) -> bool:
        caminho = _caminho_local(entrada)
        return self._aplicar(
            lambda c: acesso.com_navegador(c, familia, caminho), f"{familia} abre por {caminho}"
        )

    @Slot(str, result=bool)
    def adicionarNavegador(self, arquivo: str) -> bool:
        caminho = _caminho_local(arquivo)
        return self._aplicar(
            lambda c: acesso.com_navegador_manual(c, caminho)[0], f"navegador incluído: {caminho}"
        )

    @Slot(str)
    def retirarNavegador(self, familia: str) -> None:
        self._aplicar(lambda c: acesso.sem_navegador(c, familia), f"{familia} retirado")

    @Slot(str, result=bool)
    def definirPrincipal(self, familia: str) -> bool:
        return self._aplicar(
            lambda c: acesso.com_principal(c, familia), f"{familia} é o navegador principal"
        )

    @Slot(str, result=bool)
    def tornarPrincipal(self, familia: str) -> bool:
        """Um clique: usa o único binário que há (ou o primeiro) se nenhum foi escolhido, e marca
        o principal. Numa chamada só porque cada gravação refaz a lista da tela — um segundo
        passo vindo do QML já falaria com um botão que deixou de existir."""

        def mudar(configuracao: Configuracao) -> Configuracao:
            if familia not in separar(configuracao.navegadores):
                detectado = next((n for n in self._detectados() if n.familia == familia), None)
                if detectado is None or not detectado.opcoes:
                    raise AcessoRecusado(f"{familia} não tem binário: escolha um")
                configuracao = acesso.com_navegador(
                    configuracao, familia, detectado.opcoes[0].entrada
                )
            return acesso.com_principal(configuracao, familia)

        return self._aplicar(mudar, f"{familia} é o navegador principal")

    @Slot()
    def atualizar(self) -> None:
        """Relê os aplicativos e navegadores instalados (instalou algo com a janela aberta)."""
        self._apps = None
        self._navegadores = None
        self._frase = "listas atualizadas"
        self.mudou.emit()
