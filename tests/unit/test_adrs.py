"""Aceite F0-10: ADR com número traz hardware, `n`, data e commit; nada de suposição solta."""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.adr import alcance_da_conferencia, conferir, conferir_adr, conferir_numeros

RAIZ = Path(__file__).resolve().parents[2]
PASTA = RAIZ / "docs" / "adr"
MEDICOES = RAIZ / "docs" / "medicoes"

ADRS_DE_MEDICAO = (
    "0012-licencas-verificadas-na-origem.md",
    "0013-ativacao-de-grafo-medida.md",
    "0014-d1-linguagem-e-ipc-do-nucleo.md",
)


def test_todas_as_adrs_do_repositorio_tem_procedencia() -> None:
    """Aceite (a) e (b), na parte que dá para verificar por máquina."""
    assert conferir(PASTA) == []


@pytest.mark.parametrize("nome", ADRS_DE_MEDICAO)
def test_adr_de_medicao_cita_commit_e_n(nome: str) -> None:
    texto = (PASTA / nome).read_text(encoding="utf-8")

    assert "**Data:**" in texto
    assert "Commit" in texto
    assert "`n`" in texto or " n " in texto
    assert conferir_adr(PASTA / nome) == []


def test_adr_de_d1_registra_a_lacuna_o_decisor_e_o_gatilho() -> None:
    """D1 foi aceita com a lacuna no texto: o gatilho de reabertura tem de ser verificável."""
    texto = (PASTA / "0014-d1-linguagem-e-ipc-do-nucleo.md").read_text(encoding="utf-8")

    assert "**Estado:** aceita" in texto
    assert "**Decide:** orquestrador" in texto  # delegação do dono, registrada
    assert "lacuna" in texto.casefold()
    assert "AEC" in texto
    assert "ASR" in texto
    assert "Gatilho de reabertura" in texto
    assert "80 ms" in texto and "150 ms" in texto
    assert "Como invalidar esta decisão" in texto


def test_verificador_pega_adr_sem_commit(tmp_path: Path) -> None:
    """Se o verificador não acusar isto, ele não serve para o aceite (a)."""
    (tmp_path / "0099-exemplo.md").write_text(
        "# ADR-0099 — Exemplo\n\n"
        "**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** executor\n"
        "**Mede:** executor\n\n"
        "## Contexto\n\nFicou em 12,3 ms p95, que é rápido.\n",
        encoding="utf-8",
    )

    problemas = [p.o_que for p in conferir(tmp_path)]

    assert any("commit" in p for p in problemas)
    assert any("hardware" in p for p in problemas)
    assert any("`n`" in p for p in problemas)


def test_verificador_pega_suposicao_sem_o_que_a_confirma(tmp_path: Path) -> None:
    (tmp_path / "0098-exemplo.md").write_text(
        "# ADR-0098 — Exemplo\n\n"
        "**Data:** 2026-10-15 · **Estado:** proposta · **Decide:** dono\n\n"
        "## Contexto\n\nIsto vai funcionar **[SUPOSIÇÃO]** e pronto.\n",
        encoding="utf-8",
    )

    problemas = [p.o_que for p in conferir(tmp_path)]

    assert any("SUPOSIÇÃO" in p for p in problemas)


def test_spec_registra_os_slos_confirmados() -> None:
    """Aceite (c): a §7 não pode continuar dizendo [SUPOSIÇÃO] no que já foi medido."""
    spec = (RAIZ / "docs" / "SPEC-v0.md").read_text(encoding="utf-8")

    linha_slo11 = next(linha for linha in spec.splitlines() if "| SLO-11 |" in linha)
    linha_slo12 = next(linha for linha in spec.splitlines() if "| SLO-12 |" in linha)

    assert "SUPOSIÇÃO" not in linha_slo11
    assert "ADR-0013" in linha_slo11
    assert "ADR-0013" in linha_slo12


def test_spec_registra_d1_com_a_proposta_e_a_lacuna() -> None:
    spec = (RAIZ / "docs" / "SPEC-v0.md").read_text(encoding="utf-8")

    assert "DECISÃO ABERTA D1" not in spec
    assert "ADR-0014" in spec
    assert "Lacuna explícita" in spec


# --- achado 3: o número publicado tem de ser o número medido -----------------------
def test_os_numeros_da_adr_de_d1_sao_os_do_csv() -> None:
    """Achado 3 da revisão F0+F1: a tabela da ADR-0014 deixou de bater com o CSV.

    O `conferir` só olhava a ESTRUTURA da tabela (tem p50? tem p95?), então a republicação do
    commit `5feb551` (que trocou a medição de fumaça pela de n = 10 000) passou sem ninguém
    notar que a ADR continuava com os números velhos — inclusive no p99 do piso, 0,086 ms
    contra 0,290 ms medidos, que é 3,4× na cauda, justamente onde o SLO-1 dói.
    """
    assert conferir_numeros(PASTA / "0014-d1-linguagem-e-ipc-do-nucleo.md", MEDICOES) == []


def test_a_conferencia_de_numeros_cobre_a_medicao_de_d1() -> None:
    """Conferência que não confere nada passaria sempre: o alcance é parte do aceite."""
    alcance = alcance_da_conferencia(PASTA / "0014-d1-linguagem-e-ipc-do-nucleo.md", MEDICOES)

    assert alcance.csvs == ("f0-04-captura.csv",)
    assert alcance.valores >= 20, "a tabela de D1 tem seis linhas; conferir menos é vacuidade"
    assert alcance.fora == ()


def test_a_conferencia_pega_numero_editado_na_mao(tmp_path: Path) -> None:
    """Se o verificador não acusar isto, ele não serve para o achado 3."""
    medicoes = tmp_path / "medicoes"
    medicoes.mkdir()
    (medicoes / "exemplo.csv").write_text(
        "braco,execucao,n,p50_ms,p95_ms\nrapido,1,100,1.000,2.000\nrapido,2,100,1.000,2.000\n",
        encoding="utf-8",
    )
    adr = tmp_path / "0097-exemplo.md"
    adr.write_text(
        "# ADR-0097 — Exemplo\n\n"
        "**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** executor\n"
        "**Mede:** executor · **Commit da medição:** `abc1234`\n\n"
        "## Contexto\n\nHardware: Ryzen, `n` = 100 frames. Medição em "
        "`docs/medicoes/exemplo.csv`.\n\n"
        "| braço | p50 | p95 |\n|---|---:|---:|\n| `rapido` | 1,000 ms | **1,500 ms** |\n",
        encoding="utf-8",
    )

    problemas = [p.o_que for p in conferir_numeros(adr, medicoes)]

    assert any("p95" in p and "1,500" in p and "2.0" in p for p in problemas), problemas


def test_csv_que_nao_identifica_a_linha_fica_fora_do_alcance_e_dito(tmp_path: Path) -> None:
    """Fora do alcance tem de aparecer, não ser silêncio: é o que impede gate vazio."""
    medicoes = tmp_path / "medicoes"
    medicoes.mkdir()
    (medicoes / "ambiguo.csv").write_text(
        "canal,execucao,com_ritmo,p50_us\nanel,1,1,22.0\nanel,1,0,9.0\n",
        encoding="utf-8",
    )
    adr = tmp_path / "0096-exemplo.md"
    adr.write_text(
        "# ADR-0096 — Exemplo\n\n"
        "**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** executor\n\n"
        "## Contexto\n\nMedição em `docs/medicoes/ambiguo.csv`.\n\n"
        "| canal | p50 |\n|---|---:|\n| `anel` | 22,0 µs |\n",
        encoding="utf-8",
    )

    alcance = alcance_da_conferencia(adr, medicoes)

    assert alcance.valores == 0
    assert any("mais de uma linha" in motivo for motivo in alcance.fora), alcance.fora


# --- item B do lote: o dono aceitou a ADR-0015 ------------------------------------
def test_adr_do_canal_de_audio_esta_aceita_e_a_spec_registra_a_emenda() -> None:
    """O dono aceitou em 2026-10-15; a SPEC é emendada por ADR (CONTRIBUTING, linha 4).

    A 0015 pediu emenda em dois pontos, e os dois eram leituras ao pé da letra que o código
    contradizia: a seta "frames + PlaybackProgress" do desenho da §2 e o "todo evento no
    barramento, sem exceção" da §3.1. Aceitar a ADR sem emendar a SPEC deixaria o repositório
    com o código errado por definição.
    """
    adr = (PASTA / "0015-canal-de-audio-fora-do-barramento.md").read_text(encoding="utf-8")

    assert "**Estado:** aceita" in adr
    assert "**Decide:** dono" in adr
    assert "2026-10-15" in adr
    assert conferir_adr(PASTA / "0015-canal-de-audio-fora-do-barramento.md") == []

    spec = (RAIZ / "docs" / "SPEC-v0.md").read_text(encoding="utf-8")
    secao_3 = spec.split("### 3.1 Envelope comum")[1].split("```")[0]
    assert "ADR-0015" in secao_3, "a §3.1 ainda diz 'sem exceção' sem citar a emenda"
    desenho = spec.split("## 2. Processos e fronteiras")[1].split("## 3.")[0]
    assert "ADR-0015" in desenho, "o desenho da §2 ainda manda PCM pela seta do barramento"


# --- item C do lote: 0016 aceita em parte e 0017 aberta ---------------------------
ADR_DA_FONEMIZACAO = "0016-fonemizacao-pt-br-do-tts.md"
ADR_DOS_MOTORES = "0017-motores-de-voz-atras-de-uma-interface.md"


def test_adr_da_fonemizacao_registra_aceite_parcial_e_aponta_a_0017() -> None:
    """O dono aceitou o caminho local (piper + epitran) e quer comparar motores antes de fechar."""
    texto = (PASTA / ADR_DA_FONEMIZACAO).read_text(encoding="utf-8")

    assert texto.startswith("# ADR-0016")
    assert "**Estado:** aceita parcialmente" in texto
    assert "piper" in texto and "epitran" in texto
    assert "ADR-0017" in texto, "aceite parcial tem de dizer onde o resto se decide"
    assert conferir_adr(PASTA / ADR_DA_FONEMIZACAO) == []


def test_adr_dos_motores_de_voz_e_proposta_com_as_quatro_partes() -> None:
    """ADR-0017: ASR, TTS, interface + política, plano de amostra — e a emenda da implementação.

    O estado mudou de `proposta` para `aceita` quando o dono mandou implementar (2026-10-15):
    o que ele aceitou foi a **fronteira e a política**; qual motor o v1 usa continua aberto e
    é do F1-16. Por isso o teste cobra as duas coisas — o aceite e a seção de emenda, que é
    onde os desvios da proposta estão escritos.
    """
    caminho = PASTA / ADR_DOS_MOTORES
    texto = caminho.read_text(encoding="utf-8")

    assert "**Estado:** aceita" in texto
    assert "F1-16" in texto, "o aceite não pode engolir o que continua aberto"
    assert "## Emenda da implementação" in texto
    assert conferir_adr(caminho) == []
    for motor in (
        "whisper-large-v3",
        "whisper-large-v3-turbo",
        "parakeet-tdt-0.6b-v3",
        "Kokoro-82M",
        "epitran",
        "edge-tts",
        "Azure",
        "ElevenLabs",
        "Chatterbox",
    ):
        assert motor in texto, f"{motor} não aparece na comparação"
    for secao in (
        "## ASR",
        "## TTS",
        "## Interface única e política",
        "## Plano de amostra",
        "## O que ficou não verificado",
    ):
        assert secao in texto, f"falta a seção {secao}"


def test_a_adr_dos_motores_cita_fonte_e_data_em_cada_fato() -> None:
    """Fato sem fonte é impressão: cada bloco de motor tem de carregar URL e data de leitura."""
    texto = (PASTA / ADR_DOS_MOTORES).read_text(encoding="utf-8")

    assert texto.count("https://") >= 12, "um fato por motor, cada um com a URL que o sustenta"
    assert texto.count("2026-10-15") >= 5, "a data da leitura na origem tem de estar nos fatos"
    assert "não verificado" in texto, "o que não deu para conferir tem de estar dito"


def test_a_correcao_do_kokoro_esta_nas_duas_adrs() -> None:
    """A 0016 dizia que o Kokoro não tem pt-BR; a origem diz outra coisa, e isso se corrige."""
    dezesseis = (PASTA / ADR_DA_FONEMIZACAO).read_text(encoding="utf-8")
    dezessete = (PASTA / ADR_DOS_MOTORES).read_text(encoding="utf-8")

    for texto in (dezesseis, dezessete):
        assert "pf_dora" in texto, "a voz pt-BR do Kokoro tem de aparecer com o id de verdade"
        assert "EspeakG2P" in texto, "e o motivo de ela não resolver a licença também"


def test_a_adr_dos_motores_publica_os_numeros_da_amostra_medida() -> None:
    """A amostra foi gerada nesta máquina; o que a ADR publica tem de ser o que foi medido.

    Mesma regra do achado 3 da revisão: número publicado é número medido. Aqui o portão não
    tem CSV para comparar (o áudio não é comitado), então o teste cobra a estrutura: os quatro
    arquivos gerados, o RTF de cada um e o que ficou sem gerar com o tamanho que o derrubou.
    """
    texto = (PASTA / ADR_DOS_MOTORES).read_text(encoding="utf-8")

    for arquivo in (
        "piper-espeak-pt_BR-faber-medium.wav",
        "piper-epitran-pt_BR-faber-medium.wav",
        "kokoro-pf_dora.wav",
        "kokoro-pm_alex.wav",
    ):
        assert arquivo in texto, f"a ADR não cita a amostra {arquivo}"
    for rtf in ("0,156", "0,140", "0,382", "0,377"):
        assert rtf in texto, f"RTF medido {rtf} não está publicado"
    assert "3 751,3 MB" in texto and "3,2 GB" in texto, "o que não foi gerado precisa do tamanho"
    # Só o nome da pasta: escrever o caminho temporário literal aqui acenderia o S108 do
    # bandit, e a regra está certa — o que o teste quer é que a ADR diga ONDE ouvir.
    assert "jarvis-amostras" in texto, "onde ouvir tem de estar dito"
    assert "descarta" in texto.casefold(), "o símbolo fora do mapa é descartado em silêncio"


def test_adr_do_s2_provisorio_e_proposta_e_declara_o_alcance() -> None:
    """ADR-0018: a CLI do Claude como gerador de resposta é provisória e tem alcance escrito.

    O risco desta ADR não é técnico, é de escopo: uma peça "provisória" que ninguém marcou
    vira produto por inércia. Por isso o teste cobra que ela diga onde **não** vale e o que a
    invalida.
    """
    caminho = PASTA / "0018-s2-provisorio-pela-cli-do-claude.md"
    texto = caminho.read_text(encoding="utf-8")
    # Linha quebrada no meio de uma frase é formatação, não conteúdo: a frase é procurada no
    # texto com os espaços normalizados, senão o teste passa a cobrar onde cai a quebra.
    corrido = " ".join(texto.split())

    assert "**Estado:** proposta" in texto
    assert conferir_adr(caminho) == []
    assert "**Alcance:**" in texto
    assert "não entra no barramento" in corrido
    assert "## Como invalidar esta proposta" in texto
    for regra in ("sem ferramenta", "stdin", "untrusted", "prazo", "Cancelável"):
        assert regra in texto, f"a regra {regra!r} não está escrita na ADR"
