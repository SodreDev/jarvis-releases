"""Presets de modelo **pela janela** (ADR-0056, aceite e): o clique chega ao arquivo do dono e a
tela desenha.

Os cliques são os slots que o QML chama (`ponte.modelos.salvarPreset`, `ativar`, `abrirProvedor`,
`buscarModelos`, `ligarProvedor`), e o arquivo é lido de volta pela mesma `FonteDePresets` que a
voz e o roteador do cérebro usam. Tudo num ambiente explícito em `tmp_path` (`XDG_CONFIG_HOME`,
`XDG_CACHE_HOME`, `CI=1`): nenhuma pasta do dono é lida, e a lista "de agora" vem de um provedor
falso — nenhum provedor de verdade é consultado nem gasta cota.
"""

# ruff: noqa: F811 — as fixtures vêm de `test_janela` e são parâmetros aqui
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui` (`uv sync --group gui`)")

from PySide6.QtCore import QEventLoop
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickView

from jarvis.gui.ponte import Ponte
from jarvis.provedores.interface import ESFORCOS, Capacidades, Modelo
from jarvis.provedores.nucleo import Provedores
from jarvis.provedores.presets import FonteDePresets
from jarvis.voz.config import Configuracao, ler
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    TELAS,
    abrir,
    aplicativo,
    sem_chaveiro,
)

GROQ = "conversa-groq"
ECO = "conversa-eco"
JEV = "decisao-jev-openrouter"


class ProvedorFalso:
    """Lista sem rede, diz de que thread foi chamado e responde a `prontidao` como uma CLI."""

    def __init__(self) -> None:
        self.chamadas = 0
        self.na_thread_da_janela: list[bool] = []

    def listar(self, *, cancelado: object = None) -> tuple[Modelo, ...]:
        self.chamadas += 1
        self.na_thread_da_janela.append(threading.current_thread() is threading.main_thread())
        return (
            Modelo(
                "falso/visao-1",
                "Visão Falsa",
                Capacidades(
                    visao=True,
                    ferramentas=True,
                    esforcos=("low", "high"),
                    contexto=200_000,
                    preco_entrada=1.5,
                    preco_saida=6.0,
                ),
            ),
            Modelo("falso/texto-1"),
        )

    def prontidao(self) -> str:
        return "falta entrar: rode `falso login` no terminal"


@pytest.fixture
def ambiente(tmp_path: Path) -> dict[str, str]:
    return {
        "CI": "1",
        "HOME": str(tmp_path / "casa"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }


def _presets(tmp_path: Path) -> Path:
    return tmp_path / "config" / "jarvis" / "presets.toml"


def _ponte(tmp_path: Path, ambiente: dict[str, str]) -> Ponte:
    arquivo = tmp_path / "config" / "jarvis" / "jarvis-voz.toml"
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    return Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=arquivo, ambiente=ambiente)


def _esperar(app: QGuiApplication, segundos: float, ate: Callable[[], bool] | None = None) -> None:
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if ate is not None and ate():
            return
        time.sleep(0.005)


def _procurar(item: QQuickItem, nome: str) -> QQuickItem | None:
    """Pela árvore **visual**: o que um `Loader` carrega não é filho QObject do pai."""
    if item.objectName() == nome:
        return item
    for filho in item.childItems():
        achado = _procurar(filho, nome)
        if achado is not None:
            return achado
    return None


def _item(janela: QQuickView, nome: str) -> QQuickItem:
    achado = _procurar(janela.rootObject(), nome)
    assert achado is not None, f"não achei {nome} na tela"
    return achado


def _do(lista: list[dict[str, Any]], identificador: str) -> dict[str, Any]:
    return next(p for p in lista if p["id"] == identificador)


def test_salvar_um_preset_pela_janela_grava_o_arquivo_do_dono(
    tmp_path: Path, ambiente: dict[str, str], sem_chaveiro: None
) -> None:
    tela = cast(Any, _ponte(tmp_path, ambiente))
    modelos = tela.modelos
    assert modelos.arquivo["caminho"] == str(_presets(tmp_path))
    assert not modelos.arquivo["doDono"], "antes de salvar valem os presets do Jarvis"

    frase = modelos.salvarPreset("meu groq", "cerebro", GROQ, "openai/gpt-oss-20b", "low")

    assert frase.startswith("preset «meu groq» salvo para cérebro")
    assert "desligado" in frase, "salvar não liga a nuvem: a frase diz que falta ligar"
    assert modelos.aviso == frase
    gravados = FonteDePresets(ambiente=ambiente).atuais()
    assert gravados.origem == str(_presets(tmp_path))
    preset = gravados.por_nome("meu groq")
    assert preset is not None
    assert (preset.papel, preset.provedor, preset.modelo, preset.esforco) == (
        "cerebro",
        GROQ,
        "openai/gpt-oss-20b",
        "low",
    )
    assert gravados.ativo("cerebro") is None, "salvar não ativa"
    assert "meu groq" in [p["nome"] for p in modelos.presets]
    assert modelos.arquivo["doDono"]
    assert GROQ not in tela.configuracao["nuvem_ligada"]


def test_ativar_o_preset_e_voltar_ao_da_configuracao(
    tmp_path: Path, ambiente: dict[str, str], sem_chaveiro: None
) -> None:
    modelos = cast(Any, _ponte(tmp_path, ambiente)).modelos
    assert modelos.ativos["cerebro"] == "configuração"
    modelos.salvarPreset("meu groq", "cerebro", GROQ, "openai/gpt-oss-20b", "low")

    frase = modelos.ativar("cerebro", "meu groq")

    assert frase.startswith("cérebro: «meu groq» ativo") and "desligado" in frase
    ativo = FonteDePresets(ambiente=ambiente).atuais().ativo("cerebro")
    assert ativo is not None and ativo.nome == "meu groq"
    assert modelos.ativos["cerebro"] == "meu groq"
    do_cerebro = {p["nome"]: p for p in modelos.presets if p["papel"] == "cerebro"}
    assert do_cerebro["meu groq"]["ativo"]
    configuracao = do_cerebro["configuração"]
    assert configuracao["daConfiguracao"] and not configuracao["ativo"], (
        "a volta ao da configuração continua na tela com outro preset ativo"
    )

    assert modelos.ativar("cerebro", "configuração").startswith("cérebro: volta ao da config")
    relido = FonteDePresets(ambiente=ambiente, configuracao=Configuracao()).atuais()
    legado = relido.ativo("cerebro")
    assert legado is not None and legado.da_configuracao
    assert 'cerebro = ""' in _presets(tmp_path).read_text(encoding="utf-8")

    modelos.ativar("visao", "visão groq")
    assert FonteDePresets(ambiente=ambiente).atuais().ativos["visao"] == "visão groq"
    assert modelos.ativar("visao", "").startswith("visão: nenhum")
    assert FonteDePresets(ambiente=ambiente).atuais().ativo("visao") is None


@pytest.mark.parametrize(
    ("nome", "papel", "provedor", "modelo", "esforco", "motivo"),
    [
        ("x", "cerebro", GROQ, "modelo com espaço", "low", "fora da forma"),
        ("x", "cerebro", GROQ, "openai/gpt-oss-20b", "turbo", "esforço"),
        ("nome/com barra", "cerebro", GROQ, "", "", "fora da forma"),
        ("x", "jev", GROQ, "", "", "não serve para jev"),
        ("x", "cerebro", "conversa-que-nao-existe", "", "", "não está no registro"),
        ("configuração", "cerebro", ECO, "", "", "espelha o jarvis-voz.toml"),
        ("x", "cerebro", "conversa-openai", "sk-proj-" + "x" * 24, "", "forma de uma chave"),
        ("x", "jev", JEV, "outro/modelo", "", "só roda o que o registro lista"),
    ],
)
def test_preset_invalido_volta_com_o_motivo_e_nao_grava_nada(
    tmp_path: Path,
    ambiente: dict[str, str],
    sem_chaveiro: None,
    nome: str,
    papel: str,
    provedor: str,
    modelo: str,
    esforco: str,
    motivo: str,
) -> None:
    modelos = cast(Any, _ponte(tmp_path, ambiente)).modelos

    frase = modelos.salvarPreset(nome, papel, provedor, modelo, esforco)

    assert frase.startswith("não deu: ") and motivo in frase, frase
    assert modelos.aviso == frase
    assert not _presets(tmp_path).exists(), "o recusado não vira arquivo"


def test_arquivo_do_dono_que_nao_serviu_nao_e_gravado_por_cima(
    tmp_path: Path, ambiente: dict[str, str], sem_chaveiro: None
) -> None:
    """O dono escreveu o arquivo à mão e errou: a janela avisa e não apaga o que ele escreveu."""
    _presets(tmp_path).parent.mkdir(parents=True)
    _presets(tmp_path).write_text("versao = 1\n[[preset]\n", encoding="utf-8")
    modelos = cast(Any, _ponte(tmp_path, ambiente)).modelos
    assert any("não serviu" in aviso for aviso in modelos.arquivo["avisos"])

    salvar = modelos.salvarPreset("meu eco", "cerebro", ECO, "eco", "")
    ativar = modelos.ativar("cerebro", "eco")

    for frase in (salvar, ativar):
        assert frase.startswith("não deu: ") and "conserte-o ou apague-o" in frase
    assert _presets(tmp_path).read_text(encoding="utf-8") == "versao = 1\n[[preset]\n"


def test_a_lista_de_agora_vem_numa_thread_e_vira_a_listagem(
    aplicativo: QGuiApplication,
    tmp_path: Path,
    ambiente: dict[str, str],
    sem_chaveiro: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    falso = ProvedorFalso()
    monkeypatch.setattr(Provedores, "abrir", lambda _self, _identificador: falso)
    modelos = cast(Any, _ponte(tmp_path, ambiente)).modelos

    modelos.abrirProvedor(GROQ)
    lista = modelos.listagem
    assert (lista["provedor"], lista["origem"]) == (GROQ, "registro"), "abrir não usa a rede"
    assert "openai/gpt-oss-20b" in [m["id"] for m in lista["modelos"]]
    assert lista["frase"].startswith("4 modelos · lista do registro, conferida em")
    assert falso.chamadas == 0
    _esperar(aplicativo, 5, lambda: modelos.falta != "")
    assert modelos.falta == "falta entrar: rode `falso login` no terminal", "a prontidão da CLI"

    modelos.buscarModelos(GROQ)
    assert modelos.carregando and modelos.aviso == "buscando a lista de Groq…"
    fim = time.monotonic() + 5
    while time.monotonic() < fim and any(t.name == "jarvis-modelos" for t in threading.enumerate()):
        time.sleep(0.01)
    assert falso.na_thread_da_janela == [False], "a lista de agora é buscada fora da janela"
    assert modelos.carregando, "a resposta chega por sinal, entregue na thread da janela"
    _esperar(aplicativo, 5, lambda: not modelos.carregando)

    lista = modelos.listagem
    assert lista["origem"] == "provedor"
    assert modelos.aviso == "2 modelo(s) de Groq, lidos agora do provedor"
    resumo = {m["id"]: m["resumo"] for m in lista["modelos"]}
    assert resumo["falso/visao-1"] == (
        "vê imagem · ferramentas · 200k contexto · US$ 1,50/6,00 por milhão"
    )
    assert resumo["falso/texto-1"].count("não informado") == 4, "None é não informado, não não"
    assert (tmp_path / "cache" / "jarvis" / "modelos" / f"{GROQ}.json").is_file()
    assert modelos.esforcosDe(GROQ, "falso/visao-1") == ["low", "high"]
    assert modelos.esforcosDe(GROQ, "falso/texto-1") == list(ESFORCOS)
    assert modelos.esforcosDe(ECO, "") == [], "o eco não aceita esforço"


def test_o_jev_so_tem_o_modelo_do_registro_e_nenhum_esforco(
    tmp_path: Path, ambiente: dict[str, str], sem_chaveiro: None
) -> None:
    modelos = cast(Any, _ponte(tmp_path, ambiente)).modelos
    jev = _do(modelos.provedores, JEV)
    assert jev["papeis"] == ["jev"] and jev["listaAoVivo"] is False

    modelos.abrirProvedor(JEV)
    assert [m["id"] for m in modelos.listagem["modelos"]] == ["typesafe/jev-1.13"]
    assert modelos.esforcosDe(JEV, "") == []
    modelos.buscarModelos(JEV)
    assert not modelos.carregando and "não tem lista para buscar" in modelos.aviso

    frase = modelos.salvarPreset("jev de novo", "jev", JEV, "typesafe/jev-1.13", "")
    assert frase.startswith("preset «jev de novo» salvo para jev"), frase


def test_ligar_o_provedor_e_o_interruptor_da_janela_e_salvar_guarda(
    tmp_path: Path, ambiente: dict[str, str], sem_chaveiro: None
) -> None:
    tela = cast(Any, _ponte(tmp_path, ambiente))
    modelos = tela.modelos
    groq = _do(modelos.provedores, GROQ)
    assert (groq["nome"], groq["apelido"], groq["onde"], groq["ligado"]) == (
        "Groq",
        "groq",
        "nuvem",
        False,
    )
    assert "sai desta máquina" in groq["aviso"] and groq["variavelDaChave"] == "JARVIS_GROQ_API_KEY"
    assert _do(modelos.provedores, ECO)["ligado"], "local não tem interruptor"

    modelos.ligarProvedor(GROQ, True)
    assert modelos.aviso.startswith("Groq ligado — vale já, nesta conversa")
    assert _do(modelos.provedores, GROQ)["ligado"]
    assert GROQ in tela.configuracao["nuvem_ligada"]
    tela.salvarConfiguracao()
    assert ler(tmp_path / "config" / "jarvis" / "jarvis-voz.toml").nuvem_ligada == (GROQ,)

    modelos.ligarProvedor(GROQ, False)
    assert not _do(modelos.provedores, GROQ)["ligado"]
    modelos.ligarProvedor(ECO, True)
    assert "não há nuvem para ligar" in modelos.aviso


def test_o_painel_de_modelos_carrega_na_janela_e_desenha_o_provedor(
    abrir: Callable[[Ponte], QQuickView],
    aplicativo: QGuiApplication,
    tmp_path: Path,
    ambiente: dict[str, str],
    sem_chaveiro: None,
) -> None:
    ponte = _ponte(tmp_path, ambiente)
    janela = abrir(ponte)
    janela.show()
    _esperar(aplicativo, 0.5)
    tela = cast(Any, ponte)
    tela.abrirPainel("configuracao")
    _esperar(aplicativo, 0.8)

    assert [str(erro) for erro in janela.errors()] == []
    painel = _item(janela, "painelDeModelos")
    assert painel.height() > 0
    assert _item(janela, "preset:configuração").isVisible()

    tela.modelos.abrirProvedor("conversa-openai")
    _esperar(aplicativo, 0.4)
    assert painel.property("aberto") == "conversa-openai"
    quantos = len(tela.modelos.listagem["modelos"])
    assert quantos > 0 and _item(janela, "modelosDoProvedor").property("count") == quantos
    assert _item(janela, "avisoDoProvedorDeModelo").isVisible(), "desligado: o aviso, antes"
    tela.modelos.ligarProvedor("conversa-openai", True)
    _esperar(aplicativo, 0.3)
    assert not _item(janela, "avisoDoProvedorDeModelo").isVisible()

    # Um id fora da lista também se escolhe: quem diz se ele existe é o provedor (ADR-0056).
    filtro = _item(janela, "filtroDeModelos")
    filtro.setProperty("text", "gpt-6-luna")
    _esperar(aplicativo, 0.2)
    assert _item(janela, "modelosDoProvedor").property("count") == 1
    assert not _item(janela, "modeloEscrito").isVisible(), "o da lista não se repete"
    filtro.setProperty("text", "gpt-7-fora-da-lista")
    _esperar(aplicativo, 0.2)
    assert _item(janela, "modeloEscrito").isVisible()

    # O retrato para o dono: a coluna rolada até a caixa da resposta.
    rolagem: QQuickItem | None = painel
    while rolagem is not None and not rolagem.inherits("QQuickFlickable"):
        rolagem = rolagem.parentItem()
    assert rolagem is not None
    conteudo = cast(QQuickItem, rolagem.property("contentItem"))
    alvo = painel.mapToItem(conteudo, 0, 0).y() - 60
    teto = float(rolagem.property("contentHeight")) - rolagem.height()
    rolagem.setProperty("contentY", max(0.0, min(alvo, teto)))
    _esperar(aplicativo, 0.4)
    TELAS.mkdir(parents=True, exist_ok=True)
    assert janela.grabWindow().save(str(TELAS / "jarvis-configuracao-presets.png"))
