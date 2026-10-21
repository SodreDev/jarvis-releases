"""Guardas de clonagem do OmniVoice (ADR-0039) e o opt-in na configuração do dono.

O model card proíbe "unauthorized voice cloning, voice impersonation, fraud, scams". O que este
arquivo prova, por comportamento e por varredura:

- só vale voz **cadastrada pelo dono**, com a declaração "a voz é minha" ou "tenho permissão do
  titular" — e com o sha256 do áudio declarado (trocar o áudio invalida);
- cadastrar só aceita arquivo local, fora das pastas onde o Jarvis grava e baixa sozinho: nada
  de URL, nada de captura, nada de download;
- não existe ferramenta do assistente que cadastre ou clone voz, e as ferramentas de arquivo não
  alcançam as pastas das vozes e do motor (lista de negação da política);
- a configuração nasce com tudo desligado, e `escrever` não perde a declaração do dono.
"""

from __future__ import annotations

import math
import re
import wave
from pathlib import Path

import pytest
from tools.instalar_omnivoice import AVISO_DE_CLONAGEM, main

from jarvis.politica.canonicalizacao import Sistema, canonicalizar
from jarvis.politica.modos import motivo_de_negacao
from jarvis.voz.cli import diagnosticar
from jarvis.voz.config import Configuracao, ConfiguracaoInvalida, escrever, ler, validar
from jarvis.voz.omnivoice import (
    ARQUIVO_DA_DECLARACAO,
    VozDeReferencia,
    VozNaoAutorizada,
    cadastrar_voz,
    ler_voz,
    linhas_do_diagnostico,
    remover_voz,
    vozes_cadastradas,
)
from jarvis.voz.prontidao import o_que_falta
from jarvis.voz.provedores import provedores

RAIZ = Path(__file__).resolve().parents[3]


def gravar_wav(caminho: Path, segundos: float, taxa: int = 16_000) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(taxa)
        arquivo.writeframes(
            b"".join(
                int(6000 * math.sin(2 * math.pi * 200 * i / taxa)).to_bytes(
                    2, "little", signed=True
                )
                for i in range(int(segundos * taxa))
            )
        )
    return caminho


@pytest.fixture
def casa(tmp_path: Path) -> Path:
    return tmp_path / "casa"


@pytest.fixture
def ambiente(casa: Path) -> dict[str, str]:
    return {"HOME": str(casa)}


@pytest.fixture
def gravacao(tmp_path: Path) -> Path:
    return gravar_wav(tmp_path / "Gravações" / "eu.wav", 4.0)


def cadastrar(
    gravacao: Path,
    ambiente: dict[str, str],
    *,
    nome: str = "minha",
    audio: str = "",
    texto: str = "Esta é a minha voz.",
    declaracao: str = "minha",
    titular: str = "",
) -> VozDeReferencia:
    return cadastrar_voz(
        nome,
        audio=audio or str(gravacao),
        texto=texto,
        declaracao=declaracao,
        titular=titular,
        agora="2026-10-21",
        ambiente=ambiente,
    )


# --- cadastrar ----------------------------------------------------------------------------------


def test_cadastra_com_a_declaracao_e_o_hash_do_audio(
    gravacao: Path, ambiente: dict[str, str], casa: Path
) -> None:
    cadastrar(gravacao, ambiente)
    voz = ler_voz("minha", ambiente=ambiente)
    pasta = casa / ".local" / "share" / "jarvis" / "vozes" / "minha"
    assert voz.audio == pasta / "ref.wav" and voz.texto == "Esta é a minha voz."
    assert voz.frase_da_declaracao == "a voz é minha" and abs(voz.duracao_s - 4.0) < 0.01
    declaracao = (pasta / ARQUIVO_DA_DECLARACAO).read_text(encoding="utf-8")
    assert 'declaracao = "minha"' in declaracao and voz.sha256_do_audio in declaracao
    assert vozes_cadastradas(ambiente=ambiente) == ["minha"]


def test_permissao_exige_o_titular_e_o_registra(gravacao: Path, ambiente: dict[str, str]) -> None:
    with pytest.raises(VozNaoAutorizada, match="titular"):
        cadastrar(gravacao, ambiente, declaracao="permissao")
    cadastrar(gravacao, ambiente, nome="da-ana", declaracao="permissao", titular="Ana Souza")
    voz = ler_voz("da-ana", ambiente=ambiente)
    assert voz.frase_da_declaracao == "tenho permissão do titular para usar esta voz (Ana Souza)"


@pytest.mark.parametrize(
    ("mudancas", "motivo"),
    [
        ({"declaracao": ""}, "declare se a voz é sua"),
        ({"declaracao": "achei-na-internet"}, "declare se a voz é sua"),
        ({"audio": "https://exemplo.invalid/voz-de-alguem.wav"}, "só arquivo local"),
        ({"audio": "/nao/existe.wav"}, "não existe"),
        ({"texto": "   "}, "transcrição"),
        ({"nome": "../fora"}, "nome de voz"),
    ],
)
def test_cadastro_recusa_sem_declaracao_url_ou_dado_faltando(
    gravacao: Path, ambiente: dict[str, str], mudancas: dict[str, str], motivo: str
) -> None:
    with pytest.raises(VozNaoAutorizada, match=re.escape(motivo)):
        cadastrar(gravacao, ambiente, **mudancas)
    assert vozes_cadastradas(ambiente=ambiente) == []


@pytest.mark.parametrize(
    "pasta_do_jarvis",
    [".local/share/jarvis/area", ".local/state/jarvis/voz/sessao", ".cache/jarvis/vozes"],
)
def test_audio_que_o_jarvis_gravou_ou_baixou_nao_vira_voz(
    casa: Path, ambiente: dict[str, str], pasta_do_jarvis: str
) -> None:
    capturado = gravar_wav(casa / pasta_do_jarvis / "fala-de-alguem.wav", 5.0)
    with pytest.raises(VozNaoAutorizada, match="onde o Jarvis grava e baixa sozinho"):
        cadastrar(capturado, ambiente)


@pytest.mark.parametrize(
    ("segundos", "ok"), [(1.0, False), (3.0, True), (20.0, True), (25.0, False)]
)
def test_duracao_de_3_a_20_segundos(
    tmp_path: Path, ambiente: dict[str, str], segundos: float, ok: bool
) -> None:
    audio = gravar_wav(tmp_path / f"r{segundos}.wav", segundos, taxa=8000)
    if ok:
        cadastrar(audio, ambiente, nome=f"v{int(segundos)}")
    else:
        with pytest.raises(VozNaoAutorizada, match="use de 3 a 20 s"):
            cadastrar(audio, ambiente)


def test_arquivo_que_nao_e_wav_recusa(tmp_path: Path, ambiente: dict[str, str]) -> None:
    falso = tmp_path / "voz.mp3"
    falso.write_bytes(b"ID3 isto nao e wav")
    with pytest.raises(VozNaoAutorizada, match="não é um WAV"):
        cadastrar(falso, ambiente)


def test_nao_sobrescreve_voz_existente(gravacao: Path, ambiente: dict[str, str]) -> None:
    cadastrar(gravacao, ambiente)
    with pytest.raises(VozNaoAutorizada, match="já existe"):
        cadastrar(gravacao, ambiente)


# --- ler (o que o motor usa) --------------------------------------------------------------------


def test_trocar_o_audio_depois_invalida_a_voz(gravacao: Path, ambiente: dict[str, str]) -> None:
    cadastrar(gravacao, ambiente)
    voz = ler_voz("minha", ambiente=ambiente)
    gravar_wav(voz.audio, 5.0)  # outro áudio no lugar do declarado
    with pytest.raises(VozNaoAutorizada, match="não é o áudio que você declarou"):
        ler_voz("minha", ambiente=ambiente)


def test_sem_o_arquivo_de_declaracao_nao_usa(gravacao: Path, ambiente: dict[str, str]) -> None:
    cadastrar(gravacao, ambiente)
    voz = ler_voz("minha", ambiente=ambiente)
    (voz.audio.parent / ARQUIVO_DA_DECLARACAO).unlink()
    with pytest.raises(VozNaoAutorizada, match="sem a sua declaração"):
        ler_voz("minha", ambiente=ambiente)


@pytest.mark.parametrize(
    ("de", "para", "motivo"),
    [
        ('declaracao = "minha"', 'declaracao = "talvez"', "não vale"),
        ('declaracao = "minha"', 'declaracao = "permissao"', "diga de quem"),
    ],
)
def test_declaracao_adulterada_nao_usa(
    gravacao: Path, ambiente: dict[str, str], de: str, para: str, motivo: str
) -> None:
    cadastrar(gravacao, ambiente)
    arquivo = ler_voz("minha", ambiente=ambiente).audio.parent / ARQUIVO_DA_DECLARACAO
    arquivo.write_text(arquivo.read_text(encoding="utf-8").replace(de, para), encoding="utf-8")
    with pytest.raises(VozNaoAutorizada, match=motivo):
        ler_voz("minha", ambiente=ambiente)


def test_voz_posta_a_mao_sem_cadastro_nao_usa(casa: Path, ambiente: dict[str, str]) -> None:
    pasta = casa / ".local" / "share" / "jarvis" / "vozes" / "copiada"
    gravar_wav(pasta / "ref.wav", 5.0)
    (pasta / "ref.txt").write_text("qualquer coisa", encoding="utf-8")
    with pytest.raises(VozNaoAutorizada, match="sem a sua declaração"):
        ler_voz("copiada", ambiente=ambiente)


def test_remover_apaga_so_os_arquivos_da_voz(gravacao: Path, ambiente: dict[str, str]) -> None:
    cadastrar(gravacao, ambiente)
    pasta = ler_voz("minha", ambiente=ambiente).audio.parent
    (pasta / "nota-do-dono.txt").write_text("minha nota", encoding="utf-8")
    assert remover_voz("minha", ambiente=ambiente)
    assert not (pasta / "ref.wav").exists() and (pasta / "nota-do-dono.txt").is_file()
    assert not remover_voz("nunca-existiu", ambiente=ambiente)


# --- o comando do dono --------------------------------------------------------------------------


def test_o_comando_mostra_o_aviso_e_exige_a_declaracao(
    gravacao: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vozes = tmp_path / "vozes"
    base = ["--cadastrar-voz", "eu", "--audio", str(gravacao), "--texto", "oi, sou eu"]
    assert main([*base, "--pasta-das-vozes", str(vozes)]) == 2
    saida = capsys.readouterr().out
    assert AVISO_DE_CLONAGEM.splitlines()[0] in saida and "--declaro" in saida
    assert main([*base, "--declaro", "minha", "--pasta-das-vozes", str(vozes)]) == 0
    assert 'voz_omnivoice = "eu"' in capsys.readouterr().out
    assert main(["--vozes", "--pasta-das-vozes", str(vozes)]) == 0
    assert "eu: a voz é minha" in capsys.readouterr().out
    assert main(["--remover-voz", "eu", "--pasta-das-vozes", str(vozes)]) == 0
    assert vozes_cadastradas(pasta=vozes) == []


# --- nenhuma ferramenta do assistente clona voz ------------------------------------------------


def test_nenhuma_capacidade_do_catalogo_mexe_com_voz_de_referencia() -> None:
    proibido = re.compile(r"omnivoice|clon|voz_de_referencia|cadastrar_voz|ref_audio", re.I)
    culpados = [
        arquivo.name
        for arquivo in (RAIZ / "catalogo").glob("*.yaml")
        if proibido.search(arquivo.read_text(encoding="utf-8"))
    ]
    assert culpados == []


def test_so_o_modulo_do_motor_define_e_nenhum_outro_de_src_chama_o_cadastro() -> None:
    """Varredura: o cadastro existe para o comando do dono em `tools/`, e só para ele."""
    fontes = RAIZ / "src" / "jarvis"
    chamadores = [
        str(arquivo.relative_to(fontes))
        for arquivo in fontes.rglob("*.py")
        if "cadastrar_voz" in arquivo.read_text(encoding="utf-8")
    ]
    assert chamadores == ["voz/omnivoice.py"]


def test_as_camadas_das_ferramentas_nao_importam_o_motor() -> None:
    fontes = RAIZ / "src" / "jarvis"
    camadas = ("executor", "s2", "capacidades", "navegador", "tarefas", "memoryd", "politica")
    culpados = [
        str(arquivo.relative_to(fontes))
        for camada in camadas
        for arquivo in (fontes / camada).rglob("*.py")
        if "voz.omnivoice" in arquivo.read_text(encoding="utf-8")
    ]
    assert culpados == []


@pytest.mark.parametrize(
    "caminho",
    [
        "/casa/sodre/.local/share/jarvis/vozes/minha/ref.wav",
        "/casa/sodre/.local/share/jarvis/vozes/nova/ref.wav",
        "/casa/sodre/.local/share/jarvis/omnivoice/pesos/c5fdb5ccb189/model.safetensors",
    ],
)
def test_ferramentas_de_arquivo_nao_alcancam_vozes_nem_o_motor(caminho: str) -> None:
    canonico = canonicalizar(caminho, Sistema.POSIX)
    assert motivo_de_negacao(canonico, Path("/casa/sodre"), Sistema.POSIX) is not None


# --- configuração, prontidão e janela -----------------------------------------------------------


def test_a_configuracao_nasce_desligada() -> None:
    padrao = Configuracao()
    assert padrao.tts == "tts-piper-epitran"
    assert padrao.omnivoice_uso_pessoal is False and padrao.voz_omnivoice == ""
    assert padrao.uso_pessoal_aceito == ()


def test_escrever_e_ler_guardam_a_declaracao_do_dono(tmp_path: Path) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    escolhida = Configuracao(tts="tts-omnivoice", omnivoice_uso_pessoal=True, voz_omnivoice="minha")
    escrever(escolhida, arquivo)
    lida = ler(arquivo)
    assert lida.omnivoice_uso_pessoal and lida.voz_omnivoice == "minha"
    assert lida.uso_pessoal_aceito == ("tts-omnivoice",)
    assert "NÃO COMERCIAIS" in arquivo.read_text(encoding="utf-8")


def test_nome_de_voz_invalido_na_configuracao_recusa() -> None:
    with pytest.raises(ConfiguracaoInvalida, match="voz_omnivoice"):
        validar(Configuracao(voz_omnivoice="../../etc/passwd"))


def test_sem_declaracao_a_prontidao_diz_o_que_escrever() -> None:
    falta = o_que_falta("tts-omnivoice", Configuracao(tts="tts-omnivoice"))
    assert "uso pessoal" in falta and "omnivoice_uso_pessoal = true" in falta


def test_com_declaracao_e_sem_instalacao_a_prontidao_diz_como_instalar(tmp_path: Path) -> None:
    configuracao = Configuracao(tts="tts-omnivoice", omnivoice_uso_pessoal=True)
    falta = o_que_falta("tts-omnivoice", configuracao, ambiente={"HOME": str(tmp_path)})
    assert "não está instalado" in falta and "tools.instalar_omnivoice" in falta


def test_a_janela_mostra_o_aviso_de_uso_pessoal_e_desligado() -> None:
    (omnivoice,) = [p for p in provedores(Configuracao(), "tts") if p.motor == "tts-omnivoice"]
    assert not omnivoice.ligado and omnivoice.aviso.startswith("USO PESSOAL, NÃO COMERCIAL")
    declarado = Configuracao(omnivoice_uso_pessoal=True)
    (ligado,) = [p for p in provedores(declarado, "tts") if p.motor == "tts-omnivoice"]
    assert ligado.ligado


def test_diagnostico_diz_o_estado_e_as_vozes(
    gravacao: Path, ambiente: dict[str, str], tmp_path: Path
) -> None:
    cadastrar(gravacao, ambiente)
    linhas = linhas_do_diagnostico(aceito=False, voz="minha", ambiente=ambiente)
    texto = "\n".join(linhas)
    assert "não instalado" in texto and "omnivoice_uso_pessoal = false" in texto
    assert "★ voz minha: a voz é minha" in texto

    saida: list[str] = []
    diagnosticar(
        saida.append,
        caminho=tmp_path / "nao-existe.toml",
        ambiente={**ambiente, "CI": "1", "XDG_STATE_HOME": str(tmp_path / "estado")},
    )
    completo = "\n".join(saida)
    assert "OmniVoice (opcional, uso pessoal e não comercial" in completo
    assert "tts-omnivoice" in completo and "uso pessoal: não declarado" in completo
