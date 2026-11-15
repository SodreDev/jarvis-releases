"""STT por endpoint HTTP configurável (pedido do dono, 2026-11-14: «vou configurar o meu STT pelo
app: a URL da API e a configuração»). O espelho do TTS por endpoint (ADR-0068), do lado do ouvido.

**Só a opção.** O motor local (whisper) e o reconhecimento de hoje não mudam: o `asr-endpoint`
fica desligado até o dono escolher `asr = "asr-endpoint"` **e** ligá-lo em `nuvem_ligada` — o
áudio da fala dele sai desta máquina. Fora do ar, recusado ou mal configurado, quem transcreve é
o STT local (a reserva), com uma linha curta na tela; ele volta a tentar o endpoint depois.

O que se configura (um `[[endpoint]]` em `~/.config/jarvis/stt-endpoints.toml`; o do dono vence o
do repositório pelo nome):

- `base` (http/https, sem usuário, consulta nem fragmento) e `caminho` (o da transcrição);
- `metodo` (POST ou PUT);
- `envio`: `multipart` (o arquivo num campo de formulário, como a API de transcrição da OpenAI e
  os servidores compatíveis), `binario` (o áudio cru como corpo) ou `base64` (JSON com o áudio em
  base64 num campo);
- `formato` do áudio enviado: `wav` (PCM 16 bits num WAV) ou `pcm` (cru, 16 kHz mono 16 bits);
- `campo_do_arquivo` (multipart), `campo_do_audio` (base64), `campos` extras de formulário/JSON
  sem segredo (`model = "whisper-1"`, `language = "pt"`);
- `campo_do_texto`: o caminho do texto no JSON da resposta (`text`, `results.0.transcript`);
  vazio = a resposta é o texto puro;
- `autenticacao` (nenhuma, bearer, cabecalho), `cabecalho` e `variavel_de_ambiente` — o NOME da
  variável; o valor vem do ambiente ou do chaveiro, nunca do arquivo;
- `prazo_s`.
"""

from __future__ import annotations

import base64
import io
import json
import threading
import time
import tomllib
import uuid
import wave
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Final

from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.voz.chaves import Chave, SegredoNaConfiguracao, proibir_segredo_na_configuracao, redigir
from jarvis.voz.config import pasta_de_configuracao
from jarvis.voz.endpoint import (
    AUTENTICACOES,
    CABECALHOS_PROIBIDOS,
    FORMA_DA_VARIAVEL,
    FORMA_DO_CABECALHO,
    FORMA_DO_CAMINHO,
    FORMA_DO_NOME,
    MARCAS_DE_CREDENCIAL,
    METODOS,
    PRAZO_MAXIMO_S,
    PRAZO_MINIMO_S,
    Endpoint,
    EndpointInvalido,
    conferir_base,
    normalizar,
    pedir,
)
from jarvis.voz.interface import Hipotese, Onde

REGISTRADO: Final = "asr-endpoint"
ARQUIVO_PADRAO: Final = Path(__file__).with_name("endpoints_stt.toml")
NOME_DO_ARQUIVO: Final = "stt-endpoints.toml"
ENVIOS: Final[tuple[str, ...]] = ("multipart", "binario", "base64")
FORMATOS: Final[tuple[str, ...]] = ("wav", "pcm")
PRAZO_PADRAO_S: Final = 15.0
RETENTAR_EM_S: Final = 30.0
"""Depois de cair, o endpoint é tentado de novo só depois disto (a reserva transcreve até lá)."""
LIMITE_DA_RESPOSTA: Final = 512 * 1024
FORMA_DO_CAMPO: Final = FORMA_DO_CABECALHO
"""Nome de campo de formulário/JSON: letras, números e hífen — e `_`, aceito abaixo."""
VARIAVEL_SUGERIDA: Final = "JARVIS_STT_ENDPOINT_API_KEY"


@dataclass(frozen=True, slots=True)
class EndpointStt:
    """Um servidor de STT como o dono o configurou. Dado, sem segredo nenhum."""

    nome: str
    base: str
    caminho: str = "/v1/audio/transcriptions"
    metodo: str = "POST"
    envio: str = "multipart"
    formato: str = "wav"
    campo_do_arquivo: str = "file"
    campo_do_audio: str = "audio"
    campos: tuple[tuple[str, str], ...] = ()
    """Campos extras do formulário (multipart) ou do JSON (base64), sem segredo."""
    campo_do_texto: str = "text"
    """Caminho do texto no JSON da resposta (`text`, `results.0.transcript`); vazio = texto puro."""
    autenticacao: str = "nenhuma"
    cabecalho: str = ""
    variavel_de_ambiente: str = ""
    prazo_s: float = PRAZO_PADRAO_S
    nota: str = ""

    def transporte(self) -> Endpoint:
        """O mesmo transporte HTTP do TTS (ADR-0068): sem redirecionamento, lido por pedaços,
        mensagens redigidas. Só os campos de rede e de autenticação valem ali."""
        return Endpoint(
            nome=self.nome,
            base=self.base,
            caminho=self.caminho,
            metodo=self.metodo,
            autenticacao=self.autenticacao,
            cabecalho=self.cabecalho,
            variavel_de_ambiente=self.variavel_de_ambiente,
            prazo_s=self.prazo_s,
        )

    def para_dict(self) -> dict[str, Any]:
        """Para a janela: nada aqui é segredo (a variável vai pelo nome)."""
        return {
            "nome": self.nome,
            "base": self.base,
            "caminho": self.caminho,
            "metodo": self.metodo,
            "envio": self.envio,
            "formato": self.formato,
            "campo_do_arquivo": self.campo_do_arquivo,
            "campo_do_audio": self.campo_do_audio,
            "campos": [f"{nome}={valor}" for nome, valor in self.campos],
            "campo_do_texto": self.campo_do_texto,
            "autenticacao": self.autenticacao,
            "cabecalho": self.cabecalho,
            "variavel_de_ambiente": self.variavel_de_ambiente,
            "prazo_s": self.prazo_s,
            "nota": self.nota,
        }


def _campo_valido(nome: str) -> bool:
    return bool(nome) and FORMA_DO_CAMPO.fullmatch(nome.replace("_", "-")) is not None


def conferir(endpoint: EndpointStt) -> EndpointStt:
    """Recusa o que não serve, dizendo o campo. Chamada na leitura e no `abrir`."""
    if not FORMA_DO_NOME.fullmatch(endpoint.nome):
        raise EndpointInvalido(
            f"nome {endpoint.nome!r}: letras, números, espaço, ( ) + . - (até 60)"
        )
    base = conferir_base(endpoint.base)
    if not FORMA_DO_CAMINHO.fullmatch(endpoint.caminho):
        raise EndpointInvalido(
            f"caminho {endpoint.caminho!r}: comece com uma barra (/v1/audio/transcriptions)"
        )
    if endpoint.metodo not in METODOS:
        raise EndpointInvalido(f"metodo {endpoint.metodo!r}: válidos {', '.join(METODOS)}")
    if endpoint.envio not in ENVIOS:
        raise EndpointInvalido(f"envio {endpoint.envio!r}: válidos {', '.join(ENVIOS)}")
    if endpoint.formato not in FORMATOS:
        raise EndpointInvalido(f"formato {endpoint.formato!r}: válidos {', '.join(FORMATOS)}")
    if endpoint.envio == "multipart" and not _campo_valido(endpoint.campo_do_arquivo):
        raise EndpointInvalido(f"campo_do_arquivo {endpoint.campo_do_arquivo!r}: o nome do campo")
    if endpoint.envio == "base64" and not _campo_valido(endpoint.campo_do_audio):
        raise EndpointInvalido(f"campo_do_audio {endpoint.campo_do_audio!r}: o nome do campo")
    if endpoint.campo_do_texto and not all(
        _campo_valido(p) or p.isdigit() for p in endpoint.campo_do_texto.split(".")
    ):
        raise EndpointInvalido(
            f"campo_do_texto {endpoint.campo_do_texto!r}: caminho com pontos (results.0.transcript)"
        )
    for nome, valor in endpoint.campos:
        if not _campo_valido(nome) or any(m in nome.lower() for m in MARCAS_DE_CREDENCIAL):
            raise EndpointInvalido(
                f"campos: {nome!r} não pode ser extra (autenticação vai em `autenticacao`)"
            )
        if any(c in valor for c in "\r\n\x00") or len(valor) > 256:
            raise EndpointInvalido(f"campos: o valor de {nome!r} tem quebra de linha ou é longo")
    if not PRAZO_MINIMO_S <= endpoint.prazo_s <= PRAZO_MAXIMO_S:
        raise EndpointInvalido(
            f"prazo_s {endpoint.prazo_s}: fora de {PRAZO_MINIMO_S} a {PRAZO_MAXIMO_S} s"
        )
    if endpoint.autenticacao not in AUTENTICACOES:
        raise EndpointInvalido(
            f"autenticacao {endpoint.autenticacao!r}: válidas {', '.join(AUTENTICACOES)}"
        )
    if endpoint.autenticacao != "nenhuma" and not FORMA_DA_VARIAVEL.fullmatch(
        endpoint.variavel_de_ambiente
    ):
        raise EndpointInvalido(
            "variavel_de_ambiente: com autenticação, o NOME da variável que tem a chave "
            f"(ex.: {VARIAVEL_SUGERIDA}) — o valor nunca vai no arquivo"
        )
    if endpoint.autenticacao == "cabecalho" and (
        not FORMA_DO_CABECALHO.fullmatch(endpoint.cabecalho)
        or endpoint.cabecalho.lower() in CABECALHOS_PROIBIDOS - {"authorization"}
    ):
        raise EndpointInvalido(f"cabecalho {endpoint.cabecalho!r}: o nome (ex.: X-API-Key)")
    return replace(endpoint, base=base)


def de_dados(bruto: Mapping[str, Any], *, origem: str = "") -> EndpointStt:
    """Um `[[endpoint]]` do TOML. Campo desconhecido é erro (configuração de rede escrita errado
    não pode virar outro comportamento em silêncio)."""
    conhecidos = {f.name for f in fields(EndpointStt)}
    estranhos = sorted(set(bruto) - conhecidos)
    onde = f" em {origem}" if origem else ""
    if estranhos:
        raise EndpointInvalido(f"campo(s) {', '.join(estranhos)}{onde} não existe(m)")
    try:
        proibir_segredo_na_configuracao(bruto, arquivo=origem)
    except SegredoNaConfiguracao as erro:
        raise EndpointInvalido(str(erro)) from None
    extras = bruto.get("campos", {})
    if not isinstance(extras, Mapping) or any(
        not isinstance(v, str | int | float) or isinstance(v, bool) for v in extras.values()
    ):
        raise EndpointInvalido(f"campos{onde}: uma tabela de nome = texto")
    try:
        endpoint = EndpointStt(
            nome=str(bruto.get("nome", "")).strip(),
            base=str(bruto.get("base", "")).strip(),
            caminho=str(bruto.get("caminho", "/v1/audio/transcriptions")).strip(),
            metodo=str(bruto.get("metodo", "POST")).strip().upper(),
            envio=str(bruto.get("envio", "multipart")).strip().lower(),
            formato=str(bruto.get("formato", "wav")).strip().lower(),
            campo_do_arquivo=str(bruto.get("campo_do_arquivo", "file")).strip(),
            campo_do_audio=str(bruto.get("campo_do_audio", "audio")).strip(),
            campos=tuple((str(k), str(v)) for k, v in extras.items()),
            campo_do_texto=str(bruto.get("campo_do_texto", "text")).strip(),
            autenticacao=str(bruto.get("autenticacao", "nenhuma")).strip().lower(),
            cabecalho=str(bruto.get("cabecalho", "")).strip(),
            variavel_de_ambiente=str(bruto.get("variavel_de_ambiente", "")).strip(),
            prazo_s=float(bruto.get("prazo_s", PRAZO_PADRAO_S)),
            nota=str(bruto.get("nota", "")).strip()[:200],
        )
    except (TypeError, ValueError) as erro:
        raise EndpointInvalido(f"endpoint de STT{onde}: {erro}") from None
    try:
        return conferir(endpoint)
    except EndpointInvalido as erro:
        raise EndpointInvalido(f"{endpoint.nome or 'endpoint sem nome'}{onde}: {erro}") from None


def ler(arquivo: Path) -> tuple[EndpointStt, ...]:
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
) -> tuple[EndpointStt, ...]:
    """Os do repositório e os do dono — o do dono vence pelo nome, os novos vêm no fim."""
    do_dono = ler(arquivo if arquivo is not None else arquivo_do_dono(ambiente))
    deles = {normalizar(e.nome): e for e in do_dono}
    saida = [deles.pop(normalizar(e.nome), e) for e in ler(ARQUIVO_PADRAO)]
    return (*saida, *deles.values())


def escolher(
    nome: str, *, ambiente: Mapping[str, str] | None = None, arquivo: Path | None = None
) -> EndpointStt:
    """O endpoint pelo nome (sem acento e sem caixa). Vazio = o primeiro."""
    lista = todos(ambiente=ambiente, arquivo=arquivo)
    if not lista:
        raise EndpointInvalido("nenhum endpoint de STT configurado (stt-endpoints.toml)")
    if not nome.strip():
        return lista[0]
    alvo = normalizar(nome)
    for endpoint in lista:
        if normalizar(endpoint.nome) == alvo:
            return endpoint
    raise EndpointInvalido(
        f"endpoint de STT {nome!r} não existe (há: {', '.join(e.nome for e in lista)})"
    )


# --- o pedido -------------------------------------------------------------------------------------
def em_wav(amostras: bytes, taxa: int = TAXA_PADRAO) -> bytes:
    """PCM 16 bits mono num WAV (o que quase toda API de transcrição aceita)."""
    saida = io.BytesIO()
    with wave.open(saida, "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(taxa)
        arquivo.writeframes(amostras)
    return saida.getvalue()


def montar_pedido(
    endpoint: EndpointStt, amostras: bytes, *, fronteira: str = ""
) -> tuple[bytes, str]:
    """(corpo, Content-Type) do pedido de transcrição."""
    audio = em_wav(amostras) if endpoint.formato == "wav" else amostras
    tipo_do_audio = "audio/wav" if endpoint.formato == "wav" else "application/octet-stream"
    if endpoint.envio == "binario":
        return audio, tipo_do_audio
    if endpoint.envio == "base64":
        corpo = {nome: valor for nome, valor in endpoint.campos}
        corpo[endpoint.campo_do_audio] = base64.b64encode(audio).decode("ascii")
        return json.dumps(corpo).encode("utf-8"), "application/json"
    limite = fronteira or f"jarvis-{uuid.uuid4().hex}"
    partes = bytearray()
    for nome, valor in endpoint.campos:
        partes += (
            f'--{limite}\r\nContent-Disposition: form-data; name="{nome}"\r\n\r\n{valor}\r\n'
        ).encode()
    nome_do_arquivo = "fala.wav" if endpoint.formato == "wav" else "fala.pcm"
    partes += (
        f'--{limite}\r\nContent-Disposition: form-data; name="{endpoint.campo_do_arquivo}"; '
        f'filename="{nome_do_arquivo}"\r\nContent-Type: {tipo_do_audio}\r\n\r\n'
    ).encode()
    partes += audio + f"\r\n--{limite}--\r\n".encode()
    return bytes(partes), f"multipart/form-data; boundary={limite}"


def extrair_texto(endpoint: EndpointStt, corpo: bytes) -> str:
    """O texto da resposta, pelo `campo_do_texto` (caminho com pontos). Vazio = texto puro."""
    texto = corpo.decode("utf-8", "replace")
    if not endpoint.campo_do_texto:
        return texto.strip()
    try:
        valor: Any = json.loads(texto)
    except json.JSONDecodeError:
        raise EndpointInvalido(
            "a resposta não é JSON, mas campo_do_texto pede um campo (deixe vazio para texto puro)"
        ) from None
    for parte in endpoint.campo_do_texto.split("."):
        if isinstance(valor, list) and parte.isdigit() and int(parte) < len(valor):
            valor = valor[int(parte)]
        elif isinstance(valor, Mapping) and parte in valor:
            valor = valor[parte]
        else:
            chaves = sorted(valor)[:8] if isinstance(valor, Mapping) else type(valor).__name__
            raise EndpointInvalido(
                f"a resposta não tem «{endpoint.campo_do_texto}» (no nível de «{parte}» há: "
                f"{chaves})"
            )
    if not isinstance(valor, str):
        raise EndpointInvalido(f"«{endpoint.campo_do_texto}» não é texto na resposta")
    return valor.strip()


def chave_do(endpoint: EndpointStt, ambiente: Mapping[str, str] | None = None) -> Chave | None:
    if endpoint.autenticacao == "nenhuma":
        return None
    return Chave.do_ambiente(endpoint.variavel_de_ambiente, ambiente=ambiente)


def transcrever(
    endpoint: EndpointStt,
    amostras: bytes,
    *,
    ambiente: Mapping[str, str] | None = None,
    abrir: Any = None,
) -> str:
    """Um pedido de transcrição; o texto, ou a exceção do transporte (redigida)."""
    chave = chave_do(endpoint, ambiente)
    corpo, tipo = montar_pedido(endpoint, amostras)
    extras: dict[str, Any] = {} if abrir is None else {"abrir": abrir}
    resposta = pedir(
        endpoint.transporte(),
        endpoint.caminho,
        metodo=endpoint.metodo,
        corpo=corpo,
        tipo=tipo,
        chave=chave,
        ambiente=ambiente,
        limite=LIMITE_DA_RESPOSTA,
        **extras,
    )
    return extrair_texto(endpoint, resposta.corpo)


# --- o motor --------------------------------------------------------------------------------------
@dataclass(slots=True)
class MotorAsrEndpoint:
    """O ouvido por endpoint HTTP, com a reserva local quando ele cai (o mesmo trecho vai à
    reserva; a linha curta vai à tela por `ao_avisar`). Retenta o endpoint depois de
    `RETENTAR_EM_S`."""

    endpoint: EndpointStt
    reserva: Callable[[], Any]
    """Abre o STT local (o motor de sempre) na primeira vez que precisar dele."""
    ambiente: Mapping[str, str] | None = None
    abrir_conexao: Any = None
    relogio: Callable[[], float] = time.monotonic
    ao_avisar: Callable[[str], None] | None = None
    nome: str = "stt-endpoint"
    modelo: str = ""
    licenca: str = "não se aplica (serviço configurado pelo dono)"
    idioma: str = "pt"
    onde: Onde = Onde.NUVEM
    registrado: str = REGISTRADO
    _reserva: Any = field(default=None, repr=False)
    _caiu_em: float | None = None
    _trava: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.nome = f"stt-endpoint@{self.endpoint.nome}"
        self.modelo = self.endpoint.nome

    def abrir(self) -> None:
        conferir(self.endpoint)

    def _local(self) -> Any:
        with self._trava:
            if self._reserva is None:
                self._reserva = self.reserva()
            return self._reserva

    def _avisar(self, frase: str) -> None:
        if self.ao_avisar is not None:
            self.ao_avisar(frase)

    def transcrever(self, amostras: bytes) -> Hipotese:
        agora = self.relogio()
        if self._caiu_em is None or agora - self._caiu_em >= RETENTAR_EM_S:
            try:
                texto = transcrever(
                    self.endpoint, amostras, ambiente=self.ambiente, abrir=self.abrir_conexao
                )
            except Exception as erro:  # o ouvido nunca para: a reserva transcreve
                primeira = self._caiu_em is None
                self._caiu_em = agora
                if primeira:
                    motivo = redigir(str(erro))[:160]
                    self._avisar(f"STT {self.endpoint.nome} fora ({motivo}); ouço pelo local")
            else:
                if self._caiu_em is not None:
                    self._avisar(f"STT {self.endpoint.nome} voltou")
                self._caiu_em = None
                return Hipotese(texto, 1.0 if texto else 0.0)
        hipotese: Hipotese = self._local().transcrever(amostras)
        return hipotese


def diagnostico(
    nome: str,
    *,
    ambiente: Mapping[str, str] | None = None,
    arquivo: Path | None = None,
    abrir: Any = None,
) -> list[str]:
    """O teste do endpoint que o dono roda e manda a saída: sem segredo e sem a voz dele (manda
    1 s de silêncio). Cada linha diz um fato: a configuração, a chave (presença, nunca valor), o
    pedido e o campo do texto."""
    linhas: list[str] = []
    try:
        endpoint = escolher(nome, ambiente=ambiente, arquivo=arquivo)
    except EndpointInvalido as erro:
        return [f"configuração: recusada — {erro}"]
    linhas.append(
        f"endpoint: {endpoint.nome} · {endpoint.metodo} {endpoint.base}{endpoint.caminho} · "
        f"envio {endpoint.envio} · áudio {endpoint.formato} · texto em "
        f"«{endpoint.campo_do_texto or '(corpo inteiro)'}»"
    )
    try:
        chave = chave_do(endpoint, ambiente)
    except Exception as erro:
        return [*linhas, f"chave: falta — {erro}"]
    linhas.append("chave: definida" if chave is not None else "chave: o endpoint não usa")
    silencio = b"\x00\x00" * TAXA_PADRAO
    try:
        texto = transcrever(endpoint, silencio, ambiente=ambiente, abrir=abrir)
    except Exception as erro:
        return [*linhas, f"pedido: falhou — {redigir(str(erro))[:300]}"]
    linhas.append(f"pedido: ok · texto devolvido ({len(texto)} caracteres; silêncio enviado)")
    return linhas


# --- a janela: escolher, mudar um campo, gravar no arquivo do dono ------------------------------
CAMPOS_EDITAVEIS: Final[tuple[str, ...]] = (
    "base",
    "caminho",
    "metodo",
    "envio",
    "formato",
    "campo_do_arquivo",
    "campo_do_audio",
    "campo_do_texto",
    "autenticacao",
    "cabecalho",
    "variavel_de_ambiente",
    "prazo_s",
)


def com_campo(endpoint: EndpointStt, campo: str, valor: str) -> EndpointStt:
    """O endpoint com um campo trocado, já conferido (`EndpointInvalido` diz o porquê)."""
    if campo not in CAMPOS_EDITAVEIS:
        raise EndpointInvalido(f"o campo {campo!r} não se edita pela janela")
    limpo = valor.strip()
    try:
        proibir_segredo_na_configuracao({campo: limpo})
    except SegredoNaConfiguracao as erro:
        raise EndpointInvalido(str(erro)) from None
    if campo == "prazo_s":
        try:
            novo: Any = float(limpo.replace(",", "."))
        except ValueError:
            raise EndpointInvalido(f"prazo_s {valor!r}: um número de segundos") from None
    elif campo in ("metodo",):
        novo = limpo.upper()
    elif campo in ("envio", "formato", "autenticacao"):
        novo = limpo.lower()
    else:
        novo = limpo
    return conferir(replace(endpoint, **{campo: novo}))


def _aspas(valor: str) -> str:
    return json.dumps(valor, ensure_ascii=False)


def texto_do_arquivo(endpoints: Sequence[EndpointStt]) -> str:
    linhas = [
        "# Endpoints de STT do dono (gravado pela janela do Jarvis). Sem segredo: com",
        "# autenticação, só o NOME da variável de ambiente (o valor: ambiente ou chaveiro).",
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
            f"metodo = {_aspas(e.metodo)}",
            f"envio = {_aspas(e.envio)}",
            f"formato = {_aspas(e.formato)}",
            f"campo_do_arquivo = {_aspas(e.campo_do_arquivo)}",
            f"campo_do_audio = {_aspas(e.campo_do_audio)}",
            f"campo_do_texto = {_aspas(e.campo_do_texto)}",
            f"autenticacao = {_aspas(e.autenticacao)}",
            f"cabecalho = {_aspas(e.cabecalho)}",
            f"variavel_de_ambiente = {_aspas(e.variavel_de_ambiente)}",
            f"prazo_s = {e.prazo_s}",
            f"nota = {_aspas(e.nota)}",
        ]
        if e.campos:
            linhas += ["", "[endpoint.campos]"]
            linhas += [f"{nome} = {_aspas(valor)}" for nome, valor in e.campos]
    return "\n".join(linhas) + "\n"


def gravar(endpoint: EndpointStt, *, arquivo: Path) -> Path:
    """Grava (ou troca, pelo nome) este endpoint no arquivo do dono; os outros dele ficam."""
    conferir(endpoint)
    existentes = list(ler(arquivo))
    alvo = normalizar(endpoint.nome)
    trocado = [endpoint if normalizar(e.nome) == alvo else e for e in existentes]
    if not any(normalizar(e.nome) == alvo for e in existentes):
        trocado.append(endpoint)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_name(arquivo.name + ".novo")
    temporario.write_text(texto_do_arquivo(trocado), encoding="utf-8")
    temporario.replace(arquivo)
    return arquivo


def mudar_no_endpoint(
    nome: str, campo: str, valor: str, *, ambiente: Mapping[str, str] | None = None
) -> str:
    """O clique da janela num campo: «salvo», ou o porquê de não ter salvo."""
    try:
        endpoint = com_campo(escolher(nome, ambiente=ambiente), campo, valor)
        gravar(endpoint, arquivo=arquivo_do_dono(ambiente))
    except (EndpointInvalido, OSError) as erro:
        return f"não salvei: {erro}"
    return "salvo"


def para_a_janela(nome: str, *, ambiente: Mapping[str, str] | None = None) -> dict[str, Any]:
    """O que o painel de STT mostra: os endpoints, o escolhido e as opções. Nunca levanta (a
    abertura não pode cair por um arquivo ruim): o erro vira `erro`."""
    dados: dict[str, Any] = {
        "endpoints": [],
        "ativo": {},
        "envios": list(ENVIOS),
        "formatos": list(FORMATOS),
        "autenticacoes": list(AUTENTICACOES),
        "erro": "",
    }
    try:
        lista = todos(ambiente=ambiente)
        ativo = escolher(nome, ambiente=ambiente)
    except EndpointInvalido as erro:
        dados["erro"] = str(erro)
        return dados
    dados["endpoints"] = [
        {"nome": e.nome, "escolhido": normalizar(e.nome) == normalizar(ativo.nome)} for e in lista
    ]
    dados["ativo"] = ativo.para_dict()
    return dados


def nomes(*, ambiente: Mapping[str, str] | None = None) -> Sequence[str]:
    try:
        return [e.nome for e in todos(ambiente=ambiente)]
    except EndpointInvalido:
        return []


__all__ = [
    "CAMPOS_EDITAVEIS",
    "ENVIOS",
    "FORMATOS",
    "REGISTRADO",
    "EndpointInvalido",
    "EndpointStt",
    "MotorAsrEndpoint",
    "com_campo",
    "conferir",
    "de_dados",
    "diagnostico",
    "em_wav",
    "escolher",
    "extrair_texto",
    "gravar",
    "ler",
    "montar_pedido",
    "mudar_no_endpoint",
    "nomes",
    "para_a_janela",
    "todos",
    "transcrever",
]
