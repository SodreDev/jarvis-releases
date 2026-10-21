"""O instalador do OmniVoice: aviso antes, aceite explícito, nada silencioso, e reversível.

Nenhum `pip` de verdade e nenhum peso de verdade (pedido do dono): o `uv` é um `rodar` falso que
anota o `argv` e cria o que o `uv venv` criaria; os pesos vêm de um `http.server` em
`127.0.0.1`, com sha256 de verdade — o mesmo `jarvis.voz.modelos.baixar` do produto confere.
E há uma prova de que a suíte **não consegue** baixar os pesos reais: sob `CI=1`, a base do
Hugging Face é recusada antes de qualquer conexão.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from tools import instalar_omnivoice as modulo
from tools.instalar_omnivoice import (
    CODIGO_DAS_VERSOES,
    InstalacaoRecusada,
    Instalador,
    detectar_dispositivo,
    main,
)

from jarvis.voz.modelos import ModeloRecusado
from jarvis.voz.nuvem import NuvemRealProibidaEmCI
from jarvis.voz.omnivoice import (
    AVISO_DE_LICENCA,
    MARCA,
    ArquivoDePeso,
    Instalacao,
    PesosMalRegistrados,
    PesosRegistrados,
    pesos_registrados,
    sha256_de,
    sha256_do_texto,
)

RTX_4060 = "NVIDIA GeForce RTX 4060, 595.104.02, 8188"
ARQUIVOS = {
    "model.safetensors": b"pesos de mentira do modelo " * 50,
    "audio_tokenizer/model.safetensors": b"tokenizador de mentira " * 40,
}


class ServidorDePesos(ThreadingHTTPServer):
    arquivos: dict[str, bytes]
    pedidos: int = 0


class Mao(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        servidor = self.server
        assert isinstance(servidor, ServidorDePesos)
        servidor.pedidos += 1
        nome = self.path.split("/rev/", 1)[-1]
        corpo = servidor.arquivos.get(nome)
        if corpo is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, formato: str, *args: object) -> None:
        return None


@pytest.fixture
def servidor() -> Iterator[ServidorDePesos]:
    httpd = ServidorDePesos(("127.0.0.1", 0), Mao)
    httpd.arquivos = dict(ARQUIVOS)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def pesos_de(servidor: ServidorDePesos, revisao: str = "abc123") -> PesosRegistrados:
    porta = servidor.server_address[1]
    return PesosRegistrados(
        ids=("exemplo/OmniVoice", "exemplo/OmniVoice:audio_tokenizer"),
        licencas=("CC-BY-NC", "Boson Higgs Audio 2 Community License"),
        revisao=revisao,
        instalar_de=f"http://127.0.0.1:{porta}/rev/",
        arquivos=tuple(
            ArquivoDePeso(nome=n, bytes=len(c), sha256=hashlib.sha256(c).hexdigest())
            for n, c in ARQUIVOS.items()
        ),
    )


@dataclass
class UvFalso:
    """Faz o papel do `uv` e do Python do venv: anota o `argv` e responde como eles."""

    versoes: dict[str, str] = field(default_factory=dict)
    chamadas: list[list[str]] = field(default_factory=list)
    gpu_no_torch: bool = True

    def __call__(self, argv: Sequence[str], capturar: bool) -> str:
        argv = list(argv)
        self.chamadas.append(argv)
        if argv[1:2] == ["venv"]:
            python = Path(argv[-1]) / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/false\n", encoding="utf-8")
            return ""
        if argv[1:3] == ["pip", "install"]:
            backend = argv[argv.index("--torch-backend") + 1]
            self.versoes = {
                "omnivoice": "0.2.1",
                "torch": f"2.8.0+{backend}",
                "torchaudio": f"2.8.0+{backend}",
                "transformers": "5.3.0",
                "python": "3.12.14",
            }
            return ""
        if argv[1:3] == ["-I", "-c"] and argv[3] == CODIGO_DAS_VERSOES:
            return json.dumps(self.versoes) + "\n"
        if "--verificar" in argv:
            dispositivo = argv[argv.index("--dispositivo") + 1]
            ok = dispositivo == "cpu" or self.gpu_no_torch
            return json.dumps(
                {
                    "protocolo": 1,
                    "versoes": {"omnivoice": "0.2.1"},
                    "dispositivo_ok": ok,
                    "cuda": ok,
                    "mps": False,
                    "gpu": "GPU de mentira" if ok and dispositivo == "cuda" else "",
                }
            )
        raise AssertionError(f"chamada inesperada: {argv}")

    def instalou_pacotes(self) -> list[list[str]]:
        return [c for c in self.chamadas if c[1:3] == ["pip", "install"]]


def instalador(
    raiz: Path,
    pesos: PesosRegistrados,
    uv: UvFalso,
    *,
    nvidia: str | None = RTX_4060,
    respostas: Sequence[str] | None = None,
) -> tuple[Instalador, list[str]]:
    linhas: list[str] = []
    fila = list(respostas) if respostas is not None else None
    return (
        Instalador(
            instalacao=Instalacao(raiz),
            pesos=pesos,
            escrever=linhas.append,
            perguntar=(lambda _pergunta: fila.pop(0)) if fila is not None else None,
            rodar=uv,
            nvidia=lambda: nvidia,
            uv="uv",
            agora=lambda: "2026-10-21T13:00:00-03:00",
            sistema="Linux",
            maquina="x86_64",
        ),
        linhas,
    )


# --- o aceite vem antes de tudo -------------------------------------------------------------


def test_sem_aceite_e_sem_terminal_nada_acontece(tmp_path: Path, servidor: ServidorDePesos) -> None:
    uv = UvFalso()
    inst, linhas = instalador(tmp_path / "omnivoice", pesos_de(servidor), uv)
    assert inst.instalar(aceito=False) == 3
    texto = "\n".join(linhas)
    assert "CC-BY-NC" in texto and "PROIBIDO clonar" in texto, "o aviso aparece antes"
    assert "nunca é silencioso" in texto
    assert not (tmp_path / "omnivoice").exists()
    assert uv.chamadas == [] and servidor.pedidos == 0


def test_resposta_errada_no_terminal_nao_aceita(tmp_path: Path, servidor: ServidorDePesos) -> None:
    uv = UvFalso()
    inst, _ = instalador(tmp_path / "omnivoice", pesos_de(servidor), uv, respostas=["sim"])
    assert inst.instalar(aceito=False) == 3
    assert uv.chamadas == [] and servidor.pedidos == 0


def test_digitar_a_frase_aceita_e_registra_como(tmp_path: Path, servidor: ServidorDePesos) -> None:
    uv = UvFalso()
    inst, _ = instalador(
        tmp_path / "omnivoice", pesos_de(servidor), uv, respostas=["Aceito uso pessoal "]
    )
    assert inst.instalar(aceito=False) == 0
    aceite = Instalacao(tmp_path / "omnivoice").aceite()
    assert aceite is not None and aceite.como == "digitado no terminal"


# --- a instalação de ponta a ponta ----------------------------------------------------------


def test_instala_venv_pacotes_pesos_trabalhador_e_registros(
    tmp_path: Path, servidor: ServidorDePesos
) -> None:
    raiz = tmp_path / "omnivoice"
    pesos = pesos_de(servidor)
    uv = UvFalso()
    inst, linhas = instalador(raiz, pesos, uv)

    assert inst.instalar(aceito=True) == 0

    assert uv.chamadas[0] == ["uv", "venv", "--python", "3.12", str(raiz / "venv")]
    (pip,) = uv.instalou_pacotes()
    assert pip == [
        "uv",
        "pip",
        "install",
        "--python",
        str(raiz / "venv" / "bin" / "python"),
        "--torch-backend",
        "cu128",
        "torch==2.8.0",
        "torchaudio==2.8.0",
        "omnivoice==0.2.1",
    ]
    assert uv.chamadas[-1][1:] == [
        "-I",
        str(raiz / "trabalhador.py"),
        "--verificar",
        "--dispositivo",
        "cuda",
    ]
    instalacao = Instalacao(raiz)
    for nome, conteudo in ARQUIVOS.items():
        assert (instalacao.pasta_dos_pesos("abc123") / nome).read_bytes() == conteudo
    assert sha256_de(instalacao.trabalhador) == sha256_de(modulo.TRABALHADOR_DO_REPOSITORIO)

    aceite = instalacao.aceite()
    assert aceite is not None
    assert aceite.aceito_em == "2026-10-21T13:00:00-03:00"
    assert aceite.revisao == "abc123" and aceite.hash_dos_pesos == pesos.hash
    assert aceite.sha256_do_aviso == sha256_do_texto(AVISO_DE_LICENCA)
    assert aceite.como == "--aceito-uso-pessoal" and "CC-BY-NC" in aceite.licencas
    registro = instalacao.registro()
    assert registro is not None and registro.dispositivo == "cuda"
    assert registro.backend_do_torch == "cu128" and registro.versoes["torch"] == "2.8.0+cu128"
    assert instalacao.marca.is_file()
    assert instalacao.falta(pesos) == ""
    assert any("omnivoice_uso_pessoal = true" in linha for linha in linhas)


def test_reexecutar_nao_reinstala_nem_rebaixa_e_mantem_o_aceite(
    tmp_path: Path, servidor: ServidorDePesos
) -> None:
    raiz = tmp_path / "omnivoice"
    pesos = pesos_de(servidor)
    uv = UvFalso()
    primeiro, _ = instalador(raiz, pesos, uv)
    assert primeiro.instalar(aceito=True) == 0
    pedidos = servidor.pedidos
    aceito_em = Instalacao(raiz).aceite()

    uv.chamadas.clear()
    segundo, linhas = instalador(raiz, pesos, uv)
    assert segundo.instalar(aceito=False) == 0  # o aceite registrado vale: mesmo aviso e pesos

    assert servidor.pedidos == pedidos
    assert not uv.instalou_pacotes() and not any(c[1:2] == ["venv"] for c in uv.chamadas)
    assert Instalacao(raiz).aceite() == aceito_em
    assert any("já registrado" in linha for linha in linhas)


def test_aviso_novo_invalida_o_aceite_antigo(
    tmp_path: Path, servidor: ServidorDePesos, monkeypatch: pytest.MonkeyPatch
) -> None:
    raiz = tmp_path / "omnivoice"
    pesos = pesos_de(servidor)
    uv = UvFalso()
    primeiro, _ = instalador(raiz, pesos, uv)
    assert primeiro.instalar(aceito=True) == 0
    monkeypatch.setattr(modulo, "AVISO_DE_LICENCA", AVISO_DE_LICENCA + "\nfrase nova\n")
    segundo, _ = instalador(raiz, pesos, uv)
    assert segundo.instalar(aceito=False) == 3, (
        "o aviso mudou: pergunta de novo (sem terminal, não)"
    )


def test_trocar_de_gpu_para_cpu_reinstala_o_pytorch_certo(
    tmp_path: Path, servidor: ServidorDePesos
) -> None:
    raiz = tmp_path / "omnivoice"
    pesos = pesos_de(servidor)
    uv = UvFalso()
    inst, _ = instalador(raiz, pesos, uv)
    assert inst.instalar(aceito=True) == 0
    uv.chamadas.clear()
    assert inst.instalar(aceito=True, dispositivo="cpu") == 0
    (pip,) = uv.instalou_pacotes()
    assert pip[pip.index("--torch-backend") + 1] == "cpu"
    assert pip.count("--reinstall-package") == 2
    registro = Instalacao(raiz).registro()
    assert registro is not None and registro.dispositivo == "cpu"


def test_sem_gpu_instala_para_cpu_avisando_a_lentidao(
    tmp_path: Path, servidor: ServidorDePesos
) -> None:
    uv = UvFalso()
    inst, linhas = instalador(tmp_path / "omnivoice", pesos_de(servidor), uv, nvidia=None)
    assert inst.instalar(aceito=True) == 0
    (pip,) = uv.instalou_pacotes()
    assert pip[pip.index("--torch-backend") + 1] == "cpu"
    assert any(linha.startswith("AVISO:") and "LENTO" in linha for linha in linhas)


def test_pytorch_que_nao_ve_a_gpu_recusa_sem_registrar_aceite(
    tmp_path: Path, servidor: ServidorDePesos
) -> None:
    raiz = tmp_path / "omnivoice"
    inst, _ = instalador(raiz, pesos_de(servidor), UvFalso(gpu_no_torch=False))
    with pytest.raises(InstalacaoRecusada, match="--dispositivo cpu"):
        inst.instalar(aceito=True)
    assert Instalacao(raiz).aceite() is None


def test_peso_adulterado_e_recusado_e_nada_e_registrado(
    tmp_path: Path, servidor: ServidorDePesos
) -> None:
    raiz = tmp_path / "omnivoice"
    pesos = pesos_de(servidor)
    servidor.arquivos["model.safetensors"] = b"X" * len(ARQUIVOS["model.safetensors"])
    inst, _ = instalador(raiz, pesos, UvFalso())
    with pytest.raises(ModeloRecusado, match="não confere"):
        inst.instalar(aceito=True)
    assert not (Instalacao(raiz).pasta_dos_pesos("abc123") / "model.safetensors").exists()
    assert Instalacao(raiz).aceite() is None and Instalacao(raiz).registro() is None


def test_pasta_alheia_nao_e_usada(tmp_path: Path, servidor: ServidorDePesos) -> None:
    raiz = tmp_path / "omnivoice"
    raiz.mkdir()
    (raiz / "meu-arquivo.txt").write_text("do dono", encoding="utf-8")
    inst, _ = instalador(raiz, pesos_de(servidor), UvFalso())
    with pytest.raises(InstalacaoRecusada, match="não foi o instalador"):
        inst.instalar(aceito=True)
    assert (raiz / "meu-arquivo.txt").read_text(encoding="utf-8") == "do dono"


def test_sob_ci_os_pesos_de_verdade_nao_podem_ser_baixados(tmp_path: Path) -> None:
    """A suíte roda com `CI=1` (conftest): a base do Hugging Face é recusada antes da rede."""
    inst, _ = instalador(tmp_path / "omnivoice", pesos_registrados(), UvFalso())
    with pytest.raises(NuvemRealProibidaEmCI):
        inst.instalar(aceito=True)


# --- remover e estado -----------------------------------------------------------------------


def test_remover_apaga_a_pasta_marcada_e_e_idempotente(
    tmp_path: Path, servidor: ServidorDePesos
) -> None:
    raiz = tmp_path / "omnivoice"
    inst, _ = instalador(raiz, pesos_de(servidor), UvFalso())
    assert inst.instalar(aceito=True) == 0
    vozes = tmp_path / "vozes" / "minha"
    vozes.mkdir(parents=True)
    assert inst.remover() == 0
    assert not raiz.exists() and vozes.is_dir(), "as vozes do dono não são do instalador"
    assert inst.remover() == 0


def test_remover_recusa_pasta_sem_a_marca(tmp_path: Path, servidor: ServidorDePesos) -> None:
    raiz = tmp_path / "omnivoice"
    raiz.mkdir()
    (raiz / "importante.txt").write_text("não é do instalador", encoding="utf-8")
    inst, linhas = instalador(raiz, pesos_de(servidor), UvFalso())
    assert inst.remover() == 2
    assert (raiz / "importante.txt").is_file() and MARCA in linhas[-1]


def test_remover_recusa_link_simbolico(tmp_path: Path, servidor: ServidorDePesos) -> None:
    alvo = tmp_path / "alvo"
    alvo.mkdir()
    (alvo / MARCA).write_text("marca copiada", encoding="utf-8")
    raiz = tmp_path / "omnivoice"
    raiz.symlink_to(alvo, target_is_directory=True)
    inst, _ = instalador(raiz, pesos_de(servidor), UvFalso())
    assert inst.remover() == 2
    assert (alvo / MARCA).is_file()


def test_estado_e_main_numa_pasta_vazia(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pasta = tmp_path / "nada"
    assert main(["--estado", "--pasta", str(pasta)]) == 1
    assert "não pronto" in capsys.readouterr().out
    assert main(["--remover", "--pasta", str(pasta)]) == 0


# --- dispositivo ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("linha", "dispositivo", "backend"),
    [
        (RTX_4060, "cuda", "cu128"),
        ("NVIDIA GeForce RTX 3060, 565.57.01, 12288", "cuda", "cu126"),
        ("NVIDIA GeForce GTX 1060, 470.256.02, 6144", "cpu", "cpu"),
        (None, "cpu", "cpu"),
        ("lixo sem vírgula", "cpu", "cpu"),
    ],
)
def test_deteccao_do_dispositivo(linha: str | None, dispositivo: str, backend: str) -> None:
    deteccao = detectar_dispositivo(sistema="Linux", maquina="x86_64", nvidia=lambda: linha)
    assert (deteccao.dispositivo, deteccao.backend) == (dispositivo, backend)
    if dispositivo == "cpu":
        assert "LENTO" in deteccao.aviso


def test_pedir_cuda_sem_driver_ou_com_driver_antigo_recusa() -> None:
    with pytest.raises(InstalacaoRecusada, match="nvidia-smi"):
        detectar_dispositivo("cuda", sistema="Linux", maquina="x86_64", nvidia=lambda: None)
    with pytest.raises(InstalacaoRecusada, match="antigo"):
        detectar_dispositivo(
            "cuda", sistema="Linux", maquina="x86_64", nvidia=lambda: "GTX, 470.1, 6144"
        )


def test_apple_silicon_usa_mps_e_gpu_pequena_avisa() -> None:
    assert detectar_dispositivo(sistema="Darwin", maquina="arm64").dispositivo == "mps"
    pequena = detectar_dispositivo(
        sistema="Linux", maquina="x86_64", nvidia=lambda: "GPU pequena, 580.1, 2048"
    )
    assert pequena.dispositivo == "cuda" and "2048 MiB" in pequena.aviso


# --- os pesos do registro de verdade --------------------------------------------------------


def test_os_pesos_registrados_sao_uma_revisao_so_com_onze_arquivos() -> None:
    pesos = pesos_registrados()
    assert pesos.revisao == "c5fdb5ccb189"
    assert pesos.instalar_de.startswith("https://huggingface.co/k2-fsa/OmniVoice/resolve/")
    assert len(pesos.arquivos) == 11 and 3_200_000_000 < pesos.bytes_totais < 3_300_000_000
    assert {"model.safetensors", "audio_tokenizer/model.safetensors"} <= {
        a.nome for a in pesos.arquivos
    }
    assert pesos.hash == pesos_registrados().hash and len(pesos.hash) == 64


def registro_com(tmp_path: Path, *, nome: str = "a.bin", sha256: str = "a" * 64) -> Path:
    registro = tmp_path / "modelos.toml"
    registro.write_text(
        '[[modelo]]\nid = "x"\nlicenca = "CC-BY-NC"\nestado = "uso_pessoal"\n'
        'motor = "tts-omnivoice"\nrevisao = "r"\ninstalar_de = "https://exemplo.invalid/"\n\n'
        f'[[modelo.arquivo]]\nnome = "{nome}"\nbytes = 1\nsha256 = "{sha256}"\n',
        encoding="utf-8",
    )
    return registro


def test_registro_malformado_e_recusado(tmp_path: Path) -> None:
    assert len(pesos_registrados(arquivo=registro_com(tmp_path)).arquivos) == 1
    with pytest.raises(PesosMalRegistrados, match="fora da pasta"):
        pesos_registrados(arquivo=registro_com(tmp_path, nome="../fora.bin"))
    with pytest.raises(PesosMalRegistrados, match="sha256"):
        pesos_registrados(arquivo=registro_com(tmp_path, sha256="curto"))
    with pytest.raises(PesosMalRegistrados, match="nenhum peso"):
        pesos_registrados(arquivo=registro_com(tmp_path), motor="outro-motor")
