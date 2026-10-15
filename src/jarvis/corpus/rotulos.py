"""Rótulo de pausa do corpus de turnos: formato fechado e verificado (cartão F1-02).

Duas coisas não podem ser confundidas nunca: **pausa sintética** (voz de máquina, gerada por
nós) e **pausa real** (voz consentida, gravada pelo dono). Então o rótulo é um vocabulário
fechado, como o barramento: chave desconhecida é **recusada**, não ignorada, e cada lado tem
obrigações próprias.

- sintético: `"sintetico": true` + `semente`, `gerador`, `voz`, `licenca_voz`; **sem** `termo`
  (não se inventa consentimento para voz de máquina), e `falante` é `"sintetico"`;
- real: `termo` (identificador do termo assinado) e **nenhum** campo de geração.

O `split` 70/30 é decidido **na criação** (regra 5 de `corpus/README.md`). No sintético isso é
verificável: o split sai de uma função do par (semente, conjunto de ids), então um split
atribuído depois — ou escolhido a dedo na hora de medir — não bate e é recusado.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

FRACAO_CALIBRACAO: Final = 0.7
SPLITS: Final[frozenset[str]] = frozenset({"calibracao", "retido"})
FALANTE_SINTETICO: Final = "sintetico"

CHAVES_OBRIGATORIAS: Final[frozenset[str]] = frozenset(
    {"id", "arquivo", "sha256", "falante", "pausa_ms", "fim_de_turno", "texto", "split"}
)
CHAVES_OPCIONAIS: Final[frozenset[str]] = frozenset({"contexto"})
CHAVES_SO_SINTETICAS: Final[frozenset[str]] = frozenset(
    {"sintetico", "semente", "gerador", "voz", "licenca_voz", "texto_antes", "texto_depois"}
)
"""`texto_antes` e `texto_depois` são o que o item diz **antes** e **depois** da pausa.

Sem eles a pausa não teria posição no texto, e regenerar o áudio a partir do rótulo (o
`--verificar` do gerador) seria adivinhação. A invariante é dura e está em teste: pausa de
fim de turno **não tem** continuação; pausa no meio da frase **tem**."""
CHAVES_SO_REAIS: Final[frozenset[str]] = frozenset({"termo"})
CHAVES_CONHECIDAS: Final[frozenset[str]] = (
    CHAVES_OBRIGATORIAS | CHAVES_OPCIONAIS | CHAVES_SO_SINTETICAS | CHAVES_SO_REAIS
)


class ErroDeRotulo(ValueError):
    """Rótulo recusado. A mensagem diz o id (ou a linha) e o que estava errado."""


@dataclass(frozen=True, slots=True)
class Rotulo:
    """Uma pausa rotulada do corpus."""

    id: str
    arquivo: str
    sha256: str
    falante: str
    pausa_ms: int
    fim_de_turno: bool
    texto: str
    split: str
    contexto: str = ""
    sintetico: bool = False
    semente: int | None = None
    gerador: str = ""
    voz: str = ""
    licenca_voz: str = ""
    texto_antes: str = ""
    texto_depois: str = ""
    termo: str = ""

    def para_dict(self) -> dict[str, Any]:
        bruto: dict[str, Any] = {
            "id": self.id,
            "arquivo": self.arquivo,
            "sha256": self.sha256,
            "falante": self.falante,
            "pausa_ms": self.pausa_ms,
            "fim_de_turno": self.fim_de_turno,
            "texto": self.texto,
            "split": self.split,
        }
        if self.contexto:
            bruto["contexto"] = self.contexto
        if self.sintetico:
            bruto["sintetico"] = True
            bruto["semente"] = self.semente
            bruto["gerador"] = self.gerador
            bruto["voz"] = self.voz
            bruto["licenca_voz"] = self.licenca_voz
            bruto["texto_antes"] = self.texto_antes
            if self.texto_depois:
                bruto["texto_depois"] = self.texto_depois
        if self.termo:
            bruto["termo"] = self.termo
        return bruto


def _parece_sintetico(bruto: Mapping[str, Any]) -> bool:
    """Marcas de geração: se alguma aparece, o item tem de se declarar sintético."""
    return bool(CHAVES_SO_SINTETICAS & set(bruto)) or str(bruto.get("id", "")).startswith("s-")


def validar_rotulo(bruto: Mapping[str, Any], *, onde: str = "") -> Rotulo:
    """Valida um rótulo cru. Levanta `ErroDeRotulo` com o motivo — nunca corrige em silêncio."""
    lugar = onde or f"id={bruto.get('id', '?')!r}"
    desconhecidas = set(bruto) - CHAVES_CONHECIDAS
    if desconhecidas:
        raise ErroDeRotulo(f"{lugar}: chave(s) desconhecida(s): {', '.join(sorted(desconhecidas))}")
    faltando = CHAVES_OBRIGATORIAS - set(bruto)
    if faltando:
        raise ErroDeRotulo(f"{lugar}: falta(m) {', '.join(sorted(faltando))}")

    split = str(bruto["split"])
    if split not in SPLITS:
        raise ErroDeRotulo(f"{lugar}: split {split!r} não é 'calibracao' nem 'retido'")
    if not isinstance(bruto["fim_de_turno"], bool):
        raise ErroDeRotulo(f"{lugar}: fim_de_turno tem de ser booleano")
    pausa = bruto["pausa_ms"]
    if not isinstance(pausa, int) or isinstance(pausa, bool) or pausa <= 0:
        raise ErroDeRotulo(f"{lugar}: pausa_ms tem de ser inteiro positivo, veio {pausa!r}")
    if not str(bruto["texto"]).strip():
        raise ErroDeRotulo(f"{lugar}: texto vazio (transcrição é obrigatória)")
    arquivo = str(bruto["arquivo"])
    if not arquivo.startswith("audio/"):
        raise ErroDeRotulo(f"{lugar}: arquivo {arquivo!r} tem de estar em audio/")
    if len(str(bruto["sha256"])) != 64:
        raise ErroDeRotulo(f"{lugar}: sha256 não tem 64 hexadecimais")

    sintetico = bool(bruto.get("sintetico", False))
    if _parece_sintetico(bruto) and not sintetico:
        raise ErroDeRotulo(
            f"{lugar}: item tem marca de geração (id 's-…', semente, gerador ou voz) e não "
            "se declara 'sintetico': true — sintético e real nunca se misturam por omissão"
        )
    if sintetico:
        faltando_sintetico = {
            "semente",
            "gerador",
            "voz",
            "licenca_voz",
            "texto_antes",
        } - set(bruto)
        if faltando_sintetico:
            raise ErroDeRotulo(
                f"{lugar}: item sintético sem {', '.join(sorted(faltando_sintetico))}"
            )
        if "termo" in bruto:
            raise ErroDeRotulo(
                f"{lugar}: item sintético com 'termo' — não se inventa consentimento para voz "
                "de máquina"
            )
        if str(bruto["falante"]) != FALANTE_SINTETICO:
            raise ErroDeRotulo(
                f"{lugar}: item sintético com falante {bruto['falante']!r}; use "
                f"{FALANTE_SINTETICO!r}"
            )
        if not isinstance(bruto["semente"], int) or isinstance(bruto["semente"], bool):
            raise ErroDeRotulo(f"{lugar}: semente tem de ser inteiro")
        antes = str(bruto["texto_antes"]).strip()
        depois = str(bruto.get("texto_depois", "")).strip()
        if bool(bruto["fim_de_turno"]) and depois:
            raise ErroDeRotulo(
                f"{lugar}: pausa de fim de turno com 'texto_depois' — se o dono continuou "
                "falando, não era fim de turno"
            )
        if not bool(bruto["fim_de_turno"]) and not depois:
            raise ErroDeRotulo(
                f"{lugar}: pausa no meio da frase sem 'texto_depois' — é a continuação que "
                "faz dela um falso corte em potencial"
            )
        esperado_texto = f"{antes} {depois}".strip()
        if str(bruto["texto"]).strip() != esperado_texto:
            raise ErroDeRotulo(
                f"{lugar}: texto não é a junção de texto_antes e texto_depois ({esperado_texto!r})"
            )
    else:
        if not str(bruto.get("termo", "")).strip():
            raise ErroDeRotulo(
                f"{lugar}: item real sem 'termo' — voz de pessoa só entra com consentimento "
                "(corpus/CONSENTIMENTO.md)"
            )

    return Rotulo(
        id=str(bruto["id"]),
        arquivo=arquivo,
        sha256=str(bruto["sha256"]),
        falante=str(bruto["falante"]),
        pausa_ms=pausa,
        fim_de_turno=bool(bruto["fim_de_turno"]),
        texto=str(bruto["texto"]),
        split=split,
        contexto=str(bruto.get("contexto", "")),
        sintetico=sintetico,
        semente=int(bruto["semente"]) if sintetico else None,
        gerador=str(bruto.get("gerador", "")),
        voz=str(bruto.get("voz", "")),
        licenca_voz=str(bruto.get("licenca_voz", "")),
        texto_antes=str(bruto.get("texto_antes", "")),
        texto_depois=str(bruto.get("texto_depois", "")),
        termo=str(bruto.get("termo", "")),
    )


def split_canonico(ids: Iterable[str], semente: int) -> dict[str, str]:
    """O 70/30 que a criação tem de ter produzido, dado o par (semente, conjunto de ids).

    Ordena os ids por `sha256(semente:id)` e corta em 70%. É determinístico, não depende da
    ordem do arquivo e **não** depende de sorteio na hora de medir — que é exatamente o que a
    regra 5 do corpus proíbe.
    """
    ordenados = sorted(ids, key=lambda i: hashlib.sha256(f"{semente}:{i}".encode()).hexdigest())
    corte = round(FRACAO_CALIBRACAO * len(ordenados))
    return {
        identificador: ("calibracao" if posicao < corte else "retido")
        for posicao, identificador in enumerate(ordenados)
    }


def conferir_split(rotulos: Sequence[Rotulo]) -> list[str]:
    """Divergências entre o split gravado e o canônico (só para itens sintéticos)."""
    problemas: list[str] = []
    por_semente: dict[int, list[Rotulo]] = {}
    for rotulo in rotulos:
        if rotulo.sintetico and rotulo.semente is not None:
            por_semente.setdefault(rotulo.semente, []).append(rotulo)
    for semente, grupo in sorted(por_semente.items()):
        esperado = split_canonico((r.id for r in grupo), semente)
        problemas += [
            f"{r.id}: split {r.split!r} não é o da criação ({esperado[r.id]!r}) — "
            "split não se escolhe na hora de medir"
            for r in grupo
            if r.split != esperado[r.id]
        ]
    return problemas


def ler_rotulos(caminho: Path) -> list[Rotulo]:
    """Lê o JSONL inteiro, recusando na primeira linha inválida (com o número da linha)."""
    rotulos: list[Rotulo] = []
    texto = caminho.read_text(encoding="utf-8")
    for numero, linha in enumerate(texto.splitlines(), start=1):
        if not linha.strip():
            continue
        try:
            bruto = json.loads(linha)
        except json.JSONDecodeError as erro:
            raise ErroDeRotulo(f"{caminho.name}:{numero}: JSON inválido ({erro})") from erro
        rotulos.append(validar_rotulo(bruto, onde=f"{caminho.name}:{numero}"))
    return rotulos


def escrever_rotulos(caminho: Path, rotulos: Sequence[Rotulo]) -> None:
    linhas = [
        json.dumps(rotulo.para_dict(), ensure_ascii=False, sort_keys=True) for rotulo in rotulos
    ]
    caminho.write_text("\n".join(linhas) + ("\n" if linhas else ""), encoding="utf-8")


def validar_arquivo(
    caminho: Path, *, conferir_audio: bool = True
) -> tuple[list[Rotulo], list[str]]:
    """Rótulos e problemas do arquivo: ids repetidos, split fora da criação, áudio divergente.

    O áudio **não precisa existir** (ele é derivado e fica fora do repositório); mas se
    existir, o `sha256` do rótulo tem de bater — é o que impede medir hoje com um arquivo e
    comparar amanhã com outro.
    """
    rotulos = ler_rotulos(caminho)
    problemas: list[str] = []

    vistos: dict[str, int] = {}
    for rotulo in rotulos:
        vistos[rotulo.id] = vistos.get(rotulo.id, 0) + 1
    problemas += [f"id repetido: {i} ({n}×)" for i, n in sorted(vistos.items()) if n > 1]

    problemas += conferir_split(rotulos)

    if conferir_audio:
        for rotulo in rotulos:
            audio = caminho.parent / rotulo.arquivo
            if not audio.exists():
                continue
            digest = hashlib.sha256(audio.read_bytes()).hexdigest()
            if digest != rotulo.sha256:
                problemas.append(
                    f"{rotulo.id}: {rotulo.arquivo} mudou "
                    f"(sha256 {rotulo.sha256[:12]}… → {digest[:12]}…)"
                )
    return rotulos, problemas


def contagem(rotulos: Sequence[Rotulo]) -> dict[str, int]:
    """Contagem **separada** de sintético e real — média misturada não é número (F1 §regras)."""
    numeros = {
        "sintetico": sum(1 for r in rotulos if r.sintetico),
        "real": sum(1 for r in rotulos if not r.sintetico),
        "sintetico/fim_de_turno": sum(1 for r in rotulos if r.sintetico and r.fim_de_turno),
        "sintetico/meio_de_frase": sum(1 for r in rotulos if r.sintetico and not r.fim_de_turno),
        "real/fim_de_turno": sum(1 for r in rotulos if not r.sintetico and r.fim_de_turno),
        "real/meio_de_frase": sum(1 for r in rotulos if not r.sintetico and not r.fim_de_turno),
    }
    for split in sorted(SPLITS):
        numeros[f"split/{split}"] = sum(1 for r in rotulos if r.split == split)
    return numeros
