"""As vozes e os estilos que um endpoint de TTS expõe — achados de forma tolerante (ADR-0068).

Não existe rota padrão para «liste as suas vozes»: a ElevenLabs tem `/v2/voices`, a OpenAI não tem
nenhuma, um servidor caseiro tem a que o dono escreveu. Então aqui se **tenta**, em ordem, as rotas
do endpoint (`caminhos_de_vozes`) ou as comuns (`/api/voices`, `/voices`, `/v1/voices`,
`/api/tts/voices`), com prazo curto, e se aceita o que parecer uma lista: de textos, de objetos com
`id`/`name`/`voice_id`, ou um objeto com `voices`/`vozes`/`data`. Estilos vêm junto (o campo
`styles`/`estilos` de cada voz ou do topo) ou das rotas comuns de estilo. Nada achado não é erro —
é «o servidor não lista», e o painel fica com os campos livres e a lista editável.

É GET de catálogo: **nenhum texto do dono sai** por aqui, só a autenticação do endpoint, quando ele
tem uma. Por isso, como a lista de vozes da ElevenLabs, não depende do interruptor da nuvem.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from jarvis.rede import ErroDeRede
from jarvis.voz.endpoint import (
    CAMINHOS_DE_ESTILOS_COMUNS,
    CAMINHOS_DE_VOZES_COMUNS,
    FORMA_DA_VOZ,
    MAXIMO_DE_VOZES,
    PRAZO_DO_CATALOGO_S,
    Endpoint,
    chave_do,
    pedir,
)
from jarvis.voz.nuvem import CONEXOES, ServicoRecusou

CHAVES_DA_LISTA: Final[tuple[str, ...]] = (
    "voices",
    "vozes",
    "data",
    "items",
    "results",
    "speakers",
)
CHAVES_DO_ID: Final[tuple[str, ...]] = ("id", "voice_id", "voice", "slug", "name", "nome")
CHAVES_DO_NOME: Final[tuple[str, ...]] = ("name", "nome", "label", "display_name", "title")
CHAVES_DOS_ESTILOS: Final[tuple[str, ...]] = ("styles", "estilos", "style_list", "emotions")
CHAVES_DO_IDIOMA: Final[tuple[str, ...]] = ("language", "lang", "idioma", "locale")
LIMITE_DO_CATALOGO: Final = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class VozDoEndpoint:
    id: str
    nome: str
    estilos: tuple[str, ...] = ()
    idioma: str = ""

    def para_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "estilos": list(self.estilos),
            "idioma": self.idioma,
            "portugues": self.idioma.lower().startswith("pt"),
        }


@dataclass(frozen=True, slots=True)
class Catalogo:
    vozes: tuple[VozDoEndpoint, ...] = ()
    estilos: tuple[str, ...] = ()
    rota_das_vozes: str = ""
    rota_dos_estilos: str = ""
    tentadas: tuple[str, ...] = ()
    erro: str = ""
    """Não deu nem para falar com o servidor (o resto é «não lista», e não é erro)."""

    @property
    def frase(self) -> str:
        if self.erro:
            return f"não deu para consultar o servidor: {self.erro}"
        partes = []
        if self.vozes:
            partes.append(f"{len(self.vozes)} voz(es) em {self.rota_das_vozes}")
        if self.estilos:
            onde = self.rota_dos_estilos or self.rota_das_vozes
            partes.append(f"{len(self.estilos)} estilo(s) em {onde}")
        if not partes:
            return (
                "o servidor não lista vozes nem estilos nas rotas comuns ("
                + ", ".join(self.tentadas)
                + "): escreva a voz e os estilos à mão"
            )
        return "; ".join(partes)

    def para_dict(self) -> dict[str, Any]:
        return {
            "vozes": [v.para_dict() for v in self.vozes],
            "estilos": list(self.estilos),
            "frase": self.frase,
        }


def _texto_valido(valor: object) -> str:
    texto = str(valor).strip() if isinstance(valor, str | int) else ""
    return texto if texto and FORMA_DA_VOZ.fullmatch(texto) else ""


def _primeiro(dados: Mapping[str, Any], chaves: Sequence[str]) -> Any:
    for chave in chaves:
        if chave in dados and dados[chave] not in (None, "", [], {}):
            return dados[chave]
    return None


def _estilos_de(bruto: object) -> tuple[str, ...]:
    if isinstance(bruto, Mapping):
        bruto = list(bruto.keys())
    if not isinstance(bruto, list):
        return ()
    saida: list[str] = []
    for item in bruto:
        if isinstance(item, Mapping):
            item = _primeiro(item, ("id", "name", "nome", "style"))
        texto = _texto_valido(item)
        if texto:
            saida.append(texto)
    return tuple(dict.fromkeys(saida))


def _voz_de(bruto: object) -> VozDoEndpoint | None:
    if isinstance(bruto, str):
        texto = _texto_valido(bruto)
        return VozDoEndpoint(id=texto, nome=texto) if texto else None
    if not isinstance(bruto, Mapping):
        return None
    identificador = _texto_valido(_primeiro(bruto, CHAVES_DO_ID))
    if not identificador:
        return None
    nome = _texto_valido(_primeiro(bruto, CHAVES_DO_NOME)) or identificador
    idioma = _primeiro(bruto, CHAVES_DO_IDIOMA)
    return VozDoEndpoint(
        id=identificador,
        nome=nome[:64],
        estilos=_estilos_de(_primeiro(bruto, CHAVES_DOS_ESTILOS)),
        idioma=_texto_valido(idioma) if idioma is not None else "",
    )


def vozes_de_json(dados: object) -> tuple[tuple[VozDoEndpoint, ...], tuple[str, ...]]:
    """(vozes, estilos do topo) de uma resposta qualquer — vazio quando não parece lista."""
    estilos: tuple[str, ...] = ()
    lista: object = dados
    if isinstance(dados, Mapping):
        estilos = _estilos_de(_primeiro(dados, CHAVES_DOS_ESTILOS))
        lista = _primeiro(dados, CHAVES_DA_LISTA)
        if isinstance(lista, Mapping):  # {"voices": {"jarvis-br": {...}}}
            lista = [{"id": k, **(v if isinstance(v, Mapping) else {})} for k, v in lista.items()]
    if not isinstance(lista, list):
        return (), estilos
    vozes = [v for v in map(_voz_de, lista[:MAXIMO_DE_VOZES]) if v is not None]
    unicas = {v.id: v for v in vozes}
    return tuple(unicas.values()), estilos


def _obter_json(
    endpoint: Endpoint, caminho: str, ambiente: Mapping[str, str] | None, abrir: Any
) -> object | None:
    """O JSON da rota, ou `None` quando ela não existe / não é JSON. `ErroDeRede` sobe."""
    try:
        resposta = pedir(
            endpoint,
            caminho,
            metodo="GET",
            chave=chave_do(endpoint, ambiente),
            prazo_s=min(endpoint.prazo_s, PRAZO_DO_CATALOGO_S),
            ambiente=ambiente,
            abrir=abrir,
            limite=LIMITE_DO_CATALOGO,
        )
    except ServicoRecusou:
        return None
    if resposta.tipo and "json" not in resposta.tipo:
        return None
    try:
        dados: object = json.loads(resposta.corpo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return dados


def descobrir(
    endpoint: Endpoint,
    *,
    ambiente: Mapping[str, str] | None = None,
    abrir: Any = CONEXOES,
) -> Catalogo:
    """As vozes e os estilos que o servidor lista, nas rotas dele ou nas comuns."""
    rotas = endpoint.caminhos_de_vozes or CAMINHOS_DE_VOZES_COMUNS
    tentadas: list[str] = []
    vozes: tuple[VozDoEndpoint, ...] = ()
    estilos: tuple[str, ...] = ()
    rota_das_vozes = rota_dos_estilos = ""
    try:
        for rota in rotas:
            tentadas.append(rota)
            dados = _obter_json(endpoint, rota, ambiente, abrir)
            if dados is None:
                continue
            achadas, do_topo = vozes_de_json(dados)
            if achadas:
                vozes, rota_das_vozes = achadas, rota
                estilos = tuple(dict.fromkeys((*do_topo, *(e for v in achadas for e in v.estilos))))
                break
        if not estilos:
            for rota in CAMINHOS_DE_ESTILOS_COMUNS:
                tentadas.append(rota)
                dados = _obter_json(endpoint, rota, ambiente, abrir)
                if dados is None:
                    continue
                if isinstance(dados, Mapping):
                    achados = _estilos_de(_primeiro(dados, (*CHAVES_DOS_ESTILOS, "data")))
                else:
                    achados = _estilos_de(dados)
                if achados:
                    estilos, rota_dos_estilos = achados, rota
                    break
    except (ErroDeRede, OSError) as erro:
        return Catalogo(tentadas=tuple(tentadas), erro=str(erro)[:200])
    return Catalogo(
        vozes=vozes,
        estilos=estilos,
        rota_das_vozes=rota_das_vozes,
        rota_dos_estilos=rota_dos_estilos,
        tentadas=tuple(tentadas),
    )
