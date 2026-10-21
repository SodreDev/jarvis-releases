"""Instala o OmniVoice para USO PESSOAL — num Python isolado, fora do repositório e do pacote.

    uv run --frozen python -m tools.instalar_omnivoice                       # aviso e pergunta
    uv run --frozen python -m tools.instalar_omnivoice --aceito-uso-pessoal  # aceite na linha
    uv run --frozen python -m tools.instalar_omnivoice --dispositivo cpu     # força a CPU (lenta)
    uv run --frozen python -m tools.instalar_omnivoice --estado              # o que está instalado
    uv run --frozen python -m tools.instalar_omnivoice --remover             # desfaz a instalação
    uv run --frozen python -m tools.instalar_omnivoice --cadastrar-voz minha \
        --audio ~/Gravações/eu.wav --texto "o que eu disse no áudio" --declaro minha
    uv run --frozen python -m tools.instalar_omnivoice --vozes               # vozes cadastradas

**Por que um script de `tools/`, e não uma opção do `jarvis-voz`** (ADR-0039). Os pesos são
CC-BY-NC: não comercial não entra no produto (ADR-0011). Um `--instalar-omnivoice` dentro do
`jarvis-voz` iria no AppImage, no `.deb` e no `.rpm` — o produto distribuiria o caminho para
baixar um modelo não comercial. Aqui, como o extra do Edge (`uv sync --group edge`), quem
instala é o dono, a partir do repositório, e `tools/` não vai no pacote.

**Por que um Python isolado, e não um grupo do `pyproject.toml`.** O OmniVoice puxa o PyTorch
(GBs, e com CUDA a roda certa depende do driver) e `transformers>=5.3`. No projeto, isso
entraria na trava e no ambiente de todo mundo; e a porta de licença falha se entrar. O venv
fica em `~/.local/share/jarvis/omnivoice/venv`, e o Jarvis fala com ele por um processo à parte
(`tools/omnivoice_trabalhador.py`, copiado para a pasta) — nunca importa nada de lá.

**O que acontece, na ordem — e nada antes do aceite:**

1. o aviso de licença (`jarvis.voz.omnivoice.AVISO_DE_LICENCA`) é mostrado **sempre**; sem
   `--aceito-uso-pessoal`, o dono digita "aceito uso pessoal" — sem terminal e sem a opção,
   recusa. Aceite já registrado para os mesmos pesos e o mesmo aviso vale (a reexecução é
   idempotente); aviso ou pesos mudaram, pergunta de novo;
2. o dispositivo: GPU NVIDIA pelo `nvidia-smi` (driver ≥ 570 → CUDA 12.8; ≥ 560 → 12.6), Apple
   Silicon → MPS, senão CPU — com o aviso de que é lenta;
3. `uv venv` (Python 3.12) e `uv pip install --torch-backend …` com versões fixas;
4. os pesos de `licenses/modelos.toml` (`instalar_de`), tamanho dito antes e sha256 conferido
   enquanto escreve (`jarvis.voz.modelos.baixar`);
5. o trabalhador é copiado e roda `--verificar` (importa, vê o dispositivo — sem carregar 3 GB);
6. só então `instalacao.json` e `aceite.json` (data, revisão, hash dos pesos, hash do aviso).

`--remover` apaga a pasta inteira **se** ela tiver a marca do instalador — pasta sem a marca não
é dele, e ele não toca. As vozes que o dono cadastrou ficam (são dele).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final

from jarvis.rede import ErroDeRede
from jarvis.voz.modelos import ArquivoDeModelo, Descarga, ModeloRecusado, baixar
from jarvis.voz.omnivoice import (
    AVISO_DE_LICENCA,
    CHAVE_DO_ACEITE,
    DECLARACOES,
    MARCA,
    PROTOCOLO,
    REGISTRADO,
    Aceite,
    Instalacao,
    PesosMalRegistrados,
    PesosRegistrados,
    RegistroDaInstalacao,
    VozNaoAutorizada,
    cadastrar_voz,
    ler_voz,
    pesos_registrados,
    remover_voz,
    sha256_de,
    sha256_do_texto,
    vozes_cadastradas,
)

PYTHON_DO_VENV: Final = "3.12"
VERSAO_DO_TORCH: Final = "2.8.0"
VERSAO_DO_OMNIVOICE: Final = "0.2.1"
VERSOES: Final[Mapping[str, str]] = {
    "torch": VERSAO_DO_TORCH,
    "torchaudio": VERSAO_DO_TORCH,
    "omnivoice": VERSAO_DO_OMNIVOICE,
}
"""Fixas: o model card manda `torch==2.8.0` (+cu128 na GPU) e o `omnivoice` é o conferido no
PyPI em 2026-10-21 (Apache-2.0). O resto (transformers ≥ 5.3, …) o `uv` resolve na hora."""
DRIVERS: Final[tuple[tuple[int, str], ...]] = ((570, "cu128"), (560, "cu126"))
"""Driver NVIDIA mínimo (Linux) para a roda CUDA do PyTorch 2.8: 12.8 pede 570.26, 12.6 pede
560.28 (tabela de compatibilidade da NVIDIA). Comparamos o número principal."""
MEMORIA_SUGERIDA_MIB: Final = 4096
FRASE_DE_ACEITE: Final = "aceito uso pessoal"
TRABALHADOR_DO_REPOSITORIO: Final = Path(__file__).with_name("omnivoice_trabalhador.py")
AVISO_DE_CPU: Final = (
    "sem GPU, o OmniVoice roda na CPU, e isso é LENTO: cada frase pode levar segundos (não "
    "medido nesta máquina). Se ficar lento demais, desligue "
    f"`{CHAVE_DO_ACEITE}` e o Jarvis volta ao motor padrão."
)
CODIGO_DAS_VERSOES: Final = (
    "import json, platform\n"
    "from importlib import metadata\n"
    "v = {}\n"
    "for p in ('omnivoice', 'torch', 'torchaudio', 'transformers'):\n"
    "    try:\n"
    "        v[p] = metadata.version(p)\n"
    "    except metadata.PackageNotFoundError:\n"
    "        v[p] = ''\n"
    "v['python'] = platform.python_version()\n"
    "print(json.dumps(v))\n"
)

Rodar = Callable[[Sequence[str], bool], str]
"""`rodar(argv, capturar)`: processo com `argv` explícito; devolve o stdout se `capturar`."""


class InstalacaoRecusada(RuntimeError):
    """Não deu para instalar. A mensagem diz por quê e o que fazer."""


@dataclass(frozen=True, slots=True)
class Deteccao:
    dispositivo: str
    """`cuda`, `mps` ou `cpu` — o que o trabalhador usa."""
    backend: str
    """O `--torch-backend` do `uv` (`cu128`, `cu126`, `cpu`)."""
    descricao: str
    aviso: str = ""


def ler_nvidia_smi() -> str | None:
    """A linha do `nvidia-smi` (nome, driver, memória em MiB), ou `None` se não houver."""
    executavel = shutil.which("nvidia-smi")
    if executavel is None:
        return None
    try:
        concluido = subprocess.run(
            [
                executavel,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    saida = concluido.stdout.strip()
    return saida if concluido.returncode == 0 and saida else None


def detectar_dispositivo(
    pedido: str = "auto",
    *,
    sistema: str = "",
    maquina: str = "",
    nvidia: Callable[[], str | None] = ler_nvidia_smi,
) -> Deteccao:
    """CUDA, MPS ou CPU — e, sem GPU, a CPU **avisando** a lentidão em vez de calar."""
    sistema = sistema or platform.system()
    maquina = maquina or platform.machine()
    if pedido == "cpu":
        return Deteccao("cpu", "cpu", "CPU (pedida na linha de comando)", AVISO_DE_CPU)
    if sistema == "Darwin" and maquina == "arm64" and pedido in {"auto", "mps"}:
        return Deteccao("mps", "cpu", "Apple Silicon (MPS)")
    if pedido == "mps":
        raise InstalacaoRecusada("MPS só existe em Mac com Apple Silicon")
    linha = (nvidia() or "").splitlines()[0:1]
    campos = [c.strip() for c in linha[0].split(",")] if linha else []
    if len(campos) < 3 or not campos[1].split(".")[0].isdigit():
        if pedido == "cuda":
            raise InstalacaoRecusada(
                "--dispositivo cuda, mas o nvidia-smi não respondeu: não há driver NVIDIA aqui"
            )
        return Deteccao(
            "cpu", "cpu", "nenhuma GPU NVIDIA (o nvidia-smi não respondeu)", AVISO_DE_CPU
        )
    nome, driver, memoria = campos[0], campos[1], campos[2]
    principal = int(driver.split(".")[0])
    descricao = f"{nome}, driver {driver}, {memoria} MiB"
    backend = next((b for minimo, b in DRIVERS if principal >= minimo), "")
    if not backend:
        antigo = (
            f"o driver NVIDIA {driver} é antigo para o PyTorch {VERSAO_DO_TORCH} com CUDA "
            "(pede 560 ou mais; atualize o driver para usar a GPU)"
        )
        if pedido == "cuda":
            raise InstalacaoRecusada(antigo)
        return Deteccao("cpu", "cpu", descricao, f"{antigo}; por ora, {AVISO_DE_CPU}")
    aviso = ""
    if memoria.isdigit() and int(memoria) < MEMORIA_SUGERIDA_MIB:
        aviso = (
            f"a GPU tem {memoria} MiB; o OmniVoice em fp16 deve ocupar uns 2–3 GB [SUPOSIÇÃO "
            "pelo tamanho dos pesos, não medido]. Se faltar memória, o Jarvis volta ao motor "
            "padrão sozinho"
        )
    return Deteccao("cuda", backend, descricao, aviso)


def rodar_de_verdade(argv: Sequence[str], capturar: bool) -> str:
    """`argv` explícito, sem shell. Sem `capturar`, a saída vai para o terminal do dono (o
    `uv pip install` de GBs mostra o progresso); com, volta como texto.

    O nosso stdout é descarregado antes: num log (stdout que não é terminal) ele fica em buffer,
    e o que o `uv` escreve direto apareceria antes do aviso de licença — que veio primeiro."""
    sys.stdout.flush()
    concluido = subprocess.run(
        list(argv), capture_output=capturar, text=True, check=False, stdin=subprocess.DEVNULL
    )
    if concluido.returncode != 0:
        detalhe = (concluido.stderr or "")[-600:] if capturar else ""
        raise InstalacaoRecusada(
            f"{Path(argv[0]).name} {' '.join(argv[1:3])} saiu com {concluido.returncode}"
            + (f": {detalhe}" if detalhe else "")
        )
    if not capturar:
        return ""
    return concluido.stdout or ""


def achar_o_uv(ambiente: Mapping[str, str] | None = None) -> str:
    """O `uv` que rodou este script (`UV`, que o `uv run` exporta) ou o do PATH."""
    fonte = os.environ if ambiente is None else ambiente
    uv = fonte.get("UV") or shutil.which("uv")
    if not uv:
        raise InstalacaoRecusada(
            "o uv não foi encontrado: rode pelo uv (`uv run --frozen python -m "
            "tools.instalar_omnivoice`) — https://docs.astral.sh/uv/"
        )
    return uv


def _escrever_atomico(destino: Path, texto: str) -> None:
    parcial = destino.with_name(destino.name + ".parcial")
    parcial.write_text(texto, encoding="utf-8")
    parcial.replace(destino)


def _backend_da_versao(versao: str) -> str:
    """`2.8.0+cu128` → `cu128`; sem rótulo local (roda do PyPI) → `cpu`."""
    return versao.partition("+")[2] or "cpu"


def _agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(slots=True)
class Instalador:
    """O instalador, com tudo que toca o mundo injetável (processo, download, terminal, GPU)."""

    instalacao: Instalacao
    pesos: PesosRegistrados
    escrever: Callable[[str], None] = print
    perguntar: Callable[[str], str] | None = None
    """`None` = sem terminal: sem `--aceito-uso-pessoal`, a instalação recusa."""
    rodar: Rodar = rodar_de_verdade
    baixar_pesos: Callable[..., list[Path]] = baixar
    nvidia: Callable[[], str | None] = ler_nvidia_smi
    uv: str = "uv"
    agora: Callable[[], str] = _agora
    origem_do_trabalhador: Path = TRABALHADOR_DO_REPOSITORIO
    sistema: str = ""
    maquina: str = ""
    _progresso: dict[str, int] = field(default_factory=dict)

    # --- instalar ----------------------------------------------------------------------------

    def instalar(self, *, aceito: bool, dispositivo: str = "auto") -> int:
        self.escrever(AVISO_DE_LICENCA)
        self.escrever(
            f"Pesos: {', '.join(self.pesos.ids)} — revisão {self.pesos.revisao}, "
            f"{self.pesos.tamanho}; licenças: {'; '.join(self.pesos.licencas)}."
        )
        como = self._aceite(aceito)
        if not como:
            self.escrever("Não aceito: nada foi instalado nem baixado.")
            return 3
        deteccao = detectar_dispositivo(
            dispositivo, sistema=self.sistema, maquina=self.maquina, nvidia=self.nvidia
        )
        self.escrever(
            f"Dispositivo: {deteccao.dispositivo} — {deteccao.descricao}; PyTorch "
            f"{VERSAO_DO_TORCH} para {deteccao.backend}."
        )
        if deteccao.aviso:
            self.escrever(f"AVISO: {deteccao.aviso}")
        self._preparar_a_pasta()
        versoes = self._pacotes(deteccao)
        self._pesos()
        sha_do_trabalhador = self._trabalhador()
        relatorio = self._verificar(deteccao)
        registro = RegistroDaInstalacao(
            instalado_em=self.agora(),
            dispositivo=deteccao.dispositivo,
            backend_do_torch=deteccao.backend,
            versoes={**versoes, "gpu": str(relatorio.get("gpu", ""))},
            sha256_do_trabalhador=sha_do_trabalhador,
            protocolo=PROTOCOLO,
        )
        _escrever_atomico(self.instalacao.arquivo_da_instalacao, registro.para_json())
        anterior = self.instalacao.aceite()
        if como != "registrado" or anterior is None:
            aceite = Aceite(
                aceito_em=self.agora(),
                modelo=self.pesos.ids[0],
                revisao=self.pesos.revisao,
                hash_dos_pesos=self.pesos.hash,
                licencas=self.pesos.licencas,
                sha256_do_aviso=sha256_do_texto(AVISO_DE_LICENCA),
                como=como,
            )
            _escrever_atomico(self.instalacao.arquivo_do_aceite, aceite.para_json())
        falta = self.instalacao.falta(self.pesos)
        if falta:  # pragma: no cover — defesa: o que acabou de ser escrito tem de bater
            raise InstalacaoRecusada(f"a instalação terminou incompleta: {falta}")
        self.escrever(
            f"\nPronto: o OmniVoice está em {self.instalacao.raiz}.\n"
            "Para usar (uso pessoal), na configuração do jarvis-voz (~/.config/jarvis/"
            "jarvis-voz.toml):\n"
            f'  tts = "{REGISTRADO}"\n'
            f"  {CHAVE_DO_ACEITE} = true\n"
            '  voz_omnivoice = "<nome de uma voz cadastrada com --cadastrar-voz>"\n'
            "Sem isso, nada muda: o padrão continua o tts-piper-epitran."
        )
        return 0

    def _aceite(self, aceito_na_linha: bool) -> str:
        """Como o dono aceitou: na linha, digitando, ou o aceite já registrado. Vazio = não."""
        anterior = self.instalacao.aceite()
        if (
            anterior is not None
            and anterior.revisao == self.pesos.revisao
            and anterior.hash_dos_pesos == self.pesos.hash
            and anterior.sha256_do_aviso == sha256_do_texto(AVISO_DE_LICENCA)
        ):
            self.escrever(
                f"Aceite do uso pessoal já registrado em {anterior.aceito_em} "
                f"({anterior.como}) para estes pesos e este aviso."
            )
            return "registrado"
        if aceito_na_linha:
            return "--aceito-uso-pessoal"
        if self.perguntar is None:
            self.escrever(
                "Recusado: sem --aceito-uso-pessoal e sem terminal para perguntar. O aceite "
                "nunca é silencioso."
            )
            return ""
        resposta = self.perguntar(f'Para aceitar o uso pessoal, digite "{FRASE_DE_ACEITE}": ')
        if resposta.strip().lower() != FRASE_DE_ACEITE:
            return ""
        return "digitado no terminal"

    def _preparar_a_pasta(self) -> None:
        raiz = self.instalacao.raiz
        if raiz.is_symlink():
            raise InstalacaoRecusada(f"{raiz} é um link simbólico: o instalador não segue links")
        if raiz.exists() and not self.instalacao.marca.is_file() and any(raiz.iterdir()):
            raise InstalacaoRecusada(
                f"{raiz} já existe, tem arquivos e não foi o instalador que a criou (falta a "
                f"marca {MARCA}). Escolha outra pasta com --pasta ou esvazie esta"
            )
        raiz.mkdir(parents=True, exist_ok=True)
        if not self.instalacao.marca.is_file():
            self.instalacao.marca.write_text(
                f"Criada por tools/instalar_omnivoice.py em {self.agora()} (ADR-0039).\n"
                "`--remover` apaga esta pasta inteira; as vozes cadastradas ficam fora dela.\n",
                encoding="utf-8",
            )

    def _versoes(self) -> dict[str, str]:
        if not self.instalacao.python.exists():
            return {}
        try:
            saida = self.rodar([str(self.instalacao.python), "-I", "-c", CODIGO_DAS_VERSOES], True)
            dados = json.loads(saida.strip().splitlines()[-1])
        except (InstalacaoRecusada, ValueError, IndexError):
            return {}
        return {str(k): str(v) for k, v in dados.items()} if isinstance(dados, dict) else {}

    def _pacotes(self, deteccao: Deteccao) -> dict[str, str]:
        python = self.instalacao.python
        if not python.exists():
            self.escrever(f"Criando o Python isolado em {self.instalacao.venv}…")
            self.rodar(
                [self.uv, "venv", "--python", PYTHON_DO_VENV, str(self.instalacao.venv)], False
            )
        versoes = self._versoes()
        fora = [p for p, v in VERSOES.items() if versoes.get(p, "").partition("+")[0] != v]
        trocar = bool(versoes.get("torch")) and (
            _backend_da_versao(versoes["torch"]) != deteccao.backend
        )
        if not fora and not trocar:
            self.escrever(
                f"Pacotes já instalados: torch {versoes['torch']}, omnivoice "
                f"{versoes['omnivoice']}."
            )
            return versoes
        argv = [self.uv, "pip", "install", "--python", str(python)]
        argv += ["--torch-backend", deteccao.backend]
        if trocar:
            argv += ["--reinstall-package", "torch", "--reinstall-package", "torchaudio"]
        argv += [f"{pacote}=={versao}" for pacote, versao in VERSOES.items()]
        self.escrever("Instalando PyTorch e omnivoice no Python isolado (pode levar minutos)…")
        self.rodar(argv, False)
        versoes = self._versoes()
        errados = [p for p, v in VERSOES.items() if versoes.get(p, "").partition("+")[0] != v]
        if errados:
            raise InstalacaoRecusada(
                f"depois do uv pip install, {', '.join(errados)} não estão nas versões "
                f"fixadas ({dict(VERSOES)}); veio {versoes}"
            )
        return versoes

    def _pesos(self) -> None:
        descarga = Descarga(
            id=" + ".join(self.pesos.ids),
            papel="tts",
            licenca=" + ".join(self.pesos.licencas),
            destino=self.instalacao.pasta_dos_pesos(self.pesos.revisao),
            arquivos=tuple(
                ArquivoDeModelo(
                    nome=a.nome,
                    bytes=a.bytes,
                    sha256=a.sha256,
                    url=self.pesos.instalar_de.rstrip("/") + "/" + a.nome,
                )
                for a in self.pesos.arquivos
            ),
        )
        self.escrever(descarga.frase())
        if descarga.completa:
            return
        for caminho in self.baixar_pesos(descarga, ao_progresso=self._mostrar_progresso):
            self.escrever(f"  conferido (sha256): {caminho.name}")

    def _mostrar_progresso(self, nome: str, lidos: int, total: int) -> None:
        porcento = int(100 * lidos / total) if total else 100
        if porcento % 10 == 0 and self._progresso.get(nome) != porcento:
            self._progresso[nome] = porcento
            self.escrever(f"  {nome}: {porcento}%")

    def _trabalhador(self) -> str:
        conteudo = self.origem_do_trabalhador.read_bytes()
        parcial = self.instalacao.trabalhador.with_name(
            self.instalacao.trabalhador.name + ".parcial"
        )
        parcial.write_bytes(conteudo)
        parcial.replace(self.instalacao.trabalhador)
        return sha256_de(self.instalacao.trabalhador)

    def _verificar(self, deteccao: Deteccao) -> dict[str, object]:
        saida = self.rodar(
            [
                str(self.instalacao.python),
                "-I",
                str(self.instalacao.trabalhador),
                "--verificar",
                "--dispositivo",
                deteccao.dispositivo,
            ],
            True,
        )
        try:
            relatorio = json.loads(saida.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise InstalacaoRecusada(
                f"o trabalhador não respondeu a --verificar: {saida[-300:]!r}"
            ) from None
        if not isinstance(relatorio, dict) or relatorio.get("protocolo") != PROTOCOLO:
            raise InstalacaoRecusada(f"o trabalhador fala outro protocolo: {relatorio!r}")
        if not relatorio.get("dispositivo_ok"):
            raise InstalacaoRecusada(
                f"o PyTorch instalado não vê {deteccao.dispositivo} (cuda={relatorio.get('cuda')}, "
                f"mps={relatorio.get('mps')}). Confira o driver, ou instale para a CPU com "
                "--dispositivo cpu (lenta)"
            )
        self.escrever(
            f"Verificado: omnivoice {relatorio.get('versoes', {})} em {deteccao.dispositivo}"
            + (f" ({relatorio['gpu']})" if relatorio.get("gpu") else "")
        )
        return relatorio

    # --- remover e estado --------------------------------------------------------------------

    def remover(self) -> int:
        raiz = self.instalacao.raiz
        if not raiz.exists() and not raiz.is_symlink():
            self.escrever(f"Nada a remover: {raiz} não existe.")
            return 0
        if raiz.is_symlink() or not self.instalacao.marca.is_file():
            self.escrever(
                f"Recusado: {raiz} não tem a marca {MARCA} do instalador (ou é um link). Ela não "
                "foi criada por ele, e ele não apaga o que não criou."
            )
            return 2
        total = sum(f.stat().st_size for f in raiz.rglob("*") if f.is_file() and not f.is_symlink())
        self.escrever(f"Removendo {raiz} ({total / 1_000_000_000:.2f} GB: venv, pesos, aceite)…")
        shutil.rmtree(raiz)
        self.escrever(
            "Removido. As vozes cadastradas ficam onde estão (são suas). Se a configuração "
            f"ainda pedir {REGISTRADO}, o Jarvis volta sozinho ao motor padrão."
        )
        return 0

    def estado(self) -> int:
        instalacao = self.instalacao
        self.escrever(f"OmniVoice (uso pessoal, ADR-0039) — {instalacao.raiz}")
        registro = instalacao.registro()
        aceite = instalacao.aceite()
        if registro is not None:
            self.escrever(
                f"  instalado em {registro.instalado_em}: {registro.dispositivo} "
                f"(PyTorch {registro.versoes.get('torch', '?')}, omnivoice "
                f"{registro.versoes.get('omnivoice', '?')})"
            )
        if aceite is not None:
            self.escrever(
                f"  aceite do uso pessoal: {aceite.aceito_em} ({aceite.como}), revisão "
                f"{aceite.revisao}, pesos {aceite.hash_dos_pesos[:12]}…"
            )
        falta = instalacao.falta(self.pesos)
        self.escrever(f"  {'pronto para usar' if not falta else 'não pronto: ' + falta}")
        return 0 if not falta else 1


AVISO_DE_CLONAGEM: Final = """\
Voz de referência (ADR-0039): só a SUA voz, ou a de quem lhe deu permissão. Clonar a voz de
alguém sem autorização, imitar uma pessoa ou usar a voz para enganar é proibido pelo model card
do OmniVoice — e pode ser crime. A declaração que você faz agora fica gravada junto da voz, com o
sha256 do áudio: trocar o arquivo depois invalida a voz.
"""


def cadastrar(args: argparse.Namespace, escrever: Callable[[str], None] = print) -> int:
    """`--cadastrar-voz`: comando do dono no terminal — não existe ferramenta do assistente."""
    escrever(AVISO_DE_CLONAGEM)
    if not args.declaro:
        escrever("Recusado: diga --declaro minha (a voz é sua) ou --declaro permissao --titular …")
        return 2
    try:
        voz = cadastrar_voz(
            args.cadastrar_voz,
            audio=str(args.audio or ""),
            texto=str(args.texto or ""),
            declaracao=args.declaro,
            titular=str(args.titular or ""),
            agora=_agora(),
            pasta=args.pasta_das_vozes,
        )
    except VozNaoAutorizada as erro:
        escrever(f"Recusado: {erro}")
        return 2
    escrever(
        f"Voz {voz.nome!r} cadastrada em {voz.audio.parent}: {voz.frase_da_declaracao}, "
        f'{voz.duracao_s:.1f} s.\nPara usar: voz_omnivoice = "{voz.nome}" na configuração.'
    )
    return 0


def listar_vozes(pasta: Path | None, escrever: Callable[[str], None] = print) -> int:
    nomes = vozes_cadastradas(pasta=pasta)
    if not nomes:
        escrever("Nenhuma voz cadastrada.")
    for nome in nomes:
        try:
            voz = ler_voz(nome, pasta=pasta)
        except VozNaoAutorizada as erro:
            escrever(f"  {nome}: RECUSADA — {erro}")
            continue
        escrever(f"  {nome}: {voz.frase_da_declaracao}, {voz.duracao_s:.1f} s")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="python -m tools.instalar_omnivoice",
        description="Instala o OmniVoice para uso pessoal, fora do pacote (ADR-0039).",
    )
    analisador.add_argument(
        "--aceito-uso-pessoal",
        action="store_true",
        help="aceita, depois de ler o aviso, o uso pessoal e não comercial dos pesos",
    )
    analisador.add_argument("--dispositivo", choices=("auto", "cuda", "cpu", "mps"), default="auto")
    analisador.add_argument("--pasta", type=Path, default=None, help="outra pasta de instalação")
    analisador.add_argument("--estado", action="store_true", help="mostra o que está instalado")
    analisador.add_argument("--remover", action="store_true", help="desfaz a instalação")
    vozes = analisador.add_argument_group(
        "vozes de referência", "só a sua voz, ou a de quem lhe deu permissão (ADR-0039)"
    )
    vozes.add_argument("--cadastrar-voz", metavar="NOME", help="cadastra uma voz sua")
    vozes.add_argument("--audio", help="WAV local de 3 a 20 s (nada de URL)")
    vozes.add_argument("--texto", help="a transcrição exata do áudio")
    vozes.add_argument(
        "--declaro",
        choices=tuple(DECLARACOES),
        help="minha = a voz é minha; permissao = tenho permissão do titular",
    )
    vozes.add_argument("--titular", help="de quem é a voz, com --declaro permissao")
    vozes.add_argument("--vozes", action="store_true", help="lista as vozes cadastradas")
    vozes.add_argument("--remover-voz", metavar="NOME", help="apaga uma voz cadastrada")
    vozes.add_argument("--pasta-das-vozes", type=Path, default=None, help=argparse.SUPPRESS)
    args = analisador.parse_args(argv)

    if args.cadastrar_voz:
        return cadastrar(args)
    if args.vozes:
        return listar_vozes(args.pasta_das_vozes)
    if args.remover_voz:
        try:
            removida = remover_voz(args.remover_voz, pasta=args.pasta_das_vozes)
        except VozNaoAutorizada as erro:
            print(f"Recusado: {erro}")
            return 2
        print("Voz removida." if removida else "Essa voz não está cadastrada.")
        return 0

    instalacao = Instalacao(args.pasta) if args.pasta is not None else Instalacao.padrao()
    try:
        pesos = pesos_registrados()
        instalador = Instalador(
            instalacao=instalacao,
            pesos=pesos,
            perguntar=input if sys.stdin.isatty() else None,
        )
        if args.remover:
            return instalador.remover()
        if args.estado:
            return instalador.estado()
        instalador.uv = achar_o_uv()
        return instalador.instalar(aceito=args.aceito_uso_pessoal, dispositivo=args.dispositivo)
    except (InstalacaoRecusada, ModeloRecusado, ErroDeRede, PesosMalRegistrados) as erro:
        print(f"não deu: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
