"""Fonemização pt-BR com licença permissiva, de ponta a ponta (ADR-0016 opção B, ADR-0017).

Estes testes precisam do extra `voz` (`uv sync --group voz`): `epitran` para fonemizar e, nos
dois últimos, `onnxruntime` mais a voz do piper em cache para **sintetizar de verdade**. O CI
não instala o grupo, então eles são `skip` lá — e é por isso que a regra de tônica tem suíte
própria sem dependência (`test_tonica.py`), que roda sempre.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.voz.fonemizador import (
    SUBSTITUICOES,
    FonemizadorEpitran,
    conferir_cobertura,
)
from jarvis.voz.tonica import ACENTO_PRIMARIO

PASTA_VOZES = Path.home() / ".cache" / "jarvis" / "vozes"
VOZ = "pt_BR-faber-medium"
ARQUIVO_DA_VOZ = PASTA_VOZES / VOZ / f"{VOZ}.onnx"
ID_DA_VOZ = "rhasspy/piper-voices:pt_BR-faber-medium"

FRASE = "Jarvis, anotei a reunião de terça às quinze e trinta. Quer que eu avise o João agora?"
FRASES = (
    FRASE,
    "O jardim tem trinta árvores públicas.",
    "Hoje é dia três de março, às oito e meia da manhã.",
    "Álbuns, hifens, jovens, túneis e órgãos.",
    "Bom dia! Tudo certo por aqui; e com você?",
)

sem_voz = pytest.mark.skipif(
    not ARQUIVO_DA_VOZ.exists(),
    reason=f"a voz {VOZ} não está em {PASTA_VOZES} (ver notas do F1-02)",
)


@pytest.fixture
def fonemizar() -> FonemizadorEpitran:
    pytest.importorskip("epitran", reason="grupo `voz` não instalado")
    return FonemizadorEpitran()


def test_fonemiza_a_frase_com_tonica(fonemizar: FonemizadorEpitran) -> None:
    ipa = fonemizar(FRASE)

    assert ACENTO_PRIMARIO in ipa
    palavras_tonicas = ipa.count(ACENTO_PRIMARIO)
    assert palavras_tonicas >= 10, f"prosódia achatada: só {palavras_tonicas} tônicas"
    assert "ʒɐɾˈviʃ" in ipa or "ʒɐɾˈvis" in ipa


def test_a_pontuacao_atravessa_porque_e_ela_que_vira_pausa(
    fonemizar: FonemizadorEpitran,
) -> None:
    ipa = fonemizar("Bom dia! Tudo certo?")
    assert "!" in ipa and "?" in ipa and " " in ipa


def test_o_simbolo_substituido_e_decisao_declarada(fonemizar: FonemizadorEpitran) -> None:
    """`ʷ` sai porque em pt-BR o `u` do `qu` não soa: `quinze` é /ˈkĩzi/, não "cuinze"."""
    assert SUBSTITUICOES["ʷ"] == ""
    ipa = fonemizar("quinze")
    assert "ʷ" not in ipa
    assert "kinz" in ipa


def test_sem_tonica_e_a_prosodia_que_a_amostra_mediu(fonemizar: FonemizadorEpitran) -> None:
    """Desligar a tônica reproduz o que a ADR-0017 mediu: zero acentos na frase inteira."""
    achatado = FonemizadorEpitran(com_tonica=False)
    assert ACENTO_PRIMARIO not in achatado(FRASE)
    assert ACENTO_PRIMARIO in fonemizar(FRASE)


def test_vogal_nasal_sai_decomposta_porque_e_assim_que_a_voz_conhece(
    fonemizar: FonemizadorEpitran,
) -> None:
    ipa = fonemizar("jardim")
    assert "̃" in ipa, "o til tem de ser combinante, não vogal pré-composta"
    assert "ĩ" not in ipa


def test_contador_de_palavras_fonemizadas(fonemizar: FonemizadorEpitran) -> None:
    fonemizar("três palavras aqui")
    assert fonemizar.palavras_fonemizadas == 3


def test_numero_nao_e_fonemizado_e_isso_e_declarado(fonemizar: FonemizadorEpitran) -> None:
    """Ler `15` como "quinze" é normalização de texto, não fonemização — e falta (ver notas)."""
    ipa = fonemizar("são 15 horas")
    assert "15" in ipa


@sem_voz
def test_a_cobertura_do_inventario_da_voz_e_completa(fonemizar: FonemizadorEpitran) -> None:
    """O achado da ADR-0017: símbolo fora do mapa some em silêncio. Aqui ele é medido."""
    mapa = json.loads(ARQUIVO_DA_VOZ.with_suffix(".onnx.json").read_text(encoding="utf-8"))[
        "phoneme_id_map"
    ]

    cobertura = conferir_cobertura(fonemizar, mapa, FRASES)

    assert cobertura.completa, str(cobertura)
    assert ACENTO_PRIMARIO in cobertura.simbolos


def test_cobertura_denuncia_simbolo_fora_do_mapa() -> None:
    """A conferência acha o que está fora — prova de que "completa" não é cegueira do método."""
    cobertura = conferir_cobertura(lambda _: "abʷc", {"a", "b", "c"}, ["irrelevante"])

    assert not cobertura.completa
    assert cobertura.fora_do_mapa == ("ʷ",)
    assert "fora do inventário" in str(cobertura)


@sem_voz
def test_sintetiza_de_verdade_com_a_voz_do_piper(fonemizar: FonemizadorEpitran) -> None:
    """Caminho completo da opção B: texto → IPA MIT → voz MIT → PCM16, sem espeak-ng."""
    pytest.importorskip("onnxruntime", reason="grupo `voz` não instalado")
    from jarvis.agentd.tts import MotorPiperOnnx

    motor = MotorPiperOnnx(
        caminho=ARQUIVO_DA_VOZ,
        fonemizar=fonemizar,
        voz=VOZ,
        identificador_registrado=ID_DA_VOZ,
    )
    motor.abrir()
    amostras = motor.sintetizar("Quer que eu avise o João agora?")

    assert len(amostras) > 16000, "menos de 0,5 s de áudio para uma frase inteira"
    assert (
        max(
            abs(int.from_bytes(amostras[i : i + 2], "little", signed=True))
            for i in range(0, len(amostras), 2)
        )
        > 1000
    ), "áudio silencioso"
    assert motor.fonemas_descartados == 0, f"descartou {motor.simbolos_descartados}"
    assert motor.licenca == "MIT"


@sem_voz
def test_o_descarte_silencioso_agora_e_contado(fonemizar: FonemizadorEpitran) -> None:
    """A ADR-0016 dizia que fonema fora do mapa levantava erro; ele era descartado calado.

    Mudar descarte para erro é emenda da ADR-0016 e decisão do dono. O que o código faz hoje é
    **contar** — e é o contador que impede o próximo símbolo novo de virar voz torta anônima.
    """
    pytest.importorskip("onnxruntime", reason="grupo `voz` não instalado")
    from jarvis.agentd.tts import MotorPiperOnnx

    motor = MotorPiperOnnx(
        caminho=ARQUIVO_DA_VOZ,
        fonemizar=lambda texto: "kʷɛɾ ʷ",  # `ʷ` não está no inventário da voz
        voz=VOZ,
        identificador_registrado=ID_DA_VOZ,
    )
    motor.abrir()
    motor.sintetizar("qualquer coisa")

    assert motor.fonemas_descartados == 2
    assert motor.simbolos_descartados == {"ʷ": 2}
