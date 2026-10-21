"""O controle da entrada virtual com backend e foco falsos: ordem das travas e recusas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from jarvis.entrada.controle import ControleDeEntrada, EntradaRecusada, avaliar
from jarvis.entrada.foco import Janela
from jarvis.entrada.limite import Interruptor, LimiteDeTaxa
from jarvis.entrada.porta import EntradaIndisponivel

KATE = Janela("org.kde.kate", "notas.txt — Kate", "{k}")
KONSOLE = Janela("org.kde.konsole", "Shell", "{t}")
JARVIS = Janela("jarvis", "Jarvis", "{j}")


@dataclass
class BackendFalso:
    nome: str = "falso"
    eventos: list[tuple[Any, ...]] = field(default_factory=list)
    indisponivel: bool = False
    fechado: bool = False

    def _evento(self, *e: Any) -> None:
        if self.indisponivel:
            raise EntradaIndisponivel("você cancelou o diálogo do sistema")
        self.eventos.append(e)

    def mover(self, dx: int, dy: int) -> None:
        self._evento("mover", dx, dy)

    def clicar(self, botao: str, vezes: int) -> None:
        self._evento("clicar", botao, vezes)

    def digitar(self, texto: str) -> None:
        self._evento("digitar", texto)

    def pressionar(self, modificadores: tuple[str, ...], tecla: str) -> None:
        self._evento("pressionar", modificadores, tecla)

    def fechar(self) -> None:
        self.fechado = True


@dataclass
class FocoFalso:
    """Devolve as janelas em sequência (a última se repete): modela o foco mudando."""

    janelas: list[Janela | None]
    ativacoes: list[Janela] = field(default_factory=list)
    ativar_funciona: bool = True
    lidas: int = 0

    def atual(self) -> Janela | None:
        i = min(self.lidas, len(self.janelas) - 1)
        self.lidas += 1
        return self.janelas[i]

    def ativar(self, janela: Janela) -> bool:
        self.ativacoes.append(janela)
        if self.ativar_funciona:
            self.janelas = [janela]
            self.lidas = 0
        return self.ativar_funciona


class Dono:
    """O que `exigir` faz: guarda a pergunta e responde sim/não como a janela responderia."""

    def __init__(self, sim: bool = True) -> None:
        self.sim = sim
        self.perguntas: list[tuple[str, str, str]] = []

    def __call__(self, detalhe: str, motivo: str, causa: str) -> None:
        self.perguntas.append((detalhe, motivo, causa))
        if not self.sim:
            raise EntradaRecusada("o dono não confirmou")


def _controle(
    foco: FocoFalso, backend: BackendFalso | None = None, **extra: Any
) -> tuple[ControleDeEntrada, BackendFalso]:
    backend = backend or BackendFalso()
    controle = ControleDeEntrada(backend=backend, foco=foco, dormir=lambda _s: None, **extra)
    return controle, backend


def _rodar(
    controle: ControleDeEntrada,
    tool: str,
    args: dict[str, Any],
    dono: Dono | None = None,
    *,
    contaminado: bool = False,
    cancelado: Callable[[], bool] = lambda: False,
) -> dict[str, Any]:
    return controle.executar(
        tool, args, contaminado=contaminado, exigir=dono or Dono(), cancelado=cancelado
    )


def test_janela_comum_roda_sem_perguntar_e_o_evento_sai_pelo_backend() -> None:
    controle, backend = _controle(FocoFalso([KATE]))
    dono = Dono()
    assert _rodar(controle, "input.mouse.move", {"dx": 30, "dy": -10}, dono)["dx"] == 30
    assert (
        _rodar(controle, "input.mouse.click", {"botao": "direito", "vezes": 2}, dono)["vezes"] == 2
    )
    assert _rodar(controle, "input.key.type", {"texto": "olá"}, dono)["caracteres"] == 3
    assert _rodar(controle, "input.key.press", {"tecla": "ctrl+l"}, dono)["tecla"] == "ctrl+l"
    assert dono.perguntas == []
    assert backend.eventos == [
        ("mover", 30, -10),
        ("clicar", "direito", 2),
        ("digitar", "olá"),
        ("pressionar", ("ctrl",), "l"),
    ]


def test_o_resultado_nao_devolve_o_texto_digitado() -> None:
    controle, _ = _controle(FocoFalso([KATE]))
    assert "texto" not in _rodar(controle, "input.key.type", {"texto": "segredo"})


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("input.mouse.move", {"dx": 5000, "dy": 0}),
        ("input.mouse.move", {"dx": 0, "dy": 0}),
        ("input.mouse.move", {"dx": True, "dy": 1}),
        ("input.mouse.click", {"botao": "quarto"}),
        ("input.mouse.click", {"vezes": 4}),
        ("input.key.type", {"texto": ""}),
        ("input.key.type", {"texto": "a\x07b"}),
        ("input.key.press", {"tecla": "super+l"}),
        ("input.key.press", {"tecla": "ctrl+alt+t"}),
    ],
)
def test_argumento_fora_do_contrato_e_recusado_antes_de_olhar_a_janela(
    tool: str, args: dict[str, Any]
) -> None:
    foco = FocoFalso([KATE])
    controle, backend = _controle(foco)
    with pytest.raises(EntradaRecusada):
        _rodar(controle, tool, args)
    assert backend.eventos == [] and foco.lidas == 0


def test_terminal_pede_o_sim_e_so_age_depois_dele() -> None:
    controle, backend = _controle(FocoFalso([KONSOLE]))
    dono = Dono(sim=True)
    _rodar(controle, "input.key.type", {"texto": "ls"}, dono)
    assert "terminal" in dono.perguntas[0][1] and "Konsole".lower() in dono.perguntas[0][0].lower()
    assert dono.perguntas[0][2] == "categoria_da_janela"  # o código da trilha, sem o título
    assert backend.eventos == [("digitar", "ls")]

    negado, nao = _controle(FocoFalso([KONSOLE]))
    with pytest.raises(EntradaRecusada, match="não confirmou"):
        _rodar(negado, "input.key.type", {"texto": "ls"}, Dono(sim=False))
    assert nao.eventos == []


def test_enter_pede_o_sim_mesmo_em_janela_comum_e_quebra_de_linha_tambem() -> None:
    controle, backend = _controle(FocoFalso([KATE]))
    dono = Dono()
    _rodar(controle, "input.key.press", {"tecla": "enter"}, dono)
    _rodar(controle, "input.key.type", {"texto": "oi\nvida"}, dono)
    assert len(dono.perguntas) == 2 and "Enter" in dono.perguntas[0][1]
    assert [p[2] for p in dono.perguntas] == ["enter_envia", "enter_envia"]
    assert len(backend.eventos) == 2


def test_turno_contaminado_pede_o_sim_para_qualquer_acao() -> None:
    controle, _ = _controle(FocoFalso([KATE]))
    dono = Dono()
    _rodar(controle, "input.mouse.click", {}, dono, contaminado=True)
    assert "terceiros" in dono.perguntas[0][1]
    assert dono.perguntas[0][2] == "turno_contaminado"


def test_foco_desconhecido_e_recusa_nao_pergunta() -> None:
    controle, backend = _controle(FocoFalso([None]))
    dono = Dono()
    with pytest.raises(EntradaRecusada, match="kdotool"):
        _rodar(controle, "input.mouse.click", {}, dono)
    assert dono.perguntas == [] and backend.eventos == []


def test_o_proprio_jarvis_em_foco_e_recusa_sempre() -> None:
    controle, backend = _controle(FocoFalso([JARVIS]))
    with pytest.raises(EntradaRecusada, match="próprio Jarvis"):
        _rodar(controle, "input.mouse.click", {"botao": "esquerdo"})
    assert backend.eventos == []


@pytest.mark.parametrize(
    "janela",
    [
        Janela("org.keepassxc.KeePassXC", "Cofre"),
        Janela("org.kde.polkit-kde-authentication-agent-1", "Autenticação necessária"),
    ],
)
def test_digitar_em_senha_ou_autenticacao_e_recusa_nem_com_sim(janela: Janela) -> None:
    controle, backend = _controle(FocoFalso([janela]))
    dono = Dono(sim=True)
    with pytest.raises(EntradaRecusada, match="quem digita é o dono"):
        _rodar(controle, "input.key.type", {"texto": "hunter2"}, dono)
    assert dono.perguntas == [] and backend.eventos == []


def test_numero_de_cartao_nunca_e_digitado() -> None:
    controle, backend = _controle(FocoFalso([KATE]))
    with pytest.raises(EntradaRecusada, match="cartão"):
        _rodar(controle, "input.key.type", {"texto": "4111 1111 1111 1111"})
    assert backend.eventos == []


def test_confirmacao_na_janela_do_jarvis_devolve_o_foco_e_segue() -> None:
    # antes do sim: terminal; depois do clique no Jarvis: Jarvis; o código reativa o terminal
    foco = FocoFalso([KONSOLE, JARVIS])
    controle, backend = _controle(foco)
    _rodar(controle, "input.key.type", {"texto": "ls"}, Dono())
    assert foco.ativacoes == [KONSOLE]
    assert backend.eventos == [("digitar", "ls")]


def test_se_o_foco_nao_volta_depois_do_sim_nada_acontece() -> None:
    foco = FocoFalso([KONSOLE, JARVIS], ativar_funciona=False)
    controle, backend = _controle(foco)
    with pytest.raises(EntradaRecusada, match="foco mudou"):
        _rodar(controle, "input.key.type", {"texto": "ls"}, Dono())
    assert backend.eventos == []


def test_se_o_foco_vai_para_outra_janela_durante_a_pergunta_nada_acontece() -> None:
    foco = FocoFalso([KONSOLE, Janela("firefox", "Nubank")])
    controle, backend = _controle(foco)
    with pytest.raises(EntradaRecusada, match="foco mudou"):
        _rodar(controle, "input.key.type", {"texto": "ls"}, Dono())
    assert backend.eventos == [] and foco.ativacoes == []


def test_interromper_enquanto_a_pergunta_esta_na_tela_cancela() -> None:
    controle, backend = _controle(FocoFalso([KONSOLE]))
    with pytest.raises(EntradaRecusada, match="interrompido"):
        _rodar(controle, "input.key.type", {"texto": "ls"}, Dono(), cancelado=lambda: True)
    assert backend.eventos == []


def test_parada_do_dono_vale_antes_e_durante_a_pergunta(tmp_path: Path) -> None:
    interruptor = Interruptor(tmp_path)
    controle, backend = _controle(FocoFalso([KATE]), interruptor=interruptor)
    interruptor.parar("botão")
    with pytest.raises(EntradaRecusada, match=r"parada.*só o dono"):
        _rodar(controle, "input.mouse.click", {})

    interruptor.liberar()
    controle2, backend2 = _controle(FocoFalso([KONSOLE]), interruptor=interruptor)

    def parar_enquanto_olha(detalhe: str, motivo: str, causa: str) -> None:
        interruptor.parar("parei olhando a pergunta")

    with pytest.raises(EntradaRecusada, match="mandou parar"):
        controle2.executar(
            "input.key.type",
            {"texto": "ls"},
            contaminado=False,
            exigir=parar_enquanto_olha,
            cancelado=lambda: False,
        )
    assert backend.eventos == [] and backend2.eventos == []


def test_limite_de_taxa_recusa_a_acao_do_excesso() -> None:
    controle, backend = _controle(FocoFalso([KATE]), limite=LimiteDeTaxa(2, 60.0))
    _rodar(controle, "input.mouse.click", {})
    _rodar(controle, "input.mouse.click", {})
    with pytest.raises(EntradaRecusada, match="limite de taxa"):
        _rodar(controle, "input.mouse.click", {})
    assert len(backend.eventos) == 2


def test_acao_que_o_dono_negou_nao_gasta_a_taxa() -> None:
    controle, _ = _controle(FocoFalso([KONSOLE]), limite=LimiteDeTaxa(1, 60.0))
    with pytest.raises(EntradaRecusada):
        _rodar(controle, "input.key.type", {"texto": "ls"}, Dono(sim=False))
    _rodar(controle, "input.key.type", {"texto": "ls"}, Dono(sim=True))  # ainda cabe uma


def test_backend_indisponivel_vira_recusa_com_a_frase() -> None:
    controle, _ = _controle(FocoFalso([KATE]), BackendFalso(indisponivel=True))
    with pytest.raises(EntradaRecusada, match="cancelou o diálogo"):
        _rodar(controle, "input.mouse.click", {})


def test_avaliar_e_pura() -> None:
    assert avaliar("input.mouse.click", KATE).motivos == ()
    assert avaliar("input.mouse.click", KONSOLE).motivos
    assert avaliar("input.key.type", KATE, texto="a\nb", enter=True).motivos
