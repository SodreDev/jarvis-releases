"""O objetivo do turno: sites citados, domínios alcançados e dado do dono saindo para fora."""

from __future__ import annotations

import pytest

from jarvis.politica.abertura import decidir_abertura
from jarvis.politica.objetivo import Objetivo, dados_do_dono, enderecos_do_resultado


def test_o_site_citado_pelo_nome_ou_pelo_dominio_conta_e_o_falso_nao() -> None:
    objetivo = Objetivo.do_pedido("Abra o YouTube e depois exemplo.com.br.")
    assert objetivo.citado("https://www.youtube.com/@canal")
    assert objetivo.citado("https://m.youtube.com/")
    assert objetivo.citado("https://exemplo.com.br/a")
    assert not objetivo.citado("https://youtube.evil.com/")
    assert not objetivo.citado("https://evilyoutube.com/")


def test_o_caminho_do_objetivo_alcanca_dominios_novos() -> None:
    objetivo = Objetivo.do_pedido("abra o canal do Thiago Nigro")
    assert not objetivo.dentro("https://www.youtube.com/@oprimorico")
    objetivo.alcancar(
        enderecos_do_resultado(
            {
                "url": "https://busca.example/?q=thiago",
                "resultados": [{"url": "https://www.youtube.com/@oprimorico"}],
                "abas": [{"dominio": "noticias.example.com.br"}],
            }
        )
    )
    assert objetivo.dentro("https://www.youtube.com/watch?v=1")
    assert objetivo.dentro("https://busca.example/outra")
    assert objetivo.dentro("https://noticias.example.com.br/x")
    assert not objetivo.dentro("https://mal.example/")


@pytest.mark.parametrize(
    ("texto", "em_url", "esperado"),
    [
        ("https://a.example/?u=fulano%40exemplo.com", True, ["email"]),
        ("cpf 529.982.247-25", False, ["cpf"]),
        ("pedido 12345678901", False, []),  # 11 dígitos que não fecham o CPF
        ("cartão 4111 1111 1111 1111", False, ["cartao"]),
        ("https://a.example/?token=abcd1234efgh", True, ["senha_declarada"]),
        ("https://cdn.example/" + "a1" * 30, True, []),  # hex longo em URL não é segredo do dono
        ("o primo rico", False, []),
    ],
)
def test_dado_do_dono(texto: str, em_url: bool, esperado: list[str]) -> None:
    assert dados_do_dono(texto, em_url=em_url) == esperado


def test_dado_do_dono_so_conta_quando_vai_para_site_que_ele_nao_citou() -> None:
    objetivo = Objetivo.do_pedido("pesquisa o meu email no google")
    assert objetivo.leva_dado_do_dono("https://www.google.com/search?q=fulano%40x.com") == []
    assert objetivo.leva_dado_do_dono("https://mal.example/?q=fulano%40x.com") == ["email"]


def test_sites_open_no_pdp_segue_o_objetivo() -> None:
    def regra(url: str, objetivo: Objetivo | None) -> str:
        decidida = decidir_abertura(
            "sites.open",
            {"url": url},
            apps_autorizados=frozenset(),
            sites_sem_confirmar=frozenset(),
            contaminado=True,
            objetivo=objetivo,
        )
        return "tier" if decidida is None else decidida.veredito

    objetivo = Objetivo.do_pedido("abre o youtube")
    objetivo.alcancar(["https://busca.example/"])
    assert regra("https://www.youtube.com/", objetivo) == "tier"  # citado
    assert regra("https://busca.example/x", objetivo) == "tier"  # alcançado
    assert regra("https://mal.example/", objetivo) == "confirm"  # nem citado nem alcançado
    assert regra("https://busca.example/?e=a%40b.com", objetivo) == "confirm"  # dado para fora
    assert regra("https://www.youtube.com/", None) == "confirm"  # sem objetivo: como antes
