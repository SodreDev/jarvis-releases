"""A marca do protocolo com UM colchete (`<ferramenta>`), vista no Claude (ADR-0072): nunca vai
à voz — seguida de JSON é a proposta; seguida de texto, só a etiqueta sai."""

from __future__ import annotations

from jarvis.s2.motor import PedidoDeTool, Texto
from jarvis.s2.protocolo import LeitorDoProtocolo


# --- a marca com UM colchete (vista no Claude, ADR-0072) --------------------------------------
def _ler_tudo(partes: list[str]) -> list[object]:
    leitor = LeitorDoProtocolo()
    saida: list[object] = []
    for parte in partes:
        saida += list(leitor.alimentar(parte))
    return saida + list(leitor.fechar())


def test_etiqueta_solta_seguida_de_texto_sai_e_o_texto_fica() -> None:
    assert _ler_tudo(["<ferramenta>Anotado: você estaciona no segundo andar."]) == [
        Texto("Anotado: você estaciona no segundo andar.")
    ]
    falado = "".join(
        p.texto
        for p in _ler_tudo(["<ferramenta> Não consegui", " mandar."])
        if isinstance(p, Texto)
    )
    assert "<" not in falado and "Não consegui mandar." in falado


def test_etiqueta_solta_seguida_de_json_e_proposta_mesmo_partida() -> None:
    partes = ["<ferr", "amenta>", '{"tool_id": "system.clock.now", "args": {}}']
    assert _ler_tudo(partes) == [PedidoDeTool("system.clock.now", {})]


def test_etiqueta_solta_no_fim_nao_vai_a_voz_e_sinal_de_menor_continua_fala() -> None:
    assert _ler_tudo(["Vou ver. </ferramenta>"]) == [Texto("Vou ver. ")]
    assert _ler_tudo(["a < b e c > d"]) == [Texto("a < b e c > d")]
