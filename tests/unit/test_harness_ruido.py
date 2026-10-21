"""O harness do ruído e da dica (ADR-0043), sem whisper: as cenas, o critério de acerto e a tabela.

O que precisa do modelo, da voz piper e do espeak-ng roda à mão (`python -m tools.harness_ruido`);
aqui fica o que decide os números publicados e pode mudar sem ninguém notar.
"""

from __future__ import annotations

import numpy as np
from tools.harness_ruido import (
    APPS_FICTICIOS,
    acertou,
    cenas_de_ruido,
    resumo,
    variantes,
)

from jarvis.voz.ruido import julgar_audio, medir_trecho


def test_as_cenas_de_ruido_sao_deterministicas_e_do_tamanho_do_trecho() -> None:
    primeira = cenas_de_ruido(np.random.default_rng(1))
    segunda = cenas_de_ruido(np.random.default_rng(1))

    assert [c.amostras for c in primeira] == [c.amostras for c in segunda]
    assert {c.tipo for c in primeira} == {"ruido"}
    assert all(len(c.amostras) == 2 * 16_000 * 2 for c in primeira), "trecho de 2 s, PCM16"


def test_o_portao_segura_o_que_o_relatorio_diz_que_segura() -> None:
    """Sala, chiado, ventilador e clique caem no portão; teclado é impulso; respiração e tosse
    passam (quem as segura é o filtro da transcrição) — como o `.md` publica."""
    vereditos = {
        c.nome: julgar_audio(medir_trecho(c.amostras))
        for c in cenas_de_ruido(np.random.default_rng(20261021))
    }
    for nome in ("silencio_sala", "chiado", "ventilador", "clique_do_mouse", "teclado"):
        assert vereditos[nome] is not None, nome
    assert vereditos["respiracao"] is None and vereditos["tosse"] is None


def test_a_dica_nova_nao_usa_hotwords_e_a_antiga_e_a_lista_de_apps() -> None:
    dicas = variantes()
    assert APPS_FICTICIOS in dicas["lista_de_apps"]["initial_prompt"]
    assert "hotwords" not in dicas["dica_so_palavra"]
    assert "hotwords" not in dicas["dica_com_vocabulario"]
    assert dicas["dica_so_palavra"]["initial_prompt"] == "Jarvis."


def test_acerto_exige_as_palavras_que_importam() -> None:
    assert acertou("Manda mensagem para o Kauã Ximenes.", "Manda a mensagem para o Kauã Ximenes.")
    assert not acertou("Manda mensagem para o Kauã Ximenes.", "Manda a mensagem para o Calwash")
    assert not acertou("Abre o Spotify.", "Abrir o Spotify.")
    assert not acertou("", "qualquer coisa")


def test_a_tabela_conta_o_que_passou_e_a_fala_derrubada() -> None:
    linhas: list[dict[str, object]] = [
        {"cena": "tosse", "tipo": "ruido", "variante": "v", "virou_texto": 1, "acertou": "",
         "filtro": "sem_fala", "portao": "", "asr_ms": 100.0, "portao_us": 300.0},
        {"cena": "sala", "tipo": "ruido", "variante": "v", "virou_texto": 1, "acertou": "",
         "filtro": "", "portao": "fundo", "asr_ms": 120.0, "portao_us": 200.0},
        {"cena": "fala:Não.", "tipo": "fala", "variante": "v", "virou_texto": 1, "acertou": 1,
         "filtro": "", "portao": "", "asr_ms": 140.0, "portao_us": 250.0},
    ]  # fmt: skip

    tabela = resumo(linhas)

    assert "| v | 2/2 | 1/2 | 1/1 | 0/1 | 120 |" in tabela
    assert "sala → fundo" in tabela and "tosse → passa" in tabela
