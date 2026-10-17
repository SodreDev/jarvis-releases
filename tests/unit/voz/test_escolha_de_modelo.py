"""Escolha de modelo e de voz de nuvem: registro, portão, persistência e o caminho até o motor.

Sem rede: o que fala com "serviço" aqui é o `ServicoFalso` em porta efêmera, sob `CI=1`. O
que este arquivo prova é a corrente inteira da escolha do dono — registro → configuração →
arquivo → motor → pedido —, porque cada elo dela já falhou em silêncio uma vez: a janela
listava ids sem dizer que eram modelos, e o `voice_id` da ElevenLabs dividia campo com a voz
do piper.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.voz.app import motor_de_asr, motor_de_tts
from jarvis.voz.chaves import VARIAVEL_ELEVENLABS, VARIAVEL_GROQ, SegredoAusente
from jarvis.voz.config import (
    TTS_ELEVENLABS,
    VOZ_PADRAO,
    Configuracao,
    ConfiguracaoInvalida,
    escrever,
    ler,
    validar,
)
from jarvis.voz.elevenlabs import CABECALHO_DA_CHAVE, MotorTtsElevenLabs, listar_vozes
from jarvis.voz.interface import Onde
from jarvis.voz.nuvem import NuvemRealProibidaEmCI
from jarvis.voz.provedores import provedores
from jarvis.voz.registro import (
    ARQUIVO_MOTORES,
    MotorRecusado,
    exigir_modelo,
    exigir_motor,
    motor_registrado,
    motores_de,
)
from tests.unit.voz.servidor_falso import Roteiro, ServicoFalso
from tests.unit.voz.test_tela_config import Digitado, tela

SEGREDO = "sk_chave_de_teste_que_nao_pode_vazar_0123456789"
GROQ_V3 = "asr-groq-whisper-large-v3"
GROQ_TURBO = "asr-groq-whisper-large-v3-turbo"


# --- o registro ------------------------------------------------------------------------------


def test_a_groq_tem_um_motor_por_modelo_de_asr_que_a_doc_lista() -> None:
    """Conferido em 2026-10-16 nas páginas de speech-to-text e de modelos: só estes dois."""
    groq = [m for m in motores_de("asr", onde=Onde.NUVEM) if m.servico == "Groq"]

    assert sorted(m.modelo for m in groq) == ["whisper-large-v3", "whisper-large-v3-turbo"]
    assert all(m.preco and not m.campos_vazios for m in groq)


def test_a_elevenlabs_lista_so_modelos_com_portugues_no_endpoint_do_motor() -> None:
    motor = motor_registrado(TTS_ELEVENLABS)
    assert motor is not None

    assert motor.modelos_permitidos == ("eleven_flash_v2_5", "eleven_multilingual_v2", "eleven_v3")
    assert motor.fonte_dos_modelos.startswith("https://elevenlabs.io/docs/")
    assert motor.data_dos_modelos == "2026-10-16"
    # Os de fora ficam fora: dialogue-only, aposentados ou só inglês.
    for fora in ("eleven_v4", "eleven_v4_turbo", "eleven_turbo_v2_5", "eleven_flash_v2"):
        with pytest.raises(MotorRecusado, match="não está registrado"):
            exigir_modelo(motor, fora)


def test_modelo_vazio_e_o_padrao_do_registro() -> None:
    motor = motor_registrado(TTS_ELEVENLABS)
    assert motor is not None

    assert exigir_modelo(motor, "") == "eleven_flash_v2_5"  # o de menor latência (2026-10-16)
    assert exigir_modelo(motor, "eleven_v3") == "eleven_v3"


def test_lista_de_modelos_sem_fonte_barra_o_motor_no_portao(tmp_path: Path) -> None:
    """Modelo novo entra com procedência, ou não entra: a lista muda mais que o contrato."""
    registro = tmp_path / "motores.toml"
    texto = ARQUIVO_MOTORES.read_text(encoding="utf-8")
    registro.write_text(
        texto.replace('fonte_dos_modelos = "https://elevenlabs.io/docs/models"\n', ""),
        encoding="utf-8",
    )

    with pytest.raises(MotorRecusado, match="fonte_dos_modelos"):
        exigir_motor(TTS_ELEVENLABS, arquivo=registro, nuvem_ligada=[TTS_ELEVENLABS])


# --- a configuração --------------------------------------------------------------------------


def test_a_escolha_persiste_no_toml_e_volta_igual(tmp_path: Path) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    escolhida = Configuracao(
        asr=GROQ_V3,
        tts=TTS_ELEVENLABS,
        voz_elevenlabs="AbC123_voz-do-dono",
        modelo_elevenlabs="eleven_flash_v2_5",
        nuvem_ligada=(GROQ_V3, TTS_ELEVENLABS),
    )

    escrever(validar(escolhida), arquivo)

    assert ler(arquivo) == escolhida
    texto = arquivo.read_text(encoding="utf-8")
    assert 'asr = "asr-groq-whisper-large-v3"' in texto
    assert 'modelo_elevenlabs = "eleven_flash_v2_5"' in texto
    assert SEGREDO not in texto


def test_modelo_que_o_registro_nao_lista_recusa_o_arquivo(tmp_path: Path) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    arquivo.write_text('tts = "tts-elevenlabs"\nmodelo_elevenlabs = "eleven_v4"\n', "utf-8")

    with pytest.raises(ConfiguracaoInvalida, match="eleven_v4"):
        ler(arquivo)


@pytest.mark.parametrize("voz", ["../v1/user", "voz com espaço", "a?b=c", "x" * 65])
def test_voice_id_que_mudaria_a_url_recusa(voz: str) -> None:
    with pytest.raises(ConfiguracaoInvalida, match="voice_id"):
        validar(Configuracao(voz_elevenlabs=voz))


def test_arquivo_antigo_com_voice_id_em_voz_migra_para_o_campo_proprio(tmp_path: Path) -> None:
    """A tela de antes mandava pôr o voice_id em `voz`; o arquivo do dono pode ter isso."""
    arquivo = tmp_path / "jarvis-voz.toml"
    arquivo.write_text('tts = "tts-elevenlabs"\nvoz = "JBFqnCBsd6RMkjVDRZzb"\n', "utf-8")

    lida = ler(arquivo)

    assert lida.voz_elevenlabs == "JBFqnCBsd6RMkjVDRZzb"
    assert lida.voz == VOZ_PADRAO


def test_arquivo_antigo_com_voz_do_piper_nao_vira_voice_id(tmp_path: Path) -> None:
    """É o arquivo do dono hoje: ElevenLabs escolhida e a voz do piper no campo `voz`."""
    arquivo = tmp_path / "jarvis-voz.toml"
    arquivo.write_text('tts = "tts-elevenlabs"\nvoz = "pt_BR-faber-medium"\n', "utf-8")

    lida = ler(arquivo)

    assert lida.voz_elevenlabs == ""
    assert lida.voz == "pt_BR-faber-medium"


# --- provedor → modelo -----------------------------------------------------------------------


def test_a_groq_aparece_como_um_provedor_com_dois_modelos() -> None:
    config = Configuracao(asr=GROQ_V3, nuvem_ligada=(GROQ_V3,))

    groq = next(p for p in provedores(config, "asr") if p.nome == "Groq")

    assert groq.escolhido and groq.ligado and groq.motor == GROQ_V3
    assert [(o.modelo, o.campo, o.valor, o.escolhido) for o in groq.modelos] == [
        ("whisper-large-v3-turbo", "asr", GROQ_TURBO, False),
        ("whisper-large-v3", "asr", GROQ_V3, True),
    ]
    assert all(o.nota.startswith("US$") for o in groq.modelos)


def test_trocar_o_modelo_da_groq_nao_herda_o_interruptor() -> None:
    """Cada modelo é um motor com preço próprio no aviso: ligar é por motor (ADR-0017)."""
    config = Configuracao(asr=GROQ_V3, nuvem_ligada=(GROQ_TURBO,))

    groq = next(p for p in provedores(config, "asr") if p.nome == "Groq")

    assert groq.motor == GROQ_V3 and not groq.ligado
    assert "asr-groq-whisper-large-v3 ligado" in groq.aviso


def test_provedor_nao_escolhido_aponta_para_o_que_o_dono_ja_ligou() -> None:
    config = Configuracao(nuvem_ligada=(GROQ_V3,))

    groq = next(p for p in provedores(config, "asr") if p.nome == "Groq")

    assert not groq.escolhido and groq.motor == GROQ_V3


def test_a_elevenlabs_escolhe_modelo_pelo_campo_proprio() -> None:
    config = Configuracao(tts=TTS_ELEVENLABS, modelo_elevenlabs="eleven_v3")

    eleven = next(p for p in provedores(config, "tts") if p.nome == "ElevenLabs")

    assert [(o.modelo, o.campo, o.valor, o.escolhido) for o in eleven.modelos] == [
        ("eleven_flash_v2_5", "modelo_elevenlabs", "", False),
        ("eleven_multilingual_v2", "modelo_elevenlabs", "eleven_multilingual_v2", False),
        ("eleven_v3", "modelo_elevenlabs", "eleven_v3", True),
    ]


def test_motor_local_nao_ganha_seletor_nem_aviso() -> None:
    piper = next(p for p in provedores(Configuracao(), "tts") if p.chave == "tts-piper-epitran")

    assert piper.escolhido and piper.ligado and piper.modelos == () and piper.aviso == ""


# --- a escolha chega ao motor do laço --------------------------------------------------------


def _ambiente_do_dono() -> dict[str, str]:
    """Sem `CI`: é o caminho do dono. Nenhum teste aqui chama `transcrever` nem `sintetizar`
    com a base real — abrir o motor não abre socket (`MotorAsrGroq.abrir`)."""
    return {VARIAVEL_GROQ: "gsk_" + "x" * 40, VARIAVEL_ELEVENLABS: SEGREDO}


def test_o_laco_monta_a_groq_com_o_modelo_escolhido(tmp_path: Path) -> None:
    config = Configuracao(asr=GROQ_V3, nuvem_ligada=(GROQ_V3,))

    motor = motor_de_asr(
        config, raiz=tmp_path, cancelado=lambda: False, ambiente=_ambiente_do_dono()
    )

    assert motor.nome == "groq@whisper-large-v3"


def test_o_laco_monta_a_elevenlabs_com_a_voz_e_o_modelo_escolhidos(tmp_path: Path) -> None:
    config = Configuracao(
        tts=TTS_ELEVENLABS,
        voz_elevenlabs="vozDoDono42",
        modelo_elevenlabs="eleven_flash_v2_5",
        nuvem_ligada=(TTS_ELEVENLABS,),
    )

    motor = motor_de_tts(
        config, raiz=tmp_path, cancelado=lambda: False, ambiente=_ambiente_do_dono()
    )

    assert isinstance(motor, MotorTtsElevenLabs)
    assert (motor.voz, motor.modelo) == ("vozDoDono42", "eleven_flash_v2_5")


def test_o_modelo_escolhido_vai_no_pedido(tmp_path: Path) -> None:
    with ServicoFalso(Roteiro(corpo=b"\x00\x01" * 160, tipo="application/octet-stream")) as servico:
        motor = MotorTtsElevenLabs(
            raiz=tmp_path,
            voz="vozDoDono42",
            modelo="eleven_v3",
            base=servico.base,
            nuvem_ligada=[TTS_ELEVENLABS],
            ambiente={"CI": "1", VARIAVEL_ELEVENLABS: SEGREDO},
        )
        motor.sintetizar("Bom dia.")

    pedido = servico.pedidos[0]
    assert pedido.caminho.startswith("/v1/text-to-speech/vozDoDono42?")
    assert json.loads(pedido.corpo)["model_id"] == "eleven_v3"


def test_modelo_fora_do_registro_nao_abre_o_motor(tmp_path: Path) -> None:
    motor = MotorTtsElevenLabs(
        raiz=tmp_path,
        voz="vozDoDono42",
        modelo="eleven_v4",
        nuvem_ligada=[TTS_ELEVENLABS],
        ambiente={"CI": "1", VARIAVEL_ELEVENLABS: SEGREDO},
    )

    with pytest.raises(MotorRecusado, match="eleven_v4"):
        motor.abrir()


# --- as vozes da conta -----------------------------------------------------------------------


def _pagina(vozes: list[dict[str, object]], *, ficha: str | None) -> bytes:
    return json.dumps(
        {"voices": vozes, "has_more": ficha is not None, "next_page_token": ficha}
    ).encode()


def test_lista_as_vozes_paginando_com_a_chave_no_cabecalho() -> None:
    paginas = [
        _pagina(
            [
                {"voice_id": "zzEnglish1", "name": "Zed", "labels": {"language": "en"}},
                {"voice_id": "../fora", "name": "Malformada"},
            ],
            ficha="pag2",
        ),
        _pagina(
            [
                {
                    "voice_id": "ptVoz2",
                    "name": "Clara",
                    "category": "professional",
                    "verified_languages": [{"language": "pt", "accent": "brazilian"}],
                }
            ],
            ficha=None,
        ),
    ]
    with ServicoFalso(Roteiro(paginas=paginas)) as servico:
        vozes = listar_vozes(base=servico.base, ambiente={"CI": "1", VARIAVEL_ELEVENLABS: SEGREDO})

    # Português primeiro; o id malformado (iria no caminho da URL) fica fora.
    assert [v.id for v in vozes] == ["ptVoz2", "zzEnglish1"]
    assert vozes[0].fala_portugues and vozes[0].categoria == "professional"
    assert len(servico.pedidos) == 2
    assert servico.pedidos[0].caminho.startswith("/v2/voices?page_size=100")
    assert "next_page_token=pag2" in servico.pedidos[1].caminho
    for pedido in servico.pedidos:
        assert pedido.cabecalho(CABECALHO_DA_CHAVE) == SEGREDO
        assert SEGREDO not in pedido.caminho
    assert SEGREDO not in repr(vozes)


def test_listar_vozes_sem_chave_diz_qual_variavel_falta() -> None:
    with pytest.raises(SegredoAusente, match=VARIAVEL_ELEVENLABS):
        listar_vozes(base="http://127.0.0.1:9", ambiente={"CI": "1"})


def test_listar_vozes_nunca_fala_com_a_nuvem_de_verdade_sob_ci() -> None:
    with pytest.raises(NuvemRealProibidaEmCI):
        listar_vozes(ambiente={"CI": "1", VARIAVEL_ELEVENLABS: SEGREDO})


# --- `jarvis-voz config` ---------------------------------------------------------------------


def test_o_terminal_escolhe_o_modelo_da_elevenlabs_da_lista_do_registro(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["11", "3", "s"])

    config.rodar()

    assert ler(tmp_path / "jarvis-voz.toml").modelo_elevenlabs == "eleven_v3"
    assert any("eleven_flash_v2_5" in linha for linha in linhas)


def test_o_terminal_lista_as_vozes_da_conta_e_grava_o_id(tmp_path: Path) -> None:
    from jarvis.voz.elevenlabs import VozDaConta

    config, linhas = tela(tmp_path, [])
    config.listar_vozes = lambda: [VozDaConta(id="ptVoz2", nome="Clara", idiomas=("pt",))]
    config.entrada = Digitado(["10", "l", "1", "s"])

    config.rodar()

    assert ler(tmp_path / "jarvis-voz.toml").voz_elevenlabs == "ptVoz2"
    assert any("Clara  (ptVoz2, pt)" in linha for linha in linhas)


def test_o_terminal_recusa_voice_id_malformado(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["10", "a/b", "s"])

    config.rodar()

    assert ler(tmp_path / "jarvis-voz.toml").voz_elevenlabs == ""
    assert any("forma de um voice_id" in linha for linha in linhas)


def test_o_terminal_mostra_o_preco_de_cada_modelo_da_groq(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["1", "", "q"])

    config.rodar()

    assert any(GROQ_TURBO in linha and "US$ 0,04" in linha for linha in linhas)
    assert any(GROQ_V3 in linha and "US$ 0,111" in linha for linha in linhas)
