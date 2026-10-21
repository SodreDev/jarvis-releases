"""OmniVoice: o motor de TTS **opcional e de uso pessoal** — o que mora no disco do dono (ADR-0039).

**O que é, e por que fica de fora.** O OmniVoice (k2-fsa) clona uma voz a partir de 3–10 s de
referência e fala mais de 600 idiomas, português incluído. O código é Apache-2.0, mas os
**pesos são CC-BY-NC** ("due to constraints from its training data (e.g., Emilia)") e o
tokenizador de áudio que vem junto tem a licença comunitária da Boson. Não comercial não entra
no produto (ADR-0011): então ele nunca é o padrão, nunca é dependência, nunca vai no pacote, e
só roda quando o dono o instala para si e declara o uso pessoal na configuração.

**Onde ele mora.** Tudo numa pasta só, fora do repositório e do pacote —
`~/.local/share/jarvis/omnivoice` (`$XDG_DATA_HOME`; no Windows, `%LOCALAPPDATA%\\jarvis`):

- `venv/` — um Python isolado com o `omnivoice` e o PyTorch certo para a máquina. O processo
  do Jarvis **nunca importa** nenhum dos dois: fala com eles por um processo à parte
  (`trabalhador.py`), e a porta de licença falha se algo em `src/` importar;
- `pesos/<revisão>/` — os arquivos que `licenses/modelos.toml` lista, conferidos por sha256;
- `aceite.json` — quando o dono aceitou o uso pessoal, de qual revisão e de quais pesos (hash),
  e o hash do aviso que ele leu;
- `instalacao.json` — dispositivo, versões e o hash do trabalhador instalado;
- `.jarvis-omnivoice` — a marca de que foi o instalador que criou a pasta: `--remover` só apaga
  pasta marcada.

Quem escreve isso é `tools/instalar_omnivoice.py`, que **não vai no pacote**: o dono instala a
partir do repositório, como o extra do Edge. Este módulo descreve e confere a pasta, e é o motor.

**O motor (`MotorTtsOmniVoice`).** Mesma interface dos outros (`sintetizar(texto) -> PCM16 16 kHz
mono`, ADR-0017): quem fatia em lotes, antecipa os próximos e cancela por epoch continua sendo o
`SintetizadorEmStreaming` (7507cd5). O motor sobe o trabalhador uma vez (a carga dos 3 GB fica
fora do turno: o aplicativo aquece motor local ao abrir), manda um lote por vez **na ordem em
que os lotes chegam** — a janela de três sínteses antecipadas não pode fazer o N+2 passar na
frente do N —, consulta o cancelamento antes de mandar, e converte os 24 kHz do modelo para os
16 kHz do caminho de áudio. O trabalhador recebe um ambiente mínimo: nenhuma chave de API do
dono entra num processo de biblioteca de terceiro, e o Hugging Face fica em modo offline.

**A reserva (`MotorComReserva`).** Pedido do dono: faltou instalação, peso, GPU, declaração,
voz — ou deu erro no meio — o Jarvis fala com o motor padrão, sem parar e sem anunciar erro em
voz; o motivo fica em `motivo_da_reserva`, na tela de abertura e no `--diagnostico`.

**As guardas de clonagem (`VozDeReferencia`).** O model card proíbe clonagem sem autorização.
Por isso o motor só usa voz **cadastrada pelo dono** em `~/.local/share/jarvis/vozes/<nome>/`
(`ref.wav`, `ref.txt` e `autorizacao.toml` com a declaração "a voz é minha" ou "tenho
permissão do titular", e o sha256 do áudio declarado — trocar o áudio invalida a voz). Cadastrar
é comando do dono no terminal (`tools/instalar_omnivoice.py --cadastrar-voz`), que só aceita
arquivo local fora das pastas do Jarvis: nada de URL, nada do que o Jarvis gravou ou baixou. Não
existe ferramenta do assistente que cadastre ou clone voz, e a lista de negação da política
fecha as duas pastas para as ferramentas de arquivo.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import queue
import re
import shutil
import struct
import subprocess
import threading
import time
import tomllib
import wave
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final

from jarvis.ambiente import ambiente_ou_os
from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.licencas import ARQUIVO_MODELOS
from jarvis.voz.interface import Cancelado, MotorDeTts, Onde, nunca_cancelado
from jarvis.voz.registro import MotorRecusado, exigir_motor

REGISTRADO: Final = "tts-omnivoice"
CHAVE_DO_ACEITE: Final = "omnivoice_uso_pessoal"
PASTA: Final = "omnivoice"
MARCA: Final = ".jarvis-omnivoice"
TRABALHADOR: Final = "trabalhador.py"
PROTOCOLO: Final = 1
"""Versão do contrato entre o motor e o trabalhador. Muda quando a forma das mensagens muda."""
COMANDO_DE_INSTALACAO: Final = (
    "uv run --frozen python -m tools.instalar_omnivoice --aceito-uso-pessoal"
)
"""O que o dono roda, no repositório, para instalar (o instalador não vai no pacote)."""

AVISO_DE_LICENCA: Final = """\
OmniVoice (k2-fsa/OmniVoice) — LEIA ANTES DE INSTALAR

  * Uso PESSOAL e NÃO COMERCIAL. O código é Apache-2.0, mas os pesos do modelo são CC-BY-NC
    ("due to constraints from its training data (e.g., Emilia)"), e o tokenizador de áudio que
    vem junto é da Boson Higgs Audio 2 Community License (derivada da Meta Llama 3 Community
    License, com a Acceptable Use Policy do Llama 3).
  * É PROIBIDO clonar a voz de alguém sem autorização, imitar uma pessoa, fraudar ou aplicar
    golpe (Disclaimer do model card). O Jarvis só usa voz que você cadastrar localmente, com a
    declaração "a voz é minha" ou "tenho permissão do titular".
  * Não faz parte do Jarvis: não é dependência, não vai no pacote e nunca é o padrão. O padrão
    continua o motor local tts-piper-epitran, de uso comercial permitido.
  * O que será baixado: o PyTorch e a biblioteca omnivoice (num Python isolado nesta pasta) e
    cerca de 3,3 GB de pesos do Hugging Face, conferidos por sha256.

Fontes: https://github.com/k2-fsa/OmniVoice · https://huggingface.co/k2-fsa/OmniVoice
"""
"""O texto que o dono lê antes de qualquer download. O sha256 dele vai no `aceite.json`: mudar o
aviso invalida o aceite, e o instalador pergunta de novo."""

DECLARACAO_DE_USO: Final = (
    "uso pessoal e não comercial dos pesos do OmniVoice, sem clonar voz sem autorização"
)


class PesosMalRegistrados(ValueError):
    """`licenses/modelos.toml` não descreve um conjunto de pesos que dê para instalar."""


def pasta_de_dados(ambiente: Mapping[str, str] | None = None) -> Path:
    """A pasta de dados do Jarvis: `$XDG_DATA_HOME/jarvis` ou `%LOCALAPPDATA%\\jarvis`."""
    fonte = ambiente_ou_os(ambiente)
    casa = Path(fonte.get("HOME") or Path.home())
    if os.name == "nt":  # pragma: no cover — caminho do Windows, sem CI aqui
        base = fonte.get("LOCALAPPDATA") or str(casa / "AppData" / "Local")
    else:
        base = fonte.get("XDG_DATA_HOME") or str(casa / ".local" / "share")
    return Path(base) / "jarvis"


def pasta_padrao(ambiente: Mapping[str, str] | None = None) -> Path:
    return pasta_de_dados(ambiente) / PASTA


def sha256_de(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        while pedaco := arquivo.read(1024 * 1024):
            resumo.update(pedaco)
    return resumo.hexdigest()


def sha256_do_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ArquivoDePeso:
    nome: str
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PesosRegistrados:
    """Os pesos do motor como o registro os descreve: uma revisão, uma base, N arquivos."""

    ids: tuple[str, ...]
    licencas: tuple[str, ...]
    revisao: str
    instalar_de: str
    arquivos: tuple[ArquivoDePeso, ...]

    @property
    def hash(self) -> str:
        """O hash do **conjunto**: sha256 da lista `sha256  nome` ordenada, como o `sha256sum`.

        É o que o aceite guarda. Sai do registro, sem ler 3 GB do disco a cada partida — os
        arquivos já foram conferidos um a um quando foram escritos.
        """
        linhas = "".join(f"{a.sha256}  {a.nome}\n" for a in sorted(self.arquivos, key=_nome))
        return sha256_do_texto(linhas)

    @property
    def bytes_totais(self) -> int:
        return sum(arquivo.bytes for arquivo in self.arquivos)

    @property
    def tamanho(self) -> str:
        return f"{self.bytes_totais / 1_000_000_000:.2f} GB"


def _nome(arquivo: ArquivoDePeso) -> str:
    return arquivo.nome


def pesos_registrados(
    *, arquivo: Path = ARQUIVO_MODELOS, motor: str = REGISTRADO
) -> PesosRegistrados:
    """Junta os registros `uso_pessoal` deste motor (o modelo e o tokenizador de áudio).

    Recusa em vez de adivinhar: revisões ou bases diferentes entre os registros, nome de arquivo
    que sai da pasta (`..`, absoluto) e hash que não tem forma de sha256 são erro de registro.
    """
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    registros = [
        m
        for m in dados.get("modelo", [])
        if m.get("estado") == "uso_pessoal" and m.get("motor") == motor
    ]
    if not registros:
        raise PesosMalRegistrados(f"nenhum peso de uso pessoal registrado para {motor!r}")
    revisoes = {str(m.get("revisao", "")) for m in registros}
    bases = {str(m.get("instalar_de", "")) for m in registros}
    if len(revisoes) != 1 or len(bases) != 1 or not next(iter(bases)).startswith("https://"):
        raise PesosMalRegistrados(
            f"os registros de {motor!r} não concordam em revisão e base: {revisoes} {bases}"
        )
    arquivos: list[ArquivoDePeso] = []
    for registro in registros:
        for bruto in registro.get("arquivo", []):
            nome = str(bruto["nome"])
            partes = PurePosixPath(nome).parts
            if not partes or PurePosixPath(nome).is_absolute() or ".." in partes:
                raise PesosMalRegistrados(f"nome de arquivo fora da pasta dos pesos: {nome!r}")
            sha256 = str(bruto["sha256"])
            if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
                raise PesosMalRegistrados(f"{nome}: sha256 sem forma de sha256")
            arquivos.append(ArquivoDePeso(nome=nome, bytes=int(bruto["bytes"]), sha256=sha256))
    return PesosRegistrados(
        ids=tuple(str(m["id"]) for m in registros),
        licencas=tuple(str(m["licenca"]) for m in registros),
        revisao=next(iter(revisoes)),
        instalar_de=next(iter(bases)),
        arquivos=tuple(arquivos),
    )


@dataclass(frozen=True, slots=True)
class Aceite:
    """O registro local do aceite: o dono leu **este** aviso e aceitou **estes** pesos."""

    aceito_em: str
    modelo: str
    revisao: str
    hash_dos_pesos: str
    licencas: tuple[str, ...]
    sha256_do_aviso: str
    declaracao: str = DECLARACAO_DE_USO
    como: str = ""
    """`--aceito-uso-pessoal` ou `digitado no terminal`: o aceite nunca é silencioso."""

    def para_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def de_json(cls, texto: str) -> Aceite:
        dados: dict[str, Any] = json.loads(texto)
        dados["licencas"] = tuple(dados.get("licencas", ()))
        return cls(**dados)


@dataclass(frozen=True, slots=True)
class RegistroDaInstalacao:
    """O lado técnico: em que dispositivo, com que versões e com qual trabalhador."""

    instalado_em: str
    dispositivo: str
    backend_do_torch: str
    versoes: dict[str, str] = field(default_factory=dict)
    sha256_do_trabalhador: str = ""
    protocolo: int = PROTOCOLO

    def para_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def de_json(cls, texto: str) -> RegistroDaInstalacao:
        dados: dict[str, Any] = json.loads(texto)
        return cls(**dados)


@dataclass(frozen=True, slots=True)
class Instalacao:
    """A pasta do OmniVoice no disco do dono, e a pergunta "dá para rodar?"."""

    raiz: Path

    @classmethod
    def padrao(cls, ambiente: Mapping[str, str] | None = None) -> Instalacao:
        return cls(pasta_padrao(ambiente))

    @property
    def venv(self) -> Path:
        return self.raiz / "venv"

    @property
    def python(self) -> Path:
        if os.name == "nt":  # pragma: no cover — caminho do Windows, sem CI aqui
            return self.venv / "Scripts" / "python.exe"
        return self.venv / "bin" / "python"

    @property
    def trabalhador(self) -> Path:
        return self.raiz / TRABALHADOR

    @property
    def marca(self) -> Path:
        return self.raiz / MARCA

    @property
    def arquivo_do_aceite(self) -> Path:
        return self.raiz / "aceite.json"

    @property
    def arquivo_da_instalacao(self) -> Path:
        return self.raiz / "instalacao.json"

    def pasta_dos_pesos(self, revisao: str) -> Path:
        return self.raiz / "pesos" / revisao

    def aceite(self) -> Aceite | None:
        try:
            return Aceite.de_json(self.arquivo_do_aceite.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

    def registro(self) -> RegistroDaInstalacao | None:
        try:
            return RegistroDaInstalacao.de_json(
                self.arquivo_da_instalacao.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            return None

    def falta(self, pesos: PesosRegistrados) -> str:
        """Vazio quando dá para rodar; senão a frase, que já diz o que fazer. Não lê os 3 GB."""
        refazer = f"rode de novo, no repositório: {COMANDO_DE_INSTALACAO}"
        if not self.marca.is_file():
            return f"o OmniVoice não está instalado em {self.raiz} ({refazer})"
        if not self.python.exists():
            return f"o Python isolado do OmniVoice sumiu de {self.venv} ({refazer})"
        registro = self.registro()
        if registro is None or registro.protocolo != PROTOCOLO:
            return (
                f"a instalação não tem registro válido em {self.arquivo_da_instalacao} ({refazer})"
            )
        if not self.trabalhador.is_file() or sha256_de(self.trabalhador) != (
            registro.sha256_do_trabalhador
        ):
            return f"o trabalhador {self.trabalhador} não é o que o instalador pôs lá ({refazer})"
        aceite = self.aceite()
        if aceite is None:
            return f"falta o aceite do uso pessoal em {self.arquivo_do_aceite} ({refazer})"
        if aceite.revisao != pesos.revisao or aceite.hash_dos_pesos != pesos.hash:
            return (
                f"o aceite é da revisão {aceite.revisao} e o registro pede {pesos.revisao}: "
                f"os pesos mudaram, e o aceite vale para os que você leu ({refazer})"
            )
        pasta = self.pasta_dos_pesos(pesos.revisao)
        faltando = [
            a.nome
            for a in pesos.arquivos
            if not (pasta / a.nome).is_file() or (pasta / a.nome).stat().st_size != a.bytes
        ]
        if faltando:
            return f"faltam {len(faltando)} arquivo(s) de peso em {pasta} ({refazer})"
        return ""


# --- vozes de referência: só as que o dono cadastrou, com a declaração dele ---------------------

ARQUIVO_DA_DECLARACAO: Final = "autorizacao.toml"
DECLARACOES: Final[Mapping[str, str]] = {
    "minha": "a voz é minha",
    "permissao": "tenho permissão do titular para usar esta voz",
}
"""As duas declarações que valem. "Permissão" exige o nome de quem deu."""
FORMA_DO_NOME_DE_VOZ: Final = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
DURACAO_MINIMA_S: Final = 3.0
DURACAO_MAXIMA_S: Final = 20.0
"""3–10 s é o que o projeto recomenda; acima de 20 s a biblioteca avisa que piora e pesa."""
TEXTO_MAXIMO: Final = 1000


class VozNaoAutorizada(RuntimeError):
    """A voz não foi cadastrada pelo dono, falta a declaração, ou o áudio não é o declarado."""


def pasta_das_vozes(ambiente: Mapping[str, str] | None = None) -> Path:
    return pasta_de_dados(ambiente) / "vozes"


def pastas_do_jarvis(ambiente: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Onde o Jarvis grava ou baixa sozinho: dados, estado (sessões, captura) e cache (modelos).

    Áudio vindo daqui não vira voz de referência — pode ser a fala de qualquer pessoa que o
    microfone pegou, ou um arquivo que uma ferramenta baixou.
    """
    fonte = ambiente_ou_os(ambiente)
    casa = Path(fonte.get("HOME") or Path.home())
    estado = Path(fonte.get("XDG_STATE_HOME") or casa / ".local" / "state") / "jarvis"
    cache = Path(fonte.get("XDG_CACHE_HOME") or casa / ".cache") / "jarvis"
    return (pasta_de_dados(ambiente), estado, cache)


def _dentro(caminho: Path, pasta: Path) -> bool:
    try:
        caminho.relative_to(pasta.expanduser().resolve())
    except ValueError:
        return False
    return True


def duracao_do_wav(caminho: Path) -> float:
    """Duração de um WAV PCM, pela biblioteca padrão. Outro formato recusa com frase."""
    try:
        with wave.open(str(caminho), "rb") as arquivo:
            quadros, taxa = arquivo.getnframes(), arquivo.getframerate()
    except (wave.Error, EOFError, OSError) as erro:
        raise VozNaoAutorizada(
            f"{caminho.name} não é um WAV PCM legível ({erro}); converta para WAV 16 bits "
            "(ex.: ffmpeg -i entrada -ac 1 -ar 24000 -sample_fmt s16 ref.wav)"
        ) from None
    if taxa <= 0:
        raise VozNaoAutorizada(f"{caminho.name}: taxa de amostragem inválida")
    return quadros / taxa


@dataclass(frozen=True, slots=True)
class VozDeReferencia:
    """Uma voz que o dono cadastrou: o áudio, a transcrição e a declaração dele."""

    nome: str
    audio: Path
    texto: str
    declaracao: str
    titular: str
    declarado_em: str
    sha256_do_audio: str
    duracao_s: float

    @property
    def frase_da_declaracao(self) -> str:
        frase = DECLARACOES[self.declaracao]
        return f"{frase} ({self.titular})" if self.titular else frase


def exigir_nome_de_voz(nome: str) -> str:
    if not FORMA_DO_NOME_DE_VOZ.fullmatch(nome):
        raise VozNaoAutorizada(
            f"nome de voz {nome!r} inválido: letras minúsculas, números, _ e -, até 40"
        )
    return nome


def ler_voz(
    nome: str, *, pasta: Path | None = None, ambiente: Mapping[str, str] | None = None
) -> VozDeReferencia:
    """A voz cadastrada, conferida: declaração válida e o áudio ainda é o declarado."""
    exigir_nome_de_voz(nome)
    base = (pasta if pasta is not None else pasta_das_vozes(ambiente)) / nome
    audio, texto, declaracao = base / "ref.wav", base / "ref.txt", base / ARQUIVO_DA_DECLARACAO
    if not audio.is_file() or not texto.is_file():
        raise VozNaoAutorizada(
            f"a voz {nome!r} não está cadastrada em {base} (faltam ref.wav e ref.txt): "
            "cadastre com `uv run --frozen python -m tools.instalar_omnivoice --cadastrar-voz`"
        )
    if not declaracao.is_file():
        raise VozNaoAutorizada(
            f"a voz {nome!r} não tem {ARQUIVO_DA_DECLARACAO}: sem a sua declaração (a voz é sua, "
            "ou você tem permissão do titular), o Jarvis não a usa"
        )
    try:
        dados = tomllib.loads(declaracao.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as erro:
        raise VozNaoAutorizada(f"{declaracao} não deu para ler: {erro}") from None
    tipo = str(dados.get("declaracao", ""))
    titular = str(dados.get("titular", "")).strip()
    if tipo not in DECLARACOES:
        raise VozNaoAutorizada(
            f"{declaracao}: declaracao = {tipo!r} não vale; as que valem: {', '.join(DECLARACOES)}"
        )
    if tipo == "permissao" and not titular:
        raise VozNaoAutorizada(f"{declaracao}: com permissão, diga de quem (titular)")
    if sha256_de(audio) != str(dados.get("sha256_do_audio", "")):
        raise VozNaoAutorizada(
            f"o ref.wav da voz {nome!r} não é o áudio que você declarou (o sha256 mudou): "
            "cadastre de novo"
        )
    falado = texto.read_text(encoding="utf-8").strip()
    if not falado:
        raise VozNaoAutorizada(f"o ref.txt da voz {nome!r} está vazio: é a transcrição do ref.wav")
    return VozDeReferencia(
        nome=nome,
        audio=audio,
        texto=falado,
        declaracao=tipo,
        titular=titular,
        declarado_em=str(dados.get("declarado_em", "")),
        sha256_do_audio=str(dados["sha256_do_audio"]),
        duracao_s=duracao_do_wav(audio),
    )


def vozes_cadastradas(
    *, pasta: Path | None = None, ambiente: Mapping[str, str] | None = None
) -> list[str]:
    base = pasta if pasta is not None else pasta_das_vozes(ambiente)
    if not base.is_dir():
        return []
    return sorted(
        p.name for p in base.iterdir() if p.is_dir() and FORMA_DO_NOME_DE_VOZ.fullmatch(p.name)
    )


def cadastrar_voz(
    nome: str,
    *,
    audio: str,
    texto: str,
    declaracao: str,
    titular: str = "",
    agora: str = "",
    pasta: Path | None = None,
    ambiente: Mapping[str, str] | None = None,
) -> VozDeReferencia:
    """Cadastra uma voz do dono. Só arquivo local, fora das pastas do Jarvis, com declaração.

    É chamada pelo comando do dono em `tools/` — não existe ferramenta do assistente que chegue
    aqui, e a porta de licença confere que `src/` não chama isto.
    """
    exigir_nome_de_voz(nome)
    if "://" in audio:
        raise VozNaoAutorizada(
            "só arquivo local: o Jarvis não baixa áudio de ninguém para clonar (ADR-0039)"
        )
    if declaracao not in DECLARACOES:
        raise VozNaoAutorizada(
            f"declare se a voz é sua ou se tem permissão do titular: {', '.join(DECLARACOES)}"
        )
    titular = titular.strip()
    if declaracao == "permissao" and not titular:
        raise VozNaoAutorizada("com permissão, diga de quem é a voz (--titular)")
    falado = texto.strip()
    if not falado or len(falado) > TEXTO_MAXIMO:
        raise VozNaoAutorizada(
            f"a transcrição do áudio é obrigatória e tem até {TEXTO_MAXIMO} caracteres"
        )
    try:
        origem = Path(audio).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise VozNaoAutorizada(f"o arquivo {audio!r} não existe") from None
    if not origem.is_file():
        raise VozNaoAutorizada(f"{origem} não é um arquivo")
    for proibida in pastas_do_jarvis(ambiente):
        if _dentro(origem, proibida):
            raise VozNaoAutorizada(
                f"{origem} está em {proibida}, onde o Jarvis grava e baixa sozinho: áudio "
                "capturado ou baixado não vira voz. Use uma gravação sua, de fora dessas pastas"
            )
    duracao = duracao_do_wav(origem)
    if not DURACAO_MINIMA_S <= duracao <= DURACAO_MAXIMA_S:
        raise VozNaoAutorizada(
            f"o áudio tem {duracao:.1f} s; use de {DURACAO_MINIMA_S:.0f} a {DURACAO_MAXIMA_S:.0f} "
            "s (o recomendado é 3–10 s)"
        )
    destino = (pasta if pasta is not None else pasta_das_vozes(ambiente)) / nome
    if destino.exists():
        raise VozNaoAutorizada(
            f"a voz {nome!r} já existe em {destino}: remova antes (--remover-voz {nome})"
        )
    destino.mkdir(parents=True)
    shutil.copyfile(origem, destino / "ref.wav")
    (destino / "ref.txt").write_text(falado + "\n", encoding="utf-8")
    titular_toml = titular.replace("\\", "\\\\").replace('"', '\\"')
    (destino / ARQUIVO_DA_DECLARACAO).write_text(
        "# Declaração do dono (ADR-0039). Sem ela, o Jarvis não usa esta voz.\n"
        '# "minha" = a voz é minha; "permissao" = tenho permissão do titular.\n'
        f'declaracao = "{declaracao}"\n'
        f'titular = "{titular_toml}"\n'
        f'declarado_em = "{agora}"\n'
        f'origem = "{origem.name.replace(chr(34), "")}"\n'
        f'sha256_do_audio = "{sha256_de(destino / "ref.wav")}"\n',
        encoding="utf-8",
    )
    return ler_voz(nome, pasta=destino.parent)


def remover_voz(
    nome: str, *, pasta: Path | None = None, ambiente: Mapping[str, str] | None = None
) -> bool:
    """Apaga os três arquivos da voz e a pasta dela (se ficar vazia). Nada além disso."""
    exigir_nome_de_voz(nome)
    base = (pasta if pasta is not None else pasta_das_vozes(ambiente)) / nome
    if not base.is_dir() or base.is_symlink():
        return False
    for arquivo in ("ref.wav", "ref.txt", ARQUIVO_DA_DECLARACAO):
        (base / arquivo).unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        base.rmdir()
    return True


# --- o motor ------------------------------------------------------------------------------------

IDIOMA_DO_MODELO: Final = "pt"
"""O código que o OmniVoice usa para português (`lang_map`: "portuguese" → "pt")."""
PRAZO_DO_OLA_S: Final = 30.0
PRAZO_DE_CARGA_S: Final = 300.0
"""Carregar 3,3 GB do disco para a GPU; na CPU, mais. Passou disto, algo está errado."""
PRAZO_POR_SINTESE_S: Final = 120.0
"""Um lote de 14 a 18 palavras. Generoso de propósito: na CPU é lento (não medido aqui)."""
PRAZO_PARA_SAIR_S: Final = 5.0
VARIAVEIS_DO_TRABALHADOR: Final[tuple[str, ...]] = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "LD_LIBRARY_PATH",
    "CUDA_VISIBLE_DEVICES",
    "CUDA_DEVICE_ORDER",
)
"""O que passa do ambiente do Jarvis para o trabalhador. Lista fechada: chave de API não passa."""
OFFLINE: Final[Mapping[str, str]] = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
}
"""Os pesos já estão no disco: o trabalhador não tem por que falar com o Hugging Face."""


class ErroDoOmniVoice(RuntimeError):
    """O OmniVoice não deu conta: não instalado, sem GPU, trabalhador que caiu, prazo estourado.

    Quem o embrulha (`MotorComReserva`) volta ao motor padrão; o motivo fica guardado.
    """


class _Vez:
    """Uma trava que atende na ordem de chegada (senha de padaria).

    O `SintetizadorEmStreaming` põe N, N+1 e N+2 para sintetizar ao mesmo tempo; o trabalhador
    faz um de cada vez. Com uma trava comum, o N+2 poderia passar na frente do N — e o dono
    esperaria dois lotes a mais pelo primeiro áudio.
    """

    def __init__(self) -> None:
        self._condicao = threading.Condition()
        self._proxima = 0
        self._atendendo = 0

    @contextlib.contextmanager
    def __call__(self) -> Iterator[None]:
        with self._condicao:
            senha = self._proxima
            self._proxima += 1
            while self._atendendo != senha:
                self._condicao.wait()
        try:
            yield
        finally:
            with self._condicao:
                self._atendendo += 1
                self._condicao.notify_all()


def _ler_exato(canal: IO[bytes], tamanho: int) -> bytes | None:
    partes: list[bytes] = []
    falta = tamanho
    while falta:
        pedaco = canal.read(falta)
        if not pedaco:
            return None
        partes.append(pedaco)
        falta -= len(pedaco)
    return b"".join(partes)


_Mensagem = tuple[dict[str, Any] | None, bytes | str]
"""(cabeçalho, corpo) — ou (None, motivo) quando o canal acabou."""


@dataclass(slots=True)
class MotorTtsOmniVoice:
    """A voz cadastrada do dono, pelo OmniVoice, num processo à parte (interface da ADR-0017)."""

    instalacao: Instalacao
    pesos: PesosRegistrados
    voz_de_referencia: VozDeReferencia
    cancelado: Cancelado = nunca_cancelado
    idioma: str = IDIOMA_DO_MODELO
    taxa_alvo: int = TAXA_PADRAO
    prazo_de_carga_s: float = PRAZO_DE_CARGA_S
    prazo_por_sintese_s: float = PRAZO_POR_SINTESE_S
    comando: Sequence[str] = ()
    """Como subir o trabalhador. Vazio = o Python isolado da instalação, com `-I` (os testes
    passam o deles, com a biblioteca de mentira)."""
    ambiente: Mapping[str, str] | None = None
    """De onde saem as variáveis da lista fechada; `None` = o ambiente deste processo."""
    nome: str = "omnivoice"
    voz: str = ""
    licenca: str = "Apache-2.0 (código) + CC-BY-NC (pesos) + Boson Higgs Audio 2 (tokenizador)"
    onde: Onde = Onde.LOCAL
    registrado: str = REGISTRADO
    sinteses: int = 0
    descartadas_por_cancelamento: int = 0
    segundos_de_carga: float = 0.0
    dispositivo: str = ""
    _processo: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    _caixa: queue.Queue[_Mensagem] = field(default_factory=queue.Queue, repr=False)
    _vez: _Vez = field(default_factory=_Vez, repr=False)
    _pronto: bool = field(default=False, repr=False)
    _pedido: int = field(default=0, repr=False)
    _taxa: int = field(default=24_000, repr=False)
    _log: IO[bytes] | None = field(default=None, repr=False)
    falhou: str = ""
    """O motivo da primeira falha. Preenchido, o motor recusa de cara (a reserva assume)."""

    def __post_init__(self) -> None:
        self.voz = self.voz or self.voz_de_referencia.nome

    def _argv(self) -> list[str]:
        if self.comando:
            return [*self.comando]
        registro = self.instalacao.registro()
        dispositivo = registro.dispositivo if registro is not None else "cpu"
        return [
            str(self.instalacao.python),
            "-I",
            str(self.instalacao.trabalhador),
            "--pesos",
            str(self.instalacao.pasta_dos_pesos(self.pesos.revisao)),
            "--dispositivo",
            dispositivo,
        ]

    def _ambiente_do_trabalhador(self) -> dict[str, str]:
        fonte = ambiente_ou_os(self.ambiente)
        ambiente = {nome: fonte[nome] for nome in VARIAVEIS_DO_TRABALHADOR if nome in fonte}
        return {**ambiente, **OFFLINE}

    def abrir(self) -> None:
        """Sobe o trabalhador e volta logo: a carga do modelo corre enquanto o resto abre."""
        if self._processo is not None and self._processo.poll() is None:
            return
        self._pronto = False
        self._caixa = queue.Queue()
        if not self.comando:
            falta = self.instalacao.falta(self.pesos)
            if falta:
                raise ErroDoOmniVoice(falta)
        try:
            self._log = (self.instalacao.raiz / "trabalhador.log").open("wb")
        except OSError:
            self._log = None
        try:
            self._processo = subprocess.Popen(  # noqa: S603 — argv explícito, sem shell
                self._argv(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._log if self._log is not None else subprocess.DEVNULL,
                env=self._ambiente_do_trabalhador(),
            )
        except OSError as erro:
            raise ErroDoOmniVoice(f"o trabalhador não subiu: {erro}") from None
        canal = self._processo.stdout
        assert canal is not None
        threading.Thread(target=self._ler_mensagens, args=(canal, self._caixa), daemon=True).start()

    @staticmethod
    def _ler_mensagens(canal: IO[bytes], caixa: queue.Queue[_Mensagem]) -> None:
        """Na linha própria: cada mensagem do trabalhador vira um item da caixa, em ordem."""
        try:
            while True:
                prefixo = _ler_exato(canal, 4)
                if prefixo is None:
                    caixa.put((None, "o trabalhador encerrou"))
                    return
                dados = _ler_exato(canal, struct.unpack(">I", prefixo)[0])
                cabecalho = json.loads(dados.decode("utf-8")) if dados is not None else None
                if not isinstance(cabecalho, dict):
                    caixa.put((None, "mensagem quebrada do trabalhador"))
                    return
                tamanho = int(cabecalho.get("bytes", 0) or 0)
                corpo = _ler_exato(canal, tamanho) if tamanho else b""
                if corpo is None:
                    caixa.put((None, "o trabalhador encerrou no meio do áudio"))
                    return
                caixa.put((cabecalho, corpo))
        except (OSError, ValueError) as erro:
            caixa.put((None, f"canal do trabalhador quebrado: {type(erro).__name__}"))

    def _esperar(self, prazo_s: float, o_que: str) -> tuple[dict[str, Any], bytes]:
        try:
            cabecalho, corpo = self._caixa.get(timeout=prazo_s)
        except queue.Empty:
            self.fechar(matar=True)
            raise ErroDoOmniVoice(f"o trabalhador passou de {prazo_s:.0f} s em {o_que}") from None
        if cabecalho is None:
            self._pronto = False
            raise ErroDoOmniVoice(f"{corpo!s} ({o_que})")
        if cabecalho.get("tipo") == "erro":
            motivo = str(cabecalho.get("motivo", ""))
            detalhe = str(cabecalho.get("detalhe", ""))
            if motivo in {"sem_gpu", "carga"}:
                self._pronto = False
            raise ErroDoOmniVoice(f"{motivo}: {detalhe}" if detalhe else motivo)
        assert isinstance(corpo, bytes)
        return cabecalho, corpo

    def _enviar(self, pedido: dict[str, Any]) -> None:
        processo = self._processo
        if processo is None or processo.stdin is None:
            raise ErroDoOmniVoice("o trabalhador não está de pé")
        dados = json.dumps(pedido, ensure_ascii=False).encode("utf-8")
        try:
            processo.stdin.write(struct.pack(">I", len(dados)) + dados)
            processo.stdin.flush()
        except (BrokenPipeError, OSError) as erro:
            raise ErroDoOmniVoice(f"o trabalhador não recebe mais pedidos: {erro}") from None

    def _preparar(self) -> None:
        """Espera o `ola` e o `pronto` (a carga dos pesos) e entrega a voz de referência."""
        comeco = time.monotonic()
        ola, _ = self._esperar(PRAZO_DO_OLA_S, "subir")
        if ola.get("tipo") != "ola" or ola.get("protocolo") != PROTOCOLO:
            self.fechar(matar=True)
            raise ErroDoOmniVoice(
                f"o trabalhador fala outro protocolo ({ola!r}); reinstale: {COMANDO_DE_INSTALACAO}"
            )
        pronto, _ = self._esperar(self.prazo_de_carga_s, "carregar os pesos")
        self.dispositivo = str(pronto.get("dispositivo", ""))
        self._taxa = int(pronto.get("taxa", 24_000))
        self._pedido += 1
        self._enviar(
            {
                "op": "voz",
                "id": self._pedido,
                "audio": str(self.voz_de_referencia.audio),
                "texto": self.voz_de_referencia.texto,
            }
        )
        resposta, _ = self._esperar(PRAZO_DO_OLA_S, "preparar a voz de referência")
        if resposta.get("tipo") != "voz" or resposta.get("id") != self._pedido:
            raise ErroDoOmniVoice(f"resposta fora de ordem do trabalhador: {resposta!r}")
        self.segundos_de_carga = time.monotonic() - comeco
        self.nome = f"omnivoice@{self.dispositivo or '?'}+{self.voz}"
        self._pronto = True

    def sintetizar(self, texto: str) -> bytes:
        """Um lote. A primeira falha é **definitiva** para este motor (`falhou`): um lote que
        já esperava a vez não pode ressuscitar o trabalhador que a reserva acabou de fechar."""
        if not texto.strip():
            return b""
        try:
            with self._vez():
                if self.falhou:
                    raise ErroDoOmniVoice(self.falhou)
                if self.cancelado():
                    self.descartadas_por_cancelamento += 1
                    return b""
                if self._processo is None or self._processo.poll() is not None:
                    self.abrir()
                if not self._pronto:
                    self._preparar()
                if self.cancelado():  # a carga pode ter levado o turno embora
                    self.descartadas_por_cancelamento += 1
                    return b""
                self._pedido += 1
                self._enviar(
                    {"op": "sintetizar", "id": self._pedido, "texto": texto, "idioma": self.idioma}
                )
                cabecalho, corpo = self._esperar(self.prazo_por_sintese_s, "sintetizar")
                if cabecalho.get("tipo") != "audio" or cabecalho.get("id") != self._pedido:
                    raise ErroDoOmniVoice(f"resposta fora de ordem do trabalhador: {cabecalho!r}")
                self.sinteses += 1
                taxa = int(cabecalho.get("taxa", self._taxa))
            # Fora da vez: converter um lote enquanto o trabalhador já gera o próximo.
            return self._para_pcm16(corpo, taxa)
        except Exception as erro:
            self.falhou = self.falhou or f"{type(erro).__name__}: {erro}"[:400]
            raise

    def _para_pcm16(self, corpo: bytes, taxa: int) -> bytes:
        import numpy as np

        from jarvis.corpus.voz import reamostrar

        if len(corpo) % 4:
            raise ErroDoOmniVoice("o áudio do trabalhador não é float32")
        amostras = np.frombuffer(corpo, dtype="<f4").astype(np.float64)
        if amostras.size == 0:
            return b""
        no_alvo = reamostrar(amostras, de=taxa, para=self.taxa_alvo)
        inteiros = np.clip(np.rint(no_alvo * 32767.0), -32768, 32767).astype("<i2")
        return bytes(inteiros.tobytes())

    def fechar(self, *, matar: bool = False) -> None:
        """Pede para sair; se não sair no prazo (ou `matar`), mata — o filho é nosso, pelo PID."""
        processo, self._processo = self._processo, None
        self._pronto = False
        if processo is not None:
            if not matar and processo.poll() is None:
                with contextlib.suppress(ErroDoOmniVoice, OSError, ValueError):
                    dados = json.dumps({"op": "sair"}).encode("utf-8")
                    assert processo.stdin is not None
                    processo.stdin.write(struct.pack(">I", len(dados)) + dados)
                    processo.stdin.flush()
            with contextlib.suppress(OSError, ValueError):
                if processo.stdin is not None:
                    processo.stdin.close()
            try:
                processo.wait(timeout=0 if matar else PRAZO_PARA_SAIR_S)
            except subprocess.TimeoutExpired:
                processo.kill()
                processo.wait(timeout=PRAZO_PARA_SAIR_S)
            if processo.stdout is not None:
                processo.stdout.close()
        if self._log is not None:
            self._log.close()
            self._log = None


@dataclass(slots=True)
class MotorComReserva:
    """O motor escolhido, e o padrão no lugar dele se ele não der conta — sem parar a fala.

    A troca é **uma vez e para a sessão**: um motor que caiu no meio de uma resposta não é
    tentado de novo no lote seguinte (seria a voz trocando a cada frase, e a carga de 3 GB a
    cada tentativa). O motivo fica em `motivo_da_reserva`.
    """

    principal: MotorDeTts | None
    fabricar_reserva: Callable[[], MotorDeTts]
    motivo_da_reserva: str = ""
    observacao: str = ""
    """O que a tela de abertura mostra embaixo de "falando com": uso pessoal, ou por que não."""
    nome: str = ""
    voz: str = ""
    licenca: str = ""
    onde: Onde = Onde.LOCAL
    _reserva: MotorDeTts | None = field(default=None, repr=False)
    _trava: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.principal is None:
            self._usar(self.fabricar_reserva())
            return
        self.nome = self.principal.nome
        self.voz = self.principal.voz
        self.licenca = self.principal.licenca
        self.onde = self.principal.onde

    @classmethod
    def ja_na_reserva(
        cls, fabricar_reserva: Callable[[], MotorDeTts], motivo: str
    ) -> MotorComReserva:
        motor = cls(principal=None, fabricar_reserva=fabricar_reserva, motivo_da_reserva=motivo)
        motor.observacao = f"OmniVoice não roda agora, voz padrão no lugar: {motivo}"
        return motor

    @property
    def na_reserva(self) -> bool:
        return self._reserva is not None

    def _usar(self, reserva: MotorDeTts) -> None:
        self._reserva = reserva
        self.nome = reserva.nome
        self.voz = reserva.voz
        self.licenca = reserva.licenca
        self.onde = reserva.onde

    def sintetizar(self, texto: str) -> bytes:
        reserva = self._reserva
        if reserva is None:
            assert self.principal is not None
            try:
                amostras = self.principal.sintetizar(texto)
            except Exception as erro:  # pedido do dono: qualquer falha do opcional cai no padrão
                reserva = self._cair_na_reserva(erro)
            else:
                self.nome = self.principal.nome  # depois da carga, o nome diz o dispositivo
                return amostras
        return reserva.sintetizar(texto)

    def _cair_na_reserva(self, erro: Exception) -> MotorDeTts:
        with self._trava:
            if self._reserva is None:
                self.motivo_da_reserva = f"{type(erro).__name__}: {erro}"[:400]
                self.observacao = (
                    f"OmniVoice caiu, voz padrão no lugar até o fim da sessão: "
                    f"{self.motivo_da_reserva}"
                )
                fechar = getattr(self.principal, "fechar", None)
                if callable(fechar):
                    with contextlib.suppress(Exception):
                        fechar()
                self._usar(self.fabricar_reserva())
            assert self._reserva is not None
            return self._reserva

    def fechar(self) -> None:
        for motor in (self.principal, self._reserva):
            fechar = getattr(motor, "fechar", None)
            if callable(fechar):
                fechar()


def o_que_falta_ao_omnivoice(
    voz: str,
    *,
    instalacao: Instalacao | None = None,
    pasta_das_vozes: Path | None = None,
    ambiente: Mapping[str, str] | None = None,
) -> str:
    """Instalação, aceite, pesos e voz cadastrada — o que falta, numa frase. Vazio = roda."""
    try:
        pesos = pesos_registrados()
    except PesosMalRegistrados as erro:
        return str(erro)
    falta = (instalacao or Instalacao.padrao(ambiente)).falta(pesos)
    if falta:
        return falta
    if not voz:
        return (
            "falta escolher a voz cadastrada (voz_omnivoice = ...): cadastre a sua com "
            "`uv run --frozen python -m tools.instalar_omnivoice --cadastrar-voz`"
        )
    try:
        ler_voz(voz, pasta=pasta_das_vozes, ambiente=ambiente)
    except VozNaoAutorizada as erro:
        return str(erro)
    return ""


def motor_omnivoice(
    *,
    aceito: bool,
    voz: str,
    reserva: Callable[[], MotorDeTts],
    cancelado: Cancelado = nunca_cancelado,
    instalacao: Instalacao | None = None,
    pasta_das_vozes: Path | None = None,
    ambiente: Mapping[str, str] | None = None,
    comando: Sequence[str] = (),
) -> MotorComReserva:
    """O que `tts = "tts-omnivoice"` monta: o OmniVoice com a reserva, ou já a reserva.

    Sem a declaração do dono, sem instalação, sem voz cadastrada — volta o motor padrão, e o
    motivo vai junto. Nada disso derruba a abertura do aplicativo (pedido do dono).
    """
    try:
        exigir_motor(REGISTRADO, uso_pessoal_aceito=[REGISTRADO] if aceito else [])
        pesos = pesos_registrados()
        local = instalacao or Instalacao.padrao(ambiente)
        if not comando:
            falta = local.falta(pesos)
            if falta:
                raise ErroDoOmniVoice(falta)
        if not voz:
            raise VozNaoAutorizada("falta escolher a voz cadastrada (voz_omnivoice = ...)")
        referencia = ler_voz(voz, pasta=pasta_das_vozes, ambiente=ambiente)
        principal = MotorTtsOmniVoice(
            instalacao=local,
            pesos=pesos,
            voz_de_referencia=referencia,
            cancelado=cancelado,
            comando=comando,
            ambiente=ambiente,
        )
        principal.abrir()
    except (MotorRecusado, ErroDoOmniVoice, VozNaoAutorizada, PesosMalRegistrados, OSError) as erro:
        return MotorComReserva.ja_na_reserva(reserva, str(erro))
    motor = MotorComReserva(principal=principal, fabricar_reserva=reserva)
    motor.observacao = (
        f"uso pessoal, não comercial (pesos CC-BY-NC, ADR-0039) — voz {referencia.nome}: "
        f"{referencia.frase_da_declaracao}"
    )
    return motor


def linhas_do_diagnostico(
    *,
    aceito: bool,
    voz: str,
    instalacao: Instalacao | None = None,
    pasta_das_vozes: Path | None = None,
    ambiente: Mapping[str, str] | None = None,
) -> list[str]:
    """O que o `jarvis-voz --diagnostico` mostra do OmniVoice — sem subir o trabalhador."""
    local = instalacao or Instalacao.padrao(ambiente)
    linhas: list[str] = []
    if not local.marca.is_file():
        linhas.append(
            f"  não instalado ({local.raiz}) — o padrão segue o motor local. Para uso pessoal, "
            f"no repositório: {COMANDO_DE_INSTALACAO}"
        )
    else:
        registro, aceite = local.registro(), local.aceite()
        if registro is not None:
            linhas.append(
                f"  instalado em {local.raiz}: {registro.dispositivo} ({registro.backend_do_torch})"
                f", torch {registro.versoes.get('torch', '?')}, omnivoice "
                f"{registro.versoes.get('omnivoice', '?')}"
            )
        if aceite is not None:
            linhas.append(
                f"  aceite do uso pessoal: {aceite.aceito_em} ({aceite.como}), revisão "
                f"{aceite.revisao}"
            )
        try:
            falta = local.falta(pesos_registrados())
        except PesosMalRegistrados as erro:
            falta = str(erro)
        linhas.append(f"  {'pronto' if not falta else 'não pronto: ' + falta}")
    linhas.append(
        f"  declaração na configuração: {CHAVE_DO_ACEITE} = {'true' if aceito else 'false'}"
    )
    nomes = vozes_cadastradas(pasta=pasta_das_vozes, ambiente=ambiente)
    if not nomes:
        linhas.append("  nenhuma voz cadastrada (--cadastrar-voz, com a sua declaração)")
    for nome in nomes:
        marca = "★" if nome == voz else " "
        try:
            referencia = ler_voz(nome, pasta=pasta_das_vozes, ambiente=ambiente)
        except VozNaoAutorizada as erro:
            linhas.append(f"  {marca} voz {nome}: RECUSADA — {erro}")
            continue
        linhas.append(
            f"  {marca} voz {nome}: {referencia.frase_da_declaracao}, "
            f"{referencia.duracao_s:.1f} s, declarada em {referencia.declarado_em or '?'}"
        )
    if voz and voz not in nomes:
        linhas.append(f"  voz_omnivoice = {voz!r}, mas ela não está cadastrada")
    return linhas
