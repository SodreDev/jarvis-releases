"""TTS por um endpoint HTTP configurável (ADR-0068): o servidor de voz que o dono montou.

Pedido do dono (2026-11-14): um TTS dele, noutra máquina da rede (o painel phonon-web), e — sem
amarrar o Jarvis a ele — qualquer API de TTS que receba um JSON e devolva áudio. Por isso o motor
é **genérico** e o servidor do dono é só o primeiro *preset* (`endpoints_tts.toml`, «JARVIS-BR
(phonon-web)»), no mesmo desenho dos presets da ADR-0056: o padrão do repositório e o arquivo do
dono (`~/.config/jarvis/tts-endpoints.toml`), que vence pelo nome.

**O que é configurável, e onde.** Um `Endpoint` diz a base, o caminho de síntese, o de stream
(opcional), o método, o **molde do corpo** (um JSON com `{texto}`, `{voz}`, `{estilo}`,
`{formato}`, `{taxa}`, `{canais}` — é o que deixa a mesma peça falar com APIs de nomes de campo
diferentes), o formato do áudio que volta (PCM cru com taxa e canais, WAV, MP3 ou Opus), a
autenticação (nenhuma, `Bearer` ou um cabeçalho com nome dado) com o **nome** da variável de
ambiente — nunca o valor —, o prazo e as vozes e estilos conhecidos. A configuração do Jarvis
(`jarvis-voz.toml`) só guarda a escolha: qual endpoint, qual voz, qual estilo e qual motor fala
quando ele cai.

**Segurança, do código e não da boa vontade de quem configura:**

1. só `http`/`https`, base sem usuário, senha, consulta nem fragmento; caminho começando em uma
   barra só, sem `@`, sem `\\` — e, depois de montada, a URL é conferida: o servidor tem de ser o
   da base. O texto do dono **não vai a outro host**;
2. **redirecionamento não é seguido** (o `http.client` não segue, e um 3xx vira recusa que diz
   para onde ele apontava — sem a consulta, que pode carregar coisa);
3. a chave, quando há, sai do ambiente ou do chaveiro e vai só no cabeçalho; erro passa por
   `redigir`; cabeçalho extra não pode ser de autenticação;
4. sob `CI=1`, só a máquina local (`proibir_nuvem_real_em_ci`): a suíte fala com um servidor
   falso em porta efêmera, nunca com a rede do dono.

**Stream.** Com `caminho_stream`, o corpo chega por pedaços e o cancelamento (o barge-in, o epoch
que morreu) é consultado **entre cada um**: interrompeu, a resposta é fechada — a conexão não
volta ao pool com corpo em voo — e o que tinha chegado é descartado. O trecho continua sendo a
unidade do `SintetizadorEmStreaming` (o mapa texto ↔ amostras do F1-12 é por trecho); o stream
encurta o tempo até o fim do trecho e torna o corte imediato. Rota de stream ausente (404, 405,
501) cai no caminho comum, uma vez por sessão.

**Fora da rede não é ficar mudo (`MotorComReservaDeRede`).** Diferente da nuvem comum, aqui não
se usa o `AdaptadorRemoto`: ele declara a degradação da sessão inteira e derruba a escuta para o
botão de falar — o servidor de voz da sala estar desligado não é motivo para o Jarvis parar de
ouvir. Falhou (recusou a conexão, estourou o prazo curto, devolveu o que não é áudio), o mesmo
trecho é falado pela **voz reserva** (o motor que o dono usava antes, ou o padrão), sai um aviso
curto na tela, e o endpoint só é tentado de novo depois de `RETENTAR_EM_S`, com uma checagem de
saúde barata antes (um `connect` TCP de meio segundo) — nada de pagar o prazo inteiro a cada
frase enquanto a máquina está desligada.
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
import socket
import struct
import threading
import time
import tomllib
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, TAXA_PADRAO
from jarvis.voz.chaves import (
    VARIAVEL_TTS_ENDPOINT,
    Chave,
    SegredoNaConfiguracao,
    proibir_segredo_na_configuracao,
    redigir,
)
from jarvis.voz.config import pasta_de_configuracao
from jarvis.voz.interface import Cancelado, MotorDeTts, Onde, nunca_cancelado
from jarvis.voz.nuvem import (
    AGENTE_DO_USUARIO,
    CONEXOES,
    LIMITE_DE_CORPO,
    PEDACO_DE_LEITURA,
    STATUS_QUE_VIRAM_DEGRADACAO,
    ErroDoServico,
    ServicoRecusou,
    proibir_nuvem_real_em_ci,
)
from jarvis.voz.registro import Motor, exigir_motor

REGISTRADO: Final = "tts-endpoint"
ARQUIVO_PADRAO: Final = Path(__file__).with_name("endpoints_tts.toml")
NOME_DO_ARQUIVO: Final = "tts-endpoints.toml"
FORMATOS: Final[tuple[str, ...]] = ("pcm", "wav", "mp3", "opus")
AUTENTICACOES: Final[tuple[str, ...]] = ("nenhuma", "bearer", "cabecalho")
METODOS: Final[tuple[str, ...]] = ("POST", "PUT")
MOLDES: Final[tuple[str, ...]] = ("texto", "voz", "estilo", "formato", "taxa", "canais")
MOLDES_QUE_SOMEM: Final[frozenset[str]] = frozenset({"voz", "estilo"})
"""Campo do corpo que é **só** `{voz}` ou `{estilo}` e está vazio sai do corpo: mandar `""` faria
muita API recusar em vez de usar a voz/estilo padrão dela."""
CORPO_PADRAO: Final = (
    '{"text": "{texto}", "voice": "{voz}", "style": "{estilo}", "format": "{formato}"}'
)
CAMINHOS_DE_VOZES_COMUNS: Final[tuple[str, ...]] = (
    "/api/voices",
    "/voices",
    "/v1/voices",
    "/api/tts/voices",
)
"""Onde uma API de TTS costuma listar as vozes. Tentadas em ordem, **sem supor que existam**: 404,
HTML, JSON sem lista — tudo vira «não lista», e o painel fica com os campos livres."""
CAMINHOS_DE_ESTILOS_COMUNS: Final[tuple[str, ...]] = ("/api/styles", "/styles", "/api/tts/styles")
PRAZO_PADRAO_S: Final = 8.0
PRAZO_MINIMO_S: Final = 0.5
PRAZO_MAXIMO_S: Final = 60.0
PRAZO_DA_SAUDE_S: Final = 0.5
"""A checagem barata: um `connect` TCP. Na rede local, de pé, leva ~1 ms; desligada, a recusa volta
na hora ou o meio segundo acaba."""
PRAZO_DO_CATALOGO_S: Final = 3.0
RETENTAR_EM_S: Final = 20.0
"""Depois de uma queda, a voz reserva fala por pelo menos isto antes de o endpoint ser tentado de
novo (com a checagem de saúde antes)."""
MAXIMO_DE_VOZES: Final = 200
MAXIMO_DO_MOLDE: Final = 4096
FORMA_DO_NOME: Final[re.Pattern[str]] = re.compile(r"[^\W_][\w .()+\-]{0,59}")
FORMA_DO_HOST: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?"
)
FORMA_DO_CAMINHO_DA_BASE: Final[re.Pattern[str]] = re.compile(r"(?:/[A-Za-z0-9._~-]+)*/?")
FORMA_DO_CAMINHO: Final[re.Pattern[str]] = re.compile(
    r"/(?!/)[A-Za-z0-9._~/%:+,;=-]*(?:\?[A-Za-z0-9._~/%:+,;=&-]*)?"
)
"""Começa em **uma** barra e não tem `@`, `\\`, `#` nem espaço: nada no caminho pode virar outro
servidor quando ele é colado à base."""
FORMA_DO_CABECALHO: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
FORMA_DA_VARIAVEL: Final[re.Pattern[str]] = re.compile(r"[A-Z][A-Z0-9_]{2,63}")
FORMA_DA_VOZ: Final[re.Pattern[str]] = re.compile(r"[^\x00-\x1f\x7f\"\\]{1,64}")
"""Voz e estilo vão **dentro** do JSON (o `json.dumps` escapa), nunca na URL: a forma só barra
controle, aspas e tamanho."""
CABECALHOS_PROIBIDOS: Final[frozenset[str]] = frozenset(
    {"authorization", "proxy-authorization", "cookie", "host", "content-length", "content-type"}
)
MARCAS_DE_CREDENCIAL: Final[tuple[str, ...]] = ("auth", "token", "key", "secret", "senha", "chave")
"""Cabeçalho extra com cara de credencial é recusado: o valor dele estaria no arquivo, em texto."""
VARIAVEL_SUGERIDA: Final = VARIAVEL_TTS_ENDPOINT


class EndpointInvalido(ValueError):
    """O endpoint não serve: a mensagem diz o campo e o que é válido."""


class RotaAusente(ServicoRecusou):
    """O servidor não tem esta rota (404, 405, 501): o stream cai no caminho comum."""


class RedirecionamentoRecusado(ServicoRecusou):
    """O servidor respondeu 3xx. O Jarvis não segue — o texto só vai à base configurada."""


# --- o endpoint -----------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Endpoint:
    """Um servidor de TTS como o dono o configurou. Dado, sem segredo nenhum."""

    nome: str
    base: str
    caminho: str = "/api/tts"
    caminho_stream: str = ""
    metodo: str = "POST"
    corpo: str = CORPO_PADRAO
    """O molde do corpo, em JSON (texto), com os `{moldes}` de `MOLDES`."""
    formato: str = "pcm"
    taxa: int = 24000
    canais: int = 1
    voz: str = ""
    vozes: tuple[str, ...] = ()
    estilo: str = ""
    estilos: tuple[str, ...] = ()
    autenticacao: str = "nenhuma"
    cabecalho: str = ""
    """O nome do cabeçalho quando `autenticacao = "cabecalho"` (ex.: `X-API-Key`)."""
    variavel_de_ambiente: str = ""
    """O NOME da variável com a chave. O valor nunca passa por este arquivo."""
    cabecalhos: tuple[tuple[str, str], ...] = ()
    """Cabeçalhos extras, sem segredo (`Accept`, um `X-Cliente`)."""
    prazo_s: float = PRAZO_PADRAO_S
    caminhos_de_vozes: tuple[str, ...] = ()
    """Onde listar as vozes. Vazio = as rotas comuns (`CAMINHOS_DE_VOZES_COMUNS`)."""
    nota: str = ""

    @property
    def host(self) -> str:
        return (urlsplit(self.base).hostname or "").lower()

    @property
    def porta(self) -> int:
        partes = urlsplit(self.base)
        return partes.port or (443 if partes.scheme == "https" else 80)

    @property
    def molde(self) -> Any:
        return json.loads(self.corpo)

    @property
    def tem_stream(self) -> bool:
        return bool(self.caminho_stream)

    def url(self, caminho: str) -> str:
        """A URL de um caminho deste endpoint — conferida: o servidor é sempre o da base."""
        if not FORMA_DO_CAMINHO.fullmatch(caminho):
            raise EndpointInvalido(f"caminho {caminho!r} não é um caminho de URL simples")
        url = self.base.rstrip("/") + caminho
        if urlsplit(url).netloc.lower() != urlsplit(self.base).netloc.lower():
            raise EndpointInvalido(f"o caminho {caminho!r} mudaria o servidor da base")
        return url

    def para_dict(self) -> dict[str, Any]:
        """Para a janela: nada aqui é segredo (a variável vai pelo nome)."""
        return {
            "nome": self.nome,
            "base": self.base,
            "caminho": self.caminho,
            "caminho_stream": self.caminho_stream,
            "metodo": self.metodo,
            "corpo": self.corpo,
            "formato": self.formato,
            "taxa": self.taxa,
            "canais": self.canais,
            "voz": self.voz,
            "vozes": list(self.vozes),
            "estilo": self.estilo,
            "estilos": list(self.estilos),
            "autenticacao": self.autenticacao,
            "cabecalho": self.cabecalho,
            "variavel_de_ambiente": self.variavel_de_ambiente,
            "cabecalhos": [f"{nome}: {valor}" for nome, valor in self.cabecalhos],
            "prazo_s": self.prazo_s,
            "caminhos_de_vozes": list(self.caminhos_de_vozes),
            "nota": self.nota,
        }


def normalizar(nome: str) -> str:
    """Sem acento, sem caixa e sem espaço sobrando: «JARVIS-BR (phonon-web)» acha «jarvis-br
    (phonon-web)»."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def conferir_base(base: str) -> str:
    """A base `http(s)://servidor[:porta][/caminho]`: sem usuário, senha, consulta, fragmento."""
    try:
        partes = urlsplit(base)
        porta = partes.port
    except ValueError as erro:
        raise EndpointInvalido(f"base {base!r} não é uma URL: {erro}") from None
    if partes.scheme not in ("http", "https"):
        raise EndpointInvalido(f"base {base!r}: só http:// ou https://")
    if partes.username is not None or partes.password is not None or "@" in partes.netloc:
        raise EndpointInvalido(f"base {base!r}: sem usuário e senha na URL (use a autenticação)")
    if partes.query or partes.fragment or "?" in base or "#" in base:
        raise EndpointInvalido(f"base {base!r}: sem consulta (?) nem fragmento (#)")
    host = partes.hostname or ""
    ipv6 = partes.netloc.startswith("[")
    if not host or (not ipv6 and not FORMA_DO_HOST.fullmatch(host)):
        raise EndpointInvalido(f"base {base!r}: servidor vazio ou com caractere estranho")
    if porta is not None and not 1 <= porta <= 65535:
        raise EndpointInvalido(f"base {base!r}: porta fora de 1 a 65535")
    if not FORMA_DO_CAMINHO_DA_BASE.fullmatch(partes.path):
        raise EndpointInvalido(f"base {base!r}: o caminho da base tem caractere estranho")
    return base.rstrip("/")


def _conferir_molde(corpo: str) -> None:
    if len(corpo) > MAXIMO_DO_MOLDE:
        raise EndpointInvalido(f"corpo: o molde passa de {MAXIMO_DO_MOLDE} caracteres")
    try:
        molde = json.loads(corpo)
    except json.JSONDecodeError as erro:
        raise EndpointInvalido(f"corpo não é JSON: {erro}") from None
    if not isinstance(molde, dict):
        raise EndpointInvalido("corpo: o molde tem de ser um objeto JSON ({...})")
    achados: set[str] = set()
    for texto in _textos_do_molde(molde):
        for nome in re.findall(r"\{([A-Za-z_]+)\}", texto):
            if nome not in MOLDES:
                raise EndpointInvalido(
                    f"corpo: {{{nome}}} não existe. Os moldes são "
                    + ", ".join(f"{{{m}}}" for m in MOLDES)
                )
            achados.add(nome)
    if "texto" not in achados:
        raise EndpointInvalido("corpo: o molde não tem {texto} — o servidor não receberia a fala")


def _textos_do_molde(valor: Any) -> Iterable[str]:
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for item in valor.values():
            yield from _textos_do_molde(item)
    elif isinstance(valor, list):
        for item in valor:
            yield from _textos_do_molde(item)


def conferir(endpoint: Endpoint) -> Endpoint:
    """Recusa o que não serve, dizendo o campo. Chamada na leitura, na gravação e no `abrir`."""
    if not FORMA_DO_NOME.fullmatch(endpoint.nome):
        raise EndpointInvalido(
            f"nome {endpoint.nome!r}: letras, números, espaço, ( ) + . - (até 60)"
        )
    base = conferir_base(endpoint.base)
    for rotulo, caminho in (
        ("caminho", endpoint.caminho),
        ("caminho_stream", endpoint.caminho_stream),
    ):
        if (caminho or rotulo == "caminho") and not FORMA_DO_CAMINHO.fullmatch(caminho):
            raise EndpointInvalido(
                f"{rotulo} {caminho!r}: comece com uma barra (/api/tts), sem @, espaço nem //"
            )
    for caminho in endpoint.caminhos_de_vozes:
        if not FORMA_DO_CAMINHO.fullmatch(caminho):
            raise EndpointInvalido(f"caminhos_de_vozes tem {caminho!r}: não é um caminho simples")
    if endpoint.metodo not in METODOS:
        raise EndpointInvalido(f"metodo {endpoint.metodo!r}: válidos {', '.join(METODOS)}")
    _conferir_molde(endpoint.corpo)
    if endpoint.formato not in FORMATOS:
        raise EndpointInvalido(f"formato {endpoint.formato!r}: válidos {', '.join(FORMATOS)}")
    if not 8000 <= endpoint.taxa <= 96000:
        raise EndpointInvalido(f"taxa {endpoint.taxa}: fora de 8000 a 96000 Hz")
    if endpoint.canais not in (1, 2):
        raise EndpointInvalido(f"canais {endpoint.canais}: 1 (mono) ou 2 (estéreo)")
    if not PRAZO_MINIMO_S <= endpoint.prazo_s <= PRAZO_MAXIMO_S:
        raise EndpointInvalido(
            f"prazo_s {endpoint.prazo_s}: fora de {PRAZO_MINIMO_S} a {PRAZO_MAXIMO_S} s"
        )
    for rotulo, valores in (
        ("voz", (endpoint.voz,) if endpoint.voz else ()),
        ("vozes", endpoint.vozes),
        ("estilo", (endpoint.estilo,) if endpoint.estilo else ()),
        ("estilos", endpoint.estilos),
    ):
        for valor in valores:
            if not FORMA_DA_VOZ.fullmatch(valor):
                raise EndpointInvalido(f"{rotulo} {valor!r}: sem controle nem aspas, até 64")
    if endpoint.autenticacao not in AUTENTICACOES:
        raise EndpointInvalido(
            f"autenticacao {endpoint.autenticacao!r}: válidas {', '.join(AUTENTICACOES)}"
        )
    if endpoint.autenticacao != "nenhuma" and not FORMA_DA_VARIAVEL.fullmatch(
        endpoint.variavel_de_ambiente
    ):
        raise EndpointInvalido(
            "variavel_de_ambiente: com autenticação, o NOME da variável que tem a chave "
            f"(maiúsculas, números e _, ex.: {VARIAVEL_SUGERIDA}) — o valor nunca vai no arquivo"
        )
    if endpoint.autenticacao == "cabecalho" and (
        not FORMA_DO_CABECALHO.fullmatch(endpoint.cabecalho)
        or endpoint.cabecalho.lower() in CABECALHOS_PROIBIDOS - {"authorization"}
    ):
        raise EndpointInvalido(
            f"cabecalho {endpoint.cabecalho!r}: o nome do cabeçalho da chave (ex.: X-API-Key)"
        )
    for nome, valor in endpoint.cabecalhos:
        if (
            not FORMA_DO_CABECALHO.fullmatch(nome)
            or nome.lower() in CABECALHOS_PROIBIDOS
            or any(marca in nome.lower() for marca in MARCAS_DE_CREDENCIAL)
        ):
            raise EndpointInvalido(
                f"cabecalhos: {nome!r} não pode ser extra (autenticação vai em `autenticacao`)"
            )
        if any(c in valor for c in "\r\n\x00") or len(valor) > 256:
            raise EndpointInvalido(
                f"cabecalhos: o valor de {nome!r} tem quebra de linha ou é longo"
            )
    return replace(endpoint, base=base)


# --- os arquivos (o do repositório e o do dono) ---------------------------------------------------
def _textos(bruto: Mapping[str, Any], chave: str) -> tuple[str, ...]:
    valor = bruto.get(chave, [])
    if not isinstance(valor, list) or any(not isinstance(v, str) for v in valor):
        raise EndpointInvalido(f"{chave}: esperava uma lista de textos")
    return tuple(dict.fromkeys(v.strip() for v in valor if v.strip()))


def de_dados(bruto: Mapping[str, Any], *, origem: str = "") -> Endpoint:
    """Um `[[endpoint]]` do TOML. Campo desconhecido é erro: endpoint é configuração de rede, e um
    campo escrito errado (`caminho_strem`) não pode virar «sem stream» em silêncio."""
    conhecidos = {f.name for f in fields(Endpoint)}
    estranhos = sorted(set(bruto) - conhecidos)
    onde = f" em {origem}" if origem else ""
    if estranhos:
        raise EndpointInvalido(f"campo(s) {', '.join(estranhos)}{onde} não existe(m)")
    try:
        proibir_segredo_na_configuracao(bruto, arquivo=origem)
    except SegredoNaConfiguracao as erro:
        raise EndpointInvalido(str(erro)) from None
    corpo = bruto.get("corpo", CORPO_PADRAO)
    if isinstance(corpo, dict):
        corpo = json.dumps(corpo, ensure_ascii=False)
    cabecalhos: list[tuple[str, str]] = []
    for linha in _textos(bruto, "cabecalhos"):
        nome, _, valor = linha.partition(":")
        cabecalhos.append((nome.strip(), valor.strip()))
    try:
        endpoint = Endpoint(
            nome=str(bruto.get("nome", "")).strip(),
            base=str(bruto.get("base", "")).strip(),
            caminho=str(bruto.get("caminho", "/api/tts")).strip(),
            caminho_stream=str(bruto.get("caminho_stream", "")).strip(),
            metodo=str(bruto.get("metodo", "POST")).strip().upper(),
            corpo=str(corpo),
            formato=str(bruto.get("formato", "pcm")).strip().lower(),
            taxa=int(bruto.get("taxa", 24000)),
            canais=int(bruto.get("canais", 1)),
            voz=str(bruto.get("voz", "")).strip(),
            vozes=_textos(bruto, "vozes"),
            estilo=str(bruto.get("estilo", "")).strip(),
            estilos=_textos(bruto, "estilos"),
            autenticacao=str(bruto.get("autenticacao", "nenhuma")).strip().lower(),
            cabecalho=str(bruto.get("cabecalho", "")).strip(),
            variavel_de_ambiente=str(bruto.get("variavel_de_ambiente", "")).strip(),
            cabecalhos=tuple(cabecalhos),
            prazo_s=float(bruto.get("prazo_s", PRAZO_PADRAO_S)),
            caminhos_de_vozes=_textos(bruto, "caminhos_de_vozes"),
            nota=str(bruto.get("nota", "")).strip()[:200],
        )
    except (TypeError, ValueError) as erro:
        if isinstance(erro, EndpointInvalido):
            raise
        raise EndpointInvalido(f"endpoint{onde}: {erro}") from None
    try:
        return conferir(endpoint)
    except EndpointInvalido as erro:
        raise EndpointInvalido(f"{endpoint.nome or 'endpoint sem nome'}{onde}: {erro}") from None


def ler(arquivo: Path) -> tuple[Endpoint, ...]:
    """Os endpoints de um arquivo. Ausente = nenhum; ilegível ou inválido = erro com o motivo."""
    if not arquivo.is_file():
        return ()
    try:
        dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as erro:
        raise EndpointInvalido(f"{arquivo.name}: não deu para ler ({erro})") from None
    brutos = dados.get("endpoint", [])
    if not isinstance(brutos, list):
        raise EndpointInvalido(f"{arquivo.name}: use [[endpoint]] para cada servidor")
    return tuple(de_dados(b, origem=arquivo.name) for b in brutos if isinstance(b, dict))


def arquivo_do_dono(ambiente: Mapping[str, str] | None = None) -> Path:
    return pasta_de_configuracao(ambiente) / NOME_DO_ARQUIVO


def todos(
    *, ambiente: Mapping[str, str] | None = None, arquivo: Path | None = None
) -> tuple[Endpoint, ...]:
    """Os do repositório e os do dono — o do dono vence pelo nome, e os novos vêm no fim."""
    do_dono = ler(arquivo if arquivo is not None else arquivo_do_dono(ambiente))
    deles = {normalizar(e.nome): e for e in do_dono}
    saida = [deles.pop(normalizar(e.nome), e) for e in ler(ARQUIVO_PADRAO)]
    return (*saida, *deles.values())


def escolher(
    nome: str, *, ambiente: Mapping[str, str] | None = None, arquivo: Path | None = None
) -> Endpoint:
    """O endpoint pelo nome (sem acento e sem caixa). Vazio = o primeiro (o preset do dono)."""
    lista = todos(ambiente=ambiente, arquivo=arquivo)
    if not lista:
        raise EndpointInvalido("nenhum endpoint de TTS configurado")
    if not nome.strip():
        return lista[0]
    for endpoint in lista:
        if normalizar(endpoint.nome) == normalizar(nome):
            return endpoint
    raise EndpointInvalido(
        f"endpoint {nome!r} não existe. Os que existem: {', '.join(e.nome for e in lista)}"
    )


def _aspas(valor: str) -> str:
    return json.dumps(valor, ensure_ascii=False)


def _texto_do_arquivo(endpoints: Sequence[Endpoint]) -> str:
    """TOML à mão (como o `jarvis-voz.toml`): poucos campos e nenhuma dependência nova."""
    linhas = [
        "# Endpoints de TTS do dono (ADR-0068). Vence o do repositório com o mesmo nome.",
        "# Sem segredo: com autenticação, só o NOME da variável de ambiente que tem a chave.",
        "",
        "versao = 1",
    ]
    for e in endpoints:
        linhas += [
            "",
            "[[endpoint]]",
            f"nome = {_aspas(e.nome)}",
            f"base = {_aspas(e.base)}",
            f"caminho = {_aspas(e.caminho)}",
            f"caminho_stream = {_aspas(e.caminho_stream)}",
            f"metodo = {_aspas(e.metodo)}",
            f"corpo = {_aspas(e.corpo)}",
            f"formato = {_aspas(e.formato)}",
            f"taxa = {e.taxa}",
            f"canais = {e.canais}",
            f"voz = {_aspas(e.voz)}",
            f"vozes = [{', '.join(_aspas(v) for v in e.vozes)}]",
            f"estilo = {_aspas(e.estilo)}",
            f"estilos = [{', '.join(_aspas(v) for v in e.estilos)}]",
            f"autenticacao = {_aspas(e.autenticacao)}",
            f"cabecalho = {_aspas(e.cabecalho)}",
            f"variavel_de_ambiente = {_aspas(e.variavel_de_ambiente)}",
            "cabecalhos = ["
            + ", ".join(_aspas(f"{nome}: {valor}") for nome, valor in e.cabecalhos)
            + "]",
            f"prazo_s = {float(e.prazo_s)!r}",
            f"caminhos_de_vozes = [{', '.join(_aspas(c) for c in e.caminhos_de_vozes)}]",
            f"nota = {_aspas(e.nota)}",
        ]
    return "\n".join(linhas) + "\n"


def gravar(endpoint: Endpoint, *, arquivo: Path) -> Path:
    """Guarda (ou troca, pelo nome) um endpoint no arquivo do dono. Conferido antes de escrever."""
    novo = conferir(endpoint)
    existentes = list(ler(arquivo))
    chave = normalizar(novo.nome)
    trocado = [novo if normalizar(e.nome) == chave else e for e in existentes]
    if not any(normalizar(e.nome) == chave for e in existentes):
        trocado.append(novo)
    texto = _texto_do_arquivo(trocado)
    proibir_segredo_na_configuracao(tomllib.loads(texto), arquivo=arquivo.name)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".toml.tmp")
    temporario.write_text(texto, encoding="utf-8")
    temporario.replace(arquivo)
    return arquivo


CAMPOS_EDITAVEIS: Final[tuple[str, ...]] = (
    "base",
    "caminho",
    "caminho_stream",
    "metodo",
    "corpo",
    "formato",
    "taxa",
    "canais",
    "voz",
    "vozes",
    "estilo",
    "estilos",
    "autenticacao",
    "cabecalho",
    "variavel_de_ambiente",
    "prazo_s",
    "caminhos_de_vozes",
)
"""O que a janela muda, um campo por vez, como texto (lista = separada por vírgula)."""


def com_campo(endpoint: Endpoint, campo: str, valor: str) -> Endpoint:
    """O endpoint com um campo trocado, a partir do texto que a janela mandou — já conferido."""
    if campo not in CAMPOS_EDITAVEIS:
        raise EndpointInvalido(f"{campo!r} não é campo editável do endpoint")
    texto = valor.strip()
    novo: Any
    if campo in ("taxa", "canais"):
        try:
            novo = int(texto)
        except ValueError:
            raise EndpointInvalido(f"{campo}: esperava um número inteiro") from None
    elif campo == "prazo_s":
        try:
            novo = float(texto.replace(",", "."))
        except ValueError:
            raise EndpointInvalido("prazo_s: esperava um número (segundos)") from None
    elif campo in ("vozes", "estilos", "caminhos_de_vozes"):
        novo = tuple(dict.fromkeys(p.strip() for p in texto.split(",") if p.strip()))
    elif campo in ("metodo",):
        novo = texto.upper()
    elif campo in ("formato", "autenticacao"):
        novo = texto.lower()
    else:
        novo = texto
    return conferir(replace(endpoint, **{campo: novo}))


# --- o corpo --------------------------------------------------------------------------------------
def montar_corpo(endpoint: Endpoint, *, texto: str, voz: str, estilo: str) -> bytes:
    """O JSON do pedido: o molde com os valores. Campo que é só um molde mantém o tipo (`{taxa}`
    vira número); dentro de um texto maior, vira texto. `{voz}`/`{estilo}` vazios somem."""
    valores: dict[str, Any] = {
        "texto": texto,
        "voz": voz,
        "estilo": estilo,
        "formato": endpoint.formato,
        "taxa": endpoint.taxa,
        "canais": endpoint.canais,
    }
    sumir = object()

    def preencher(item: Any) -> Any:
        if isinstance(item, str):
            sozinho = re.fullmatch(r"\{([a-z]+)\}", item)
            if sozinho and sozinho.group(1) in valores:
                nome = sozinho.group(1)
                if nome in MOLDES_QUE_SOMEM and not valores[nome]:
                    return sumir
                return valores[nome]
            return re.sub(
                r"\{([a-z]+)\}",
                lambda m: str(valores.get(m.group(1), m.group(0))),
                item,
            )
        if isinstance(item, dict):
            cheio = {chave: preencher(v) for chave, v in item.items()}
            return {chave: v for chave, v in cheio.items() if v is not sumir}
        if isinstance(item, list):
            return [v for v in (preencher(x) for x in item) if v is not sumir]
        return item

    return json.dumps(preencher(endpoint.molde), ensure_ascii=False).encode("utf-8")


_MARCAS_DE_MARKDOWN: Final = re.compile(r"(\*\*|__|`+|~~)")
_COMECO_DE_LISTA: Final = re.compile(r"(?m)^\s*(?:#{1,6}|[-*•]|\d+[.)])\s+")
_LINK_MARKDOWN: Final = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def texto_para_a_voz(texto: str) -> str:
    """O texto que vai ao servidor: limpo, mas íntegro em pt-BR (ADR-0068, emenda de 2026-11-15).

    Sai só o que não é fala — marcas de markdown, começo de lista, link no formato de markdown
    (fica o texto dele), emoji e caractere de controle. Fica tudo o que a pronúncia precisa:
    acento, cedilha, número, hora («14h30»), sigla e pontuação. Nada é trocado por extenso aqui:
    quem lê número é o servidor, e trocar no cliente erra mais do que acerta."""
    limpo = _LINK_MARKDOWN.sub(r"\1", texto)
    limpo = _COMECO_DE_LISTA.sub("", limpo)
    limpo = _MARCAS_DE_MARKDOWN.sub("", limpo)
    limpo = "".join(
        c
        for c in unicodedata.normalize("NFC", limpo)
        if c in "\n\t" or unicodedata.category(c) not in {"So", "Cc", "Cf", "Cs", "Co", "Sk"}
    )
    return " ".join(limpo.split())


# --- o pedido -------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RespostaDoEndpoint:
    """O que voltou do servidor — ou o que foi descartado pelo cancelamento."""

    corpo: bytes = b""
    status: int = 0
    tipo: str = ""
    cancelada: bool = False
    bytes_descartados: int = 0
    pedacos: int = 0
    primeiro_byte_s: float = 0.0
    total_s: float = 0.0


def chave_do(endpoint: Endpoint, ambiente: Mapping[str, str] | None = None) -> Chave | None:
    """A chave, se o endpoint tem autenticação: do ambiente ou do chaveiro, nunca do arquivo."""
    if endpoint.autenticacao == "nenhuma":
        return None
    return Chave.do_ambiente(endpoint.variavel_de_ambiente, ambiente=ambiente)


def _cabecalhos(endpoint: Endpoint, chave: Chave | None) -> dict[str, str]:
    saida = {"User-Agent": AGENTE_DO_USUARIO}
    for nome, valor in endpoint.cabecalhos:
        saida[nome] = valor
    if chave is not None:
        if endpoint.autenticacao == "bearer":
            saida["Authorization"] = f"Bearer {chave.usar()}"
        else:
            saida[endpoint.cabecalho] = chave.usar()
    return saida


def pedir(
    endpoint: Endpoint,
    caminho: str,
    *,
    metodo: str = "POST",
    corpo: bytes | None = None,
    tipo: str = "application/json",
    chave: Chave | None = None,
    cancelado: Cancelado = nunca_cancelado,
    prazo_s: float | None = None,
    ambiente: Mapping[str, str] | None = None,
    abrir: Any = CONEXOES,
    limite: int = LIMITE_DE_CORPO,
    relogio: Callable[[], float] = time.monotonic,
) -> RespostaDoEndpoint:
    """Um pedido ao endpoint, lido por pedaços com o cancelamento consultado entre eles.

    Levanta `ErroDoServico` (não deu para falar, 5xx, prazo), `RotaAusente` (404/405/501),
    `RedirecionamentoRecusado` (3xx) ou `ServicoRecusou` (o resto do 4xx). Nenhuma mensagem leva a
    chave: tudo passa por `redigir`.
    """
    chaves = [chave] if chave is not None else []
    if cancelado():
        return RespostaDoEndpoint(cancelada=True)
    proibir_nuvem_real_em_ci(endpoint.base, ambiente)
    url = endpoint.url(caminho)
    pedido = urllib.request.Request(url=url, data=corpo, method=metodo)  # noqa: S310 — conferida
    if corpo is not None:
        pedido.add_header("Content-Type", tipo)
        pedido.add_header("Content-Length", str(len(corpo)))
    for nome, valor in _cabecalhos(endpoint, chave).items():
        pedido.add_header(nome, valor)
    prazo = endpoint.prazo_s if prazo_s is None else prazo_s
    comeco = relogio()
    try:
        resposta = abrir(pedido, timeout=prazo)
    except urllib.error.HTTPError as erro:
        detalhe = redigir(erro.read().decode("utf-8", "replace")[:300], chaves).strip()
        if erro.code in (404, 405, 501):
            raise RotaAusente(f"{erro.code} em {caminho}: o servidor não tem esta rota") from None
        if erro.code in STATUS_QUE_VIRAM_DEGRADACAO or erro.code >= 500:
            raise ErroDoServico(f"{erro.code} do servidor de voz: {detalhe}") from None
        raise ServicoRecusou(
            f"o servidor de voz recusou o pedido ({erro.code}): {detalhe}. Confira o corpo "
            "(os nomes dos campos), a voz, o estilo e a autenticação do endpoint"
        ) from None
    except urllib.error.URLError as erro:
        raise ErroDoServico(
            redigir(
                f"não deu para falar com {endpoint.host}:{endpoint.porta}: {erro.reason}", chaves
            )
        ) from None
    except (OSError, TimeoutError) as erro:
        raise ErroDoServico(f"não deu para falar com {endpoint.host}: {erro}") from None
    with resposta:
        status = int(resposta.status)
        if 300 <= status < 400:
            destino = urlsplit(resposta.cabecalho("Location"))
            para = (
                f"{destino.scheme}://{destino.netloc}{destino.path}"
                if destino.netloc
                else (destino.path or "(sem Location)")
            )
            resposta.close()
            raise RedirecionamentoRecusado(
                f"o servidor de voz redirecionou ({status}) para {para}: o Jarvis não segue "
                "redirecionamento — o texto só vai à base configurada. Corrija a base ou o caminho"
            )
        tipo = resposta.cabecalho("Content-Type").split(";")[0].strip().lower()
        recebido = bytearray()
        pedacos = 0
        primeiro = 0.0
        while True:
            if cancelado():
                resposta.close()
                return RespostaDoEndpoint(
                    status=status,
                    tipo=tipo,
                    cancelada=True,
                    bytes_descartados=len(recebido),
                    pedacos=pedacos,
                    primeiro_byte_s=primeiro,
                    total_s=relogio() - comeco,
                )
            try:
                pedaco = resposta.read(PEDACO_DE_LEITURA)
            except (OSError, TimeoutError) as erro:
                resposta.close()
                raise ErroDoServico(
                    f"o servidor de voz parou no meio do áudio ({type(erro).__name__})"
                ) from None
            if not pedaco:
                break
            if not pedacos:
                primeiro = relogio() - comeco
            pedacos += 1
            recebido += pedaco
            if len(recebido) > limite:
                resposta.close()
                raise ErroDoServico(f"o servidor de voz mandou mais de {limite} bytes: abandonado")
    return RespostaDoEndpoint(
        corpo=bytes(recebido),
        status=status,
        tipo=tipo,
        pedacos=pedacos,
        primeiro_byte_s=primeiro,
        total_s=relogio() - comeco,
    )


# --- o áudio --------------------------------------------------------------------------------------
CHAVES_DE_AUDIO_NO_JSON: Final[tuple[str, ...]] = ("audio", "audio_base64", "audioContent", "data")


def _audio_do_json(corpo: bytes) -> bytes:
    """Há API que devolve `{"audio": "<base64>"}`. Sem isso, o JSON é erro — e a frase diz qual."""
    try:
        dados = json.loads(corpo.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        dados = None
    if isinstance(dados, dict):
        for chave in CHAVES_DE_AUDIO_NO_JSON:
            valor = dados.get(chave)
            if isinstance(valor, str) and len(valor) > 16:
                with contextlib.suppress(ValueError):
                    return base64.b64decode(valor.split(",")[-1], validate=False)
    trecho = corpo[:200].decode("utf-8", "replace").strip()
    raise ServicoRecusou(
        f"o servidor de voz devolveu JSON em vez de áudio: {trecho!r}. Confira o corpo do pedido e "
        "o formato"
    )


def _parece_json(corpo: bytes) -> bool:
    """Sem `Content-Type` de JSON, só é JSON o que **analisa** como JSON: PCM cru pode começar com
    o byte de `{` por acaso, e confundir isso com erro mandaria um trecho bom para a reserva."""
    inicio, fim = corpo[:1], corpo.rstrip()[-1:]
    if len(corpo) > 1_000_000 or (inicio, fim) not in ((b"{", b"}"), (b"[", b"]")):
        return False
    try:
        json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return True


def _pcm_de_wav(corpo: bytes) -> tuple[bytes, int, int, int]:
    """(amostras, taxa, canais, bits) de um WAV — tolerante ao tamanho errado do stream."""
    if len(corpo) < 12 or corpo[:4] != b"RIFF" or corpo[8:12] != b"WAVE":
        raise ServicoRecusou("o servidor de voz devolveu algo que não é WAV (confira o formato)")
    posicao = 12
    taxa = canais = bits = codigo = 0
    while posicao + 8 <= len(corpo):
        marca, tamanho = (
            corpo[posicao : posicao + 4],
            struct.unpack("<I", corpo[posicao + 4 : posicao + 8])[0],
        )
        posicao += 8
        if marca == b"fmt ":
            codigo, canais, taxa = struct.unpack("<HHI", corpo[posicao : posicao + 8])
            bits = struct.unpack("<H", corpo[posicao + 14 : posicao + 16])[0]
        elif marca == b"data":
            fim = len(corpo) if tamanho in (0, 0xFFFFFFFF) else min(len(corpo), posicao + tamanho)
            if not taxa:
                raise ServicoRecusou("WAV sem o bloco fmt antes do data")
            if (codigo, bits) not in ((1, 16), (3, 32), (0xFFFE, 16)):
                raise ServicoRecusou(f"WAV com codificação {codigo}/{bits} bits: use PCM 16 bits")
            return corpo[posicao:fim], taxa, canais, bits
        posicao += tamanho + (tamanho & 1)
    raise ServicoRecusou("WAV sem o bloco de dados")


TAPS_DA_VOZ: Final = 32
"""Meia largura do núcleo sinc do reamostrador para a voz do servidor (ADR-0068, emenda)."""
_CABECALHO_WAV: Final = re.compile(rb"RIFF....WAVE", re.DOTALL)


def _wavs(corpo: bytes) -> list[bytes]:
    """O corpo cortado em cada cabeçalho WAV: o stream que manda um WAV por frase traz um
    cabeçalho novo no meio dos dados, e ele não é áudio (tocado, vira estalo e chiado)."""
    inicios = [m.start() for m in _CABECALHO_WAV.finditer(corpo)]
    if not inicios or inicios[0] != 0:
        inicios = [0, *inicios]
    return [corpo[a:b] for a, b in zip(inicios, [*inicios[1:], len(corpo)], strict=True)]


def _wav_para_16k(corpo: bytes) -> bytes:
    import numpy as np

    saida: list[bytes] = []
    for pedaco in _wavs(corpo):
        dados, taxa, canais, bits = _pcm_de_wav(pedaco)
        if bits == 32:
            sinal = np.frombuffer(dados[: len(dados) // 4 * 4], dtype="<f4") * 32767.0
            saida.append(_para_16k_mono(sinal, taxa=taxa, canais=canais))
        else:
            saida.append(_pcm16_cru(dados, taxa=taxa, canais=canais))
    return b"".join(saida)


def formato_lido(corpo: bytes, *, formato: str, taxa: int, canais: int) -> tuple[str, int, int]:
    """O formato, a taxa e os canais do áudio como ele VEIO (o do cabeçalho, num WAV): é o que o
    painel mostra e o teste compara com a configuração."""
    if corpo[:4] == b"RIFF":
        try:
            _dados, taxa_do_wav, canais_do_wav, _bits = _pcm_de_wav(_wavs(corpo)[0])
        except ServicoRecusou:
            return "wav", 0, 0
        return "wav", taxa_do_wav, canais_do_wav
    if formato == "wav":
        return "pcm", taxa, canais  # pediu WAV e veio PCM cru: lido na taxa da configuração
    return formato, taxa, canais


def _para_16k_mono(amostras: Any, *, taxa: int, canais: int) -> bytes:
    import numpy as np

    from jarvis.corpus.voz import reamostrar

    sinal = np.asarray(amostras, dtype=np.float64)
    if canais > 1:
        sinal = sinal[: (sinal.size // canais) * canais].reshape(-1, canais).mean(axis=1)
    if sinal.size == 0:
        return b""
    # Núcleo mais longo que o da medição (16): a voz que o dono ouve, de 22–48 kHz para os
    # 16 kHz do caminho de áudio, sem serrilhado nos agudos (o «chiado» dos sibilantes).
    no_alvo = reamostrar(sinal, de=taxa, para=TAXA_PADRAO, taps=TAPS_DA_VOZ)
    inteiros = np.clip(np.rint(no_alvo), -32768, 32767).astype("<i2")
    return bytes(inteiros.tobytes())


def _pcm16_cru(corpo: bytes, *, taxa: int, canais: int) -> bytes:
    import numpy as np

    quadro = BYTES_POR_AMOSTRA * canais
    util = corpo[: (len(corpo) // quadro) * quadro]  # um byte solto no fim do stream não é áudio
    amostras = np.frombuffer(util, dtype="<i2")
    if taxa == TAXA_PADRAO and canais == 1:
        return bytes(util)
    return _para_16k_mono(amostras, taxa=taxa, canais=canais)


def para_pcm16(corpo: bytes, *, formato: str, taxa: int, canais: int, tipo: str = "") -> bytes:
    """O áudio do servidor no formato do caminho de áudio do Jarvis: PCM16 16 kHz mono."""
    if tipo in ("application/json", "text/json") or _parece_json(corpo):
        corpo = _audio_do_json(corpo)
    if tipo.startswith("text/"):
        trecho = corpo[:160].decode("utf-8", "replace").strip()
        raise ServicoRecusou(f"o servidor de voz devolveu texto em vez de áudio: {trecho!r}")
    if corpo[:4] == b"RIFF":
        formato = "wav"  # tolerância: pediu pcm e veio WAV (o servidor manda o cabeçalho)
    elif formato == "wav":
        formato = "pcm"  # e o contrário: pediu WAV e veio PCM cru (o servidor ignora o formato)
    if formato == "pcm":
        return _pcm16_cru(corpo, taxa=taxa, canais=canais)
    if formato == "wav":
        return _wav_para_16k(corpo)
    from jarvis.voz.edge import DecodificadorAusente, mp3_para_pcm16

    try:
        # O `ffmpeg` detecta o contêiner (MP3, Ogg/Opus) pelo conteúdo: o mesmo decodificador do
        # Edge, em processo separado com argv explícito.
        return mp3_para_pcm16(corpo)
    except DecodificadorAusente:
        raise ServicoRecusou(
            f"o formato {formato} precisa do ffmpeg, que não está nesta máquina: instale-o ou "
            'peça PCM/WAV ao servidor (formato = "pcm")'
        ) from None


# --- o motor --------------------------------------------------------------------------------------
def saudavel(
    endpoint: Endpoint,
    *,
    prazo_s: float = PRAZO_DA_SAUDE_S,
    ambiente: Mapping[str, str] | None = None,
) -> bool:
    """A checagem barata: abre e fecha um TCP com o servidor. Sem pedido, sem texto."""
    proibir_nuvem_real_em_ci(endpoint.base, ambiente)
    try:
        with socket.create_connection((endpoint.host, endpoint.porta), timeout=prazo_s):
            return True
    except OSError:
        return False


@dataclass(frozen=True, slots=True)
class QuemFalou:
    """O que falou um trecho (ADR-0068, emenda de 2026-11-15: o dono confere no painel e no log
    se é mesmo a voz e o estilo que ele escolheu, ou a reserva)."""

    motor: str
    voz: str = ""
    estilo: str = ""
    servidor: str = ""
    via: str = ""
    """`stream`, `comum` (o caminho de síntese) ou `reserva` (o endpoint não falou)."""
    formato: str = ""
    taxa: int = 0
    """A taxa do áudio como veio do servidor (a do cabeçalho, num WAV)."""
    canais: int = 0
    motivo: str = ""
    """Na reserva: por que o endpoint não falou."""

    def frase(self) -> str:
        if self.via == "reserva":
            return (
                f"falou a reserva {self.motor}"
                + (f" (voz {self.voz})" if self.voz else "")
                + (f" — o endpoint não: {self.motivo}" if self.motivo else "")
            )
        audio = f"{self.formato} {self.taxa} Hz" if self.taxa else self.formato
        return (
            f"falou {self.servidor}: voz {self.voz or 'padrão'}, estilo {self.estilo or 'padrão'}"
            f" ({self.via}, {audio})"
        )


@dataclass(slots=True)
class MotorTtsEndpoint:
    """A voz de um servidor HTTP configurado, atrás da mesma interface dos outros motores."""

    endpoint: Endpoint
    voz: str = ""
    estilo: str = ""
    """O estilo de fala em uso: muda na hora pela janela ou pela voz do dono («fala mais calmo»)."""
    registrado: str = REGISTRADO
    nuvem_ligada: Collection[str] = ()
    cancelado: Cancelado = nunca_cancelado
    ambiente: Mapping[str, str] | None = None
    abrir_conexao: Any = field(default_factory=lambda: CONEXOES, repr=False)
    nome: str = ""
    licenca: str = ""
    onde: Onde = Onde.NUVEM
    sinteses: int = 0
    caracteres_enviados: int = 0
    descartadas_por_cancelamento: int = 0
    bytes_descartados: int = 0
    pelo_stream: int = 0
    sem_stream: bool = False
    """O servidor não tem a rota de stream (404/405/501): daqui em diante, o caminho comum."""
    ultima: QuemFalou | None = None
    """Quem falou o último trecho por este endpoint: servidor, voz, estilo e o áudio como veio."""
    _motor: Motor | None = field(default=None, repr=False)
    _chave: Chave | None = field(default=None, repr=False)
    _aberto: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if not self.nome:
            self.nome = f"endpoint:{self.endpoint.nome}"
        self.voz = self.voz or self.endpoint.voz
        self.estilo = self.estilo or self.endpoint.estilo

    def abrir(self) -> Motor:
        motor = exigir_motor(self.registrado, nuvem_ligada=self.nuvem_ligada)
        self._motor = motor
        self.licenca = motor.licenca_do_cliente
        self.endpoint = conferir(self.endpoint)
        proibir_nuvem_real_em_ci(self.endpoint.base, self.ambiente)
        self._chave = chave_do(self.endpoint, self.ambiente)
        self._aberto = True
        return motor

    @property
    def aviso(self) -> str:
        motor = self._motor or exigir_motor(self.registrado, nuvem_ligada=[self.registrado])
        return motor.frase_de_aviso

    def saudavel(self, prazo_s: float = PRAZO_DA_SAUDE_S) -> bool:
        return saudavel(self.endpoint, prazo_s=prazo_s, ambiente=self.ambiente)

    def aquecer(self) -> bool:
        """A conexão aberta antes do primeiro trecho (sem texto nenhum)."""
        if not self._aberto:
            self.abrir()
        aquecer = getattr(self.abrir_conexao, "aquecer", None)
        if not callable(aquecer):
            return False
        proibir_nuvem_real_em_ci(self.endpoint.base, self.ambiente)
        return bool(aquecer(self.endpoint.base, min(self.endpoint.prazo_s, 2.0)))

    def sintetizar(self, texto: str) -> bytes:
        """PCM16 16 kHz do trecho; vazio só quando cancela. Falha **levanta** — é o que deixa a
        reserva falar o mesmo trecho no lugar, em vez de um silêncio."""
        if not self._aberto:
            self.abrir()
        if self.cancelado():
            self.descartadas_por_cancelamento += 1
            return b""
        texto = texto_para_a_voz(texto)
        if not texto:
            return b""
        self.sinteses += 1
        self.caracteres_enviados += len(texto)
        corpo = montar_corpo(self.endpoint, texto=texto, voz=self.voz, estilo=self.estilo)
        resposta: RespostaDoEndpoint | None = None
        usou_o_stream = False
        if self.endpoint.tem_stream and not self.sem_stream:
            try:
                resposta = self._pedir(self.endpoint.caminho_stream, corpo)
                self.pelo_stream += 1
                usou_o_stream = True
            except RotaAusente:
                self.sem_stream = True
        if resposta is None:
            resposta = self._pedir(self.endpoint.caminho, corpo)
        if resposta.cancelada:
            self.descartadas_por_cancelamento += 1
            self.bytes_descartados += resposta.bytes_descartados
            return b""
        amostras = para_pcm16(
            resposta.corpo,
            formato=self.endpoint.formato,
            taxa=self.endpoint.taxa,
            canais=self.endpoint.canais,
            tipo=resposta.tipo,
        )
        if not amostras and texto.strip():
            raise ErroDoServico("o servidor de voz respondeu sem áudio")
        formato, taxa, canais = formato_lido(
            resposta.corpo,
            formato=self.endpoint.formato,
            taxa=self.endpoint.taxa,
            canais=self.endpoint.canais,
        )
        self.ultima = QuemFalou(
            motor=REGISTRADO,
            servidor=self.endpoint.nome,
            voz=self.voz,
            estilo=self.estilo,
            via="stream" if usou_o_stream else "comum",
            formato=formato,
            taxa=taxa,
            canais=canais,
        )
        return amostras

    def _pedir(self, caminho: str, corpo: bytes) -> RespostaDoEndpoint:
        return pedir(
            self.endpoint,
            caminho,
            metodo=self.endpoint.metodo,
            corpo=corpo,
            chave=self._chave,
            cancelado=self.cancelado,
            ambiente=self.ambiente,
            abrir=self.abrir_conexao,
        )


def _motivo_curto(erro: BaseException) -> str:
    return str(erro).split(". ")[0][:160] or type(erro).__name__


@dataclass(slots=True)
class MotorComReservaDeRede:
    """O endpoint, e a voz reserva no lugar dele enquanto ele não responde — sem ficar mudo.

    Diferente do `MotorComReserva` do OmniVoice (que troca uma vez e para a sessão), aqui a queda é
    **um episódio**: o servidor da rede volta quando a máquina liga. Depois de `retentar_em_s`, a
    checagem de saúde (TCP curto) diz se vale tentar; tentou e voltou, a voz do endpoint retoma.
    Seguro com as sínteses antecipadas em paralelo do `SintetizadorEmStreaming`.
    """

    principal: MotorTtsEndpoint | None
    fabricar_reserva: Callable[[], MotorDeTts]
    retentar_em_s: float = RETENTAR_EM_S
    relogio: Callable[[], float] = time.monotonic
    ao_avisar: Callable[[str], None] = field(default=lambda _frase: None, repr=False)
    """A linha curta na tela quando cai e quando volta. O app liga em `escrever_na_tela`."""
    observacao: str = ""
    motivo_da_reserva: str = ""
    nome: str = ""
    voz: str = ""
    licenca: str = ""
    onde: Onde = Onde.NUVEM
    quedas: int = 0
    pela_reserva: int = 0
    ultima: QuemFalou | None = None
    """Quem falou o último trecho: o endpoint (com voz, estilo e o áudio como veio) ou a reserva."""
    ao_mudar_quem_fala: Callable[[QuemFalou], None] = field(default=lambda _quem: None, repr=False)
    """Chamado quando muda quem fala (outro motor, voz, estilo ou formato): o app escreve no log
    e na tela, e o painel mostra."""
    _fora_ate: float = field(default=0.0, repr=False)
    _conferido: bool = field(default=False, repr=False)
    _reserva: MotorDeTts | None = field(default=None, repr=False)
    _trava: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def __post_init__(self) -> None:
        if self.principal is None:
            reserva = self._reserva_pronta()
            self.nome, self.voz = reserva.nome, reserva.voz
            self.licenca, self.onde = reserva.licenca, reserva.onde
            return
        self.nome = self.principal.nome
        self.voz = self.principal.voz
        self.licenca = self.principal.licenca
        self.onde = self.principal.onde

    @classmethod
    def ja_na_reserva(
        cls, fabricar_reserva: Callable[[], MotorDeTts], motivo: str
    ) -> MotorComReservaDeRede:
        motor = cls(principal=None, fabricar_reserva=fabricar_reserva, motivo_da_reserva=motivo)
        motor.observacao = f"endpoint de voz não roda agora, voz reserva no lugar: {motivo}"
        return motor

    @property
    def na_reserva(self) -> bool:
        return self.principal is None or self._fora_ate > 0

    @property
    def estilo(self) -> str:
        return self.principal.estilo if self.principal is not None else ""

    def definir_estilo(self, estilo: str) -> None:
        if self.principal is not None:
            self.principal.estilo = estilo

    def definir_voz(self, voz: str) -> None:
        if self.principal is not None:
            self.principal.voz = voz
            self.voz = voz

    @property
    def estilos(self) -> tuple[str, ...]:
        return self.principal.endpoint.estilos if self.principal is not None else ()

    def _reserva_pronta(self) -> MotorDeTts:
        with self._trava:
            if self._reserva is None:
                self._reserva = self.fabricar_reserva()
            return self._reserva

    def _usar_o_endpoint(self) -> bool:
        if self.principal is None:
            return False
        with self._trava:
            agora = self.relogio()
            if self._fora_ate and agora < self._fora_ate:
                return False
            if self._fora_ate or not self._conferido:
                self._conferido = True
                if not self.principal.saudavel():
                    self._cair_com(f"{self.principal.endpoint.host} não atende", agora)
                    return False
                if self._fora_ate:
                    self._fora_ate = 0.0
                    self.motivo_da_reserva = ""
                    self.ao_avisar(f"voz: {self.principal.endpoint.nome} voltou")
            return True

    def _cair_com(self, motivo: str, agora: float) -> None:
        assert self.principal is not None
        episodio_novo = not self._fora_ate
        self._fora_ate = agora + self.retentar_em_s
        self.motivo_da_reserva = motivo
        if episodio_novo:
            self.quedas += 1
            self.ao_avisar(
                f"voz: {self.principal.endpoint.nome} não respondeu ({motivo}) — falo com a voz "
                f"reserva e tento de novo em {self.retentar_em_s:.0f} s"
            )

    def sintetizar(self, texto: str) -> bytes:
        if self._usar_o_endpoint():
            assert self.principal is not None
            try:
                amostras = self.principal.sintetizar(texto)
            except Exception as erro:  # pedido do dono: o endpoint caiu, a reserva fala no lugar
                with self._trava:
                    self._cair_com(_motivo_curto(erro), self.relogio())
            else:
                if self.principal.ultima is not None:
                    self._falou(self.principal.ultima)
                return amostras
        self.pela_reserva += 1
        reserva = self._reserva_pronta()
        amostras = reserva.sintetizar(texto)
        self._falou(
            QuemFalou(
                motor=reserva.nome,
                voz=reserva.voz,
                via="reserva",
                motivo=self.motivo_da_reserva,
            )
        )
        return amostras

    def _falou(self, quem: QuemFalou) -> None:
        mudou = quem != self.ultima
        self.ultima = quem
        if mudou:
            with contextlib.suppress(Exception):
                self.ao_mudar_quem_fala(quem)

    def aquecer(self) -> bool:
        """Numa linha à parte, no começo: a conexão com o endpoint e a reserva já montada (a voz
        local carregada), para a primeira queda não custar o carregamento dela."""
        pronto = False
        if self.principal is not None:
            with contextlib.suppress(Exception):
                pronto = self._usar_o_endpoint() and self.principal.aquecer()
        with contextlib.suppress(Exception):
            reserva = self._reserva_pronta()
            if reserva.onde is Onde.LOCAL:
                reserva.sintetizar("oi")
        return pronto

    def fechar(self) -> None:
        for motor in (self.principal, self._reserva):
            fechar = getattr(motor, "fechar", None)
            if callable(fechar):
                with contextlib.suppress(Exception):
                    fechar()


def motor_endpoint(
    *,
    nome: str,
    voz: str,
    estilo: str,
    nuvem_ligada: Collection[str],
    reserva: Callable[[], MotorDeTts],
    cancelado: Cancelado = nunca_cancelado,
    ambiente: Mapping[str, str] | None = None,
    arquivo: Path | None = None,
    abrir_conexao: Any = CONEXOES,
) -> MotorComReservaDeRede:
    """O que `tts = "tts-endpoint"` monta: o endpoint com a reserva, ou já a reserva — com o
    motivo em `observacao` (endpoint inexistente, desligado, sem chave). Nada disso derruba a
    abertura do aplicativo: o Jarvis fala do mesmo jeito."""
    from jarvis.voz.chaves import SegredoAusente
    from jarvis.voz.nuvem import NuvemRealProibidaEmCI
    from jarvis.voz.registro import MotorRecusado

    try:
        escolhido = escolher(nome, ambiente=ambiente, arquivo=arquivo)
        principal = MotorTtsEndpoint(
            endpoint=escolhido,
            voz=voz,
            estilo=estilo,
            nuvem_ligada=nuvem_ligada,
            cancelado=cancelado,
            ambiente=ambiente,
            abrir_conexao=abrir_conexao,
        )
        principal.abrir()
    except (MotorRecusado, EndpointInvalido, SegredoAusente, NuvemRealProibidaEmCI) as erro:
        return MotorComReservaDeRede.ja_na_reserva(reserva, str(erro))
    motor = MotorComReservaDeRede(principal=principal, fabricar_reserva=reserva)
    motor.observacao = (
        f"servidor de voz {escolhido.nome} ({escolhido.base}), voz {principal.voz or 'padrão'}, "
        f"estilo {principal.estilo or 'padrão'} — fora do ar, a voz reserva fala no lugar"
    )
    return motor


def o_que_falta_ao_endpoint(
    nome: str, *, ambiente: Mapping[str, str] | None = None, arquivo: Path | None = None
) -> str:
    """O endpoint escolhido existe, é válido e tem a chave (quando pede)? Vazio = roda. Se o
    servidor está de pé é outra pergunta — essa, a checagem de saúde responde na hora de falar."""
    from jarvis.voz.chaves import SegredoAusente

    try:
        escolhido = escolher(nome, ambiente=ambiente, arquivo=arquivo)
        chave_do(escolhido, ambiente)
    except EndpointInvalido as erro:
        return f"endpoint de voz: {erro}"
    except SegredoAusente:
        return (
            f"falta a chave do endpoint ({escolhido.variavel_de_ambiente}): guarde no chaveiro "
            "ou exporte no shell — ela nunca vai no arquivo"
        )
    return ""


# --- o estilo pela voz do dono --------------------------------------------------------------------
SINONIMOS_DE_ESTILO: Final[dict[str, tuple[str, ...]]] = {
    "cordial": ("cordial", "normal", "padrao", "educado", "gentil", "simpatico", "de sempre"),
    "calmo": ("calmo", "calma", "tranquilo", "tranquila", "devagar", "suave", "baixinho"),
    "urgente": ("urgente", "urgencia", "apressado", "rapido", "com pressa"),
    "ironico": ("ironico", "ironia", "sarcastico", "sarcasmo", "debochado"),
    "seco": ("seco", "direto", "curto", "objetivo", "serio"),
}
"""Palavras faladas → o estilo do preset do dono. Para os estilos de outro servidor, vale o nome
dele mesmo («usa o estilo narrador»)."""
_VERBOS_DE_ESTILO: Final[frozenset[str]] = frozenset(
    [
        "fala",
        "fale",
        "falar",
        "responde",
        "responda",
        "fica",
        "fique",
        "seja",
        "usa",
        "use",
        "usar",
        "muda",
        "mude",
        "mudar",
        "troca",
        "troque",
        "trocar",
        "coloca",
        "coloque",
        "poe",
        "ponha",
        "volta",
        "volte",
        "voltar",
        "passa",
        "passe",
    ]
)
_PALAVRAS_DO_ESTILO: Final[frozenset[str]] = frozenset({"tom", "estilo", "modo", "jeito", "voz"})
_ENCHIMENTO: Final[frozenset[str]] = frozenset(
    [
        "ei",
        "oi",
        "ok",
        "jarvis",
        "por",
        "favor",
        "pfv",
        "pode",
        "voce",
        "o",
        "a",
        "os",
        "as",
        "um",
        "uma",
        "para",
        "pra",
        "pro",
        "ao",
        "aos",
        "de",
        "do",
        "da",
        "num",
        "numa",
        "com",
        "em",
        "no",
        "na",
        "forma",
        "fala",
        "mais",
        "bem",
        "pouco",
        "agora",
        "ai",
        "comigo",
        "de",
        "novo",
    ]
)


def _sem_acento(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z ]", " ", sem.lower()).split())


def comando_de_estilo(fala: str, estilos: Sequence[str], padrao: str = "") -> str | None:
    """O estilo que a fala **inteira** pede («fala mais calmo», «tom urgente», «volta ao
    normal»), dentre os `estilos` do endpoint — ou `None`: o resto vai ao cérebro como sempre.
    Conservador: a fala tem de caber toda na forma, e o alvo tem de ser um estilo que existe."""
    if not estilos:
        return None
    palavras = _sem_acento(fala).split()
    while palavras and palavras[0] in {"ei", "oi", "ok", "jarvis", "por", "favor", "pode", "voce"}:
        palavras.pop(0)
    if not palavras:
        return None
    if palavras[0] in _VERBOS_DE_ESTILO:
        palavras = palavras[1:]
    elif palavras[0] not in _PALAVRAS_DO_ESTILO:
        return None  # «tom urgente» vale; «urgente» sozinho, não (é palavra de conversa)
    resto = [p for p in palavras if p not in _ENCHIMENTO and p not in _PALAVRAS_DO_ESTILO]
    if not resto or len(resto) > 2:
        return None
    alvo = " ".join(resto)
    por_nome = {_sem_acento(e): e for e in estilos}
    if alvo in por_nome:
        return por_nome[alvo]
    for estilo, sinonimos in SINONIMOS_DE_ESTILO.items():
        if alvo in sinonimos:
            if estilo in por_nome:
                return por_nome[estilo]
            if estilo == "cordial" and padrao:
                return padrao
    if alvo in ("normal", "padrao", "de sempre") and padrao:
        return padrao
    return None


def estilos_conhecidos(endpoint: Endpoint, extras: Iterable[str] = ()) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys((*([endpoint.estilo] if endpoint.estilo else []), *endpoint.estilos, *extras))
    )
