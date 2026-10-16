"""O gerente de workspace (ADR-0019): a IA propõe, o código dispõe — sem abrir janela.

Cada teste aqui é uma das cinco regras do dono, no ponto em que ela custa: proposta que não
é do vocabulário, componente fora do catálogo, campo que a tela executaria, colisão com o que
ele já estava lendo, módulo fixado, integração com a máquina dele, fechar sem perder e trocar
de modo sem destruir.
"""

from __future__ import annotations

import pytest

from jarvis.gui.acoes import Acao, AcaoInvalida, Area, Modo, Tipo, ler_acao
from jarvis.gui.componentes import ComponenteNaoAutorizado, componente, validar_dados
from jarvis.gui.workspace import LAYOUT_ANTERIOR, EstadoDoWidget, Workspace


def criar(componente_id: str, **extras: object) -> Acao:
    return ler_acao({"tipo": "createWidget", "componente": componente_id, **extras})


# --- o vocabulário é fechado ----------------------------------------------------------------


def test_campo_que_a_tela_executaria_e_recusado() -> None:
    """A porta que a ADR fecha: nada de HTML, script ou comando vindo da IA."""
    with pytest.raises(AcaoInvalida, match="nunca conteúdo para a tela executar"):
        ler_acao({"tipo": "createWidget", "componente": "resumo", "html": "<script>x()</script>"})


def test_tipo_de_acao_inventado_e_recusado_dizendo_os_que_existem() -> None:
    with pytest.raises(AcaoInvalida, match="createWidget"):
        ler_acao({"tipo": "executeShell"})


def test_componente_fora_do_catalogo_vira_recusa_com_motivo() -> None:
    espaco = Workspace()

    resultado = espaco.propor({"tipo": "createWidget", "componente": "iframe"})

    assert not resultado.aceita
    assert "não está no catálogo" in resultado.motivo
    assert espaco.widgets == {}


def test_campo_que_o_componente_nao_tem_e_recusado() -> None:
    with pytest.raises(ComponenteNaoAutorizado, match="campos que este componente não tem"):
        validar_dados(componente("resumo"), {"javascript": "alert(1)"})


def test_item_com_estado_inventado_e_recusado() -> None:
    with pytest.raises(ComponenteNaoAutorizado, match="estado"):
        validar_dados(componente("tarefas"), {"itens": [{"titulo": "x", "estado": "explodindo"}]})


def test_area_fora_da_grade_e_recusada() -> None:
    with pytest.raises(AcaoInvalida, match="não cabe na grade"):
        Area(coluna=10, linha=0, colunas=4, linhas=2)


# --- colisão: quem se muda é o novo ---------------------------------------------------------


def test_em_colisao_quem_se_muda_e_o_novo() -> None:
    espaco = Workspace()
    primeiro = espaco.aplicar(criar("tarefas"))
    area_de_antes = espaco.widgets[primeiro.widget].area

    segundo = espaco.aplicar(
        criar("fontes", area={"coluna": 0, "linha": 0, "colunas": 2, "linhas": 5})
    )

    assert segundo.aceita
    assert espaco.widgets[primeiro.widget].area == area_de_antes, "mexeram no que o dono já lia"
    assert not espaco.widgets[segundo.widget].area.colide_com(area_de_antes)
    assert "estava ocupado" in segundo.ajuste


def test_sem_espaco_a_acao_e_recusada_pedindo_para_fechar_algo() -> None:
    espaco = Workspace()
    espaco.aplicar(Acao(tipo=Tipo.MODO, modo=Modo.EXECUCAO))
    for _ in range(3):
        espaco.aplicar(criar("codigo", area={"coluna": 0, "linha": 0, "colunas": 4, "linhas": 8}))

    apertado = espaco.aplicar(
        criar("codigo", area={"coluna": 0, "linha": 0, "colunas": 8, "linhas": 8})
    )

    assert not apertado.aceita
    assert "Feche ou minimize" in apertado.motivo


def test_nada_nasce_em_cima_do_nucleo() -> None:
    """O núcleo é zona reservada do modo, não um módulo que dá para empurrar."""
    espaco = Workspace()

    resultado = espaco.aplicar(
        criar("resumo", area={"coluna": 4, "linha": 1, "colunas": 4, "linhas": 4})
    )

    assert resultado.aceita
    assert not espaco.widgets[resultado.widget].area.colide_com(espaco.nucleo)


# --- o que o dono fixou é dele ---------------------------------------------------------------


def test_modulo_fixado_nao_e_movido_nem_fechado_pela_ia() -> None:
    espaco = Workspace()
    criado = espaco.aplicar(criar("conversa"))
    espaco.fixar(criado.widget)

    movido = espaco.aplicar(
        Acao(
            tipo=Tipo.MOVER, widget=criado.widget, area=Area(coluna=0, linha=0, colunas=6, linhas=2)
        )
    )
    fechado = espaco.aplicar(Acao(tipo=Tipo.REMOVER, widget=criado.widget))

    assert not movido.aceita and "o dono fixou" in movido.motivo
    assert not fechado.aceita and "só ele" in fechado.motivo
    assert criado.widget in espaco.widgets


def test_o_dono_move_e_quem_estava_la_se_muda() -> None:
    espaco = Workspace()
    dele = espaco.aplicar(criar("conversa"))
    outro = espaco.aplicar(criar("tarefas"))
    area_do_outro = espaco.widgets[outro.widget].area

    assert espaco.mover_pelo_dono(dele.widget, area_do_outro.coluna, area_do_outro.linha)

    assert espaco.widgets[dele.widget].area.coluna == area_do_outro.coluna
    assert espaco.widgets[outro.widget].area != area_do_outro


# --- integração com a máquina do dono: confirmação ------------------------------------------


def test_componente_sensivel_vira_pendencia_e_so_entra_com_o_sim() -> None:
    espaco = Workspace()
    espaco.aplicar(Acao(tipo=Tipo.MODO, modo=Modo.EXECUCAO))  # é onde um console faz sentido

    proposta = espaco.aplicar(criar("terminal", motivo="acompanhar a saída do build"))

    assert not proposta.aceita and proposta.pendente
    assert "encosta na sua máquina" in proposta.motivo
    assert "acompanhar a saída do build" in proposta.motivo
    assert espaco.widgets == {}, "abriu o console antes de o dono responder"

    feito = espaco.confirmar(proposta.pendencia, sim=True)

    assert feito is not None and feito.aceita
    assert espaco.widgets[feito.widget].componente == "terminal"
    assert espaco.pendentes == {}


def test_pendencia_negada_nao_deixa_resto() -> None:
    espaco = Workspace()
    proposta = espaco.aplicar(criar("screenshots"))

    recusa = espaco.confirmar(proposta.pendencia, sim=False)

    assert recusa is not None and not recusa.aceita
    assert espaco.widgets == {} and espaco.pendentes == {}


# --- fechar não é apagar; trocar de modo não destrói ----------------------------------------


def test_fechar_guarda_e_recuperar_traz_de_volta_com_os_dados() -> None:
    espaco = Workspace()
    criado = espaco.aplicar(
        criar("fontes", dados={"itens": [{"titulo": "Nota do executor", "fonte": "repo"}]})
    )

    assert espaco.fechar_pelo_dono(criado.widget)
    assert [w.id for w in espaco.fechados] == [criado.widget]

    assert espaco.recuperar(criado.widget)
    assert espaco.widgets[criado.widget].dados["itens"][0]["titulo"] == "Nota do executor"
    assert espaco.fechados == []


def test_trocar_de_modo_realoca_em_vez_de_destruir_e_da_para_voltar() -> None:
    espaco = Workspace()
    criado = espaco.aplicar(
        criar("tarefas", area={"coluna": 0, "linha": 0, "colunas": 2, "linhas": 5})
    )
    antes = espaco.widgets[criado.widget].area

    mudanca = espaco.aplicar(Acao(tipo=Tipo.MODO, modo=Modo.PESQUISA))

    assert mudanca.aceita
    assert criado.widget in espaco.widgets, "trocar de modo não pode sumir com módulo"
    assert not espaco.widgets[criado.widget].area.colide_com(espaco.nucleo)

    volta = espaco.aplicar(Acao(tipo=Tipo.RESTAURAR, layout=LAYOUT_ANTERIOR))

    assert volta.aceita
    assert espaco.modo is Modo.ASSISTENTE
    assert espaco.widgets[criado.widget].area == antes


def test_restaurar_layout_que_nao_existe_diz_quais_existem() -> None:
    espaco = Workspace()

    resultado = espaco.aplicar(Acao(tipo=Tipo.RESTAURAR, layout="inventado"))

    assert not resultado.aceita
    assert "não há layout guardado" in resultado.motivo


def test_maximizar_e_restaurar_devolvem_a_area_de_antes() -> None:
    espaco = Workspace()
    criado = espaco.aplicar(criar("codigo"))
    antes = espaco.widgets[criado.widget].area

    assert espaco.maximizar(criado.widget)
    assert espaco.widgets[criado.widget].maximizado
    assert espaco.restaurar_tamanho(criado.widget)

    assert espaco.widgets[criado.widget].area == antes
    assert not espaco.widgets[criado.widget].maximizado


def test_o_estado_de_cada_modulo_e_contado_nao_suposto() -> None:
    """Visto × em execução × resultado: o pedido do dono vira campo, não cor adivinhada."""
    espaco = Workspace()
    criado = espaco.aplicar(criar("codigo"))

    assert espaco.estado_de(criado.widget, EstadoDoWidget.EXECUTANDO)

    assert espaco.widgets[criado.widget].estado is EstadoDoWidget.EXECUTANDO
    assert espaco.para_dict()["widgets"][0]["estado"] == "executando"


def test_toda_proposta_deixa_rastro_no_historico() -> None:
    espaco = Workspace()

    espaco.propor({"tipo": "createWidget", "componente": "iframe"})
    espaco.aplicar(criar("tarefas"))

    assert len(espaco.historico) == 2
    assert espaco.historico[0].frase().startswith("createWidget: recusada")
    assert espaco.historico[1].frase() == "createWidget: feito"
