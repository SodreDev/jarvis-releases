"""O envio no WhatsApp Web (ADR-0060, fatia D): os guardrails, todos no código.

Regras e porquês em `docs/redes-sociais-riscos.md` (§4–§6). Este módulo é puro: decide se um
envio pode acontecer (`Guardiao.decidir`), confere o contato do cabeçalho (`conferir_contato`),
monta o ritmo da digitação (`ritmo`) e guarda o registro e as pausas em arquivos 0600. Quem
executa o envio na página é `jarvis.social.enviar`, e só depois de um «pode» daqui.

Na dúvida, a resposta é sempre «não envia, só notifica o dono»."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import time
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from jarvis.social.arquivo import anexar_privado, escrever_privado

# --- os números (docs/redes-sociais-riscos.md §4.4) --------------------------------------------
TETO_RIGIDO_POR_HORA: Final = 8
TETO_RIGIDO_POR_DIA: Final = 30
"""Nenhum arquivo passa disto: o ajuste do dono só aperta."""
PADRAO_POR_HORA: Final = 4
PADRAO_POR_DIA: Final = 15
INTERVALO_MINIMO_S: Final = 180.0
"""Entre dois envios quaisquer, mesmo para contatos diferentes."""
INTERVALO_PISO_S: Final = 60.0
SILENCIO_PADRAO: Final = (0, 6)
"""Madrugada sem envio: de 0h até 6h (a hora 6 já pode)."""
REACAO_S: Final = (20.0, 90.0)
"""O atraso antes de começar a digitar: aleatório, nunca instantâneo."""
PAUSA_DE_ALERTA_S: Final = 24 * 3600.0
LIMITE_DO_TEXTO: Final = 300
"""Resposta de quem está ausente é curta; acima disto o Jarvis só notifica."""
REDES_COM_ENVIO: Final = frozenset({"whatsapp"})
ARQUIVO_DOS_ENVIOS: Final = "envios.jsonl"
"""O log 0600 de cada envio ou recusa, ao lado do `redes.toml` (nunca no repositório)."""
ALERTAS: Final = frozenset(
    {"captcha", "verificacao", "limitada", "atividade_incomum", "logout", "elementos_sumiram"}
)

# --- o conteúdo barrado (§4.4) ---------------------------------------------------------------
_DINHEIRO: Final = re.compile(
    r"(?ix)(r\$|us\$|€|"
    r"\b(pix|reais|dinheiro|grana|transfer\w*|deposit\w*|dep[oó]sito\w*|boleto\w*|"
    r"pag(a|ar|o|ue|amento)\w*|empr[eé]st\w*|emprest\w*|cart[aã]o|cr[eé]dito|d[eé]bito|"
    r"conta\s+banc\w*|ag[eê]ncia|saldo|fatura|cobran[cç]a|valor\s+de|vaquinha)\b)"
)
_SENSIVEL: Final = re.compile(
    r"(?ix)\b(cpf|cnpj|rg|senha|password|token|c[oó]digo\s+de\s+(verifica|seguran)|"
    r"c[oó]digo\s+sms|otp|2fa|chave\s+pix)\b"
)
_NUMERO_LONGO: Final = re.compile(r"\d[\d .-]{7,}\d")
"""CPF, cartão, conta, telefone, código: número longo não sai por resposta automática."""
_LINK: Final = re.compile(r"(?i)\b(https?://|www\.|[a-z0-9-]+\.(com|br|net|org|io|me|ly)\b)")


class EnvioRecusado(ValueError):
    """Uma recusa com o motivo curto (`codigo`) e a frase para o dono."""

    def __init__(self, codigo: str, frase: str) -> None:
        super().__init__(frase)
        self.codigo = codigo
        self.frase = frase


def _normal(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join("".join(c for c in base if not unicodedata.combining(c)).split())


def digitos(telefone: str) -> str:
    return re.sub(r"\D", "", telefone)


def mesmo_telefone(a: str, b: str) -> bool:
    """Compara pelos últimos 10 dígitos (DDD + número), para «+55 11 9…» casar com «11 9…».
    Menos de 8 dígitos de um dos lados não é telefone: não casa."""
    da, db = digitos(a), digitos(b)
    if len(da) < 8 or len(db) < 8:
        return False
    return da[-10:] == db[-10:] if min(len(da), len(db)) >= 10 else da[-8:] == db[-8:]


def hash_do_texto(texto: str) -> str:
    return hashlib.sha256(" ".join(texto.split()).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Permitido:
    nome: str
    telefone: str


@dataclass(frozen=True, slots=True)
class AjusteDoEnvio:
    automatico: bool = False
    """A chave mestra. Desligada (o padrão), a ferramenta de envio nem existe para o modelo."""
    ausente: bool = False
    """O dono disse que está ausente. Sem isto, nada é enviado sozinho."""
    por_hora: int = PADRAO_POR_HORA
    por_dia: int = PADRAO_POR_DIA
    intervalo_s: float = INTERVALO_MINIMO_S
    silencio: tuple[int, int] = SILENCIO_PADRAO
    permitidos: tuple[Permitido, ...] = ()

    def apertado(self) -> AjusteDoEnvio:
        """Os números dentro dos limites do código: o arquivo só aperta, nunca afrouxa."""
        inicio, fim = self.silencio
        return AjusteDoEnvio(
            automatico=self.automatico,
            ausente=self.ausente,
            por_hora=max(0, min(TETO_RIGIDO_POR_HORA, self.por_hora)),
            por_dia=max(0, min(TETO_RIGIDO_POR_DIA, self.por_dia)),
            intervalo_s=max(INTERVALO_PISO_S, self.intervalo_s),
            silencio=(inicio % 24, fim % 24),
            permitidos=self.permitidos,
        )


@dataclass(frozen=True, slots=True)
class PedidoDeEnvio:
    rede: str
    nome: str
    """O contato como está na lista permitida (quem escreveu)."""
    telefone: str
    texto: str
    escreveu_primeiro: bool
    """Há mensagem não lida dele: o Jarvis só responde, nunca inicia conversa."""
    grupo: bool = False


@dataclass(frozen=True, slots=True)
class Registro:
    momento: float
    rede: str
    contato: str
    hash: str
    resultado: str
    """`enviado`, `recusado:<codigo>` ou `pausa:<alerta>`."""


@dataclass
class HistoricoDeEnvios:
    """O log 0600 (`envios.jsonl`): rede, contato, hash do texto, hora e resultado — nunca o
    texto em claro. É dele que saem as contas do teto e do intervalo."""

    caminho: Path
    _cache: list[Registro] | None = field(default=None, repr=False)

    def registros(self) -> list[Registro]:
        if self._cache is None:
            lidos: list[Registro] = []
            try:
                linhas = self.caminho.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                linhas = []
            for linha in linhas:
                try:
                    dados = json.loads(linha)
                    lidos.append(
                        Registro(
                            float(dados["momento"]),
                            str(dados["rede"]),
                            str(dados["contato"]),
                            str(dados["hash"]),
                            str(dados["resultado"]),
                        )
                    )
                except (ValueError, KeyError, TypeError):
                    continue  # linha quebrada não derruba o teto: as outras contam
            self._cache = lidos
        return self._cache

    def anotar(self, registro: Registro) -> None:
        anexar_privado(
            self.caminho,
            json.dumps(
                {
                    "momento": registro.momento,
                    "hora": datetime.fromtimestamp(registro.momento).isoformat(timespec="seconds"),
                    "rede": registro.rede,
                    "contato": registro.contato,
                    "hash": registro.hash,
                    "resultado": registro.resultado,
                },
                ensure_ascii=False,
            ),
        )
        self.registros().append(registro)

    def enviados(self, rede: str) -> list[Registro]:
        return [r for r in self.registros() if r.rede == rede and r.resultado == "enviado"]


@dataclass
class Pausas:
    """As pausas de 24 h por sinal de alerta (§6), num arquivo 0600 (`redes-pausas.json`)."""

    caminho: Path

    def _ler(self) -> dict[str, dict[str, Any]]:
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return (
            {k: v for k, v in dados.items() if isinstance(v, dict)}
            if isinstance(dados, dict)
            else {}
        )

    def pausar(self, rede: str, alerta: str, agora: float) -> None:
        if alerta not in ALERTAS:
            raise ValueError(f"alerta desconhecido {alerta!r}")
        dados = self._ler()
        dados[rede] = {"ate": agora + PAUSA_DE_ALERTA_S, "alerta": alerta}
        escrever_privado(self.caminho, json.dumps(dados, ensure_ascii=False))

    def tirar(self, rede: str) -> None:
        """Só o dono tira a pausa antes das 24 h (pela aba)."""
        dados = self._ler()
        if dados.pop(rede, None) is not None:
            escrever_privado(self.caminho, json.dumps(dados, ensure_ascii=False))

    def ativa(self, rede: str, agora: float) -> str:
        """O alerta que pausou a rede, ou vazio se não há pausa em vigor."""
        pausa = self._ler().get(rede)
        if not pausa:
            return ""
        try:
            ate = float(pausa.get("ate", 0))
        except (TypeError, ValueError):
            return "pausa_ilegivel"  # na dúvida, pausado
        return str(pausa.get("alerta", "alerta")) if agora < ate else ""


def conteudo_barrado(texto: str) -> str:
    """O motivo, se o texto não pode sair sozinho; vazio se pode."""
    if not texto.strip():
        return "vazio"
    if len(texto) > LIMITE_DO_TEXTO:
        return "longo"
    if _DINHEIRO.search(texto):
        return "dinheiro"
    if _SENSIVEL.search(texto) or _NUMERO_LONGO.search(texto):
        return "dado_sensivel"
    if _LINK.search(texto):
        return "link"
    return ""


FRASES: Final[dict[str, str]] = {
    "desligado": "o envio automático está desligado",
    "presente": "o modo ausente está desligado: com você presente o Jarvis só propõe",
    "rede_sem_envio": "esta rede é só leitura: o Jarvis só notifica",
    "pausado": "o envio desta rede está pausado por um sinal de alerta",
    "fora_da_lista": "o contato não está na sua lista permitida",
    "ambiguo": "mais de um contato da lista bate com este: o Jarvis não escolhe",
    "nao_escreveu": "o Jarvis só responde quem escreveu primeiro",
    "grupo": "o Jarvis não responde em grupo",
    "madrugada": "é madrugada: sem envio nesse horário",
    "teto_hora": "o teto de envios por hora foi atingido",
    "teto_dia": "o teto de envios do dia foi atingido",
    "intervalo": "o último envio foi há pouco: o intervalo mínimo não passou",
    "repetido": "é o mesmo texto do envio anterior para outro contato",
    "vazio": "texto vazio",
    "longo": "texto longo demais para uma resposta automática",
    "dinheiro": "o texto fala de dinheiro ou pagamento",
    "dado_sensivel": "o texto tem dado sensível (documento, senha, código, número longo)",
    "link": "o texto tem link",
}


class Guardiao:
    """Decide cada envio. Cada recusa vira registro e notificação, nunca uma tentativa nova."""

    def __init__(
        self,
        *,
        ajuste: Callable[[], AjusteDoEnvio],
        historico: HistoricoDeEnvios,
        pausas: Pausas,
        relogio: Callable[[], float] = time.time,
    ) -> None:
        self._ajuste = ajuste
        self.historico = historico
        self.pausas = pausas
        self._relogio = relogio

    def permitido(self, nome: str, telefone: str) -> Permitido:
        """O contato da lista que casa com este (telefone; o nome confere junto)."""
        candidatos = [
            p
            for p in self._ajuste().apertado().permitidos
            if mesmo_telefone(p.telefone, telefone) and _normal(p.nome) == _normal(nome)
        ]
        if not candidatos:
            raise EnvioRecusado("fora_da_lista", FRASES["fora_da_lista"])
        if len(candidatos) > 1:
            raise EnvioRecusado("ambiguo", FRASES["ambiguo"])
        return candidatos[0]

    def decidir(self, pedido: PedidoDeEnvio) -> Permitido:
        """Devolve o contato permitido se pode enviar agora; senão levanta `EnvioRecusado`."""
        ajuste = self._ajuste().apertado()
        agora = self._relogio()
        if not ajuste.automatico:
            raise EnvioRecusado("desligado", FRASES["desligado"])
        if not ajuste.ausente:
            raise EnvioRecusado("presente", FRASES["presente"])
        if pedido.rede not in REDES_COM_ENVIO:
            raise EnvioRecusado("rede_sem_envio", FRASES["rede_sem_envio"])
        if self.pausas.ativa(pedido.rede, agora):
            raise EnvioRecusado("pausado", FRASES["pausado"])
        if pedido.grupo:
            raise EnvioRecusado("grupo", FRASES["grupo"])
        contato = self.permitido(pedido.nome, pedido.telefone)
        if not pedido.escreveu_primeiro:
            raise EnvioRecusado("nao_escreveu", FRASES["nao_escreveu"])
        motivo = conteudo_barrado(pedido.texto)
        if motivo:
            raise EnvioRecusado(motivo, FRASES[motivo])
        if na_madrugada(datetime.fromtimestamp(agora).hour, ajuste.silencio):
            raise EnvioRecusado("madrugada", FRASES["madrugada"])
        enviados = self.historico.enviados(pedido.rede)
        if sum(1 for r in enviados if agora - r.momento < 3600) >= ajuste.por_hora:
            raise EnvioRecusado("teto_hora", FRASES["teto_hora"])
        if sum(1 for r in enviados if agora - r.momento < 86_400) >= ajuste.por_dia:
            raise EnvioRecusado("teto_dia", FRASES["teto_dia"])
        if enviados and agora - enviados[-1].momento < ajuste.intervalo_s:
            raise EnvioRecusado("intervalo", FRASES["intervalo"])
        if (
            enviados
            and enviados[-1].hash == hash_do_texto(pedido.texto)
            and not mesmo_telefone(enviados[-1].contato, contato.telefone)
        ):
            raise EnvioRecusado("repetido", FRASES["repetido"])
        return contato

    def anotar(self, pedido: PedidoDeEnvio, resultado: str) -> None:
        self.historico.anotar(
            Registro(
                self._relogio(),
                pedido.rede,
                digitos(pedido.telefone) or pedido.nome,
                hash_do_texto(pedido.texto),
                resultado,
            )
        )


def na_madrugada(hora: int, silencio: tuple[int, int]) -> bool:
    inicio, fim = silencio
    if inicio == fim:
        return False
    if inicio < fim:
        return inicio <= hora < fim
    return hora >= inicio or hora < fim


# --- conferir o contato (§4.2) -----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Cabecalho:
    """O que a extensão leu no cabeçalho do chat aberto."""

    nome: str
    telefone: str = ""
    grupo: bool = False
    ambiguo: bool = False


def conferir_contato(esperado: Permitido, cabecalho: Cabecalho) -> None:
    """O chat aberto é o do contato esperado? Levanta `EnvioRecusado` se não for, ou na dúvida.

    O nome tem de bater; o telefone, quando o cabeçalho o mostra (contato salvo às vezes não
    mostra), tem de bater também. Grupo e chat ambíguo nunca passam."""
    if cabecalho.grupo:
        raise EnvioRecusado("grupo", FRASES["grupo"])
    if cabecalho.ambiguo:
        raise EnvioRecusado("ambiguo", "o cabeçalho do chat é ambíguo: o Jarvis não envia")
    if _normal(cabecalho.nome) != _normal(esperado.nome):
        raise EnvioRecusado(
            "contato_divergente", "o chat aberto não é o do contato esperado: o Jarvis não envia"
        )
    if cabecalho.telefone and not mesmo_telefone(cabecalho.telefone, esperado.telefone):
        raise EnvioRecusado(
            "telefone_divergente",
            "o telefone do chat aberto não é o do contato: o Jarvis não envia",
        )


# --- o ritmo (§4.3) ----------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Tecla:
    texto: str
    atraso_ms: int
    """Quanto esperar ANTES desta tecla."""


def reacao(aleatorio: random.Random) -> float:
    """Os segundos antes de começar a responder."""
    return aleatorio.uniform(*REACAO_S)


def ritmo(texto: str, aleatorio: random.Random, *, mediana_ms: float = 170.0) -> list[Tecla]:
    """Uma tecla por caractere, com intervalo log-normal e pausa maior depois de espaço e de
    pontuação. Sem erro de propósito (opcional pelo documento; aqui, não)."""
    sigma = 0.45
    teclas: list[Tecla] = []
    anterior = ""
    for caractere in texto:
        atraso = aleatorio.lognormvariate(math.log(mediana_ms), sigma)
        if anterior == " ":
            atraso *= 1.6
        elif anterior in ".,;:!?":
            atraso *= 2.8
        teclas.append(Tecla(caractere, int(min(1_500.0, max(40.0, atraso)))))
        anterior = caractere
    return teclas


def em_pedacos(teclas: Sequence[Tecla], teto_ms: int = 5_000) -> list[list[Tecla]]:
    """Pedaços que cabem num pedido curto à extensão (cada um < `teto_ms` de digitação)."""
    pedacos: list[list[Tecla]] = []
    atual: list[Tecla] = []
    soma = 0
    for tecla in teclas:
        if atual and soma + tecla.atraso_ms > teto_ms:
            pedacos.append(atual)
            atual, soma = [], 0
        atual.append(tecla)
        soma += tecla.atraso_ms
    if atual:
        pedacos.append(atual)
    return pedacos


def permitidos_de(linhas: Iterable[tuple[str, str]]) -> tuple[Permitido, ...]:
    return tuple(Permitido(nome.strip(), telefone.strip()) for nome, telefone in linhas)


__all__ = [
    "ALERTAS",
    "ARQUIVO_DOS_ENVIOS",
    "INTERVALO_MINIMO_S",
    "PADRAO_POR_DIA",
    "PADRAO_POR_HORA",
    "PAUSA_DE_ALERTA_S",
    "TETO_RIGIDO_POR_DIA",
    "TETO_RIGIDO_POR_HORA",
    "AjusteDoEnvio",
    "Cabecalho",
    "EnvioRecusado",
    "Guardiao",
    "HistoricoDeEnvios",
    "Pausas",
    "PedidoDeEnvio",
    "Permitido",
    "Registro",
    "Tecla",
    "conferir_contato",
    "conteudo_barrado",
    "digitos",
    "em_pedacos",
    "hash_do_texto",
    "mesmo_telefone",
    "na_madrugada",
    "reacao",
    "ritmo",
]
