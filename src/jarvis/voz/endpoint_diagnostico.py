"""O teste do endpoint de TTS que o dono roda na máquina dele e manda a saída (ADR-0068).

`jarvis --testar-endpoint [NOME|URL]` (ou `jarvis-voz --testar-endpoint`). Em ordem, e parando só
quando não dá para seguir:

1. **a configuração** — base, caminhos, formato, autenticação (o modo e o NOME da variável; a chave
   aparece só como «definida/ausente», nunca o valor);
2. **resolver** o nome do servidor (o IP que o sistema dá, e quanto levou);
3. **conectar** (TCP) e medir;
4. **o OpenAPI**, se o servidor publicar (`/openapi.json`, como faz o FastAPI): as rotas e os campos
   do corpo da rota de síntese — é o que diz se o molde (`text`, `voice`…) bate;
5. **as vozes e os estilos** que o servidor lista (as rotas comuns, sem supor que existam);
6. **um POST curto** em cada caminho (síntese e stream): status, tipo, bytes, pedaços, latência do
   primeiro byte e do total, a duração do áudio depois de virar PCM16 16 kHz e o pico.

Nada de segredo sai: os cabeçalhos não são impressos, e toda frase de erro passa por `redigir`. O
texto mandado é fixo («Teste de voz do Jarvis.»), não do dono.
"""

from __future__ import annotations

import json
import os
import socket
import time
import wave
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

from jarvis import __version__
from jarvis.voz import endpoint as ep
from jarvis.voz.chaves import Chave, SegredoAusente, redigir
from jarvis.voz.endpoint_catalogo import descobrir
from jarvis.voz.nuvem import CONEXOES, ErroDoServico, ServicoRecusou, proibir_nuvem_real_em_ci

TEXTO_DE_TESTE: Final = "Teste de voz do Jarvis."
DURACAO_PLAUSIVEL_S: Final = (1.0, 3.2)
"""Quanto «Teste de voz do Jarvis.» (23 caracteres) dura falado em pt-BR, com folga para pausa e
estilo calmo: fora disso, o áudio PCM cru está sendo lido numa taxa que não é a dele."""
TAXAS_COMUNS: Final[tuple[int, ...]] = (16000, 22050, 24000, 44100, 48000)
ROTAS_DO_OPENAPI: Final[tuple[str, ...]] = (
    "/openapi.json",
    "/docs/openapi.json",
    "/api/openapi.json",
)


def alvo_do_teste(
    alvo: str, *, nome_configurado: str = "", ambiente: Mapping[str, str] | None = None
) -> ep.Endpoint:
    """`alvo` vazio = o endpoint da configuração; um nome = esse; uma URL = o preset nessa base."""
    texto = alvo.strip()
    if texto.startswith(("http://", "https://")):
        return ep.com_campo(ep.escolher("", ambiente=ambiente), "base", texto)
    return ep.escolher(texto or nome_configurado, ambiente=ambiente)


def _ms(segundos: float) -> str:
    return f"{segundos * 1000:.0f} ms"


def _campos_do_openapi(dados: Mapping[str, Any], caminho: str) -> str:
    """Os campos do corpo JSON do POST em `caminho`, lidos do esquema (com `$ref` de um nível)."""
    rota = (dados.get("paths") or {}).get(caminho) or {}
    corpo = ((rota.get("post") or {}).get("requestBody") or {}).get("content") or {}
    esquema = (corpo.get("application/json") or {}).get("schema") or {}
    referencia = str(esquema.get("$ref", ""))
    if referencia.startswith("#/components/schemas/"):
        nome = referencia.rsplit("/", 1)[-1]
        esquema = ((dados.get("components") or {}).get("schemas") or {}).get(nome) or {}
    propriedades = esquema.get("properties") or {}
    obrigatorios = set(esquema.get("required") or [])
    if not isinstance(propriedades, Mapping) or not propriedades:
        return ""
    partes = []
    for campo, definicao in propriedades.items():
        tipo = definicao.get("type", "?") if isinstance(definicao, Mapping) else "?"
        valores = definicao.get("enum") if isinstance(definicao, Mapping) else None
        extra = f" {valores}" if isinstance(valores, list) and len(valores) <= 8 else ""
        marca = "*" if campo in obrigatorios else ""
        partes.append(f"{campo}{marca}:{tipo}{extra}")
    return ", ".join(partes)


def pasta_das_amostras(ambiente: Mapping[str, str] | None = None) -> Path | None:
    """Onde o teste grava o WAV de amostra: `$XDG_STATE_HOME/jarvis` (padrão
    `~/.local/state/jarvis`). `None` = o ambiente dado não diz onde (a suíte): não grava."""
    fonte = os.environ if ambiente is None else ambiente
    if fonte.get("XDG_STATE_HOME"):
        return Path(fonte["XDG_STATE_HOME"]) / "jarvis"
    if fonte.get("HOME"):
        return Path(fonte["HOME"]) / ".local" / "state" / "jarvis"
    return None


def _gravar_wav(arquivo: Path, pcm16: bytes, *, taxa: int, canais: int = 1) -> Path:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(arquivo), "wb") as saida:
        saida.setnchannels(canais)
        saida.setsampwidth(2)
        saida.setframerate(taxa)
        saida.writeframes(pcm16)
    return arquivo


def taxa_plausivel(bytes_pcm16: int, canais: int) -> list[int]:
    """As taxas comuns em que o PCM cru do teste dura o que a frase dura falada."""
    baixo, alto = DURACAO_PLAUSIVEL_S
    amostras = bytes_pcm16 / 2 / max(1, canais)
    return [t for t in TAXAS_COMUNS if baixo <= amostras / t <= alto]


def diagnosticar(
    endpoint: ep.Endpoint,
    escrever: Callable[[str], None] = print,
    *,
    ambiente: Mapping[str, str] | None = None,
    abrir: Any = CONEXOES,
    voz: str = "",
    estilo: str = "",
    pasta_de_saida: Path | None = None,
) -> int:
    """Imprime o teste e devolve 0 (sintetizou por algum caminho) ou 1."""
    chaves: list[Chave] = []
    proibir_nuvem_real_em_ci(endpoint.base, ambiente)

    def dizer(linha: str) -> None:
        escrever(redigir(linha, chaves))

    dizer(f"jarvis {__version__} — teste do endpoint de TTS")
    dizer(f"endpoint: {endpoint.nome}")
    dizer(
        f"  base: {endpoint.base}  ·  síntese: {endpoint.metodo} {endpoint.caminho}"
        f"  ·  stream: {endpoint.caminho_stream or '(nenhum)'}"
    )
    dizer(
        f"  formato: {endpoint.formato} ({endpoint.taxa} Hz, {endpoint.canais} canal/is) · "
        f"prazo: {endpoint.prazo_s:g} s"
    )
    dizer(f"  corpo: {endpoint.corpo}")
    voz = voz or endpoint.voz
    estilo = estilo or endpoint.estilo
    dizer(f"  voz: {voz or '(padrão do servidor)'} · estilo: {estilo or '(padrão do servidor)'}")
    if endpoint.autenticacao == "nenhuma":
        dizer("  autenticação: nenhuma")
    else:
        origem = Chave.origem(endpoint.variavel_de_ambiente, ambiente=ambiente)
        onde = f" (cabeçalho {endpoint.cabecalho})" if endpoint.autenticacao == "cabecalho" else ""
        estado = f"definida ({origem})" if origem else "AUSENTE"
        dizer(
            f"  autenticação: {endpoint.autenticacao}{onde} · "
            f"{endpoint.variavel_de_ambiente}: {estado}"
        )
    try:
        chave = ep.chave_do(endpoint, ambiente)
    except SegredoAusente:
        dizer("FALHOU: a chave não está no ambiente nem no chaveiro — nada foi enviado")
        return 1
    if chave is not None:
        chaves.append(chave)

    # 2. resolver
    comeco = time.monotonic()
    try:
        enderecos = sorted(
            {str(i[4][0]) for i in socket.getaddrinfo(endpoint.host, endpoint.porta)}
        )
    except OSError as erro:
        dizer(f"resolver {endpoint.host}: FALHOU ({erro})")
        return 1
    dizer(f"resolver {endpoint.host}: {', '.join(enderecos)} em {_ms(time.monotonic() - comeco)}")

    # 3. conectar
    comeco = time.monotonic()
    try:
        with socket.create_connection((endpoint.host, endpoint.porta), timeout=3.0):
            pass
    except OSError as erro:
        dizer(
            f"conectar {endpoint.host}:{endpoint.porta}: FALHOU em "
            f"{_ms(time.monotonic() - comeco)} ({erro}). O servidor está ligado, escutando em "
            "0.0.0.0 (não só 127.0.0.1) e com a porta liberada no firewall da outra máquina?"
        )
        return 1
    dizer(f"conectar {endpoint.host}:{endpoint.porta}: ok em {_ms(time.monotonic() - comeco)}")

    # 4. o OpenAPI
    for rota in ROTAS_DO_OPENAPI:
        try:
            resposta = ep.pedir(
                endpoint,
                rota,
                metodo="GET",
                chave=chave,
                prazo_s=3.0,
                ambiente=ambiente,
                abrir=abrir,
            )
            dados = json.loads(resposta.corpo.decode("utf-8"))
        except (ServicoRecusou, ErroDoServico, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(dados, Mapping) or "paths" not in dados:
            continue
        rotas = sorted((dados.get("paths") or {}).keys())
        dizer(f"openapi em {rota}: {len(rotas)} rota(s): {', '.join(rotas[:20])}")
        for caminho in dict.fromkeys((endpoint.caminho, endpoint.caminho_stream)):
            if caminho:
                campos = _campos_do_openapi(dados, caminho)
                dizer(f"  corpo de {caminho}: {campos or '(o esquema não diz)'}")
        break
    else:
        dizer("openapi: o servidor não publica (tudo bem: o molde do corpo vale como está)")

    # 5. vozes e estilos
    catalogo = descobrir(endpoint, ambiente=ambiente, abrir=abrir)
    dizer(f"vozes/estilos: {catalogo.frase}")
    if catalogo.vozes:
        dizer("  vozes: " + ", ".join(v.id for v in catalogo.vozes[:30]))
    if catalogo.estilos:
        dizer("  estilos: " + ", ".join(catalogo.estilos[:30]))

    # 6. sintetizar
    corpo = ep.montar_corpo(endpoint, texto=TEXTO_DE_TESTE, voz=voz, estilo=estilo)
    # O corpo exato (o texto é o fixo do teste, não do dono): é a prova de que a voz e o estilo
    # escolhidos chegam ao servidor.
    dizer(f"corpo enviado: {corpo.decode('utf-8')}")
    pasta = pasta_de_saida if pasta_de_saida is not None else pasta_das_amostras(ambiente)
    algum = False
    for rotulo, caminho in (("síntese", endpoint.caminho), ("stream", endpoint.caminho_stream)):
        if not caminho:
            continue
        try:
            resposta = ep.pedir(
                endpoint,
                caminho,
                metodo=endpoint.metodo,
                corpo=corpo,
                chave=chave,
                ambiente=ambiente,
                abrir=abrir,
            )
        except (ServicoRecusou, ErroDoServico) as erro:
            dizer(f"{rotulo} {endpoint.metodo} {caminho}: FALHOU — {erro}")
            continue
        linha = (
            f"{rotulo} {endpoint.metodo} {caminho}: {resposta.status} "
            f"{resposta.tipo or '(sem tipo)'}"
            f", {len(resposta.corpo)} bytes em {resposta.pedacos} pedaço(s), 1º byte "
            f"{_ms(resposta.primeiro_byte_s)}, total {_ms(resposta.total_s)}"
        )
        try:
            amostras = ep.para_pcm16(
                resposta.corpo,
                formato=endpoint.formato,
                taxa=endpoint.taxa,
                canais=endpoint.canais,
                tipo=resposta.tipo,
            )
        except (ServicoRecusou, ErroDoServico) as erro:
            dizer(f"{linha}\n  áudio: NÃO DEU — {erro}")
            continue
        duracao = len(amostras) / 2 / 16000
        formato, taxa, canais = ep.formato_lido(
            resposta.corpo, formato=endpoint.formato, taxa=endpoint.taxa, canais=endpoint.canais
        )
        if formato == "wav":
            dizer(f"  veio: WAV {taxa} Hz, {canais} canal/is (a taxa vem do cabeçalho)")
        elif formato == "pcm":
            plausiveis = taxa_plausivel(len(resposta.corpo), endpoint.canais)
            dizer(
                f"  veio: PCM cru, lido como {endpoint.taxa} Hz (a configuração; PCM cru não diz)"
            )
            if plausiveis and endpoint.taxa not in plausiveis:
                dizer(
                    f"  ATENÇÃO: lido a {endpoint.taxa} Hz a frase dura {duracao:.2f} s, fora do "
                    f"plausível; a {' ou '.join(str(t) for t in plausiveis)} Hz ela dura o normal "
                    "— a taxa configurada deve estar errada (a voz sai rápida/aguda ou lenta/"
                    'grave). Corrija `taxa` ou use formato = "wav".'
                )
        try:
            if pasta is None:
                raise OSError("sem pasta de estado no ambiente")
            ouvir = _gravar_wav(pasta / f"teste-endpoint-{rotulo}.wav", amostras, taxa=16000)
            dizer(f"  amostra (o que o Jarvis toca, PCM16 16 kHz): {ouvir}")
            if formato == "wav":
                bruto = pasta / f"teste-endpoint-{rotulo}-como-veio.wav"
                bruto.write_bytes(resposta.corpo)
                dizer(f"  como veio do servidor: {bruto}")
            elif formato == "pcm":
                bruto = _gravar_wav(
                    pasta / f"teste-endpoint-{rotulo}-como-veio.wav",
                    resposta.corpo[: len(resposta.corpo) // 2 * 2],
                    taxa=endpoint.taxa,
                    canais=endpoint.canais,
                )
                dizer(f"  como veio do servidor (a {endpoint.taxa} Hz): {bruto}")
        except OSError as erro:
            dizer(f"  amostra: não gravei ({erro})")
        pico = max(
            (
                abs(int.from_bytes(amostras[i : i + 2], "little", signed=True))
                for i in range(0, len(amostras), 2)
            ),
            default=0,
        )
        dizer(
            f"{linha}\n  áudio: {duracao:.2f} s em PCM16 16 kHz, pico {pico}/32767"
            + (" — SILÊNCIO?" if pico < 100 else "")
        )
        algum = algum or duracao > 0
    dizer(
        "RESULTADO: "
        + (
            "ok — o Jarvis consegue falar por este endpoint"
            if algum
            else "FALHOU — nenhum caminho devolveu áudio"
        )
    )
    return 0 if algum else 1
