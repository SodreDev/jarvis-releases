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
partir do repositório, como o extra do Edge. Este módulo só descreve e confere — ele é o que o
motor e o diagnóstico leem para saber se dá para rodar.
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final

from jarvis.ambiente import ambiente_ou_os
from jarvis.licencas import ARQUIVO_MODELOS

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
    if os.name == "nt":  # pragma: no cover — caminho do Windows, sem CI aqui
        base = fonte.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = fonte.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
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
