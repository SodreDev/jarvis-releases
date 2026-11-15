"""TTS por endpoint HTTP configurável (ADR-0068), contra um servidor falso em 127.0.0.1.

Nada aqui fala com a rede do dono: o preset «JARVIS-BR (phonon-web)» aponta para a máquina dele,
e o único teste que o abre prova justamente que sob `CI=1` ele é recusado **antes** do socket.
"""

from __future__ import annotations

import base64
import io
import json
import socket
import struct
import threading
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.audio_io.quadro import TAXA_PADRAO, de_int16
from jarvis.voz import endpoint as ep
from jarvis.voz.chaves import SegredoAusente
from jarvis.voz.config import Configuracao, ConfiguracaoInvalida, escrever, ler, validar
from jarvis.voz.endpoint import (
    Endpoint,
    EndpointInvalido,
    MotorComReservaDeRede,
    MotorTtsEndpoint,
    RedirecionamentoRecusado,
)
from jarvis.voz.interface import Onde
from jarvis.voz.nuvem import NuvemRealProibidaEmCI, ServicoRecusou
from jarvis.voz.registro import MotorRecusado
from tests.unit.voz.endpoint_falso import EndpointFalso, Rota

MOTOR = "tts-endpoint"
SEM_ARQUIVO_DO_DONO = Path(__file__).with_name("nao-existe-tts-endpoints.toml")
"""A suíte nunca lê o `~/.config/jarvis/tts-endpoints.toml` do dono."""
SEGREDO = "chave-do-endpoint-de-teste-que-nao-pode-vazar-0123"


def pcm(amostras: int, valor: int = 1000) -> bytes:
    return de_int16([valor] * amostras)


def endpoint_em(servidor: EndpointFalso, **mudancas: object) -> Endpoint:
    base = Endpoint(
        nome="falso",
        base=servidor.base,
        caminho="/api/tts",
        caminho_stream="/api/tts/stream",
        formato="pcm",
        taxa=24000,
        voz="jarvis-br",
        estilo="cordial",
        estilos=("cordial", "calmo", "urgente"),
        prazo_s=3.0,
    )
    return ep.conferir(replace(base, **mudancas))  # type: ignore[arg-type]


def motor_em(
    servidor: EndpointFalso, ambiente: dict[str, str] | None = None, **mudancas: object
) -> MotorTtsEndpoint:
    motor = MotorTtsEndpoint(
        endpoint=endpoint_em(servidor, **mudancas),
        nuvem_ligada=[MOTOR],
        ambiente=ambiente if ambiente is not None else {"CI": "1"},
    )
    motor.abrir()
    return motor


def porta_fechada() -> int:
    with socket.socket() as soquete:
        soquete.bind(("127.0.0.1", 0))
        return int(soquete.getsockname()[1])


# --- o endpoint e o arquivo -----------------------------------------------------------------------


def test_o_preset_do_dono_vem_pronto_e_valido() -> None:
    preset = ep.escolher("", arquivo=SEM_ARQUIVO_DO_DONO)
    assert preset.nome == "JARVIS-BR (phonon-web)"
    assert (preset.caminho, preset.caminho_stream, preset.metodo) == (
        "/api/tts",
        "/api/tts/stream",
        "POST",
    )
    assert (preset.voz, preset.estilo, preset.formato, preset.taxa, preset.canais) == (
        "jarvis-br",
        "cordial",
        "pcm",
        24000,
        1,
    )
    assert preset.estilos == ("cordial", "calmo", "urgente", "ironico", "seco")
    assert preset.autenticacao == "nenhuma"
    assert ep.escolher("jarvis-br (PHONON-WEB)", arquivo=SEM_ARQUIVO_DO_DONO) == preset


def test_sob_ci_o_preset_do_dono_nao_abre_socket(tmp_path: Path) -> None:
    """A rede do dono nunca entra na suíte: o portão de CI recusa antes de conectar."""
    motor = MotorTtsEndpoint(
        endpoint=ep.escolher("", arquivo=SEM_ARQUIVO_DO_DONO),
        nuvem_ligada=[MOTOR],
        ambiente={"CI": "1"},
    )
    with pytest.raises(NuvemRealProibidaEmCI):
        motor.abrir()


def test_desligado_nao_abre() -> None:
    with EndpointFalso() as servidor:
        motor = MotorTtsEndpoint(endpoint=endpoint_em(servidor), ambiente={"CI": "1"})
        with pytest.raises(MotorRecusado, match="desligado"):
            motor.abrir()
        assert servidor.pedidos == []


@pytest.mark.parametrize(
    ("campo", "valor", "motivo"),
    [
        ("base", "ftp://127.0.0.1:1", "http"),
        ("base", "http://dono:senha@127.0.0.1:1", "usuário"),
        ("base", "http://127.0.0.1:1/?x=1", "consulta"),
        ("base", "http://127.0.0.1:1#a", "fragmento"),
        ("caminho", "//outro.host/api", "barra"),
        ("caminho", "@outro.host/api", "barra"),
        ("caminho", "api/tts", "barra"),
        ("caminho_stream", "/a b", "barra"),
        ("corpo", '{"voice": "{voz}"}', "{texto}"),
        ("corpo", '{"text": "{texto}", "x": "{senha}"}', "não existe"),
        ("corpo", "[1, 2]", "objeto"),
        ("formato", "flac", "válidos"),
        ("taxa", 100, "fora"),
        ("autenticacao", "bearer", "variavel_de_ambiente"),
        ("cabecalhos", (("Authorization", "Bearer x"),), "autenticacao"),
        ("cabecalhos", (("X-Api-Token", "abc"),), "autenticacao"),
        ("metodo", "GET", "válidos"),
    ],
)
def test_o_endpoint_recusa_o_que_mandaria_o_texto_para_outro_lugar(
    campo: str, valor: object, motivo: str
) -> None:
    correto = Endpoint(nome="x", base="http://127.0.0.1:1")
    with pytest.raises(EndpointInvalido, match=motivo):
        ep.conferir(replace(correto, **{campo: valor}))  # type: ignore[arg-type]


def test_a_url_montada_e_sempre_do_servidor_da_base() -> None:
    endpoint = ep.conferir(Endpoint(nome="x", base="http://127.0.0.1:5/raiz/"))
    assert endpoint.url("/api/tts?f=pcm") == "http://127.0.0.1:5/raiz/api/tts?f=pcm"
    with pytest.raises(EndpointInvalido):
        endpoint.url("@evil.example/x")


def test_o_arquivo_do_dono_vence_pelo_nome_e_grava_sem_segredo(tmp_path: Path) -> None:
    arquivo = tmp_path / "tts-endpoints.toml"
    preset = ep.escolher("", arquivo=arquivo)
    meu = ep.com_campo(preset, "base", "http://127.0.0.1:20202")
    ep.gravar(meu, arquivo=arquivo)
    outro = Endpoint(
        nome="Outra API",
        base="https://tts.exemplo.org",
        corpo='{"input": {"text": "{texto}"}, "voice_id": "{voz}", "sample_rate": "{taxa}"}',
        autenticacao="bearer",
        variavel_de_ambiente="OUTRA_TTS_API_KEY",
    )
    ep.gravar(outro, arquivo=arquivo)
    lista = ep.todos(arquivo=arquivo)
    assert [e.nome for e in lista] == ["JARVIS-BR (phonon-web)", "Outra API"]
    assert lista[0].base == "http://127.0.0.1:20202"
    assert lista[1] == ep.conferir(outro)
    texto = arquivo.read_text(encoding="utf-8")
    assert "OUTRA_TTS_API_KEY" in texto and SEGREDO not in texto


def test_arquivo_do_dono_com_campo_estranho_ou_chave_e_recusado(tmp_path: Path) -> None:
    arquivo = tmp_path / "tts-endpoints.toml"
    arquivo.write_text(
        '[[endpoint]]\nnome = "x"\nbase = "http://127.0.0.1:1"\ncaminho_strem = "/s"\n', "utf-8"
    )
    with pytest.raises(EndpointInvalido, match="caminho_strem"):
        ep.todos(arquivo=arquivo)
    arquivo.write_text(
        '[[endpoint]]\nnome = "x"\nbase = "http://127.0.0.1:1"\n'
        'nota = "sk-abcdefghijklmnopqrstu"\n',
        "utf-8",
    )
    with pytest.raises(EndpointInvalido, match="chave"):
        ep.todos(arquivo=arquivo)


def test_com_campo_converte_o_texto_da_janela() -> None:
    preset = ep.escolher("", arquivo=SEM_ARQUIVO_DO_DONO)
    assert ep.com_campo(preset, "taxa", "22050").taxa == 22050
    assert ep.com_campo(preset, "prazo_s", "2,5").prazo_s == 2.5
    assert ep.com_campo(preset, "estilos", "calmo, seco,calmo").estilos == ("calmo", "seco")
    with pytest.raises(EndpointInvalido):
        ep.com_campo(preset, "nome", "outro")


# --- o corpo --------------------------------------------------------------------------------------


def test_o_molde_preenche_com_o_tipo_certo_e_tira_o_vazio() -> None:
    endpoint = ep.conferir(
        Endpoint(
            nome="x",
            base="http://127.0.0.1:1",
            corpo='{"t": "{texto}", "v": "{voz}", "s": "{estilo}", "r": "{taxa}", '
            '"o": {"fmt": "audio/{formato}"}, "l": ["{estilo}", "x"]}',
        )
    )
    corpo = json.loads(ep.montar_corpo(endpoint, texto='Diz "oi"', voz="", estilo="calmo"))
    assert corpo == {
        "t": 'Diz "oi"',
        "s": "calmo",
        "r": 24000,
        "o": {"fmt": "audio/pcm"},
        "l": ["calmo", "x"],
    }


# --- o pedido -------------------------------------------------------------------------------------


def test_sintetiza_pelo_stream_e_reamostra_para_16k() -> None:
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(corpo=pcm(24000), pedacos=6, chunked=True)
        motor = motor_em(servidor)
        amostras = motor.sintetizar("Olá, tudo bem?")
    assert len(amostras) // 2 == pytest.approx(TAXA_PADRAO, abs=2)
    pedido = servidor.de("/api/tts/stream")[0]
    assert json.loads(pedido.corpo) == {
        "text": "Olá, tudo bem?",
        "voice": "jarvis-br",
        "style": "cordial",
        "format": "pcm",
    }
    assert not pedido.cabecalho("Authorization")
    assert motor.pelo_stream == 1 and servidor.de("/api/tts") == []


def test_sem_rota_de_stream_cai_no_caminho_comum_uma_vez() -> None:
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts"] = Rota(corpo=pcm(2400))
        motor = motor_em(servidor)
        assert motor.sintetizar("um")
        assert motor.sintetizar("dois")
    assert motor.sem_stream
    assert len(servidor.de("/api/tts/stream")) == 1
    assert len(servidor.de("/api/tts")) == 2


def test_bearer_vai_so_no_cabecalho_e_o_erro_nao_mostra_a_chave() -> None:
    ambiente = {"CI": "1", "MINHA_TTS_API_KEY": SEGREDO}
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(status=401, corpo=f"chave {SEGREDO} ruim".encode())
        motor = motor_em(
            servidor,
            ambiente,
            autenticacao="bearer",
            variavel_de_ambiente="MINHA_TTS_API_KEY",
        )
        with pytest.raises(ServicoRecusou) as erro:
            motor.sintetizar("oi")
    assert SEGREDO not in str(erro.value)
    pedido = servidor.pedidos[0]
    assert pedido.cabecalho("Authorization") == f"Bearer {SEGREDO}"
    assert SEGREDO.encode() not in pedido.corpo and SEGREDO not in pedido.caminho


def test_cabecalho_proprio_e_chave_ausente() -> None:
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(corpo=pcm(240))
        motor = motor_em(
            servidor,
            {"CI": "1", "MINHA_TTS_API_KEY": SEGREDO},
            autenticacao="cabecalho",
            cabecalho="X-Chave-Da-Voz",
            variavel_de_ambiente="MINHA_TTS_API_KEY",
        )
        motor.sintetizar("oi")
        assert servidor.pedidos[0].cabecalho("X-Chave-Da-Voz") == SEGREDO
        sem_chave = MotorTtsEndpoint(
            endpoint=motor.endpoint, nuvem_ligada=[MOTOR], ambiente={"CI": "1"}
        )
        with pytest.raises(SegredoAusente, match="MINHA_TTS_API_KEY"):
            sem_chave.abrir()


def test_redirecionamento_nao_e_seguido() -> None:
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(
            status=302, cabecalhos={"Location": "http://outro.exemplo/roubo?texto=oi"}
        )
        motor = motor_em(servidor)
        with pytest.raises(RedirecionamentoRecusado, match=r"outro\.exemplo/roubo") as erro:
            motor.sintetizar("segredo do dono")
    assert "texto=oi" not in str(erro.value)
    assert len(servidor.pedidos) == 1


def test_cancelar_no_meio_do_stream_descarta_e_fecha() -> None:
    cancelado = threading.Event()
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(
            corpo=pcm(24000 * 2), pedacos=12, pausa_s=0.05, chunked=True
        )
        motor = motor_em(servidor)
        motor.cancelado = cancelado.is_set
        threading.Timer(0.12, cancelado.set).start()
        assert motor.sintetizar("uma frase longa") == b""
    assert motor.descartadas_por_cancelamento == 1
    assert motor.bytes_descartados > 0


def test_cancelado_antes_nem_manda_o_texto() -> None:
    with EndpointFalso() as servidor:
        motor = motor_em(servidor)
        motor.cancelado = lambda: True
        assert motor.sintetizar("oi") == b""
    assert servidor.pedidos == []


def test_json_de_erro_com_200_vira_recusa_e_json_com_audio_serve() -> None:
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(corpo=b'{"erro": "voz?"}', tipo="application/json")
        motor = motor_em(servidor)
        with pytest.raises(ServicoRecusou, match="JSON"):
            motor.sintetizar("oi")
        audio = base64.b64encode(pcm(1600)).decode()
        servidor.rotas["/api/tts/stream"] = Rota(
            corpo=json.dumps({"audio": audio}).encode(), tipo="application/json"
        )
        motor = motor_em(servidor, taxa=16000)
        assert len(motor.sintetizar("oi")) == 3200


def test_pcm_que_comeca_com_chave_nao_e_confundido_com_json() -> None:
    corpo = b"{" + pcm(800)[1:]
    assert len(ep.para_pcm16(corpo, formato="pcm", taxa=16000, canais=1)) == 1600


def test_wav_estereo_44k_vira_16k_mono() -> None:
    memoria = io.BytesIO()
    with wave.open(memoria, "wb") as arquivo:
        arquivo.setnchannels(2)
        arquivo.setsampwidth(2)
        arquivo.setframerate(44100)
        arquivo.writeframes(struct.pack("<hh", 1000, 3000) * 44100)
    amostras = ep.para_pcm16(memoria.getvalue(), formato="wav", taxa=0, canais=0)
    assert len(amostras) // 2 == pytest.approx(16000, abs=2)
    meio = struct.unpack("<h", amostras[16000:16002])[0]
    assert meio == pytest.approx(2000, abs=5)


def test_texto_html_em_vez_de_audio_e_recusado() -> None:
    with pytest.raises(ServicoRecusou, match="texto"):
        ep.para_pcm16(b"<html>erro</html>", formato="pcm", taxa=24000, canais=1, tipo="text/html")


# --- a reserva ------------------------------------------------------------------------------------


class Reserva:
    nome = "reserva"
    voz = "padrao"
    licenca = "MIT"
    onde = Onde.LOCAL

    def __init__(self) -> None:
        self.textos: list[str] = []

    def sintetizar(self, texto: str) -> bytes:
        self.textos.append(texto)
        return pcm(160, valor=7)


class Relogio:
    def __init__(self) -> None:
        self.agora = 100.0

    def __call__(self) -> float:
        return self.agora


def test_fora_da_rede_a_reserva_fala_o_mesmo_trecho_e_volta_depois() -> None:
    reserva, relogio = Reserva(), Relogio()
    avisos: list[str] = []
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(corpo=pcm(2400))
        principal = motor_em(servidor)
        vivo = principal.endpoint
        principal.endpoint = replace(vivo, base=f"http://127.0.0.1:{porta_fechada()}")
        motor = MotorComReservaDeRede(
            principal=principal,
            fabricar_reserva=lambda: reserva,
            relogio=relogio,
            ao_avisar=avisos.append,
        )
        assert motor.sintetizar("primeira frase") == pcm(160, valor=7)
        assert motor.sintetizar("segunda frase") == pcm(160, valor=7)
        assert reserva.textos == ["primeira frase", "segunda frase"]
        caido = motor.na_reserva
        assert len(avisos) == 1 and "reserva" in avisos[0] and caido
        # O servidor voltou (a máquina ligou), e o prazo de retentar passou.
        principal.endpoint = vivo
        relogio.agora += ep.RETENTAR_EM_S + 1
        assert len(motor.sintetizar("terceira")) == 3200
    assert "voltou" in avisos[-1]
    assert not motor.na_reserva
    assert motor.quedas == 1


def test_erro_do_servidor_no_meio_nao_deixa_o_jarvis_mudo() -> None:
    reserva = Reserva()
    avisos: list[str] = []
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(status=500, corpo=b"caiu")
        motor = MotorComReservaDeRede(
            principal=motor_em(servidor), fabricar_reserva=lambda: reserva, ao_avisar=avisos.append
        )
        assert motor.sintetizar("oi") == pcm(160, valor=7)
        assert motor.sintetizar("tudo bem") == pcm(160, valor=7)
    assert reserva.textos == ["oi", "tudo bem"]
    assert len(servidor.pedidos) == 1  # na janela de retentar, nem tenta
    assert len(avisos) == 1


def test_prazo_curto_estourado_cai_na_reserva() -> None:
    reserva = Reserva()
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(corpo=pcm(240), atraso_s=1.5)
        motor = MotorComReservaDeRede(
            principal=motor_em(servidor, prazo_s=0.5), fabricar_reserva=lambda: reserva
        )
        assert motor.sintetizar("oi") == pcm(160, valor=7)
    assert reserva.textos == ["oi"]


def test_cancelado_no_endpoint_nao_chama_a_reserva() -> None:
    reserva = Reserva()
    with EndpointFalso() as servidor:
        principal = motor_em(servidor)
        principal.cancelado = lambda: True
        motor = MotorComReservaDeRede(principal=principal, fabricar_reserva=lambda: reserva)
        assert motor.sintetizar("oi") == b""
    assert reserva.textos == []


def test_motor_endpoint_mal_configurado_ja_nasce_na_reserva(tmp_path: Path) -> None:
    reserva = Reserva()
    motor = ep.motor_endpoint(
        nome="não existe",
        voz="",
        estilo="",
        nuvem_ligada=[MOTOR],
        reserva=lambda: reserva,
        ambiente={"CI": "1"},
        arquivo=tmp_path / "nenhum.toml",
    )
    assert motor.principal is None and "não existe" in motor.observacao
    assert motor.sintetizar("oi") == pcm(160, valor=7)


# --- a configuração -------------------------------------------------------------------------------


def test_os_campos_do_endpoint_vao_e_voltam_do_arquivo(tmp_path: Path) -> None:
    caminho = tmp_path / "jarvis-voz.toml"
    configuracao = Configuracao(
        tts=MOTOR,
        nuvem_ligada=(MOTOR,),
        endpoint_tts="JARVIS-BR (phonon-web)",
        voz_endpoint="jarvis-br",
        estilo_endpoint="calmo",
        reserva_do_endpoint="tts-parametrico",
    )
    escrever(configuracao, caminho)
    assert ler(caminho) == configuracao


@pytest.mark.parametrize(
    "mudanca",
    [
        {"reserva_do_endpoint": MOTOR},
        {"reserva_do_endpoint": "asr-whisper-local"},
        {"estilo_endpoint": 'cal"mo'},
        {"endpoint_tts": "../fora"},
    ],
)
def test_a_configuracao_recusa_o_que_nao_serve(mudanca: dict[str, str]) -> None:
    with pytest.raises(ConfiguracaoInvalida):
        validar(Configuracao().com(**mudanca))


# --- o estilo pela voz ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fala", "estilo"),
    [
        ("fala mais calmo", "calmo"),
        ("Jarvis, fala de forma calma, por favor", "calmo"),
        ("tom urgente", "urgente"),
        ("muda o tom para urgente", "urgente"),
        ("usa o estilo irônico", "ironico"),
        ("fala de um jeito mais seco", "seco"),
        ("volta ao normal", "cordial"),
        ("fala comigo", None),
        ("urgente", None),
        ("fala sobre o tempo amanhã", None),
        ("abre o Discord", None),
    ],
)
def test_o_estilo_pedido_pela_voz(fala: str, estilo: str | None) -> None:
    estilos = ("cordial", "calmo", "urgente", "ironico", "seco")
    assert ep.comando_de_estilo(fala, estilos, "cordial") == estilo


def test_sem_estilos_no_endpoint_nada_e_comando() -> None:
    assert ep.comando_de_estilo("fala mais calmo", ()) is None


# --- no laço -----------------------------------------------------------------------------------


def _configurar_o_dono(tmp_path: Path, base: str) -> dict[str, str]:
    """O arquivo do dono numa pasta temporária, com a base apontando para o servidor falso."""
    arquivo = tmp_path / "jarvis" / ep.NOME_DO_ARQUIVO
    preset = ep.escolher("", arquivo=arquivo)
    ep.gravar(ep.com_campo(preset, "base", base), arquivo=arquivo)
    return {"CI": "1", "XDG_CONFIG_HOME": str(tmp_path)}


def test_o_app_monta_o_endpoint_com_o_estilo_do_dono(tmp_path: Path) -> None:
    from jarvis.voz.app import motor_de_tts

    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(corpo=pcm(2400))
        ambiente = _configurar_o_dono(tmp_path, servidor.base)
        configuracao = Configuracao(
            tts=MOTOR,
            nuvem_ligada=(MOTOR,),
            estilo_endpoint="calmo",
            reserva_do_endpoint="tts-parametrico",
        )
        motor = motor_de_tts(
            configuracao, raiz=tmp_path / "sessao", cancelado=lambda: False, ambiente=ambiente
        )
        assert isinstance(motor, MotorComReservaDeRede) and motor.principal is not None
        assert len(motor.sintetizar("oi")) == 3200
    assert json.loads(servidor.pedidos[-1].corpo)["style"] == "calmo"


def test_o_app_com_o_endpoint_desligado_fala_pela_reserva_sem_pedido(tmp_path: Path) -> None:
    from jarvis.voz.app import motor_de_tts

    with EndpointFalso() as servidor:
        ambiente = _configurar_o_dono(tmp_path, servidor.base)
        configuracao = Configuracao(tts=MOTOR, reserva_do_endpoint="tts-parametrico")
        motor = motor_de_tts(
            configuracao, raiz=tmp_path / "sessao", cancelado=lambda: False, ambiente=ambiente
        )
        assert isinstance(motor, MotorComReservaDeRede) and motor.principal is None
        assert "desligado" in motor.observacao
        assert motor.sintetizar("oi")
    assert servidor.pedidos == []


def test_barge_in_no_meio_do_stream_nao_publica_nada(tmp_path: Path) -> None:
    """ADR-0040: o dono cortou, o pedido em voo é abandonado e nenhum pedaço chega à fila."""
    from jarvis.agentd.tts import SintetizadorEmStreaming

    cancelado = threading.Event()
    reserva = Reserva()
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts/stream"] = Rota(
            corpo=pcm(48000), pedacos=20, pausa_s=0.05, chunked=True
        )
        principal = motor_em(servidor)
        principal.cancelado = cancelado.is_set
        motor = MotorComReservaDeRede(principal=principal, fabricar_reserva=lambda: reserva)
        sintetizador = SintetizadorEmStreaming(motor=motor, cancelado=cancelado.is_set)
        threading.Timer(0.2, cancelado.set).start()
        pedacos = list(sintetizador.pedacos("Uma frase longa. Outra frase. Mais uma."))
    assert pedacos == []
    assert reserva.textos == []
    assert principal.descartadas_por_cancelamento >= 1
