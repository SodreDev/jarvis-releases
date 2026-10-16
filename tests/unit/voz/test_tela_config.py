"""A tela de configuração com entrada simulada: escolher, avisar, confirmar e gravar.

A tela inteira recebe `entrada` e `saida` injetadas, então aqui não há terminal, não há gente
e não há espera: cada teste é uma lista de teclas digitadas e o que apareceu na tela.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from jarvis.voz.chaves import VARIAVEL_ELEVENLABS, VARIAVEL_GROQ
from jarvis.voz.config import Configuracao, ler
from jarvis.voz.tela_config import CONFIRMACAO, TelaDeConfiguracao


@dataclass
class Digitado:
    """Entrada simulada: devolve as respostas na ordem, e guarda o que foi perguntado."""

    respostas: list[str]
    perguntas: list[str] = field(default_factory=list)

    def __call__(self, pergunta: str) -> str:
        self.perguntas.append(pergunta)
        if not self.respostas:
            raise EOFError
        return self.respostas.pop(0)


def tela(tmp_path: Path, respostas: Sequence[str]) -> tuple[TelaDeConfiguracao, list[str]]:
    linhas: list[str] = []
    return (
        TelaDeConfiguracao(
            caminho=tmp_path / "jarvis-voz.toml",
            entrada=Digitado(list(respostas)),
            saida=linhas.append,
        ),
        linhas,
    )


def texto(linhas: Sequence[str]) -> str:
    return "\n".join(linhas)


# --- desenho --------------------------------------------------------------------------------


def test_a_tela_mostra_o_que_esta_escolhido(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["q"])
    config.rodar()

    saida = texto(linhas)
    assert "Ouvir (ASR)" in saida and "asr-whisper-local" in saida
    assert "Falar (TTS)" in saida and "tts-piper-epitran" in saida
    assert "[local]" in saida
    assert "Resposta (S2)" in saida and "provisório até a F2" in saida


def test_a_tela_nunca_mostra_valor_de_chave(tmp_path: Path) -> None:
    """Só "definida" ou "AUSENTE" — o valor não é lido nem por engano."""
    segredo = "gsk_chave_que_nao_pode_aparecer_123456789"
    import os

    os.environ[VARIAVEL_GROQ] = segredo
    try:
        config, linhas = tela(tmp_path, ["9", "q"])
        config.rodar()
    finally:
        del os.environ[VARIAVEL_GROQ]

    saida = texto(linhas)
    assert segredo not in saida
    assert f"{VARIAVEL_GROQ}: definida" in saida
    assert f"{VARIAVEL_ELEVENLABS}: AUSENTE" in saida
    assert f"export {VARIAVEL_GROQ}=" in saida


# --- escolhas -------------------------------------------------------------------------------


def test_escolher_motor_local_e_salvar(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["2", "3", "s"])  # TTS → 3ª opção → salvar
    assert config.rodar() == 0

    assert config.salvou
    gravado = ler(tmp_path / "jarvis-voz.toml")
    assert gravado.tts == "tts-parametrico"
    assert "salvo em" in texto(linhas)


def test_sair_sem_salvar_nao_grava(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["3", "voz-nova", "q"])
    config.rodar()

    assert not (tmp_path / "jarvis-voz.toml").exists()
    assert "sem salvar" in texto(linhas)


def test_numero_que_nao_existe_nao_muda_nada(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["2", "99", "q"])
    config.rodar()

    assert config.configuracao.tts == "tts-piper-epitran"
    assert "não existe essa opção" in texto(linhas)


def test_vazio_mantem_a_escolha_atual(tmp_path: Path) -> None:
    config, _ = tela(tmp_path, ["1", "", "q"])
    config.rodar()
    assert config.configuracao.asr == "asr-whisper-local"


def test_trocar_a_escuta_para_vad(tmp_path: Path) -> None:
    config, _ = tela(tmp_path, ["8", "3", "s"])
    config.rodar()
    assert ler(tmp_path / "jarvis-voz.toml").escuta == "vad"


def test_escolher_o_s2_provisorio(tmp_path: Path) -> None:
    config, _ = tela(tmp_path, ["5", "2", "s"])
    config.rodar()
    assert ler(tmp_path / "jarvis-voz.toml").s2 == "claude"


# --- nuvem: avisar, confirmar, e só então ligar ------------------------------------------------


def _indice_de(config: TelaDeConfiguracao, papel: str, identificador: str) -> str:
    from jarvis.voz.registro import motores_de

    return str([m.id for m in motores_de(papel)].index(identificador) + 1)


def test_escolher_nuvem_mostra_o_aviso_e_exige_sim(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, [])
    escolha = _indice_de(config, "asr", "asr-groq-whisper-large-v3-turbo")
    config.entrada = Digitado(["1", escolha, CONFIRMACAO, "s"])
    config.rodar()

    saida = texto(linhas)
    assert "sai desta máquina para Groq" in saida
    assert "30 dias" in saida
    gravado = ler(tmp_path / "jarvis-voz.toml")
    assert gravado.asr == "asr-groq-whisper-large-v3-turbo"
    assert gravado.nuvem_ligada == ("asr-groq-whisper-large-v3-turbo",)


def test_recusar_o_aviso_deixa_o_motor_escolhido_e_desligado(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, [])
    escolha = _indice_de(config, "asr", "asr-groq-whisper-large-v3-turbo")
    config.entrada = Digitado(["1", escolha, "não", "s"])
    config.rodar()

    gravado = ler(tmp_path / "jarvis-voz.toml")
    assert gravado.asr == "asr-groq-whisper-large-v3-turbo"
    assert gravado.nuvem_ligada == (), "ligou nuvem sem o dono confirmar"
    assert "fica escolhido e desligado" in texto(linhas)


def test_a_tela_lembra_de_exportar_a_chave_que_falta(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, [])
    escolha = _indice_de(config, "asr", "asr-groq-whisper-large-v3-turbo")
    config.entrada = Digitado(["1", escolha, CONFIRMACAO, "q"])
    config.rodar()

    assert f"export {VARIAVEL_GROQ}=" in texto(linhas)
    assert "nunca entra neste arquivo" in texto(linhas)


def test_servico_sem_termos_exige_dois_sins(tmp_path: Path) -> None:
    """O `tts-edge` não tem contrato publicado: o segundo "sim" é o que escreve isso no TOML."""
    config, linhas = tela(tmp_path, [])
    escolha = _indice_de(config, "tts", "tts-edge")
    config.entrada = Digitado(["2", escolha, CONFIRMACAO, CONFIRMACAO, "s"])
    config.rodar()

    saida = texto(linhas)
    assert "ATENÇÃO" in saida and "não publica termos" in saida
    gravado = ler(tmp_path / "jarvis-voz.toml")
    assert gravado.nuvem_ligada == ("tts-edge",)
    assert gravado.nuvem_sem_termos == ("tts-edge",)


def test_o_segundo_sim_negado_nao_liga_nada(tmp_path: Path) -> None:
    config, _ = tela(tmp_path, [])
    escolha = _indice_de(config, "tts", "tts-edge")
    config.entrada = Digitado(["2", escolha, CONFIRMACAO, "não", "s"])
    config.rodar()

    gravado = ler(tmp_path / "jarvis-voz.toml")
    assert gravado.nuvem_ligada == ()
    assert gravado.nuvem_sem_termos == ()


def test_s_abreviado_nao_confirma_nuvem(tmp_path: Path) -> None:
    """A confirmação é por extenso: "s" seria fácil demais para o que ela significa."""
    config, _ = tela(tmp_path, [])
    escolha = _indice_de(config, "asr", "asr-groq-whisper-large-v3-turbo")
    config.entrada = Digitado(["1", escolha, "s", "q"])
    config.rodar()

    assert config.configuracao.nuvem_ligada == ()


# --- o arquivo gravado ---------------------------------------------------------------------


def test_o_arquivo_gravado_e_relido_sem_perder_nada(tmp_path: Path) -> None:
    config, _ = tela(tmp_path, [])
    escolha = _indice_de(config, "tts", "tts-elevenlabs")
    config.entrada = Digitado(["2", escolha, CONFIRMACAO, "10", "voz-do-dono", "11", "2", "s"])
    config.rodar()

    gravado = ler(tmp_path / "jarvis-voz.toml")
    assert gravado == Configuracao(
        asr="asr-whisper-local",
        tts="tts-elevenlabs",
        s2="eco",
        voz_elevenlabs="voz-do-dono",
        modelo_elevenlabs="eleven_flash_v2_5",
        nuvem_ligada=("tts-elevenlabs",),
    )


def test_o_arquivo_avisa_para_nao_escrever_chave(tmp_path: Path) -> None:
    config, _ = tela(tmp_path, ["s"])
    config.rodar()

    escrito = (tmp_path / "jarvis-voz.toml").read_text(encoding="utf-8")
    assert "Nunca escreva chave de API aqui" in escrito
    assert "export JARVIS_GROQ_API_KEY" in escrito


def test_fim_de_entrada_fecha_a_tela_sem_estrago(tmp_path: Path) -> None:
    """Ctrl+D no meio da tela não pode deixar o arquivo pela metade."""
    config, _ = tela(tmp_path, [])
    config.entrada = Digitado([])
    assert config.rodar() == 0
    assert not (tmp_path / "jarvis-voz.toml").exists()


def test_a_tela_recusa_configuracao_invalida_ao_salvar(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["s"])
    config.configuracao = config.configuracao.com(asr="motor-que-nao-existe")
    config.passo("s")

    assert not config.salvou
    assert "não deu para salvar" in texto(linhas)


def test_configuracao_existente_e_carregada_ao_abrir(tmp_path: Path) -> None:
    from jarvis.voz.config import escrever

    escrever(Configuracao(tts="tts-parametrico", escuta="vad"), tmp_path / "jarvis-voz.toml")
    config, linhas = tela(tmp_path, ["q"])
    config.rodar()

    assert config.configuracao.tts == "tts-parametrico"
    assert "vad" in texto(linhas)


@pytest.mark.parametrize("escolha", ["", "x", "42"])
def test_escolha_sem_sentido_so_explica(tmp_path: Path, escolha: str) -> None:
    config, linhas = tela(tmp_path, [escolha, "q"])
    config.rodar()
    assert "escolha um número" in texto(linhas)


# --- modos de ativação (ADR-0021) -----------------------------------------------------------
def test_escolher_a_palavra_de_ativacao(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["8", "2", "12", "Sexta", "0,9", "s"])
    config.rodar()
    salvo = ler(tmp_path / "jarvis-voz.toml")
    assert salvo.escuta == "palavra"
    assert salvo.palavra == "sexta"
    assert salvo.limiar_palavra == 0.9
    assert "palavra de ativação" in texto(linhas)


def test_palavra_que_nao_serve_e_recusada_sem_mudar_nada(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["12", "ô jarvis", "", "q"])
    config.rodar()
    assert config.configuracao.palavra == "jarvis"
    assert "recusado: " in texto(linhas)
    assert not config.mudou


def test_limiar_fora_da_faixa_e_recusado(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["12", "", "0.3", "q"])
    config.rodar()
    assert config.configuracao.limiar_palavra == 0.75
    assert "fora da faixa" in texto(linhas)


def test_escolher_o_atalho_e_voltar_para_a_barra(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["13", "ctrl+shift+j", "s"])
    config.rodar()
    assert ler(tmp_path / "jarvis-voz.toml").atalho == "Ctrl+Shift+J"
    assert "com a janela em foco" in texto(linhas)

    de_volta, _ = tela(tmp_path, ["13", "-", "s"])
    de_volta.rodar()
    assert ler(tmp_path / "jarvis-voz.toml").atalho == ""


def test_atalho_sem_modificador_e_recusado(tmp_path: Path) -> None:
    config, linhas = tela(tmp_path, ["13", "j", "q"])
    config.rodar()
    assert config.configuracao.atalho == ""
    assert "modificador" in texto(linhas)
