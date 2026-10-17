"""O lado do TTS do stream: `ResponseChunk` do epoch corrente → síntese → fila (ADR-0025, regra 10).

O cérebro corta o texto na fronteira; aqui cada pedaço vira um trecho do
`SintetizadorEmStreaming`, que já sabe parar no cancelamento e descartar o pedaço em voo. O que
este módulo acrescenta é só a montagem dos trechos a partir dos eventos:

- pedaço de **outro epoch** ou de **outra resposta** é ignorado (§3.3 regra 6; a borda do
  barramento já descarta o epoch velho, e isto é a segunda trava, local);
- `seq` fora de ordem é **defeito**, não ruído: levanta, em vez de falar frase embaralhada;
- o texto da `Fala` é a junção dos pedaços com um espaço — é contra ele que `texto_ate` mede o
  tocado, e é esse tocado que volta ao cérebro por `Cerebro.ouvido`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

from jarvis.agentd.tts import Fala, SintetizadorEmStreaming, Trecho
from jarvis.audio_io.playback import Pedaco


class StreamForaDeOrdem(RuntimeError):
    """Pedaço com `seq` diferente do esperado: o stream perdeu ou trocou um pedaço."""


def trechos_do_stream(
    pedacos: Iterable[Mapping[str, Any]], *, epoch: int, response_id: str | None = None
) -> Iterator[tuple[int, str]]:
    """`(inicio_no_texto, texto)` dos pedaços da resposta, até o `last`."""
    esperado = 0
    posicao = 0
    resposta = response_id
    for pedaco in pedacos:
        if int(pedaco["epoch"]) != epoch:
            continue
        if resposta is None:
            resposta = str(pedaco["response_id"])
        elif pedaco["response_id"] != resposta:
            continue
        if int(pedaco["seq"]) != esperado:
            raise StreamForaDeOrdem(f"esperava seq {esperado}, veio {pedaco['seq']}")
        esperado += 1
        texto = str(pedaco["text"])
        if texto:
            yield posicao, texto
            posicao += len(texto) + 1
        if pedaco["last"]:
            return


def falar_stream_para(
    sintetizador: SintetizadorEmStreaming,
    pedacos: Iterable[Mapping[str, Any]],
    enfileirar: Callable[[Pedaco], bool],
    *,
    chunk_id: str = "tts",
) -> Fala:
    """Sintetiza o stream e entrega ao playback, como `falar_para` faz com o texto inteiro."""
    sintetizados: list[Pedaco] = []
    trechos: list[Trecho] = []
    textos: list[str] = []
    recusados = 0
    stream = trechos_do_stream(pedacos, epoch=sintetizador.epoch)
    for pedaco, trecho in sintetizador.pedacos_do_stream(
        _anotando(stream, textos), chunk_id=chunk_id
    ):
        if not enfileirar(pedaco):
            recusados += 1
            continue
        sintetizados.append(pedaco)
        trechos.append(trecho)
    return Fala(
        texto=" ".join(textos),
        pedacos=tuple(sintetizados),
        trechos=tuple(trechos),
        cancelada_em=len(sintetizados) if (sintetizador.cancelado() or recusados) else None,
    )


def _anotando(trechos: Iterator[tuple[int, str]], textos: list[str]) -> Iterator[tuple[int, str]]:
    for inicio, texto in trechos:
        textos.append(texto)
        yield inicio, texto


def avisos_tocados(
    pedacos: Iterable[Mapping[str, Any]], fala: Fala, amostras_tocadas: int, *, epoch: int
) -> tuple[set[str], set[str]]:
    """Quais avisos **tocaram inteiros** e quais foram cortados (ADR-0025, regra 15, P4).

    Um aviso é entregue quando todo pedaço que o carrega (`notif_ids`) saiu inteiro pelo
    alto-falante; qualquer pedaço dele cortado ou não sintetizado devolve o aviso para a fila.
    Os pedaços com texto, na ordem, casam um a um com os trechos da `Fala`.
    """
    por_aviso: dict[str, bool] = {}
    indice = 0
    for pedaco in pedacos:
        if int(pedaco["epoch"]) != epoch or not pedaco["text"]:
            continue
        tocou = indice < len(fala.trechos) and (
            fala.trechos[indice].fim_em_amostras <= amostras_tocadas
        )
        for notif_id in pedaco.get("notif_ids", ()):
            por_aviso[str(notif_id)] = por_aviso.get(str(notif_id), True) and tocou
        indice += 1
    tocados = {n for n, ok in por_aviso.items() if ok}
    return tocados, set(por_aviso) - tocados
