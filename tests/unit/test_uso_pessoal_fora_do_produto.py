"""ADR-0039: o que é de uso pessoal (pesos não comerciais) fica **fora** do produto — provado.

A porta de licença continua verde no repositório como está, e tem de **falhar** (código 6)
assim que alguém puser o OmniVoice, ou o PyTorch que só ele usa, no caminho do produto:
dependência, grupo que o empacotador instala, trava, ambiente do projeto, `import` em `src/`,
download do produto, padrão de configuração ou `ligado = true`. Cada injeção abaixo é uma dessas
portas de entrada; o empacotador tem a sua própria recusa, testada no fim.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tools import empacotar
from tools.empacotar import Falhou, Lugares
from tools.license_gate import (
    ARQUIVO_MODELOS,
    ARQUIVO_MOTORES,
    conferir_uso_pessoal,
    inventariar_modelos,
    main,
)

from jarvis.licencas import Categoria

RAIZ = Path(__file__).resolve().parents[2]
PESSOAIS = {"k2-fsa/OmniVoice", "k2-fsa/OmniVoice:audio_tokenizer"}


def injetar(texto: str, ancora: str, linha: str) -> str:
    """Põe `linha` logo depois da primeira `ancora` — que tem de existir, senão o teste mente."""
    assert ancora in texto, f"âncora {ancora!r} sumiu do arquivo de verdade"
    return texto.replace(ancora, ancora + "\n" + linha, 1)


def copia(tmp_path: Path, nome: str, texto: str | None = None) -> Path:
    destino = tmp_path / Path(nome).name
    destino.write_text(
        texto if texto is not None else (RAIZ / nome).read_text("utf-8"), encoding="utf-8"
    )
    return destino


# --- o repositório como está ------------------------------------------------------------------


def test_o_repositorio_como_esta_passa() -> None:
    assert conferir_uso_pessoal() == []
    assert main([]) == 0


def test_os_pesos_estao_registrados_como_nao_comerciais_de_uso_pessoal() -> None:
    registrados = {m.nome: m for m in inventariar_modelos() if m.estado == "uso_pessoal"}
    assert set(registrados) == PESSOAIS
    assert registrados["k2-fsa/OmniVoice"].categoria is Categoria.NAO_COMERCIAL
    assert not any(m.bloqueia for m in registrados.values()), "fora do produto não bloqueia aqui"


def test_a_porta_avisa_extra_opcional_e_nao_comercial(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    saida = capsys.readouterr().out
    assert "EXTRA OPCIONAL: tts-omnivoice" in saida
    assert "NÃO COMERCIAL (uso pessoal): tts-omnivoice" in saida and "CC-BY-NC" in saida
    assert "2 de uso pessoal fora do produto" in saida


# --- dependências: pyproject.toml -------------------------------------------------------------


@pytest.mark.parametrize(
    ("ancora", "linha"),
    [
        ("dependencies = [", '  "omnivoice>=0.2",'),  # dependência do produto
        ("dependencies = [", '  "torch>=2.8",'),  # o PyTorch no produto
        ("voz = [", '    "torchaudio>=2.8",'),  # grupo que o empacotador instala
        ("memoria = [", '    "omnivoice==0.2.1",'),  # idem, com a biblioteca
        ("edge = [", '    "omnivoice==0.2.1",'),  # grupo fora do pacote: nem assim
    ],
)
def test_omnivoice_ou_pytorch_no_pyproject_derruba_a_porta(
    tmp_path: Path, ancora: str, linha: str
) -> None:
    pyproject = copia(tmp_path, "pyproject.toml")
    pyproject.write_text(injetar(pyproject.read_text("utf-8"), ancora, linha), encoding="utf-8")
    assert main(["--pyproject", str(pyproject)]) == 6


def test_um_grupo_proprio_do_omnivoice_tambem_derruba(tmp_path: Path) -> None:
    pyproject = copia(tmp_path, "pyproject.toml")
    texto = injetar(
        pyproject.read_text("utf-8"), "[dependency-groups]", 'omnivoice = ["omnivoice"]'
    )
    pyproject.write_text(texto, encoding="utf-8")
    falhas = conferir_uso_pessoal(pyproject=pyproject)
    assert falhas and "grupo omnivoice" in falhas[0]


def test_pytorch_num_grupo_que_nao_vai_no_pacote_nao_e_produto(tmp_path: Path) -> None:
    """Medição pode usar PyTorch: o que a porta cobra é o caminho do pacote, não o repositório."""
    pyproject = copia(tmp_path, "pyproject.toml")
    pyproject.write_text(
        injetar(pyproject.read_text("utf-8"), "medicao = [", '  "torch>=2.8",'), encoding="utf-8"
    )
    assert conferir_uso_pessoal(pyproject=pyproject) == []


# --- trava: uv.lock ---------------------------------------------------------------------------

PYPROJECT_PEQUENO = """
[project]
name = "jarvis"
dependencies = ["numpy>=2"]

[dependency-groups]
memoria = ["lancedb"]
medicao = ["chromadb"]
"""


def trava(*pacotes: str) -> str:
    return 'version = 1\n\n[[package]]\nname = "numpy"\n\n' + "\n".join(pacotes)


LANCEDB_COM_TORCH = '[[package]]\nname = "lancedb"\ndependencies = [{ name = "torch" }]\n'
LANCEDB_LIMPO = '[[package]]\nname = "lancedb"\ndependencies = [{ name = "numpy" }]\n'
CHROMADB_COM_TORCH = '[[package]]\nname = "chromadb"\ndependencies = [{ name = "torch" }]\n'
TORCH = '[[package]]\nname = "torch"\n'


def test_trava_com_pytorch_alcancavel_pelo_pacote_derruba(tmp_path: Path) -> None:
    pyproject = copia(tmp_path, "pyproject.toml", PYPROJECT_PEQUENO)
    uv_lock = copia(tmp_path, "uv.lock", trava(LANCEDB_COM_TORCH, TORCH))
    falhas = conferir_uso_pessoal(pyproject=pyproject, trava=uv_lock)
    assert falhas == [
        "uv.lock: torch é alcançável a partir do que vai no pacote (dependências do produto + "
        f"grupos {', '.join(empacotar.GRUPOS)})"
    ]
    assert main(["--pyproject", str(pyproject), "--trava", str(uv_lock)]) == 6


def test_trava_com_pytorch_so_num_grupo_de_fora_passa(tmp_path: Path) -> None:
    pyproject = copia(tmp_path, "pyproject.toml", PYPROJECT_PEQUENO)
    uv_lock = copia(tmp_path, "uv.lock", trava(LANCEDB_LIMPO, CHROMADB_COM_TORCH, TORCH))
    assert conferir_uso_pessoal(pyproject=pyproject, trava=uv_lock) == []


def test_o_extra_pedido_entra_no_fecho(tmp_path: Path) -> None:
    """`{ name = "x", extra = ["y"] }` instala as dependências do extra — o fecho segue."""
    pyproject = copia(tmp_path, "pyproject.toml", PYPROJECT_PEQUENO)
    lancedb = (
        '[[package]]\nname = "lancedb"\ndependencies = [{ name = "uvicorn", extra = ["std"] }]\n'
    )
    uvicorn = (
        '[[package]]\nname = "uvicorn"\n\n'
        '[package.optional-dependencies]\nstd = [{ name = "torchaudio" }]\n'
    )
    uv_lock = copia(
        tmp_path, "uv.lock", trava(lancedb, uvicorn, '[[package]]\nname = "torchaudio"\n')
    )
    falhas = conferir_uso_pessoal(pyproject=pyproject, trava=uv_lock)
    assert len(falhas) == 1 and "torchaudio é alcançável" in falhas[0]


def test_omnivoice_em_qualquer_lugar_da_trava_derruba(tmp_path: Path) -> None:
    uv_lock = copia(tmp_path, "uv.lock")
    uv_lock.write_text(
        uv_lock.read_text("utf-8") + '\n[[package]]\nname = "omnivoice"\nversion = "0.2.1"\n',
        encoding="utf-8",
    )
    assert "uv.lock: omnivoice está na trava do projeto" in conferir_uso_pessoal(trava=uv_lock)


# --- ambiente e código ------------------------------------------------------------------------


def test_omnivoice_instalado_no_ambiente_do_projeto_derruba(tmp_path: Path) -> None:
    info = tmp_path / "site-packages" / "omnivoice-0.2.1.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: omnivoice\nVersion: 0.2.1\nLicense-Expression: Apache-2.0\n",
        encoding="utf-8",
    )
    assert main(["--pasta-pacotes", str(info.parent)]) == 6


@pytest.mark.parametrize(
    "linha",
    ["import torch", "from omnivoice import OmniVoice", "    import torchaudio.functional as F"],
)
def test_src_que_importa_a_biblioteca_ou_o_pytorch_derruba(tmp_path: Path, linha: str) -> None:
    fontes = tmp_path / "src"
    (fontes / "jarvis" / "voz").mkdir(parents=True)
    (fontes / "jarvis" / "voz" / "atalho.py").write_text(f"def f():\n{linha}\n", encoding="utf-8")
    assert main(["--fontes", str(fontes)]) == 6


def test_citar_o_nome_em_comentario_nao_e_importar(tmp_path: Path) -> None:
    fontes = tmp_path / "src"
    fontes.mkdir()
    (fontes / "m.py").write_text("# o worker importa torch; daqui, não\nx = 'torch'\n", "utf-8")
    assert conferir_uso_pessoal(fontes=fontes) == []


# --- registro e NOTICE ------------------------------------------------------------------------


def test_peso_pessoal_no_download_do_produto_derruba(tmp_path: Path) -> None:
    modelos = copia(tmp_path, "licenses/modelos.toml")
    texto = injetar(
        modelos.read_text("utf-8"),
        'id = "k2-fsa/OmniVoice"',
        'baixar_de = "https://huggingface.co/k2-fsa/OmniVoice/resolve/main/"',
    )
    modelos.write_text(texto, encoding="utf-8")
    assert main(["--modelos", str(modelos)]) == 6


def test_peso_pessoal_virando_em_uso_bloqueia_como_nao_comercial(tmp_path: Path) -> None:
    modelos = copia(tmp_path, "licenses/modelos.toml")
    texto = modelos.read_text("utf-8")
    ancora = 'licenca = "CC-BY-NC"\nestado = "uso_pessoal"'
    assert ancora in texto
    modelos.write_text(texto.replace(ancora, 'licenca = "CC-BY-NC"\nestado = "em_uso"'), "utf-8")
    assert main(["--modelos", str(modelos)]) != 0


def test_motor_pessoal_ligado_por_padrao_derruba(tmp_path: Path) -> None:
    motores = copia(tmp_path, "licenses/motores.toml")
    texto = motores.read_text("utf-8")
    ancora = 'id = "tts-omnivoice"\npapel = "tts"\nonde = "local"\nligado = false'
    assert ancora in texto
    motores.write_text(texto.replace(ancora, ancora.replace("false", "true")), "utf-8")
    assert main(["--motores", str(motores)]) == 6


def test_motor_pessoal_como_padrao_do_produto_derruba() -> None:
    falhas = conferir_uso_pessoal(padroes={"tts-omnivoice"})
    assert falhas == ["motor tts-omnivoice: é de uso pessoal e virou o padrão do produto"]


def test_sem_atribuicao_no_notice_derruba(tmp_path: Path) -> None:
    aviso = copia(tmp_path, "NOTICE")
    aviso.write_text(aviso.read_text("utf-8").replace("k2-fsa/OmniVoice", "omnivoice"), "utf-8")
    falhas = conferir_uso_pessoal(aviso_legal=aviso)
    assert sorted(falhas) == sorted(
        f"modelo {m}: não aparece no NOTICE (atribuição e aviso)" for m in PESSOAIS
    )


def test_peso_pessoal_que_aponta_para_motor_comum_derruba(tmp_path: Path) -> None:
    modelos = copia(tmp_path, "licenses/modelos.toml")
    texto = modelos.read_text("utf-8").replace('motor = "tts-omnivoice"', 'motor = "tts-edge"', 1)
    modelos.write_text(texto, encoding="utf-8")
    falhas = conferir_uso_pessoal(modelos=modelos, motores=ARQUIVO_MOTORES)
    assert any("não é um motor de uso pessoal" in f for f in falhas)
    assert ARQUIVO_MODELOS.read_text("utf-8").count('motor = "tts-omnivoice"') == 2


# --- o empacotador recusa sozinho -------------------------------------------------------------


def test_o_empacotador_acha_o_que_nao_pode_ir() -> None:
    exportado = (
        "# gerado pelo uv\n-e .\nnumpy==2.3.4\ntorch==2.8.0+cu128 ; sys_platform == 'linux'\n"
        "omnivoice==0.2.1\nTorchAudio==2.8.0\npyside6-essentials==6.9.3\n"
    )
    assert empacotar.proibidos_nos_requisitos(exportado) == ["omnivoice", "torch", "torchaudio"]
    assert empacotar.proibidos_nos_requisitos("numpy==2.3.4\ntorchvision==0.23\n") == []


def test_o_empacotador_acha_o_que_foi_instalado(tmp_path: Path) -> None:
    (tmp_path / "lib" / "site-packages" / "torch-2.8.0.dist-info").mkdir(parents=True)
    (tmp_path / "lib" / "site-packages" / "numpy-2.3.4.dist-info").mkdir(parents=True)
    assert empacotar.proibidos_instalados(tmp_path) == ["torch"]


def test_o_appdir_nao_e_montado_com_pytorch_na_trava_exportada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prova de comportamento: com `torch` na lista exportada, nada é instalado no AppDir."""
    chamadas: list[list[str]] = []

    def rodar_falso(argv: list[str], **_: object) -> None:
        chamadas.append(list(argv))
        if argv[1:3] == ["python", "install"]:
            (Path(argv[4]) / "cpython-3.12-falso" / "bin").mkdir(parents=True)
        if argv[1:2] == ["export"]:
            Path(argv[argv.index("-o") + 1]).write_text("numpy==2.3.4\ntorch==2.8.0\n", "utf-8")

    monkeypatch.setattr(empacotar, "rodar", rodar_falso)
    with pytest.raises(Falhou, match="torch"):
        empacotar.montar_appdir(Lugares(tmp_path / "dist"))
    assert not any(argv[1:3] == ["pip", "install"] for argv in chamadas)
