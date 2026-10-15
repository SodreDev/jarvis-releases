"""Gerador do corpus sintético de turno (cartão F1-02).
Corpus sintético de turno: ≥ 500 pausas rotuladas, sem esperar o microfone (cartão F1-02).

    # gera o corpus comitado (voz de verdade; precisa do .onnx da voz e do espeak-ng)
    uv run --frozen python tools/corpus_sintetico.py --n 500 --semente 20261015 \
        --gerador piper --saida corpus/turnos

    # encanamento sem modelo nenhum (é o que o CI exercita)
    uv run --frozen python tools/corpus_sintetico.py --n 12 --gerador parametrico --saida /tmp/x

    # regenera a partir dos rótulos e compara sha256 (determinismo, aceite (c))
    uv run --frozen python tools/corpus_sintetico.py --verificar --saida corpus/turnos

**Para que serve e para que não serve.** Serve para desenvolver sem o dono, pegar regressão no
CI e **ordenar** candidatos de detector. **Não fecha SLO-4 nem SLO-9** (docs/F1-tarefas.md, "Por
que sintético não fecha o SLO-4"): a pausa aqui é a que nós sorteamos, e prosódia de TTS é mais
limpa do que a humana. Todo item sai com `"sintetico": true`; média que mistura sintético e real
é recusada na revisão.

**O prefixo é ambíguo de propósito.** Cada enunciado completo ("abre a pasta de fotos") aparece
também como prefixo de um enunciado maior ("abre a pasta de fotos / na área de trabalho"), com a
pausa no meio. Assim o detector não consegue acertar só pela escolha das palavras: o mesmo
começo, com a mesma pausa possível, é fim de turno em um item e falso corte em outro.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Final

from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.audio_io.sintese import (
    aplicar_ganho_db,
    eco,
    misturar,
    ruido_rosa,
    silencio,
)
from jarvis.audio_io.sumidouros import SumidouroDeArquivo
from jarvis.corpus.rotulos import Rotulo, escrever_rotulos, ler_rotulos, split_canonico
from jarvis.corpus.voz import Voz

SEMENTE_PADRAO: Final = 20_261_015

FAIXA_PAUSA_FIM_MS: Final = (300, 900)
"""Pausa de fim de turno. Faixa declarada: é a que **nós** escolhemos, não a humana."""
FAIXA_PAUSA_MEIO_MS: Final = (200, 1200)
"""Hesitação no meio da frase — sobrepõe a faixa de cima **de propósito**: é o caso difícil."""
FAIXA_SILENCIO_INICIAL_MS: Final = (120, 280)
SILENCIO_FINAL_MS: Final = 200
FRACAO_RUIDO_PADRAO: Final = 0.3
FRACAO_ECO_PADRAO: Final = 0.1
GANHO_RUIDO_DB: Final = -12.0
ATRASO_ECO_MS: Final = 120.0
GANHO_ECO_DB: Final = -18.0


@dataclass(frozen=True, slots=True)
class Dominio:
    """Um pedaço do uso do v1 (SPEC §1, Q3: calendário só em rascunho)."""

    nome: str
    verbos: tuple[str, ...]
    objetos: tuple[str, ...]
    complementos: tuple[str, ...]

    def prefixos(self) -> list[str]:
        return [f"{verbo} {objeto}" for verbo in self.verbos for objeto in self.objetos]


DOMINIOS: Final[tuple[Dominio, ...]] = (
    Dominio(
        nome="arquivos",
        verbos=("abre", "fecha", "renomeia", "duplica", "compacta"),
        objetos=(
            "a pasta de fotos",
            "o documento do aluguel",
            "a planilha do mês",
            "a nota da reunião",
            "o recibo da farmácia",
            "a apresentação do curso",
        ),
        complementos=(
            "na área de trabalho",
            "que está no pendrive",
            "da pasta de downloads",
            "do ano passado",
            "antes de eu sair",
        ),
    ),
    Dominio(
        nome="midia",
        verbos=("toca", "pausa", "abaixa", "adianta", "repete"),
        objetos=(
            "a playlist de domingo",
            "o podcast da manhã",
            "o vídeo da aula",
            "a rádio da cozinha",
            "a música que eu salvei",
            "o episódio novo",
        ),
        complementos=(
            "na caixa de som da sala",
            "sem perder o lugar",
            "só até eu voltar",
            "no volume de ontem",
            "quando o café ficar pronto",
        ),
    ),
    Dominio(
        nome="calendario",
        verbos=("marca", "adia", "confirma", "cancela", "lembra"),
        objetos=(
            "a consulta do dentista",
            "a reunião de quinta",
            "o aniversário da minha mãe",
            "a entrega do relatório",
            "o jogo do fim de semana",
            "a renovação do contrato",
        ),
        complementos=(
            "para a semana que vem",
            "no fim da tarde",
            "junto com o aviso do carro",
            "antes do almoço",
            "e me avisa uma hora antes",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class Item:
    """O plano de um item, antes de existir áudio."""

    indice: int
    identificador: str
    dominio: str
    texto_antes: str
    texto_depois: str
    fim_de_turno: bool
    pausa_ms: int
    com_ruido: bool
    com_eco: bool

    @property
    def texto(self) -> str:
        return f"{self.texto_antes} {self.texto_depois}".strip()

    @property
    def contexto(self) -> str:
        partes = [
            "pedido completo, pausa no fim" if self.fim_de_turno else "hesitação no meio da frase",
            f"domínio {self.dominio}",
        ]
        if self.com_ruido:
            partes.append(f"ruído rosa a {GANHO_RUIDO_DB:.0f} dB")
        if self.com_eco:
            partes.append(f"eco do nosso TTS a {GANHO_ECO_DB:.0f} dB e {ATRASO_ECO_MS:.0f} ms")
        return "; ".join(partes)


def semente_do_item(semente: int, identificador: str) -> int:
    """Semente própria de cada item, derivada do id: regenerar um item não exige os outros."""
    digest = hashlib.sha256(f"{semente}:{identificador}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def planejar(
    n: int,
    *,
    semente: int,
    fracao_ruido: float = FRACAO_RUIDO_PADRAO,
    fracao_eco: float = FRACAO_ECO_PADRAO,
) -> list[Item]:
    """Plano determinístico de `n` itens, metade fim de turno e metade meio de frase.

    50/50 é escolha declarada: a proporção humana de verdade só sai do corpus real (F1-15), e
    um conjunto equilibrado deixa falso corte e atraso serem estimados com a mesma precisão —
    e impede um detector de ganhar pontos respondendo sempre a classe majoritária.
    """
    if n < 2:
        raise ValueError("n tem de ser pelo menos 2 (um de cada classe)")
    sorteio = Random(semente)  # noqa: S311 — plano de corpus, não segredo

    completos: list[tuple[str, str]] = []
    com_continuacao: list[tuple[str, str, str]] = []
    for dominio in DOMINIOS:
        for prefixo in dominio.prefixos():
            completos.append((dominio.nome, prefixo))
            com_continuacao += [
                (dominio.nome, prefixo, complemento) for complemento in dominio.complementos
            ]
    sorteio.shuffle(completos)
    sorteio.shuffle(com_continuacao)

    metade = n // 2
    itens: list[Item] = []
    for posicao in range(n):
        fim_de_turno = posicao < metade
        identificador = f"s-{posicao + 1:04d}"
        propria = Random(semente_do_item(semente, identificador))  # noqa: S311
        if fim_de_turno:
            nome_dominio, antes = completos[posicao % len(completos)]
            depois = ""
            faixa = FAIXA_PAUSA_FIM_MS
        else:
            nome_dominio, antes, depois = com_continuacao[(posicao - metade) % len(com_continuacao)]
            faixa = FAIXA_PAUSA_MEIO_MS
        itens.append(
            Item(
                indice=posicao,
                identificador=identificador,
                dominio=nome_dominio,
                texto_antes=antes,
                texto_depois=depois,
                fim_de_turno=fim_de_turno,
                pausa_ms=propria.randint(*faixa),
                com_ruido=propria.random() < fracao_ruido,
                com_eco=propria.random() < fracao_eco,
            )
        )
    return itens


def montar_audio(item: Item, voz: Voz, *, semente: int) -> bytes:
    """Áudio do item: silêncio, fala, a pausa medida e (se houver) a continuação."""
    propria = Random(semente_do_item(semente, item.identificador) ^ 0x5F5F)  # noqa: S311
    inicio = propria.randint(*FAIXA_SILENCIO_INICIAL_MS)
    partes = [
        silencio(inicio, taxa=TAXA_PADRAO),
        voz.falar(item.texto_antes, semente=semente_do_item(semente, item.identificador)),
        silencio(item.pausa_ms, taxa=TAXA_PADRAO),
    ]
    if item.texto_depois:
        partes.append(
            voz.falar(
                item.texto_depois,
                semente=semente_do_item(semente, f"{item.identificador}:depois"),
            )
        )
        partes.append(silencio(SILENCIO_FINAL_MS, taxa=TAXA_PADRAO))
    sinal = b"".join(partes)

    if item.com_ruido:
        duracao_ms = len(sinal) / 2 / TAXA_PADRAO * 1000.0
        sinal = misturar(
            sinal,
            aplicar_ganho_db(
                ruido_rosa(duracao_ms, aleatorio=propria, taxa=TAXA_PADRAO), GANHO_RUIDO_DB
            ),
        )
    if item.com_eco:
        atrasado = eco(sinal, atraso_ms=ATRASO_ECO_MS, ganho_db=GANHO_ECO_DB, taxa=TAXA_PADRAO)[
            : len(sinal)
        ]
        sinal = misturar(sinal, atrasado)
    return sinal


def escrever_audio(caminho: Path, amostras: bytes) -> str:
    """Grava o WAV pelo sumidouro do F1-01 e devolve o sha256 do arquivo."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    sumidouro = SumidouroDeArquivo(caminho=caminho)
    sumidouro.abrir()
    try:
        sumidouro.escrever(amostras)
    finally:
        sumidouro.fechar()
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def gerar_corpus(
    n: int,
    *,
    semente: int,
    pasta: Path,
    voz: Voz,
    fracao_ruido: float = FRACAO_RUIDO_PADRAO,
    fracao_eco: float = FRACAO_ECO_PADRAO,
) -> list[Rotulo]:
    """Gera áudio e rótulos. O `split` 70/30 é decidido **aqui**, na criação."""
    itens = planejar(n, semente=semente, fracao_ruido=fracao_ruido, fracao_eco=fracao_eco)
    splits = split_canonico((item.identificador for item in itens), semente)

    rotulos: list[Rotulo] = []
    for item in itens:
        amostras = montar_audio(item, voz, semente=semente)
        relativo = f"audio/{item.identificador}.wav"
        digest = escrever_audio(pasta / relativo, amostras)
        rotulos.append(
            Rotulo(
                id=item.identificador,
                arquivo=relativo,
                sha256=digest,
                falante="sintetico",
                pausa_ms=item.pausa_ms,
                fim_de_turno=item.fim_de_turno,
                texto=item.texto,
                split=splits[item.identificador],
                contexto=item.contexto,
                sintetico=True,
                semente=semente,
                gerador=voz.nome,
                voz=voz.voz,
                licenca_voz=voz.licenca,
                texto_antes=item.texto_antes,
                texto_depois=item.texto_depois,
            )
        )
    escrever_rotulos(pasta / "rotulos.jsonl", rotulos)
    return rotulos


def regenerar_e_comparar(pasta: Path, *, voz: Voz, amostra: int | None = None) -> list[str]:
    """Aceite (c): regenera o áudio **a partir do rótulo** e compara o sha256.

    Nada de adivinhação: o rótulo carrega semente, texto antes e depois da pausa, duração da
    pausa e o id (que é a semente do item). Se o gerador mudar de comportamento, isto acusa.
    """
    rotulos = ler_rotulos(pasta / "rotulos.jsonl")
    sinteticos = [r for r in rotulos if r.sintetico]
    alvo = sinteticos[:amostra] if amostra is not None else sinteticos
    problemas: list[str] = []
    with tempfile.TemporaryDirectory(prefix="jarvis-corpus-") as temporario:
        for rotulo in alvo:
            if rotulo.gerador.split("@")[0] != voz.nome.split("@")[0]:
                problemas.append(
                    f"{rotulo.id}: rótulo diz gerador {rotulo.gerador!r} e a verificação está "
                    f"rodando {voz.nome!r}"
                )
                continue
            assert rotulo.semente is not None
            item = Item(
                indice=0,
                identificador=rotulo.id,
                dominio="",
                texto_antes=rotulo.texto_antes,
                texto_depois=rotulo.texto_depois,
                fim_de_turno=rotulo.fim_de_turno,
                pausa_ms=rotulo.pausa_ms,
                com_ruido=f"{GANHO_RUIDO_DB:.0f} dB" in rotulo.contexto,
                com_eco="eco do nosso TTS" in rotulo.contexto,
            )
            amostras = montar_audio(item, voz, semente=rotulo.semente)
            digest = escrever_audio(Path(temporario) / f"{rotulo.id}.wav", amostras)
            if digest != rotulo.sha256:
                problemas.append(
                    f"{rotulo.id}: regerado com sha256 {digest[:12]}…, rótulo diz "
                    f"{rotulo.sha256[:12]}…"
                )
    return problemas
