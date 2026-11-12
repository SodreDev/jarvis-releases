"""`redes.toml`: o que o dono ligou nas redes sociais (ADR-0060). Tudo desligado por padrão.

    navegador_preferido = ""        # vazio = o navegador principal do jarvis-voz.toml

    [redes.whatsapp]
    monitorar = true
    notificar = true

O arquivo mora ao lado do `jarvis-voz.toml` (na pasta de configuração do usuário), com 0600, e é
gravado a cada clique da aba «redes sociais» — só pela janela ou pelo dono à mão. Chave
desconhecida ou valor fora do tipo recusa o arquivo inteiro, com o campo na mensagem: um ajuste
de segurança errado não pode virar o padrão em silêncio."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from jarvis.social.arquivo import escrever_privado, texto_toml
from jarvis.social.envio import (
    INTERVALO_MINIMO_S,
    PADRAO_POR_DIA,
    PADRAO_POR_HORA,
    SILENCIO_PADRAO,
    TETO_RIGIDO_POR_DIA,
    TETO_RIGIDO_POR_HORA,
    AjusteDoEnvio,
    Permitido,
)
from jarvis.social.redes import IDS, rede
from jarvis.voz.config import pasta_de_configuracao

ARQUIVO: Final = "redes.toml"
_FAMILIA: Final = re.compile(r"[a-z0-9_-]{0,40}")
_CHAVES_DE_CIMA: Final = frozenset({"navegador_preferido", "redes", "envio"})
_CHAVES_DO_ENVIO: Final = frozenset(
    {"automatico", "ausente", "por_hora", "por_dia", "intervalo_min", "silencio", "permitido"}
)
_TELEFONE: Final = re.compile(r"\+?[0-9 ()-]{8,24}")
MAXIMO_DE_PERMITIDOS: Final = 50
_CHAVES_DA_REDE: Final = frozenset({"monitorar", "notificar"})


class ConfiguracaoSocialInvalida(ValueError):
    """O `redes.toml` não cabe no contrato. A mensagem diz o campo."""


@dataclass(frozen=True, slots=True)
class AjusteDaRede:
    monitorar: bool = False
    """Abrir (ou reusar) a aba de fundo da rede e ler o estado dela."""
    notificar: bool = True
    """Com o monitor ligado, avisar o dono quando chegar mensagem. Sem monitor, não faz nada."""


@dataclass(frozen=True, slots=True)
class ConfiguracaoSocial:
    navegador_preferido: str = ""
    """A família do navegador (`brave`, `firefox`…); vazio = o principal do `jarvis-voz.toml`."""
    redes: Mapping[str, AjusteDaRede] = field(default_factory=dict)
    envio: AjusteDoEnvio = field(default_factory=AjusteDoEnvio)
    """O envio no WhatsApp (fatia D): desligado, sem ausente e sem ninguém na lista por padrão."""

    def com_envio(self, **campos: Any) -> ConfiguracaoSocial:
        novo = replace(self.envio, **campos)
        _validar_envio(novo)
        return replace(self, envio=novo)

    def ajuste(self, identificador: str) -> AjusteDaRede:
        rede(identificador)  # a rede existe
        return self.redes.get(identificador, AjusteDaRede())

    def com_rede(self, identificador: str, **campos: bool) -> ConfiguracaoSocial:
        fora = sorted(set(campos) - _CHAVES_DA_REDE)
        if fora:
            raise ConfiguracaoSocialInvalida(f"ajuste de rede desconhecido {fora}")
        novas = dict(self.redes)
        novas[identificador] = replace(self.ajuste(identificador), **campos)
        return replace(self, redes=novas)

    def com_navegador(self, familia: str) -> ConfiguracaoSocial:
        return replace(self, navegador_preferido=_familia(familia))

    def monitoradas(self) -> tuple[str, ...]:
        return tuple(r for r in IDS if self.ajuste(r).monitorar)


def caminho_padrao(ambiente: Mapping[str, str] | None = None) -> Path:
    return pasta_de_configuracao(ambiente) / ARQUIVO


def ler(caminho: Path) -> ConfiguracaoSocial:
    """O arquivo, validado. Sem arquivo: tudo desligado."""
    try:
        texto = caminho.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ConfiguracaoSocial()
    try:
        dados = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as erro:
        raise ConfiguracaoSocialInvalida(f"{caminho.name}: TOML inválido ({erro})") from None
    return de_dict(dados)


def de_dict(dados: Mapping[str, Any]) -> ConfiguracaoSocial:
    fora = sorted(set(dados) - _CHAVES_DE_CIMA)
    if fora:
        raise ConfiguracaoSocialInvalida(f"chave desconhecida {fora}")
    navegador = dados.get("navegador_preferido", "")
    if not isinstance(navegador, str):
        raise ConfiguracaoSocialInvalida("navegador_preferido: esperava texto")
    blocos = dados.get("redes", {})
    if not isinstance(blocos, dict):
        raise ConfiguracaoSocialInvalida("redes: esperava uma tabela por rede")
    redes: dict[str, AjusteDaRede] = {}
    for identificador, bloco in blocos.items():
        if identificador not in IDS:
            raise ConfiguracaoSocialInvalida(
                f"redes.{identificador}: rede desconhecida (só {', '.join(IDS)})"
            )
        if not isinstance(bloco, dict):
            raise ConfiguracaoSocialInvalida(f"redes.{identificador}: esperava uma tabela")
        fora = sorted(set(bloco) - _CHAVES_DA_REDE)
        if fora:
            raise ConfiguracaoSocialInvalida(f"redes.{identificador}: chave desconhecida {fora}")
        redes[identificador] = AjusteDaRede(
            monitorar=_logico(bloco, "monitorar", identificador, padrao=False),
            notificar=_logico(bloco, "notificar", identificador, padrao=True),
        )
    return ConfiguracaoSocial(
        navegador_preferido=_familia(navegador),
        redes=redes,
        envio=_envio(dados.get("envio", {})),
    )


def _envio(bloco: object) -> AjusteDoEnvio:
    if not isinstance(bloco, dict):
        raise ConfiguracaoSocialInvalida("envio: esperava uma tabela")
    fora = sorted(set(bloco) - _CHAVES_DO_ENVIO)
    if fora:
        raise ConfiguracaoSocialInvalida(f"envio: chave desconhecida {fora}")

    def logico(chave: str) -> bool:
        valor = bloco.get(chave, False)
        if not isinstance(valor, bool):
            raise ConfiguracaoSocialInvalida(f"envio.{chave}: esperava true ou false")
        return valor

    def inteiro(chave: str, padrao: int) -> int:
        valor = bloco.get(chave, padrao)
        if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
            raise ConfiguracaoSocialInvalida(f"envio.{chave}: esperava um inteiro >= 0")
        return int(valor)

    silencio = bloco.get("silencio", list(SILENCIO_PADRAO))
    if (
        not isinstance(silencio, list)
        or len(silencio) != 2
        or not all(
            isinstance(h, int) and not isinstance(h, bool) and 0 <= h <= 23 for h in silencio
        )
    ):
        raise ConfiguracaoSocialInvalida("envio.silencio: [hora de início, hora de fim], de 0 a 23")
    lista = bloco.get("permitido", [])
    if not isinstance(lista, list) or len(lista) > MAXIMO_DE_PERMITIDOS:
        raise ConfiguracaoSocialInvalida(f"envio.permitido: até {MAXIMO_DE_PERMITIDOS} contatos")
    permitidos = []
    for item in lista:
        if not isinstance(item, dict) or set(item) != {"nome", "telefone"}:
            raise ConfiguracaoSocialInvalida("envio.permitido: cada um tem nome e telefone")
        if not all(isinstance(v, str) for v in item.values()):
            raise ConfiguracaoSocialInvalida("envio.permitido: nome e telefone são texto")
        permitidos.append(Permitido(item["nome"].strip(), item["telefone"].strip()))
    envio = AjusteDoEnvio(
        automatico=logico("automatico"),
        ausente=logico("ausente"),
        por_hora=inteiro("por_hora", PADRAO_POR_HORA),
        por_dia=inteiro("por_dia", PADRAO_POR_DIA),
        intervalo_s=60.0 * inteiro("intervalo_min", int(INTERVALO_MINIMO_S // 60)),
        silencio=(silencio[0], silencio[1]),
        permitidos=tuple(permitidos),
    )
    _validar_envio(envio)
    return envio


def _validar_envio(envio: AjusteDoEnvio) -> None:
    """O arquivo só aperta: acima do teto rígido é recusado (não vira o teto em silêncio)."""
    if envio.por_hora > TETO_RIGIDO_POR_HORA or envio.por_dia > TETO_RIGIDO_POR_DIA:
        raise ConfiguracaoSocialInvalida(
            f"envio: o teto é de {TETO_RIGIDO_POR_HORA} por hora e {TETO_RIGIDO_POR_DIA} por dia"
        )
    for permitido in envio.permitidos:
        if not permitido.nome or len(permitido.nome) > 80:
            raise ConfiguracaoSocialInvalida("envio.permitido: nome vazio ou longo")
        if not _TELEFONE.fullmatch(permitido.telefone):
            raise ConfiguracaoSocialInvalida(
                f"envio.permitido: telefone de {permitido.nome!r} fora do formato"
            )
    chaves = [
        (p.nome.casefold(), "".join(c for c in p.telefone if c.isdigit())) for p in envio.permitidos
    ]
    if len(set(chaves)) != len(chaves):
        raise ConfiguracaoSocialInvalida("envio.permitido: contato repetido")


def _logico(bloco: Mapping[str, Any], chave: str, rede_id: str, *, padrao: bool) -> bool:
    valor = bloco.get(chave, padrao)
    if not isinstance(valor, bool):
        raise ConfiguracaoSocialInvalida(f"redes.{rede_id}.{chave}: esperava true ou false")
    return valor


def _familia(valor: str) -> str:
    texto = valor.strip().lower()
    if not _FAMILIA.fullmatch(texto):
        raise ConfiguracaoSocialInvalida(
            f"navegador_preferido: {valor[:40]!r} não é uma família de navegador"
        )
    return texto


def texto(configuracao: ConfiguracaoSocial) -> str:
    """O TOML do arquivo, com o cabeçalho que diz o que é e que está desligado por padrão."""
    linhas = [
        "# Redes sociais do Jarvis (ADR-0060). Gravado pela aba «redes sociais» a cada clique.",
        "# Tudo desligado por padrão. Arquivo pessoal (0600): não versionar, não compartilhar.",
        "",
        f"navegador_preferido = {texto_toml(configuracao.navegador_preferido)}",
    ]
    for identificador in IDS:
        if identificador not in configuracao.redes:
            continue
        ajuste = configuracao.redes[identificador]
        linhas += [
            "",
            f"[redes.{identificador}]",
            f"monitorar = {'true' if ajuste.monitorar else 'false'}",
            f"notificar = {'true' if ajuste.notificar else 'false'}",
        ]
    envio = configuracao.envio
    linhas += [
        "",
        "# Envio só no WhatsApp, só para a lista, só com «ausente» (docs/redes-sociais-riscos.md).",
        "[envio]",
        f"automatico = {'true' if envio.automatico else 'false'}",
        f"ausente = {'true' if envio.ausente else 'false'}",
        f"por_hora = {envio.por_hora}",
        f"por_dia = {envio.por_dia}",
        f"intervalo_min = {int(envio.intervalo_s // 60)}",
        f"silencio = [{envio.silencio[0]}, {envio.silencio[1]}]",
    ]
    for permitido in envio.permitidos:
        linhas += [
            "",
            "[[envio.permitido]]",
            f"nome = {texto_toml(permitido.nome)}",
            f"telefone = {texto_toml(permitido.telefone)}",
        ]
    return "\n".join(linhas) + "\n"


def gravar(configuracao: ConfiguracaoSocial, caminho: Path) -> None:
    """Grava com 0600. Relê o próprio texto antes: o que vai ao disco tem de voltar igual."""
    conteudo = texto(configuracao)
    if de_dict(tomllib.loads(conteudo)) != configuracao:  # pragma: no cover — contrato interno
        raise ConfiguracaoSocialInvalida("o texto gravado não volta igual ao ajuste")
    escrever_privado(caminho, conteudo)


__all__ = [
    "ARQUIVO",
    "AjusteDaRede",
    "ConfiguracaoSocial",
    "ConfiguracaoSocialInvalida",
    "caminho_padrao",
    "de_dict",
    "gravar",
    "ler",
    "texto",
]
