"""A trilha de diagnóstico: só metadados, redigida, curta, rotativa e legível pelo diagnóstico."""

from __future__ import annotations

import json
import time
from pathlib import Path

from jarvis.trilha import (
    ARQUIVO,
    CAMPOS,
    CAUSAS,
    DIAS_DE_RETENCAO,
    EVENTOS,
    FORA_DA_FORMA,
    PERMISSAO_DA_PASTA,
    PERMISSAO_DO_ARQUIVO,
    SEGUNDOS_POR_DIA,
    TrilhaDeDiagnostico,
    codigo_do_motivo,
    eventos_do_ultimo_turno,
    limites,
    resumo_do_ultimo_turno,
    ruidos_descartados,
)


def _linhas(pasta: Path) -> list[dict[str, object]]:
    return [json.loads(linha) for linha in (pasta / ARQUIVO).read_text("utf-8").splitlines()]


def test_texto_e_redigido_e_cortado_e_numero_fica_como_esta(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path, relogio=lambda: 10.0)
    trilha.novo_turno("t-1", motor="eco")
    trilha.evento("turno.fim", ms_total=12.5, erro="chave sk-abcdefghijklmnopqrstuv " + "a" * 400)
    evento = _linhas(tmp_path)[1]
    assert evento["turno"] == "t-1" and evento["ms_total"] == 12.5
    erro = str(evento["erro"])
    assert "sk-abcdefghijklmnopqrstuv" not in erro and "[REDIGIDO:" in erro
    assert len(erro) <= 161


def test_gira_o_arquivo_e_guarda_so_as_copias_combinadas(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path, tamanho_maximo=300, copias=2)
    for i in range(40):
        trilha.evento("ferramenta", tool_id=f"t{i}", motivo="erro_da_ferramenta+pdp_negou")
    nomes = sorted(p.name for p in tmp_path.iterdir())
    assert nomes == [ARQUIVO, f"{ARQUIVO}.1", f"{ARQUIVO}.2"]
    assert all(p.stat().st_size <= 300 for p in tmp_path.iterdir())


def test_disco_que_falha_nao_derruba_o_turno(tmp_path: Path) -> None:
    arquivo_no_lugar_da_pasta = tmp_path / "ocupado"
    arquivo_no_lugar_da_pasta.write_text("não sou pasta", "utf-8")
    TrilhaDeDiagnostico(arquivo_no_lugar_da_pasta).evento("ferramenta", tool_id="x")


def test_o_resumo_e_do_ultimo_turno_com_ferramenta_permissao_e_fim(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-velho", motor="eco")
    trilha.evento("ferramenta", tool_id="velha", status="ok")
    trilha.novo_turno("t-novo", motor="claude")
    trilha.evento(
        "ferramenta",
        tool_id="browser.click",
        status="erro",
        ms=40.0,
        pdp="allow",
        motivo="erro_da_ferramenta",
        codigo=codigo_do_motivo("a página não deixou (alvo_ausente): não achei"),
    )
    trilha.evento(
        "permissao", tool_id="sites.open", origem="pdp", motivo="destino_externo", resposta="não"
    )
    trilha.evento("turno.fim", fim="concluido", ms_total=900.0, ferramentas=2)

    assert [e["turno"] for e in eventos_do_ultimo_turno(tmp_path)] == ["t-novo"] * 4
    texto = "\n".join(resumo_do_ultimo_turno(tmp_path))
    assert "motor claude" in texto and "velha" not in texto
    assert "browser.click: erro em 40 ms (PDP allow) [alvo_ausente] — erro_da_ferramenta" in texto
    assert "pediu permissão para sites.open (pdp): destino_externo → não" in texto
    assert "fim: concluido" in texto and "total 900 ms" in texto


def test_sem_trilha_o_resumo_diz_que_nao_ha_turno(tmp_path: Path) -> None:
    assert "nenhum turno" in resumo_do_ultimo_turno(tmp_path / "nada")[0]


def test_a_linha_do_fim_diz_quantos_passos_antigos_foram_podados(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    trilha.evento("turno.fim", fim="concluido", ms_total=10.0, ferramentas=7, resultados_podados=3)
    assert any("passos antigos podados 3" in linha for linha in resumo_do_ultimo_turno(tmp_path))


def test_a_linha_da_ferramenta_diz_a_fase_e_a_do_fim_o_estado_do_objetivo(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    trilha.evento("ferramenta", tool_id="browser.read", status="ok", ms=5.0, fase="verificando")
    trilha.evento("turno.fim", fim="concluido", ms_total=9.0, ferramentas=1, objetivo="concluido")
    texto = "\n".join(resumo_do_ultimo_turno(tmp_path))
    assert "browser.read: ok em 5 ms (PDP ?) · fase verificando" in texto
    assert "objetivo concluido" in texto


# --- allowlist de campos (dono, 2026-10-20): o que não está na lista não é gravado -------------


def test_campo_de_fora_da_allowlist_nao_e_gravado_e_o_nome_aparece(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    trilha.evento(
        "ferramenta",
        tool_id="browser.click",
        status="ok",
        url="https://banco.example/conta/123?token=abc",
        texto_da_pagina="saldo: 10 mil",
        seletor="#senha",
    )
    evento = _linhas(tmp_path)[1]

    assert set(evento) == {"t", "turno", "evento", "tool_id", "status", "campos_fora"}
    assert evento["campos_fora"] == ["seletor", "texto_da_pagina", "url"]
    bruto = (tmp_path / ARQUIVO).read_text("utf-8")
    for proibido in ("banco.example", "token=abc", "saldo", "#senha"):
        assert proibido not in bruto, proibido


def test_campo_permitido_noutro_evento_nao_entra_neste(tmp_path: Path) -> None:
    """`motivo` existe, mas não em `turno.inicio`: a allowlist é por evento, não global."""
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude", motivo="o dono pediu o extrato do banco")
    evento = _linhas(tmp_path)[0]

    assert evento["campos_fora"] == ["motivo"] and "motivo" not in evento
    assert "extrato" not in (tmp_path / ARQUIVO).read_text("utf-8")


def test_evento_desconhecido_grava_so_o_cabecalho(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    trilha.evento("fala.do.dono", motivo="minha senha é hunter2hunter2", tool_id="x")
    evento = _linhas(tmp_path)[1]

    fora = evento["campos_fora"]
    assert set(evento) == {"t", "turno", "evento", "campos_fora"}
    assert evento["evento"] == "fala.do.dono"
    assert isinstance(fora, list) and sorted(fora) == ["motivo", "tool_id"]
    assert "hunter2" not in (tmp_path / ARQUIVO).read_text("utf-8")


def test_valor_fora_da_forma_do_campo_vira_marca(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    trilha.evento(
        "ferramenta",
        tool_id="olha o extrato do banco do dono",  # frase onde devia vir um código
        status="ok",
        ms="rápido",
        argumentos={"path": "~/Documentos"},  # mapa onde devia vir a lista de nomes
    )
    evento = _linhas(tmp_path)[1]

    assert evento["tool_id"] == FORA_DA_FORMA and evento["ms"] == FORA_DA_FORMA
    assert evento["argumentos"] == FORA_DA_FORMA
    assert "extrato" not in (tmp_path / ARQUIVO).read_text("utf-8")


def test_a_lista_de_argumentos_guarda_nomes_e_nao_valores(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    trilha.evento("ferramenta", tool_id="files.list_dir", argumentos=["path", "minha senha"])
    assert _linhas(tmp_path)[1]["argumentos"] == ["path", FORA_DA_FORMA]


def test_todo_campo_de_todo_evento_tem_forma_declarada() -> None:
    """Allowlist sem furo: nenhum evento pode permitir campo que `CAMPOS` não conhece."""
    for tipo, permitidos in EVENTOS.items():
        assert permitidos <= set(CAMPOS), tipo


def test_texto_de_erro_perde_a_url_inteira_e_o_caminho(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    trilha.evento(
        "turno.fim",
        fim="erro",
        erro=(
            "não achei o alvo (alvo_ausente) em https://conta.example/extrato/2026?cpf=111 "
            "nem no arquivo /home/sodre/Documentos/extrato-do-banco.pdf"
        ),
    )
    erro = str(_linhas(tmp_path)[1]["erro"])

    assert "(alvo_ausente)" in erro and "https://conta.example/…" in erro
    assert "extrato/2026" not in erro and "cpf=111" not in erro
    assert "extrato-do-banco" not in erro and "/…" in erro


# --- o motivo é código (auditoria dos Lotes B e C, achado 2) -------------------------------------
SENTINELA = "SENTINELA-DA-PAGINA " + "rótulo que a página escreveu " * 8  # > 160 caracteres


def test_o_motivo_so_grava_codigo_da_allowlist_e_a_frase_vira_marca(tmp_path: Path) -> None:
    """A frase da pergunta cita o rótulo que a página dá ao elemento: na trilha ela não entra,
    nem cortada em 160 caracteres. Código da allowlist (ou vários, com `+`) entra como está."""
    assert len(SENTINELA) > 160
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    frase = f"clicar em «{SENTINELA}» envia uma mensagem ou publicação"
    trilha.evento("permissao", tool_id="browser.click", origem="risco_dinamico", motivo=frase)
    trilha.evento("ferramenta", tool_id="browser.click", status="negado", motivo=SENTINELA[:30])
    trilha.evento("permissao", tool_id="browser.click", motivo="palavra_de_risco")
    trilha.evento("permissao", tool_id="input.key.type", motivo="enter_envia+turno_contaminado")
    trilha.evento("permissao", tool_id="input.key.type", motivo="enter_envia+inventado")
    trilha.evento("ferramenta", tool_id="browser.read", status="ok", motivo="")
    motivos = [e.get("motivo") for e in _linhas(tmp_path)[1:]]

    assert motivos == [
        FORA_DA_FORMA,
        FORA_DA_FORMA,
        "palavra_de_risco",
        "enter_envia+turno_contaminado",
        FORA_DA_FORMA,
        "",
    ]
    assert "SENTINELA" not in (tmp_path / ARQUIVO).read_text("utf-8")


def test_o_codigo_da_extensao_so_vem_do_comeco_da_frase() -> None:
    """No meio da frase pode estar o rótulo do elemento: "(algo)" ali não vira código."""
    assert codigo_do_motivo("a página não deixou (alvo_ausente): não achei") == "alvo_ausente"
    assert codigo_do_motivo("«Nome (sentinela_da_pagina)» não é um campo de texto") == ""
    assert codigo_do_motivo("este pedido vai pelo método app (cita_app): fica de fora") == ""


def test_a_allowlist_de_causas_so_tem_codigos() -> None:
    assert all(c and c == c.strip() and " " not in c and "+" not in c for c in CAUSAS)


# --- local, permissões, rotação e retenção ----------------------------------------------------


def test_a_pasta_e_o_arquivo_ficam_so_para_o_dono(tmp_path: Path) -> None:
    pasta = tmp_path / "diagnostico"
    pasta.mkdir()
    (pasta / ARQUIVO).write_text("", "utf-8")
    (pasta / ARQUIVO).chmod(0o644)  # arquivo da versão antiga, com permissão frouxa
    pasta.chmod(0o755)

    TrilhaDeDiagnostico(pasta).evento("ferramenta", tool_id="x")

    assert pasta.stat().st_mode & 0o777 == PERMISSAO_DA_PASTA
    assert (pasta / ARQUIVO).stat().st_mode & 0o777 == PERMISSAO_DO_ARQUIVO


def test_arquivo_sem_toque_alem_da_retencao_e_apagado(tmp_path: Path) -> None:
    velho = TrilhaDeDiagnostico(tmp_path)
    velho.novo_turno("t-velho", motor="claude")
    (tmp_path / f"{ARQUIVO}.1").write_text('{"evento": "turno.inicio", "turno": "t-1"}\n', "utf-8")
    assert (tmp_path / ARQUIVO).exists()

    adiante = time.time() + (DIAS_DE_RETENCAO + 1) * SEGUNDOS_POR_DIA
    TrilhaDeDiagnostico(tmp_path, relogio=lambda: adiante).evento("ferramenta", tool_id="x")

    linhas = _linhas(tmp_path)
    assert not (tmp_path / f"{ARQUIVO}.1").exists()
    assert len(linhas) == 1 and linhas[0]["tool_id"] == "x"  # o antigo saiu, o novo nasceu


def test_a_retencao_nao_apaga_o_que_esta_dentro_do_prazo(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    TrilhaDeDiagnostico(tmp_path).evento("ferramenta", tool_id="x")
    assert [e["evento"] for e in _linhas(tmp_path)] == ["turno.inicio", "ferramenta"]


def test_os_limites_dizem_onde_mora_quanto_gira_e_quanto_dura(tmp_path: Path) -> None:
    TrilhaDeDiagnostico(tmp_path).evento("ferramenta", tool_id="x")
    texto = "\n".join(limites(tmp_path))

    assert str(tmp_path / ARQUIVO) in texto and "0600" in texto and "0700" in texto
    assert "rotação: 512 KiB por arquivo e 3 cópias" in texto
    assert f"retenção: {DIAS_DE_RETENCAO} dias" in texto and "nada sai da máquina" in texto


# --- resumo honesto -----------------------------------------------------------------------------


def test_ferramenta_que_comecou_e_nao_terminou_aparece_assim(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    trilha.evento("ferramenta.inicio", tool_id="browser.click", argumentos=["seletor"], pdp="allow")
    texto = "\n".join(resumo_do_ultimo_turno(tmp_path))

    assert "ferramenta browser.click: começou e não terminou (sem resultado na trilha)" in texto
    assert "sem linha de fim: o turno foi interrompido ou o app saiu antes" in texto


def test_inicio_com_fim_aparece_uma_vez_so(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-1", motor="claude")
    trilha.evento("ferramenta.inicio", tool_id="files.list_dir", argumentos=["path"], pdp="allow")
    trilha.evento("ferramenta", tool_id="files.list_dir", status="ok", ms=3.0, pdp="allow")
    trilha.evento("turno.fim", fim="concluido", ms_total=10.0, ferramentas=1)
    texto = "\n".join(resumo_do_ultimo_turno(tmp_path))

    assert texto.count("files.list_dir") == 1 and "começou e não terminou" not in texto
    assert "sem linha de fim" not in texto


def test_sem_turno_o_resumo_explica_e_cita_a_retencao(tmp_path: Path) -> None:
    linha = resumo_do_ultimo_turno(tmp_path / "vazia")[0]
    assert "nenhum turno registrado" in linha and f"{DIAS_DE_RETENCAO} dias" in linha


def test_o_evento_de_ruido_leva_codigos_e_numeros_e_a_contagem_sai_por_motivo(
    tmp_path: Path,
) -> None:
    """ADR-0043: o trecho que não virou pedido — etapa, motivo e números. Um campo de texto que
    alguém tente pôr ali (o que o ASR ouviu) não é gravado: só o nome dele aparece."""
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.evento("ruido", turno="escuta", etapa="trecho", motivo="impulso", maior_fala_ms=40.0)
    trilha.evento(
        "ruido", turno="escuta", etapa="texto", motivo="sem_fala", sem_fala=0.55, texto="Obrigado."
    )
    trilha.evento("ruido", turno="escuta", etapa="trecho", motivo="impulso", contraste_db=35.7)

    linhas = [json.loads(linha) for linha in (tmp_path / ARQUIVO).read_text().splitlines()]
    assert linhas[0]["motivo"] == "impulso" and linhas[0]["maior_fala_ms"] == 40.0
    assert "texto" not in linhas[1] and linhas[1]["campos_fora"] == ["texto"]
    assert "Obrigado" not in (tmp_path / ARQUIVO).read_text()
    assert ruidos_descartados(tmp_path) == {"impulso": 2, "sem_fala": 1}
    assert ruidos_descartados(tmp_path / "nao-existe") == {}
