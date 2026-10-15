"""Cartão F1-13: PTT, indicador que não mente e *kill switch*, com os quatro aceites.

O aceite que importa é o (b): a propriedade nas **duas** direções. "Nunca ouvindo com a fonte
fechada" é o que protege a privacidade do dono; "nunca fonte aberta com o indicador apagado" é
o que protege a confiança dele no indicador. As duas são a mesma frase vista de dois lados, e
aqui elas são exercitadas por sequência pseudoaleatória de ações, com semente fixa.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from jarvis.audio_io import (
    AMOSTRAS_POR_QUADRO,
    TAXA_PADRAO,
    Captura,
    DetectorDeEnergia,
    FonteSintetica,
    Quadro,
    TipoDeTrecho,
    Trecho,
)
from jarvis.audio_io.controle import TICKS_ENTRE_ESCRITAS, ControleDoMicrofone
from jarvis.audio_io.erros import DispositivoIndisponivel
from jarvis.microfone import ARQUIVO_PEDIDO, Modo, Pedido, escrever_pedido, ler_pedido
from jarvis.relogio import RelogioFalso
from jarvis.ui.atalhos import (
    VARIAVEL_ARQUIVO,
    VARIAVEL_BACKEND,
    AtalhoDeSistema,
    AtalhoFalso,
    AtalhoIndisponivel,
    SemAtalho,
    atalho_do_ambiente,
)
from jarvis.ui.painel import PainelDoMicrofone

SESSAO = "0193f0a0-0000-7000-8000-000000000000"
ROTEIRO = (
    Trecho(TipoDeTrecho.SILENCIO, 100.0),
    Trecho(TipoDeTrecho.FALA, 400.0),
    Trecho(TipoDeTrecho.SILENCIO, 200.0),
)


@dataclass(slots=True)
class FonteContada:
    """Conta amostras, aberturas e fechamentos: é a verdade contra a qual o indicador vale."""

    interna: FonteSintetica
    device_id: str = "contada:0"
    taxa: int = TAXA_PADRAO
    amostras_entregues: int = 0
    aberturas: int = 0
    fechamentos: int = 0
    erro_ao_abrir: Exception | None = None
    _origem: Iterator[Quadro] | None = field(default=None, repr=False)

    @property
    def aberta(self) -> bool:
        return self.aberturas > self.fechamentos

    def abrir(self) -> None:
        if self.erro_ao_abrir is not None:
            raise self.erro_ao_abrir
        self.interna.abrir()
        self._origem = iter(self.interna.quadros())
        self.aberturas += 1

    def quadros(self) -> Iterator[Quadro]:
        assert self._origem is not None
        for quadro in self._origem:
            self.amostras_entregues += quadro.n_amostras
            yield quadro

    def fechar(self) -> None:
        if self.aberta:
            self.fechamentos += 1
        self.interna.fechar()


@dataclass(slots=True)
class Bancada:
    """Painel da `ui` e controle do `audio-io` ligados pela pasta de sessão, como em produção."""

    painel: PainelDoMicrofone
    controle: ControleDoMicrofone
    captura: Captura
    fonte: FonteContada
    atalho: AtalhoFalso
    eventos: int = 0

    def volta(self, *, quadros: int = 1) -> None:
        """Uma volta do sistema: a `ui` pede, o `audio-io` aplica e captura o que couber."""
        self.painel.tick()
        self.controle.tick()
        if self.captura.aberta:
            for _ in range(quadros):
                self.eventos += len(self.captura.tick())


def montar(tmp_path: Path, *, modo: Modo = Modo.PTT) -> Bancada:
    relogio = RelogioFalso()
    fonte = FonteContada(interna=FonteSintetica(relogio=relogio, semente=3, roteiro=ROTEIRO))
    captura = Captura(fonte=fonte, relogio=relogio, session_id=SESSAO, detector=DetectorDeEnergia())
    atalho = AtalhoFalso(arquivo=None)
    painel = PainelDoMicrofone(raiz=tmp_path, atalho=atalho, modo=modo)
    controle = ControleDoMicrofone(raiz=tmp_path, captura=captura, modo_inicial=modo)
    return Bancada(painel=painel, controle=controle, captura=captura, fonte=fonte, atalho=atalho)


def test_apertar_abre_a_fonte_e_soltar_fecha(tmp_path: Path) -> None:
    """Aceite (a), primeira metade: a tecla abre e fecha a **fonte**, não um filtro."""
    bancada = montar(tmp_path)

    bancada.volta()
    fechado_no_comeco = (bancada.painel.ouvindo, bancada.fonte.aberta)

    bancada.atalho.apertar()
    bancada.volta()
    aberto = (bancada.painel.ouvindo, bancada.fonte.aberta)
    recem_aberto = bancada.painel.estado.amostras
    for _ in range(TICKS_ENTRE_ESCRITAS):
        bancada.volta()
    amostras_com_a_tecla = bancada.painel.estado.amostras

    escritas_antes = bancada.controle.escritas
    bancada.atalho.soltar()
    bancada.volta()

    assert fechado_no_comeco == (False, False), "tecla solta não abre microfone"
    assert aberto == (True, True)
    # A contagem é retrato: no tick em que a fonte abriu ela é 0 de verdade (ninguém capturou
    # ainda), e o controle republica depois de TICKS_ENTRE_ESCRITAS. O que **não** atrasa é o
    # zero do fechamento, que é o que o indicador precisa — é o `assert` lá embaixo.
    assert recem_aberto == 0
    assert amostras_com_a_tecla >= TICKS_ENTRE_ESCRITAS * AMOSTRAS_POR_QUADRO
    assert bancada.fonte.aberturas == 1 and bancada.fonte.fechamentos == 1
    assert bancada.controle.escritas == escritas_antes + 1, (
        "fechar é mudança visível: publica na hora, sem esperar os 250 ms"
    )
    assert bancada.painel.ouvindo is False
    assert bancada.painel.estado.amostras == 0, "fonte fechada: a contagem desta abertura é 0"


def test_indicador_apagado_significa_zero_amostra(tmp_path: Path) -> None:
    """Aceite (a), segunda metade: com o indicador apagado, nada sai da fonte."""
    bancada = montar(tmp_path)

    for passo in range(12):
        if passo == 3:
            bancada.atalho.apertar()
        if passo == 7:
            bancada.atalho.soltar()
        entregues_antes = bancada.fonte.amostras_entregues
        bancada.volta(quadros=2)
        if not bancada.painel.ouvindo:
            assert bancada.fonte.amostras_entregues == entregues_antes
            assert bancada.painel.estado.amostras == 0

    assert bancada.fonte.amostras_entregues > 0, "o teste tem de ter capturado em algum momento"


def test_propriedade_nas_duas_direcoes(tmp_path: Path) -> None:
    """Aceite (b): nunca "ouvindo" com a fonte fechada, nunca fonte aberta com o indicador apagado.

    Sequência pseudoaleatória com semente fixa (determinística): aperta, solta, desliga,
    religa e troca de modo em qualquer ordem — inclusive as ordens que ninguém pensaria em
    escrever à mão, como desligar com a tecla apertada e religar já solta.
    """
    bancada = montar(tmp_path)
    sorteio = random.Random(7)
    acoes = ("apertar", "soltar", "desligar", "ligar", "escuta", "ptt")
    vistos: set[tuple[bool, bool]] = set()

    for _ in range(300):
        match sorteio.choice(acoes):
            case "apertar":
                bancada.atalho.apertar()
            case "soltar":
                bancada.atalho.soltar()
            case "desligar":
                bancada.painel.desligar()
            case "ligar":
                bancada.painel.ligar()
            case "escuta":
                if not bancada.painel.desligado:
                    bancada.painel.modo = Modo.ESCUTA
            case "ptt":
                if not bancada.painel.desligado:
                    bancada.painel.modo = Modo.PTT
        bancada.volta()

        indicador = bancada.painel.ouvindo
        fonte_aberta = bancada.fonte.aberta
        assert indicador == fonte_aberta, (
            f"indicador={indicador} com fonte_aberta={fonte_aberta}: o indicador mentiu"
        )
        assert bancada.captura.aberta == fonte_aberta
        vistos.add((indicador, fonte_aberta))

    assert vistos == {(False, False), (True, True)}, (
        "a sequência precisa ter passado pelos dois estados, senão a propriedade é vazia"
    )


def test_kill_switch_zera_amostra_e_evento_e_a_ui_diz_que_esta_desligado(tmp_path: Path) -> None:
    """Aceite (c): zero amostra, zero evento, playback silenciado e a frase na tela."""
    bancada = montar(tmp_path, modo=Modo.ESCUTA)
    bancada.volta(quadros=10)
    # Guardado em local: `assert painel.ouvindo` estreitaria a propriedade para
    # `Literal[True]` e o mypy (warn_unreachable) chamaria o resto do teste de inalcançável.
    ouvia_antes = bancada.painel.ouvindo
    assert ouvia_antes, "antes de desligar, o microfone estava aberto"
    entregues = bancada.fonte.amostras_entregues
    eventos = bancada.eventos

    bancada.painel.desligar()
    for _ in range(20):
        bancada.volta(quadros=5)

    assert bancada.fonte.amostras_entregues == entregues, "o kill switch não deixa passar amostra"
    assert bancada.eventos == eventos, "zero evento novo"
    assert bancada.painel.ouvindo is False
    assert bancada.controle.silenciar_playback is True, "o kill switch corta o playback também"
    frase = bancada.painel.frase()
    assert "desligado" in frase.lower()
    assert bancada.painel.escrever_tela().startswith(frase)

    bancada.atalho.apertar()
    bancada.volta()
    assert bancada.painel.ouvindo is False, "nem a tecla reabre enquanto está desligado"

    bancada.painel.ligar()
    bancada.volta()
    assert bancada.painel.estado.modo is Modo.ESCUTA, "religar volta ao modo de antes"


def test_sem_dispositivo_a_ui_explica_e_oferece_o_modo_de_arquivo(tmp_path: Path) -> None:
    """Aceite (d): estado vazio útil, em uma frase, em vez de tela morta."""
    bancada = montar(tmp_path, modo=Modo.ESCUTA)
    bancada.fonte.erro_ao_abrir = DispositivoIndisponivel(
        "nenhum backend de captura instalado (sounddevice ausente)"
    )

    bancada.volta()

    assert bancada.painel.ouvindo is False
    assert bancada.painel.estado.indisponivel is not None
    frase = bancada.painel.frase()
    assert "arquivo" in frase.lower(), "a frase tem de oferecer o caminho que funciona"
    assert uma_frase(frase)


def test_estado_velho_nao_acende_o_indicador(tmp_path: Path) -> None:
    """Processo de áudio morto com a fonte aberta é a pior mentira: o indicador apaga."""
    bancada = montar(tmp_path, modo=Modo.ESCUTA)
    bancada.volta(quadros=3)
    ouvia_antes = bancada.painel.ouvindo
    assert ouvia_antes

    bancada.painel.agora = lambda: time.time() + 10 * bancada.painel.tolerancia_s

    assert bancada.painel.em_contato is False
    assert bancada.painel.ouvindo is False
    assert "contato" in bancada.painel.frase().lower()


def test_pedido_ilegivel_nao_abre_o_microfone(tmp_path: Path) -> None:
    """Na dúvida, fechado. Arquivo corrompido não pode virar microfone aberto."""
    escrever_pedido(tmp_path, Pedido(modo=Modo.ESCUTA))
    assert ler_pedido(tmp_path) == Pedido(modo=Modo.ESCUTA)

    (tmp_path / ARQUIVO_PEDIDO).write_text("{isto não é json", encoding="utf-8")
    assert ler_pedido(tmp_path) == Pedido(modo=Modo.DESLIGADO)

    (tmp_path / ARQUIVO_PEDIDO).write_text(json.dumps({"modo": "inventado"}), encoding="utf-8")
    assert ler_pedido(tmp_path) == Pedido(modo=Modo.DESLIGADO)


def test_pedido_ilegivel_fecha_a_fonte_aberta(tmp_path: Path) -> None:
    bancada = montar(tmp_path, modo=Modo.ESCUTA)
    bancada.volta(quadros=2)
    assert bancada.painel.ouvindo

    (tmp_path / ARQUIVO_PEDIDO).write_text("", encoding="utf-8")
    bancada.controle.tick()

    assert bancada.captura.aberta is False
    assert bancada.fonte.aberta is False


def test_o_painel_nao_tem_campo_para_acender_o_indicador(tmp_path: Path) -> None:
    """A regra é estrutural: `ouvindo` é propriedade derivada, sem setter."""
    painel = PainelDoMicrofone(raiz=tmp_path)

    with pytest.raises(AttributeError):
        painel.ouvindo = True  # type: ignore[misc]


def test_sem_estado_nenhum_o_indicador_fica_apagado(tmp_path: Path) -> None:
    painel = PainelDoMicrofone(raiz=tmp_path)

    assert painel.em_contato is False
    assert painel.ouvindo is False


@pytest.mark.parametrize(
    ("valor", "nome"),
    [("falso", "falso"), ("portal", "portal"), ("windows", "windows"), ("nenhum", "nenhum")],
)
def test_backend_de_atalho_vem_do_ambiente(valor: str, nome: str, tmp_path: Path) -> None:
    atalho = atalho_do_ambiente(raiz=tmp_path, ambiente={VARIAVEL_BACKEND: valor})

    assert atalho.nome == nome


def test_backend_de_atalho_desconhecido_e_erro_explicito(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="não existe"):
        atalho_do_ambiente(raiz=tmp_path, ambiente={VARIAVEL_BACKEND: "teclado-mágico"})


def test_atalho_falso_pode_vir_de_arquivo_para_outro_processo_apertar(tmp_path: Path) -> None:
    arquivo = tmp_path / "tecla"
    atalho = atalho_do_ambiente(
        ambiente={VARIAVEL_BACKEND: "falso", VARIAVEL_ARQUIVO: str(arquivo)}
    )
    assert isinstance(atalho, AtalhoFalso)

    solto_sem_arquivo = atalho.pressionado()
    arquivo.write_text("1", encoding="utf-8")
    apertado = atalho.pressionado()
    arquivo.write_text("0", encoding="utf-8")

    assert (solto_sem_arquivo, apertado, atalho.pressionado()) == (False, True, False)


def test_atalho_de_sistema_nao_derruba_a_ui_e_vira_frase(tmp_path: Path) -> None:
    """Portal e Windows são declarados e não implementados: a `ui` cai no botão da tela."""
    painel = PainelDoMicrofone(
        raiz=tmp_path, atalho=AtalhoDeSistema(nome="portal", detalhe="exige sessão gráfica")
    )

    with pytest.raises(AtalhoIndisponivel):
        AtalhoDeSistema(nome="portal").abrir()
    painel.abrir()

    assert painel.sem_atalho is not None
    assert painel.aviso is not None
    assert "botão da tela" in painel.aviso
    assert uma_frase(painel.aviso)
    assert painel.escrever_tela().splitlines() == [painel.frase(), painel.aviso]


def uma_frase(texto: str) -> bool:
    """O cartão pede **uma** frase: sem quebra de linha e com um ponto final só."""
    return "\n" not in texto and texto.endswith(".") and texto.count(".") == 1


@pytest.mark.parametrize("modo", [Modo.ESCUTA, Modo.PTT, Modo.DESLIGADO])
def test_toda_frase_do_painel_e_uma_frase(modo: Modo, tmp_path: Path) -> None:
    bancada = montar(tmp_path, modo=modo)
    frases = {bancada.painel.frase()}
    bancada.volta(quadros=2)
    frases.add(bancada.painel.frase())
    bancada.atalho.apertar()
    bancada.volta(quadros=2)
    frases.add(bancada.painel.frase())

    assert all(uma_frase(f) for f in frases), frases


def test_painel_sem_atalho_nunca_aperta(tmp_path: Path) -> None:
    painel = PainelDoMicrofone(raiz=tmp_path, atalho=SemAtalho(), modo=Modo.PTT)

    assert painel.tick() == Pedido(modo=Modo.PTT, pressionado=False)
    assert ler_pedido(tmp_path) == Pedido(modo=Modo.PTT, pressionado=False)
