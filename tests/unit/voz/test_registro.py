"""O portão de motor de voz: as quatro recusas e o aviso que vem dos campos (ADR-0017)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.voz.interface import Onde
from jarvis.voz.registro import (
    CAMPOS_DE_NUVEM,
    MOTORES_DE_NUVEM_LIGADOS_POR_PADRAO,
    Motor,
    MotorRecusado,
    conferir,
    exigir_motor,
    ler_motores,
    motor_registrado,
    motores_de,
)

REGISTRO_MINIMO = """
[[motor]]
id = "local-ok"
papel = "tts"
onde = "local"
ligado = true
licenca_do_cliente = "MIT"
marca_dagua = "não"
fonte = "https://exemplo.invalid/licenca"
data_de_acesso = "2026-10-15"

[[motor]]
id = "nuvem-completa"
papel = "asr"
onde = "nuvem"
ligado = false
servico = "Serviço"
variavel_da_chave = "JARVIS_TESTE_API_KEY"
licenca_do_cliente = "Apache-2.0"
uso_comercial = "permitido"
retencao_declarada = "até 30 dias"
treina_com_entrada = "não"
dono_da_saida = "o cliente"
marca_dagua = "não"
fonte = "https://exemplo.invalid/termos"
data_de_acesso = "2026-10-15"

[[motor]]
id = "nuvem-sem-termos"
papel = "tts"
onde = "nuvem"
ligado = false
servico = "Serviço sem contrato"
licenca_do_cliente = "LGPL-3.0"
uso_comercial = ""
retencao_declarada = ""
treina_com_entrada = ""
dono_da_saida = ""
marca_dagua = "não declarada"
fonte = "https://exemplo.invalid/pacote"
data_de_acesso = "2026-10-15"

[[motor]]
id = "licenca-copyleft"
papel = "tts"
onde = "local"
ligado = true
licenca_do_cliente = "GPL-3.0"
marca_dagua = "não"
fonte = "https://exemplo.invalid/gpl"
data_de_acesso = "2026-10-15"

[[motor]]
id = "marca-dagua"
papel = "tts"
onde = "nuvem"
ligado = false
servico = "Marcador"
licenca_do_cliente = "MIT"
uso_comercial = "permitido"
retencao_declarada = "nenhuma"
treina_com_entrada = "não"
dono_da_saida = "o cliente"
marca_dagua = "sim, PerTh em todo áudio gerado"
fonte = "https://exemplo.invalid/marca"
data_de_acesso = "2026-10-15"
"""


@pytest.fixture
def registro(tmp_path: Path) -> Path:
    arquivo = tmp_path / "motores.toml"
    arquivo.write_text(REGISTRO_MINIMO, encoding="utf-8")
    return arquivo


def test_motor_nao_registrado_nao_roda(registro: Path) -> None:
    with pytest.raises(MotorRecusado, match="não está em"):
        exigir_motor("inventado", arquivo=registro)


def test_licenca_nao_permissiva_do_cliente_barra(registro: Path) -> None:
    """A régua da ADR-0011 vale para a biblioteca que faz a chamada, não só para o peso."""
    with pytest.raises(MotorRecusado, match="não é permissiva"):
        exigir_motor("licenca-copyleft", arquivo=registro)


def test_campo_de_termos_vazio_barra_a_nuvem(registro: Path) -> None:
    """Política 4: no v0, 'não verificado' não liga nuvem — é o caso do `tts-edge`."""
    with pytest.raises(MotorRecusado) as erro:
        exigir_motor("nuvem-sem-termos", arquivo=registro)
    for campo in CAMPOS_DE_NUVEM:
        assert campo in str(erro.value)


def test_nuvem_completa_continua_desligada_sem_o_dono(registro: Path) -> None:
    """Ter os termos em ordem **não** liga nuvem: falta o interruptor do dono (política 1)."""
    with pytest.raises(MotorRecusado, match="está desligado"):
        exigir_motor("nuvem-completa", arquivo=registro)


def test_nuvem_liga_pela_lista_do_dono(registro: Path) -> None:
    motor = exigir_motor("nuvem-completa", arquivo=registro, nuvem_ligada=["nuvem-completa"])
    assert motor.onde is Onde.NUVEM


def test_interruptor_de_outro_motor_nao_liga_este(registro: Path) -> None:
    with pytest.raises(MotorRecusado, match="está desligado"):
        exigir_motor("nuvem-completa", arquivo=registro, nuvem_ligada=["marca-dagua"])


def test_motor_local_roda_sem_interruptor(registro: Path) -> None:
    assert exigir_motor("local-ok", arquivo=registro).onde is Onde.LOCAL


def test_aviso_de_nuvem_vem_dos_campos(registro: Path) -> None:
    """Política 3: os quatro campos aparecem no aviso, e ele é derivado, não escrito à mão."""
    motor = motor_registrado("nuvem-completa", arquivo=registro)
    assert motor is not None
    frase = motor.frase_de_aviso
    assert "sai desta máquina para Serviço" in frase
    assert "o seu áudio" in frase  # papel asr: o que sai é o áudio
    for valor in ("até 30 dias", "não", "o cliente", "permitido"):
        assert valor in frase
    assert "https://exemplo.invalid/termos" in frase
    assert "2026-10-15" in frase


def test_aviso_muda_quando_o_fato_muda(registro: Path, tmp_path: Path) -> None:
    """Se o aviso fosse prosa na tela, mudar a retenção não mudaria o que o dono lê."""
    outro = tmp_path / "outro.toml"
    outro.write_text(
        REGISTRO_MINIMO.replace(
            'retencao_declarada = "até 30 dias"', 'retencao_declarada = "90 dias"'
        ),
        encoding="utf-8",
    )
    antes = motor_registrado("nuvem-completa", arquivo=registro)
    depois = motor_registrado("nuvem-completa", arquivo=outro)
    assert antes is not None and depois is not None
    assert "até 30 dias" in antes.frase_de_aviso
    assert "90 dias" in depois.frase_de_aviso


def test_motor_local_nao_tem_aviso(registro: Path) -> None:
    motor = motor_registrado("local-ok", arquivo=registro)
    assert motor is not None
    assert motor.frase_de_aviso == ""


def test_texto_do_tts_e_audio_do_asr_sao_ditos_diferente(registro: Path) -> None:
    asr = motor_registrado("nuvem-completa", arquivo=registro)
    tts = motor_registrado("marca-dagua", arquivo=registro)
    assert asr is not None and tts is not None
    assert "o seu áudio" in asr.frase_de_aviso
    assert "o texto que o Jarvis vai falar" in tts.frase_de_aviso


def test_marca_dagua_entra_no_aviso_e_nao_declarada_nao_vira_nao(registro: Path) -> None:
    """Política 5. E "não declarada" é falta de informação, não um "não" otimista."""
    marcador = motor_registrado("marca-dagua", arquivo=registro)
    sem_termos = motor_registrado("nuvem-sem-termos", arquivo=registro)
    limpo = motor_registrado("nuvem-completa", arquivo=registro)
    assert marcador is not None and sem_termos is not None and limpo is not None
    assert marcador.marca_o_audio and "PerTh" in marcador.frase_de_aviso
    assert sem_termos.marca_o_audio  # "não declarada" conta como "pode marcar"
    assert not limpo.marca_o_audio and "Marca d'água" not in limpo.frase_de_aviso


def test_campo_desconhecido_no_toml_nao_quebra_a_leitura(tmp_path: Path) -> None:
    arquivo = tmp_path / "motores.toml"
    arquivo.write_text(
        REGISTRO_MINIMO + '\nlatencia_medida_ms = 123\n[[motor]]\nid = "x"\npapel = "tts"\n'
        'onde = "local"\nligado = true\nlicenca_do_cliente = "MIT"\nmarca_dagua = "não"\n'
        'fonte = "https://exemplo.invalid/x"\ndata_de_acesso = "2026-10-15"\n'
        'campo_que_o_codigo_nao_conhece = "ainda"\n',
        encoding="utf-8",
    )
    assert exigir_motor("x", arquivo=arquivo).id == "x"


def test_conferir_diz_o_que_falta_sem_ler_valor_de_chave(registro: Path) -> None:
    """O diagnóstico recebe **nomes** de variável, nunca valores (ver `jarvis.voz.chaves`)."""
    faltas = conferir(arquivo=registro, nuvem_ligada=["nuvem-completa"], ambiente=())
    por_motor = {f.motor: f.motivo for f in faltas}
    assert "JARVIS_TESTE_API_KEY" in por_motor["nuvem-completa"]
    com_chave = conferir(
        arquivo=registro, nuvem_ligada=["nuvem-completa"], ambiente=["JARVIS_TESTE_API_KEY"]
    )
    assert "nuvem-completa" not in {f.motor for f in com_chave}


def test_filtro_por_papel_e_por_onde(registro: Path) -> None:
    assert {m.id for m in motores_de("tts", arquivo=registro)} == {
        "local-ok",
        "nuvem-sem-termos",
        "licenca-copyleft",
        "marca-dagua",
    }
    assert {m.id for m in motores_de(onde=Onde.NUVEM, arquivo=registro)} == {
        "nuvem-completa",
        "nuvem-sem-termos",
        "marca-dagua",
    }


# --- o registro de verdade, que é o que o produto carrega ---------------------------------


def test_registro_do_produto_nasce_sem_nuvem_ligada() -> None:
    """Política 1 da ADR-0017, conferida no arquivo comitado — não na intenção de quem leu."""
    assert MOTORES_DE_NUVEM_LIGADOS_POR_PADRAO == ()
    for motor in motores_de(onde=Onde.NUVEM):
        assert not motor.ligado, f"{motor.id} nasceu ligado e é de nuvem"


def test_todo_motor_de_nuvem_do_produto_declara_servico_e_chave_ou_diz_porque() -> None:
    for motor in motores_de(onde=Onde.NUVEM):
        assert motor.servico, f"{motor.id} não diz para quem o dado vai"
        assert motor.nota, f"{motor.id} não explica o que o dono precisa saber"


def test_edge_esta_barrado_no_registro_do_produto() -> None:
    """O motor existe implementado; o portão o recusa por falta de termos (ADR-0017)."""
    with pytest.raises(MotorRecusado) as erro:
        exigir_motor("tts-edge", nuvem_ligada=["tts-edge"])
    assert "não verificado" in str(erro.value)


def test_motores_locais_do_produto_passam_no_portao() -> None:
    for motor in motores_de(onde=Onde.LOCAL):
        if motor.id == "tts-piper-espeak":
            continue  # linha de base de medição, fora do produto por licença (ADR-0016)
        assert exigir_motor(motor.id).id == motor.id


def test_piper_com_espeak_e_barrado_por_licenca() -> None:
    """A opção A da ADR-0016 (distribuir espeak-ng) é decisão do dono, não do código."""
    with pytest.raises(MotorRecusado, match="não é permissiva"):
        exigir_motor("tts-piper-espeak")


def test_todo_motor_do_produto_tem_fonte_e_data() -> None:
    for motor in ler_motores():
        assert not set(motor.campos_vazios) & {"fonte", "data_de_acesso"}, motor.id


def test_motor_e_dado_imutavel() -> None:
    motor = Motor(id="x", papel="tts", onde=Onde.LOCAL)
    with pytest.raises((AttributeError, TypeError)):
        motor.ligado = True  # type: ignore[misc]


# --- a liberação "fora do produto" é só de `tools/` ----------------------------------------


def test_so_fora_do_produto_e_liberado_e_so_com_o_parametro() -> None:
    """`tools/` mede a linha de base com espeak-ng; `src/` nunca liga GPL."""
    assert exigir_motor("tts-piper-espeak", permitir_fora_do_produto=True).estado == (
        "fora_do_produto"
    )
    with pytest.raises(MotorRecusado, match="não é permissiva"):
        exigir_motor("tts-piper-espeak")


def test_o_parametro_nao_libera_motor_que_nao_se_declara_fora_do_produto(
    registro: Path,
) -> None:
    with pytest.raises(MotorRecusado, match="não é permissiva"):
        exigir_motor("licenca-copyleft", arquivo=registro, permitir_fora_do_produto=True)


def test_nenhum_arquivo_de_src_pede_a_liberacao() -> None:
    """Varredura estrutural: a decisão de rodar GPL mora em `tools/`, e só lá.

    Um teste de comportamento não pegaria isto — o defeito seria um `True` escrito num
    `dataclass` de `src/` que ninguém revisita. Por isso a prova é por varredura, como o P2
    faz com mapa de frase para ação.
    """
    from pathlib import Path as Caminho

    raiz = Caminho(__file__).resolve().parents[3] / "src"
    culpados = [
        arquivo.relative_to(raiz)
        for arquivo in raiz.rglob("*.py")
        if "permitir_fora_do_produto=True" in arquivo.read_text(encoding="utf-8")
    ]
    assert not culpados, f"`src/` pedindo liberação de GPL: {culpados}"
