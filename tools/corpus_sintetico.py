"""Linha de comando do corpus sintético de turno (cartão F1-02).

    # gera o corpus comitado (voz de verdade; precisa do .onnx da voz e do espeak-ng)
    uv run --frozen python tools/corpus_sintetico.py --n 500 --semente 20261015 \
        --gerador piper --saida corpus/turnos

    # encanamento sem modelo nenhum (é o que o CI exercita)
    uv run --frozen python tools/corpus_sintetico.py --n 12 --gerador parametrico --saida /tmp/x

    # regenera a partir dos rótulos e compara sha256 (determinismo, aceite (c))
    uv run --frozen python tools/corpus_sintetico.py --verificar --saida corpus/turnos

A lógica do gerador (e os testes dela) está em `jarvis.corpus.sintetico`. Aqui moram a
interface e a **voz piper-ONNX**, porque ela precisa de processo externo (`espeak-ng`, o
fonemizador) e `src/` não gera processo: a proibição de canivete suíço da SPEC §4 é regra do
linter (`S603`) no código de produção, e o corpus não é motivo para abrir exceção nela.

A cadeia de licença da voz e o porquê do determinismo por `noise_scale = 0` estão em
`jarvis.corpus.voz`, que define o protocolo que `VozPiper` cumpre.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from typing import Any, Final

from jarvis.audio_io.quadro import TAXA_PADRAO, de_int16
from jarvis.corpus.rotulos import contagem, validar_arquivo
from jarvis.corpus.sintetico import (
    FRACAO_ECO_PADRAO,
    FRACAO_RUIDO_PADRAO,
    SEMENTE_PADRAO,
    gerar_corpus,
    regenerar_e_comparar,
)
from jarvis.corpus.voz import (
    LICENCA_VOZ_PADRAO,
    PASTA_VOZES_PADRAO,
    RITMO_MAXIMO,
    RITMO_MINIMO,
    URL_VOZ,
    VOZ_PADRAO,
    Voz,
    VozIndisponivel,
    VozParametrica,
    reamostrar,
)

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_PADRAO: Final = RAIZ / "corpus" / "turnos"
ESPEAK: Final = "espeak-ng"
VOZ_ESPEAK: Final = "pt-br"


def fonemizar(texto: str) -> str:
    """IPA do espeak-ng para pt-BR. Processo separado, `argv` explícito, sem shell (SPEC §4)."""
    try:
        concluido = subprocess.run(
            [ESPEAK, "-v", VOZ_ESPEAK, "-q", "--ipa"],
            input=texto,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as erro:
        raise VozIndisponivel(
            f"{ESPEAK} não está instalado: é o fonemizador da geração do corpus "
            "(GPL-3.0, fora do produto — licenses/ferramentas-externas.toml). "
            "No Fedora/Nobara: `sudo dnf install espeak-ng`."
        ) from erro
    # O espeak quebra em linhas nas vírgulas e nos pontos; a frase do corpus é uma só.
    return " ".join(parte.strip() for parte in concluido.stdout.split("\n") if parte.strip())


@dataclass(slots=True)
class VozPiper:
    """Voz de verdade: `.onnx` do piper rodado por `onnxruntime`, fonemas do espeak-ng."""

    pasta: Path = field(default_factory=lambda: PASTA_VOZES_PADRAO / VOZ_PADRAO)
    voz: str = VOZ_PADRAO
    nome: str = "piper-onnx"
    licenca: str = LICENCA_VOZ_PADRAO
    _sessao: Any = field(default=None, repr=False)
    _config: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def caminho_modelo(self) -> Path:
        return self.pasta / f"{self.voz}.onnx"

    def abrir(self) -> None:
        import onnxruntime as ort

        modelo = self.caminho_modelo
        config = modelo.with_suffix(".onnx.json")
        if not modelo.exists() or not config.exists():
            raise VozIndisponivel(
                f"a voz {self.voz} não está em {self.pasta}. Os pesos não são versionados "
                f"(63 MB): baixe os dois arquivos de {URL_VOZ}{self.voz}.onnx "
                f"e {URL_VOZ}{self.voz}.onnx.json para essa pasta."
            )
        self._config = json.loads(config.read_text(encoding="utf-8"))
        self._sessao = ort.InferenceSession(str(modelo), providers=["CPUExecutionProvider"])
        versao = str(self._config.get("piper_version", "?"))
        self.nome = f"piper-onnx@{versao}+{self.voz}"

    def _ids(self, texto: str) -> list[int]:
        mapa: dict[str, list[int]] = self._config["phoneme_id_map"]
        ids = [*mapa["^"], *mapa["_"]]
        desconhecidos: list[str] = []
        for simbolo in fonemizar(texto):
            if simbolo in mapa:
                ids += [*mapa[simbolo], *mapa["_"]]
            else:
                desconhecidos.append(simbolo)
        if desconhecidos:
            raise VozIndisponivel(
                f"fonema fora do inventário da voz {self.voz}: {sorted(set(desconhecidos))} "
                f"(texto: {texto!r}). O corpus usa vocabulário fechado justamente para isto "
                "não acontecer em silêncio."
            )
        return [*ids, *mapa["$"]]

    def falar(self, texto: str, *, semente: int) -> bytes:
        import numpy as np

        if self._sessao is None:
            self.abrir()
        aleatorio = Random(semente)  # noqa: S311 — sorteia ritmo, não segredo
        ritmo = aleatorio.uniform(RITMO_MINIMO, RITMO_MAXIMO)
        ids = self._ids(texto)
        saida = self._sessao.run(
            None,
            {
                "input": np.array([ids], dtype=np.int64),
                "input_lengths": np.array([len(ids)], dtype=np.int64),
                # noise_scale = 0 e noise_w = 0: determinismo por construção (ver docstring).
                "scales": np.array([0.0, ritmo, 0.0], dtype=np.float32),
            },
        )[0].squeeze()
        taxa = int(self._config["audio"]["sample_rate"])
        em_16k = reamostrar(saida.astype(np.float64), de=taxa, para=TAXA_PADRAO)
        inteiros = np.clip(np.rint(em_16k * 32767.0), -32768, 32767).astype(np.int64)
        return de_int16([int(v) for v in inteiros])


def montar_voz(gerador: str, pasta_voz: Path | None) -> Voz:
    """A voz pedida. `parametrico` não precisa de nada; `piper` precisa do .onnx e do espeak."""
    if gerador == "parametrico":
        return VozParametrica()
    voz = VozPiper(pasta=pasta_voz) if pasta_voz is not None else VozPiper()
    voz.abrir()
    return voz


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--n", type=int, default=500, help="quantas pausas (padrão 500)")
    analisa.add_argument("--semente", type=int, default=SEMENTE_PADRAO)
    analisa.add_argument("--saida", type=Path, default=PASTA_PADRAO)
    analisa.add_argument("--gerador", choices=("piper", "parametrico"), default="piper")
    analisa.add_argument(
        "--voz-dir", type=Path, default=None, help="pasta com <voz>.onnx e <voz>.onnx.json"
    )
    analisa.add_argument("--fracao-ruido", type=float, default=FRACAO_RUIDO_PADRAO)
    analisa.add_argument("--fracao-eco", type=float, default=FRACAO_ECO_PADRAO)
    analisa.add_argument(
        "--verificar", action="store_true", help="regenera a partir dos rótulos e compara sha256"
    )
    analisa.add_argument("--amostra", type=int, default=None, help="verifica só os N primeiros")
    args = analisa.parse_args(argv)

    try:
        if args.verificar:
            problemas = regenerar_e_comparar(
                args.saida,
                voz=montar_voz(args.gerador, args.voz_dir),
                amostra=args.amostra,
            )
            for problema in problemas:
                print(f"DIVERGÊNCIA {problema}")
            if problemas:
                print(f"\n{len(problemas)} divergência(s): o gerador não é mais determinístico")
                return 1
            print("regeneração confere com os rótulos")
            return 0

        rotulos = gerar_corpus(
            args.n,
            semente=args.semente,
            pasta=args.saida,
            voz=montar_voz(args.gerador, args.voz_dir),
            fracao_ruido=args.fracao_ruido,
            fracao_eco=args.fracao_eco,
        )
    except VozIndisponivel as erro:
        print(f"FALHOU: {erro}")
        return 2

    _, problemas = validar_arquivo(args.saida / "rotulos.jsonl")
    for problema in problemas:
        print(f"PROBLEMA {problema}")
    if problemas:
        return 1
    for chave, quantos in sorted(contagem(rotulos).items()):
        print(f"{chave}: {quantos}")
    print(f"\n{len(rotulos)} rótulo(s) em {args.saida / 'rotulos.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
