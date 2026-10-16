"""A regra de tônica do pt-BR, palavra por palavra (ADR-0017).

A lacuna que a amostra mediu era "o `epitran` não marca tônica". O que se prova aqui é a
**regra**, sem `epitran` e sem voz: dada a palavra escrita, qual sílaba é a tônica; e dado um
IPA, onde o acento entra. Os dois testes de ponta a ponta (com `epitran` de verdade) estão em
`test_fonemizador.py`, que é marcado para o ambiente que tem o extra.
"""

from __future__ import annotations

import pytest

from jarvis.voz.tonica import (
    ACENTO_PRIMARIO,
    ATONAS,
    acentuar,
    marcar_tonica,
    nucleos_escritos,
    nucleos_ipa,
    silaba_tonica,
)


@pytest.mark.parametrize(
    ("palavra", "esperado"),
    [
        # regra 1: acento gráfico manda
        ("árvore", 3),
        ("público", 3),
        ("história", 2),
        ("túnel", 2),
        ("fácil", 2),
        ("porém", 1),
        ("chapéu", 1),
        ("café", 1),
        ("órgão", 2),  # com dois sinais, o acento vence o til
        ("sótão", 2),
        ("irmã", 1),  # só o til: ele manda
        ("reunião", 1),
        # regra 2: a terminação manda
        ("terça", 2),
        ("quinze", 2),
        ("trinta", 2),
        ("agora", 2),
        ("avise", 2),
        ("computador", 1),
        ("jarvis", 1),
        ("anotei", 1),
        ("feliz", 1),
        ("papel", 1),
        ("jardim", 1),
        ("album", 1),  # sem acento gráfico, `-um` é oxítona (é `álbum` que é paroxítona)
        ("falam", 2),
        ("homem", 2),
        ("jovens", 2),
        ("homens", 2),
        ("jardins", 1),
        ("casas", 2),
        ("pires", 2),
        # monossílabo tônico
        ("eu", 1),
        ("quer", 1),
        ("tres", 1),
    ],
)
def test_qual_silaba_e_a_tonica(palavra: str, esperado: int) -> None:
    assert silaba_tonica(palavra) == esperado


@pytest.mark.parametrize("palavra", sorted(ATONAS))
def test_palavra_atona_nao_recebe_marca(palavra: str) -> None:
    """Marcar as 40 átonas deixaria a frase com uma ênfase por palavra — o oposto de prosódia."""
    assert silaba_tonica(palavra) == 0
    assert acentuar(palavra, "ɐ") == "ɐ"


def test_maiuscula_e_pontuacao_nao_mudam_a_regra() -> None:
    assert silaba_tonica("Jarvis,") == silaba_tonica("jarvis") == 1
    assert silaba_tonica("AGORA!") == 2


def test_palavra_vazia_e_sem_vogal_nao_quebram() -> None:
    assert silaba_tonica("") == 0
    assert silaba_tonica("...") == 0
    assert silaba_tonica("psst") == 0


def test_nucleos_escritos_agrupa_vogais_vizinhas() -> None:
    assert len(nucleos_escritos("reuniao")) == 2  # "eu" e "iao"
    assert len(nucleos_escritos("casa")) == 2
    assert nucleos_escritos("") == []


def test_nucleos_ipa_tratam_glide_e_til_como_parte_do_nucleo() -> None:
    assert len(nucleos_ipa("ɾewniɐ̃w̃")) == 2  # "ew" e "iɐ̃w̃"
    assert len(nucleos_ipa("tɛɾsɐ")) == 2
    assert len(nucleos_ipa("ɐnotɛj")) == 3  # "ɐ", "o", "ɛj": o `j` final é coda


def test_glide_entre_vogais_abre_silaba_em_vez_de_fechar() -> None:
    """`João` é `ʒo` + `wɐ̃w̃`: com o `w` colado no núcleo anterior, a tônica ia para `Jo`."""
    assert [("ʒowɐ̃w̃")[a:b] for a, b in nucleos_ipa("ʒowɐ̃w̃")] == ["o", "ɐ̃w̃"]
    assert marcar_tonica("ʒowɐ̃w̃", 1) == f"ʒo{ACENTO_PRIMARIO}wɐ̃w̃"


def test_vogal_nasal_pre_composta_tambem_e_nucleo() -> None:
    """`ĩ` (U+0129) e `i` + til combinante são a mesma vogal, e as duas aparecem no `epitran`."""
    assert len(nucleos_ipa("ʒɐɾdĩ")) == 2
    assert len(nucleos_ipa("ʒɐɾdĩ")) == 2


def test_o_acento_vai_antes_do_ataque_da_silaba() -> None:
    assert marcar_tonica("tɛɾsɐ", 2) == f"{ACENTO_PRIMARIO}tɛɾsɐ"
    assert marcar_tonica("ɐɡoɾɐ", 2) == f"ɐ{ACENTO_PRIMARIO}ɡoɾɐ"  # a-GO-ra: `ɡ` abre a sílaba


def test_ataque_de_duas_consoantes_so_em_obstruinte_mais_liquida() -> None:
    """`tɾ` abre sílaba (`trinta`); `ɾv` não (`Jarvis` = `ʒaɾ` + `vis`)."""
    assert marcar_tonica("tɾintɐ", 2) == f"{ACENTO_PRIMARIO}tɾintɐ"
    assert marcar_tonica("ʒɐɾviʃ", 1) == f"ʒɐɾ{ACENTO_PRIMARIO}viʃ"


def test_modificador_nao_e_consoante_separada() -> None:
    """`kʷ` é um fonema: o acento não pode entrar no meio dele."""
    assert marcar_tonica("kʷɛɾ", 1) == f"{ACENTO_PRIMARIO}kʷɛɾ"


def test_nao_marca_duas_vezes_nem_fora_do_alcance() -> None:
    marcado = marcar_tonica("tɛɾsɐ", 2)
    assert marcar_tonica(marcado, 1) == marcado, "uma palavra, um acento primário"
    assert marcar_tonica("tɛɾsɐ", 9) == "tɛɾsɐ", "pedido além do número de sílabas não inventa"
    assert marcar_tonica("tɛɾsɐ", 0) == "tɛɾsɐ"
    assert marcar_tonica("", 1) == ""
