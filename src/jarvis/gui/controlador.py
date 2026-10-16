"""Quem **propõe** mudanças de tela (ADR-0019) — hoje um roteiro, amanhã o `s2`.

A camada de cima da interface é o "AI Controller": o que olha a conversa e propõe ações de
workspace. Ele não existe ainda — o `s2` da SPEC §2 é da F2, e inventar um agora seria
construir em cima de uma voz que ninguém ouviu (ADR-0018).

O que existe é **a fronteira dele**, que é o que importa agora: um `Controlador` devolve
propostas no vocabulário fechado de `jarvis.gui.acoes`, e quem as julga é o `Workspace`. O
roteiro de demonstração abaixo passa pelo mesmo caminho que a IA vai passar — mesma leitura,
mesma validação, mesma recusa —, então trocar o roteiro por um modelo não muda uma linha da
tela nem do gerente.

**Nada aqui finge ser real.** O conteúdo das propostas é sobre este repositório (arquivos,
cartões e decisões que existem), e todo módulo criado por um componente de demonstração
aparece na tela com o selo "DEMONSTRAÇÃO". O dono pediu exatamente isso: ver a composição dos
três modos sem que a tela minta que já há busca na web, navegador ou terminal ligados.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from jarvis.gui.acoes import Modo


@runtime_checkable
class Controlador(Protocol):
    """Quem propõe. Devolve ações cruas: o `Workspace` é que lê, valida e decide."""

    def propor(self, modo: Modo, *, pedido: str = "") -> Sequence[dict[str, Any]]: ...


def _acao(tipo: str, **campos: Any) -> dict[str, Any]:
    return {"tipo": tipo, **campos}


class RoteiroDeDemonstracao:
    """As três composições que o dono quer ver, com conteúdo deste repositório."""

    nome = "roteiro de demonstração"

    def propor(self, modo: Modo, *, pedido: str = "") -> Sequence[dict[str, Any]]:
        if modo is Modo.PESQUISA:
            return self._pesquisa(pedido)
        if modo is Modo.EXECUCAO:
            return self._execucao()
        return self._assistente()

    # --- modo 1: assistente ---------------------------------------------------------------
    def _assistente(self) -> Sequence[dict[str, Any]]:
        return [
            _acao("setWorkspaceMode", modo="assistente", motivo="estado inicial"),
            _acao(
                "createWidget",
                componente="tarefas",
                titulo="Contexto ativo",
                area={"coluna": 0, "linha": 1, "colunas": 3, "linhas": 3},
                motivo="o dono pediu para ver o que está em andamento",
                dados={
                    "itens": [
                        {"titulo": "Laço de voz", "detalhe": "F1 fechada", "estado": "resultado"},
                        {
                            "titulo": "Janela do aplicativo",
                            "detalhe": "ADR-0019",
                            "estado": "executando",
                        },
                        {
                            "titulo": "AppImage, .deb e .rpm",
                            "detalhe": "ADR-0020",
                            "estado": "espera",
                        },
                        {
                            "titulo": "Voz na máquina do dono",
                            "detalhe": "F1-16",
                            "estado": "espera",
                        },
                    ]
                },
            ),
            _acao(
                "createWidget",
                componente="notificacoes",
                # Do mesmo tamanho e na mesma altura do contexto, do outro lado do núcleo: a
                # composição fica equilibrada e o resto é espaço livre de propósito. O estado da
                # máquina já está no alto da tela; um card repetindo os mesmos números era ruído.
                area={"coluna": 9, "linha": 1, "colunas": 3, "linhas": 3},
                motivo="avisos que chegaram enquanto o dono falava (ADR-0025)",
                dados={
                    "avisos": [
                        {
                            "tipo": "precisa_decisao",
                            "origem": "tarefa · empacotar",
                            "resumo": "O .rpm está pronto; publicar exige a sua ordem",
                            "instante": "há 2 min",
                            "entrega": "so_card",
                            "confianca": "terceiros",
                        },
                        {
                            "tipo": "concluida",
                            "origem": "tarefa · baixar voz",
                            "resumo": "pt_BR-faber-medium baixada e conferida",
                            "instante": "há 6 min",
                            "entrega": "falado",
                            "confianca": "terceiros",
                        },
                        {
                            "tipo": "evento",
                            "origem": "jarvis",
                            "resumo": "Nuvem desligada: nada sai desta máquina",
                            "instante": "agora",
                            "entrega": "na_fila",
                            "confianca": "propria",
                        },
                    ]
                },
            ),
        ]

    # --- modo 2: pesquisa ------------------------------------------------------------------
    def _pesquisa(self, pedido: str) -> Sequence[dict[str, Any]]:
        consulta = pedido or "o que a especificação decide sobre epoch e barge-in"
        return [
            _acao("setWorkspaceMode", modo="pesquisa", motivo=consulta),
            _acao(
                "createWidget",
                componente="fontes",
                titulo="Fontes",
                area={"coluna": 0, "linha": 2, "colunas": 2, "linhas": 6},
                dados={
                    "itens": [
                        {"titulo": "SPEC §3.3", "detalhe": "regras de epoch", "estado": "visto"},
                        {"titulo": "ADR-0002", "detalhe": "epoch e cancelamento"},
                        {"titulo": "ADR-0015", "detalhe": "canal de áudio"},
                        {"titulo": "F1-11", "detalhe": "20 pontos de cancelamento"},
                        {"titulo": "docs/medicoes", "detalhe": "barge-in medido"},
                    ]
                },
            ),
            _acao(
                "createWidget",
                componente="noticias",
                titulo="Resultados",
                # Logo abaixo da faixa da consulta, sem a linha vazia que sobrava entre as duas;
                # fontes, resultados e análise terminam juntos, no fim da grade — como no modo
                # execução —, sem a faixa morta que sobrava acima da barra de conversa.
                area={"coluna": 2, "linha": 1, "colunas": 6, "linhas": 7},
                dados={
                    "itens": [
                        {
                            "titulo": "Falar por cima incrementa o epoch",
                            "detalhe": (
                                "A síntese para de produzir, a fila de playback descarta o que "
                                "não tocou e o motor de nuvem abandona o corpo em voo — as três "
                                "consultam a mesma pergunta."
                            ),
                            "fonte": "SPEC §3.3, regra 1",
                            "instante": "ADR-0002",
                            "estado": "resultado",
                        },
                        {
                            "titulo": "O áudio não passa pelo barramento",
                            "detalhe": (
                                "Quadros de PCM vão por canal próprio, com cabeçalho "
                                "epoch/seq/ts/amostras; só o PlaybackProgress é evento."
                            ),
                            "fonte": "ADR-0015",
                            "instante": "aceita em 2026-10-15",
                        },
                        {
                            "titulo": "Nada tocado depois do cancelamento",
                            "detalhe": (
                                "A suíte de cancelamento é portão próprio no verificar.py, para "
                                "o aceite virar regressão em vez de evento único."
                            ),
                            "fonte": "cartão F1-11",
                            "instante": "20 pontos",
                        },
                    ]
                },
            ),
            _acao(
                "createWidget",
                componente="resumo",
                titulo="Análise do Jarvis",
                area={"coluna": 8, "linha": 1, "colunas": 4, "linhas": 7},
                dados={
                    "texto": (
                        'O cancelamento é uma pergunta só — "o epoch ainda é meu?" — feita por '
                        "três lugares independentes. É isso que faz o barge-in não depender de "
                        "ninguém avisar ninguém."
                    ),
                    "topicos": [
                        "Quem é dono do epoch é o laço, não o motor de voz",
                        "A fila de playback é esvaziada no mesmo tique",
                        "A fila do driver não é nossa: isso está declarado como não verificado",
                        "Medir no ouvido do dono é o cartão F1-16",
                    ],
                },
            ),
        ]

    # --- modo 3: execução -------------------------------------------------------------------
    def _execucao(self) -> Sequence[dict[str, Any]]:
        return [
            _acao("setWorkspaceMode", modo="execucao", motivo="empacotar o aplicativo"),
            _acao(
                "createWidget",
                componente="tarefas",
                titulo="Executando",
                area={"coluna": 0, "linha": 2, "colunas": 2, "linhas": 6},
                dados={
                    "itens": [
                        {
                            "titulo": "Montar o AppDir",
                            "detalhe": "948,2 MB",
                            "estado": "resultado",
                        },
                        {
                            "titulo": "Empacotar o AppImage",
                            "detalhe": "squashfs com zstd",
                            "estado": "executando",
                        },
                        {"titulo": "Gerar .deb e .rpm", "detalhe": "nfpm", "estado": "espera"},
                        {
                            "titulo": "Instalar em contêiner",
                            "detalhe": "debian 13 e fedora 44",
                            "estado": "espera",
                        },
                        {
                            "titulo": "Rodar as telas no pacote",
                            "detalhe": "--capturar",
                            "estado": "espera",
                        },
                        {
                            "titulo": "Conferir licenças no artefato",
                            "detalhe": "LGPL-3.0 e GPL-3.0",
                            "estado": "espera",
                        },
                        {
                            "titulo": "Publicar",
                            "detalhe": "só com ordem do dono",
                            "estado": "espera",
                        },
                    ]
                },
            ),
            _acao(
                "createWidget",
                componente="codigo",
                titulo="src/jarvis/voz/app.py",
                area={"coluna": 2, "linha": 0, "colunas": 6, "linhas": 5},
                dados={
                    "linhas": [
                        'def interromper(self, motivo: str = "barge_in") -> int:',
                        '    """O dono falou por cima: o epoch morre e tudo cai junto."""',
                        "    self.epoch += 1",
                        "    self._turno_cancelado = True",
                        "    self._mudar(self._repouso)",
                        '    self.escrever_na_tela(f"  ⟂ interrompido ({motivo})")',
                        "    return self.epoch",
                        "",
                        "def _quer_falar(self, captura: Captura) -> bool:",
                        '    """Quem diz que o dono está falando: o dedo dele ou o VAD."""',
                        "    if self.pressionado is not None:",
                        "        return self.pressionado()",
                        "    return bool(captura.detector.falando)",
                    ]
                },
            ),
            _acao(
                "createWidget",
                componente="terminal",
                titulo="Saída do empacotador",
                area={"coluna": 2, "linha": 5, "colunas": 6, "linhas": 3},
                motivo="acompanhar o build do AppImage",
                dados={
                    "linhas": [
                        "$ uv run python tools/empacotar.py tudo",
                        "1/6 Python relocável        cpython-3.12.14 (68 MB)",
                        "2/6 dependências da trava   47 rodas de uv.lock",
                        "3/6 o próprio Jarvis        jarvis-0.0.0-py3-none-any.whl",
                        "4/6 dados, licenças, ícones usr/share/jarvis, usr/share/licenses",
                        "5/6 lançador                usr/bin/jarvis + AppRun",
                        "6/6 poda                    34,5 MB de peso morto",
                        "   AppDir: 948.2 MB",
                        "   AppImage: Jarvis-0.0.0-x86_64.AppImage (244.1 MB)",
                    ]
                },
            ),
            _acao(
                "createWidget",
                componente="arquivos",
                titulo="Artefatos",
                area={"coluna": 8, "linha": 0, "colunas": 4, "linhas": 3},
                motivo="conferir o que saiu do empacotador",
                dados={
                    "itens": [
                        {"titulo": "Jarvis-x86_64.AppImage", "detalhe": "executável único"},
                        {"titulo": "jarvis_0.0.0_amd64.deb", "detalhe": "Debian/Ubuntu"},
                        {"titulo": "jarvis-0.0.0.x86_64.rpm", "detalhe": "Fedora/Nobara"},
                        {"titulo": "share/licenses/jarvis", "detalhe": "LGPL-3.0 e GPL-3.0"},
                    ]
                },
            ),
            _acao(
                "createWidget",
                componente="graficos",
                titulo="Esta máquina",
                area={"coluna": 8, "linha": 3, "colunas": 4, "linhas": 2},
            ),
            _acao(
                "createWidget",
                componente="notificacoes",
                titulo="Avisos do empacotamento",
                area={"coluna": 8, "linha": 5, "colunas": 4, "linhas": 3},
                dados={
                    "avisos": [
                        {
                            "tipo": "evento",
                            "origem": "empacotar",
                            "resumo": "Modelos ficam fora do pacote: baixados no primeiro uso",
                            "instante": "há 1 min",
                            "entrega": "calado",
                            "confianca": "propria",
                        },
                        {
                            "tipo": "precisa_decisao",
                            "origem": "empacotar",
                            "resumo": "Publicar exige ordem do dono: nada de release, tag ou push",
                            "instante": "agora",
                            "entrega": "so_card",
                            "confianca": "propria",
                        },
                    ]
                },
            ),
        ]
