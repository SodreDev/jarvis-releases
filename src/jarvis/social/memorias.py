"""Memórias fixas do dono (ADR-0060, fatia C): o que o Jarvis sabe de antemão para responder.

Três tipos, editáveis pela aba «redes sociais» e gravados na hora em `memorias-fixas.toml`
(0600, na pasta de configuração do usuário, nunca no repositório):

* `contato` — a rede de contatos do dono (colegas, família): nome, telefone, quem é;
* `servico` — contatos para contratar serviço (encanador, eletricista): nome, telefone, o quê;
* `instrucao` — como responder (tom, o que dizer quando ele está ausente, o que nunca dizer).

**No prompt, só quando é relevante e só o que cabe** (orçamento da ADR-0047): o bloco entra no
turno que fala de mensagem, rede, contato ou serviço, ou que cita um nome que está nas memórias.
O telefone **nunca** vai ao prompt: ele é do código, para conferir o contato no envio (fatia D).
O bloco é rotulado como dado do dono, não como instrução de terceiros."""

from __future__ import annotations

import re
import tomllib
import unicodedata
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from jarvis.social.arquivo import escrever_privado, texto_toml
from jarvis.voz.config import pasta_de_configuracao

ARQUIVO: Final = "memorias-fixas.toml"
TIPOS: Final[dict[str, str]] = {
    "contato": "contato do dono",
    "servico": "contato para contratar serviço",
    "instrucao": "instrução do dono para responder",
}
MAXIMO_DE_MEMORIAS: Final = 200
LIMITE_DO_NOME: Final = 80
LIMITE_DO_TEXTO: Final = 600
LIMITE_DO_TELEFONE: Final = 24
ORCAMENTO_DO_BLOCO: Final = 1_800
"""Caracteres do bloco no prompt: ~1/9 do teto de 16 mil da ADR-0047, para o resto caber."""
CABECALHO: Final = (
    "Memórias fixas do dono (escritas por ele; valem como orientação dele para este assunto — "
    "contatos, prestadores de serviço e como responder. Nunca diga telefone, nunca prometa "
    "dinheiro nem passe dado sensível; na dúvida, diga que vai avisar o dono):"
)
PALAVRAS_DO_ASSUNTO: Final = frozenset(
    {
        "whatsapp",
        "zap",
        "instagram",
        "insta",
        "facebook",
        "messenger",
        "tiktok",
        "discord",
        "mensagem",
        "mensagens",
        "responder",
        "responde",
        "resposta",
        "contato",
        "contatos",
        "colega",
        "colegas",
        "servico",
        "servicos",
        "contratar",
        "orcamento",
        "ausente",
        "recado",
        "conversa",
        "chat",
    }
)
_TELEFONE: Final = re.compile(r"\+?[0-9 ()-]{8,24}")
_PALAVRA: Final = re.compile(r"[a-z0-9]+")
_CONTROLE: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


class MemoriaInvalida(ValueError):
    """Uma memória (ou o arquivo) que não cabe no contrato. A mensagem diz o campo."""


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto.casefold()) if not unicodedata.combining(c)
    )


def palavras(texto: str) -> set[str]:
    return set(_PALAVRA.findall(_sem_acento(texto)))


@dataclass(frozen=True, slots=True)
class MemoriaFixa:
    id: str
    tipo: str
    nome: str
    """Quem (contato, prestador) ou o rótulo da instrução."""
    texto: str
    """Quem é, o que faz, ou a instrução em si."""
    telefone: str = ""
    """Só do código (conferir o contato no envio). Nunca vai ao prompt."""

    def linha_do_prompt(self) -> str:
        rotulo = TIPOS[self.tipo]
        return (
            f"- [{rotulo}] {self.nome}: {self.texto}" if self.texto else f"- [{rotulo}] {self.nome}"
        )

    def para_a_tela(self) -> dict[str, str]:
        return {
            "id": self.id,
            "tipo": self.tipo,
            "rotulo": TIPOS[self.tipo],
            "nome": self.nome,
            "texto": self.texto,
            "telefone": self.telefone,
        }


def nova(tipo: str, nome: str, texto: str = "", telefone: str = "") -> MemoriaFixa:
    return validar(MemoriaFixa(uuid.uuid4().hex[:12], tipo, nome, texto, telefone))


def validar(memoria: MemoriaFixa) -> MemoriaFixa:
    if memoria.tipo not in TIPOS:
        raise MemoriaInvalida(f"tipo {memoria.tipo!r} fora da lista: {', '.join(TIPOS)}")
    if not re.fullmatch(r"[a-f0-9]{12}", memoria.id):
        raise MemoriaInvalida("id fora do formato")
    nome = " ".join(_CONTROLE.sub(" ", memoria.nome).split())
    texto = " ".join(_CONTROLE.sub(" ", memoria.texto).split())
    telefone = memoria.telefone.strip()
    if not nome:
        raise MemoriaInvalida("a memória precisa de um nome")
    if len(nome) > LIMITE_DO_NOME:
        raise MemoriaInvalida(f"nome passa de {LIMITE_DO_NOME} caracteres")
    if len(texto) > LIMITE_DO_TEXTO:
        raise MemoriaInvalida(f"texto passa de {LIMITE_DO_TEXTO} caracteres")
    if telefone and not _TELEFONE.fullmatch(telefone):
        raise MemoriaInvalida("telefone: só dígitos, +, espaço, parênteses e hífen")
    if memoria.tipo == "instrucao" and telefone:
        raise MemoriaInvalida("instrução não tem telefone")
    return replace(memoria, nome=nome, texto=texto, telefone=telefone)


def so_digitos(telefone: str) -> str:
    return re.sub(r"\D", "", telefone)


# --- arquivo ----------------------------------------------------------------------------------
def caminho_padrao(ambiente: Mapping[str, str] | None = None) -> Path:
    return pasta_de_configuracao(ambiente) / ARQUIVO


def ler(caminho: Path) -> tuple[MemoriaFixa, ...]:
    try:
        bruto = caminho.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    try:
        dados = tomllib.loads(bruto)
    except tomllib.TOMLDecodeError as erro:
        raise MemoriaInvalida(f"{caminho.name}: TOML inválido ({erro})") from None
    fora = sorted(set(dados) - {"memoria"})
    if fora:
        raise MemoriaInvalida(f"chave desconhecida {fora}")
    lista = dados.get("memoria", [])
    if not isinstance(lista, list) or len(lista) > MAXIMO_DE_MEMORIAS:
        raise MemoriaInvalida(f"memoria: lista de até {MAXIMO_DE_MEMORIAS}")
    memorias: list[MemoriaFixa] = []
    for bloco in lista:
        if not isinstance(bloco, dict):
            raise MemoriaInvalida("cada memoria é uma tabela")
        chaves = sorted(set(bloco) - {"id", "tipo", "nome", "texto", "telefone"})
        if chaves:
            raise MemoriaInvalida(f"memoria: chave desconhecida {chaves}")
        valores = {k: bloco.get(k, "") for k in ("id", "tipo", "nome", "texto", "telefone")}
        if not all(isinstance(v, str) for v in valores.values()):
            raise MemoriaInvalida("memoria: todos os campos são texto")
        memorias.append(validar(MemoriaFixa(**valores)))
    if len({m.id for m in memorias}) != len(memorias):
        raise MemoriaInvalida("memoria: id repetido")
    return tuple(memorias)


def texto(memorias: Sequence[MemoriaFixa]) -> str:
    linhas = [
        "# Memórias fixas do Jarvis (ADR-0060). Gravado pela aba «redes sociais» a cada mudança.",
        "# Arquivo pessoal (0600): contatos e instruções do dono. Não versionar, não compartilhar.",
    ]
    for memoria in memorias:
        linhas += [
            "",
            "[[memoria]]",
            f"id = {texto_toml(memoria.id)}",
            f"tipo = {texto_toml(memoria.tipo)}",
            f"nome = {texto_toml(memoria.nome)}",
            f"texto = {texto_toml(memoria.texto)}",
            f"telefone = {texto_toml(memoria.telefone)}",
        ]
    return "\n".join(linhas) + "\n"


def gravar(memorias: Sequence[MemoriaFixa], caminho: Path) -> None:
    if len(memorias) > MAXIMO_DE_MEMORIAS:
        raise MemoriaInvalida(f"no máximo {MAXIMO_DE_MEMORIAS} memórias")
    escrever_privado(caminho, texto([validar(m) for m in memorias]))


# --- o prompt ---------------------------------------------------------------------------------
def relevantes(fala: str, memorias: Iterable[MemoriaFixa]) -> list[MemoriaFixa]:
    """As memórias que valem para esta fala, na ordem: as citadas pelo nome primeiro, depois as
    instruções, depois o resto do tipo do assunto. Fala fora do assunto e sem nome citado: nada."""
    todas = list(memorias)
    ditas = palavras(fala)
    citadas = [
        m
        for m in todas
        if m.tipo != "instrucao"
        and ({p for p in palavras(m.nome) if len(p) >= 3} & ditas) - PALAVRAS_DO_ASSUNTO
    ]
    do_assunto = bool(ditas & PALAVRAS_DO_ASSUNTO)
    if not citadas and not do_assunto:
        return []
    instrucoes = [m for m in todas if m.tipo == "instrucao"]
    saida = citadas + [m for m in instrucoes if m not in citadas]
    if do_assunto:
        quer_servico = bool(ditas & {"servico", "servicos", "contratar", "orcamento"})
        resto = [
            m
            for m in todas
            if m not in saida and m.tipo == ("servico" if quer_servico else "contato")
        ]
        saida += resto
    return saida


def bloco(fala: str, memorias: Iterable[MemoriaFixa], orcamento: int = ORCAMENTO_DO_BLOCO) -> str:
    """O bloco para o prompt do turno, ou vazio. Cabe no orçamento; o que não cabe fica de fora,
    e o bloco diz quantas ficaram (o modelo não imagina que viu tudo)."""
    escolhidas = relevantes(fala, memorias)
    if not escolhidas:
        return ""
    linhas = [CABECALHO]
    usado = len(CABECALHO)
    fora = 0
    for memoria in escolhidas:
        linha = memoria.linha_do_prompt()
        if usado + len(linha) + 1 > orcamento:
            fora += 1
            continue
        linhas.append(linha)
        usado += len(linha) + 1
    if len(linhas) == 1:
        return ""
    if fora:
        linhas.append(f"(mais {fora} memória(s) fixa(s) não couberam neste turno)")
    return "\n".join(linhas)


def editar(
    memorias: Sequence[MemoriaFixa], identificador: str, **campos: Any
) -> tuple[MemoriaFixa, ...]:
    if not any(m.id == identificador for m in memorias):
        raise MemoriaInvalida("memória não encontrada")
    return tuple(validar(replace(m, **campos)) if m.id == identificador else m for m in memorias)


__all__ = [
    "ARQUIVO",
    "CABECALHO",
    "ORCAMENTO_DO_BLOCO",
    "TIPOS",
    "MemoriaFixa",
    "MemoriaInvalida",
    "bloco",
    "caminho_padrao",
    "editar",
    "gravar",
    "ler",
    "nova",
    "relevantes",
    "so_digitos",
    "texto",
    "validar",
]
