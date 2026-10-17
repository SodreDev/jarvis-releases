"""Peso de modelo não entra no pacote: é baixado no primeiro uso, dito e conferido (ADR-0020).

**Por que não vai junto.** A voz do piper tem 63,2 MB e um modelo de ASR tem centenas; pôr
isso dentro do AppImage, do `.deb` e do `.rpm` triplicaria os três artefatos para entregar um
arquivo que a máquina do dono pode já ter — e ainda obrigaria a reempacotar tudo a cada troca
de voz. Modelo é **dado**, não programa.

**Três promessas, e as três são verificáveis:**

1. **o tamanho é dito antes.** Ninguém começa um download de 63 MB sem o dono saber que são
   63 MB e para onde vão;
2. **o conteúdo é conferido depois.** Tamanho **e** sha256 do registro (`licenses/modelos.toml`),
   calculados enquanto o arquivo é escrito. Diferente, o arquivo é apagado e a mensagem diz o
   que esperava — um peso trocado no meio do caminho é exatamente o que não se descobre por
   acidente;
3. **o arquivo só aparece inteiro.** A escrita é num temporário ao lado, e a troca para o nome
   final é `Path.replace` — nada de meia voz no disco porque a rede caiu.

A rede segue a mesma regra do resto do produto: sob `CI=1`, só base local (o servidor falso da
suíte). A suíte inteira baixa de `127.0.0.1`, e nenhum teste puxa 63 MB da internet.
"""

from __future__ import annotations

import hashlib
import tomllib
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from jarvis.licencas import ARQUIVO_MODELOS
from jarvis.rede import ErroDeRede
from jarvis.voz.nuvem import proibir_nuvem_real_em_ci

PASTA_PADRAO: Final = Path.home() / ".cache" / "jarvis"
"""Onde os pesos ficam. É a mesma pasta que o `jarvis-voz` já usa para a voz local."""

PEDACO: Final = 1024 * 1024
PRAZO_S: Final = 60.0


class ModeloRecusado(RuntimeError):
    """O que chegou não é o que o registro descreve. A mensagem diz o que esperava."""


@dataclass(frozen=True, slots=True)
class ArquivoDeModelo:
    """Um arquivo de peso, com o tamanho e o hash que o registro publica."""

    nome: str
    bytes: int
    sha256: str
    url: str

    @property
    def tamanho(self) -> str:
        """O tamanho em MB decimais — que é como um download é anunciado a uma pessoa."""
        return f"{self.bytes / 1_000_000:.1f} MB"


@dataclass(frozen=True, slots=True)
class Descarga:
    """Tudo o que falta baixar para um modelo funcionar."""

    id: str
    papel: str
    licenca: str
    destino: Path
    arquivos: tuple[ArquivoDeModelo, ...]

    @property
    def bytes_totais(self) -> int:
        return sum(arquivo.bytes for arquivo in self.arquivos)

    @property
    def tamanho(self) -> str:
        return f"{self.bytes_totais / 1_000_000:.1f} MB"

    def falta(self) -> tuple[ArquivoDeModelo, ...]:
        """O que ainda não está no disco — conferindo o tamanho, não só a existência."""
        return tuple(
            arquivo
            for arquivo in self.arquivos
            if not (self.destino / arquivo.nome).exists()
            or (self.destino / arquivo.nome).stat().st_size != arquivo.bytes
        )

    @property
    def completa(self) -> bool:
        return not self.falta()

    def frase(self) -> str:
        """O que o dono lê antes de autorizar: o que é, quanto pesa e onde vai parar."""
        if self.completa:
            return f"{self.id} já está em {self.destino}"
        faltando = self.falta()
        soma = sum(a.bytes for a in faltando) / 1_000_000
        return (
            f"{self.id} ({self.licenca}) precisa de {len(faltando)} arquivo(s), {soma:.1f} MB "
            f"no total, baixados para {self.destino}"
        )


def _descarga(bruto: Mapping[str, Any], pasta: Path) -> Descarga | None:
    base = str(bruto.get("baixar_de", "")).strip()
    arquivos = bruto.get("arquivo") or []
    if not base or not arquivos:
        return None
    for arquivo in arquivos:
        partes = Path(str(arquivo["nome"])).parts
        if not partes or Path(str(arquivo["nome"])).is_absolute() or ".." in partes:
            raise ValueError(f"nome de arquivo fora da pasta do modelo: {arquivo['nome']!r}")
    return Descarga(
        id=str(bruto["id"]),
        papel=str(bruto.get("papel", "")),
        licenca=str(bruto.get("licenca", "")),
        destino=pasta / str(bruto.get("destino", "")).strip("/"),
        arquivos=tuple(
            ArquivoDeModelo(
                nome=str(arquivo["nome"]),
                bytes=int(arquivo["bytes"]),
                sha256=str(arquivo["sha256"]),
                url=base.rstrip("/") + "/" + str(arquivo["nome"]),
            )
            for arquivo in arquivos
        ),
    )


def descargas(
    *, arquivo: Path = ARQUIVO_MODELOS, pasta: Path | None = None
) -> tuple[Descarga, ...]:
    """Tudo o que o registro declara como baixável. Modelo sem `baixar_de` fica de fora."""
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    base = pasta or PASTA_PADRAO
    achadas = (_descarga(modelo, base) for modelo in dados.get("modelo", []))
    return tuple(descarga for descarga in achadas if descarga is not None)


def descarga_da_voz(
    voz: str, *, arquivo: Path = ARQUIVO_MODELOS, pasta: Path | None = None
) -> Descarga | None:
    """A descarga da voz escolhida na configuração (`pt_BR-faber-medium`, por exemplo)."""
    return next((d for d in descargas(arquivo=arquivo, pasta=pasta) if d.id.endswith(voz)), None)


def baixar(
    descarga: Descarga,
    *,
    ao_progresso: Callable[[str, int, int], None] | None = None,
    ambiente: Mapping[str, str] | None = None,
) -> list[Path]:
    """Baixa o que falta, conferindo tamanho e sha256 **enquanto** escreve.

    `ao_progresso` recebe (nome, bytes lidos, bytes totais) — é o que move a barra na janela
    sem a janela saber o que é um pedaço de 1 MB.
    """
    escritos: list[Path] = []
    descarga.destino.mkdir(parents=True, exist_ok=True)
    for arquivo in descarga.falta():
        proibir_nuvem_real_em_ci(arquivo.url, ambiente)
        destino = descarga.destino / arquivo.nome
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_suffix(destino.suffix + ".parcial")
        resumo = hashlib.sha256()
        lidos = 0
        try:
            with (
                urllib.request.urlopen(arquivo.url, timeout=PRAZO_S) as resposta,  # noqa: S310
                parcial.open("wb") as saida,
            ):
                while pedaco := resposta.read(PEDACO):
                    if lidos + len(pedaco) > arquivo.bytes:
                        raise ModeloRecusado(
                            f"{arquivo.nome}: o servidor mandou mais do que os "
                            f"{arquivo.bytes} bytes declarados no registro"
                        )
                    saida.write(pedaco)
                    resumo.update(pedaco)
                    lidos += len(pedaco)
                    if ao_progresso is not None:
                        ao_progresso(arquivo.nome, lidos, arquivo.bytes)
        except OSError as erro:
            parcial.unlink(missing_ok=True)
            raise ErroDeRede(f"não deu para baixar {arquivo.nome}: {erro}") from None
        except ModeloRecusado:
            parcial.unlink(missing_ok=True)
            raise
        if lidos != arquivo.bytes or resumo.hexdigest() != arquivo.sha256:
            parcial.unlink(missing_ok=True)
            raise ModeloRecusado(
                f"{arquivo.nome} não confere com o registro: vieram {lidos} bytes "
                f"(sha256 {resumo.hexdigest()[:12]}…) e o esperado eram {arquivo.bytes} bytes "
                f"(sha256 {arquivo.sha256[:12]}…). O arquivo foi apagado"
            )
        parcial.replace(destino)
        escritos.append(destino)
    return escritos
