"""O corpo das tools `browser.*` (ADR-0027): o que roda depois que o PDP deixou passar.

O executor chama `CorposDoNavegador.executar` com o que ele **já validou** (schema do manifesto e
decisão do PDP sobre o tier estático). Aqui entra o risco **dinâmico**: antes de clicar ou digitar,
o alvo é inspecionado e o código decide se aquilo é perigoso; se for, `exigir` pergunta ao dono —
é a mesma janela e o mesmo PDP de qualquer tool perigosa, e nada que a página ou o modelo escrevam
chega a esse "sim". Tudo o que volta da página é dado de terceiro, truncado.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Final

from jarvis.navegador import risco
from jarvis.navegador.cliente import ClienteDoNavegador, NavegadorFalhou, NavegadorIndisponivel
from jarvis.politica.abertura import UrlRecusada, dominio, validar_url

FERRAMENTAS_DO_NAVEGADOR: Final = frozenset(
    {
        "browser.tabs",
        "browser.read",
        "browser.click",
        "browser.type",
        "browser.scroll",
        "browser.navigate",
    }
)
FERRAMENTA_DE_CONFIRMACAO: Final = "browser.acao_sensivel"
"""Manifesto `perigoso` que o **código** consulta no PDP; o modelo nunca a vê nem a chama."""

LIMITE_DAS_ABAS: Final = 40
LIMITE_DO_TEXTO: Final = 3_500
LIMITE_DOS_LINKS: Final = 10
LIMITE_DAS_DATAS: Final = 8
LIMITE_DO_TITULO: Final = 120
PIXELS_PADRAO: Final = 600


class AcaoRecusada(Exception):
    """O dono disse não (ou o prazo acabou), ou a política recusou: a ação **não** aconteceu."""


Exigir = Callable[[str, str], None]
"""`(detalhe, motivo)`: pergunta ao dono e volta se ele disse sim; levanta `AcaoRecusada`."""


def _curto(valor: object, limite: int) -> str:
    texto = " ".join(str(valor).split())
    return texto if len(texto) <= limite else texto[:limite] + "…"


class CorposDoNavegador:
    def __init__(self, cliente: ClienteDoNavegador) -> None:
        self.cliente = cliente

    def executar(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        *,
        contaminado: bool,
        liberados: frozenset[str],
        exigir: Exigir,
        cancelado: Callable[[], bool],
    ) -> dict[str, Any]:
        try:
            if tool_id == "browser.tabs":
                return self._abas()
            if tool_id == "browser.read":
                return self._ler(args, exigir)
            if tool_id == "browser.navigate":
                return self._navegar(args, contaminado, liberados, exigir)
            if tool_id == "browser.scroll":
                return self._rolar(args)
            if tool_id == "browser.click":
                return self._clicar(args, contaminado, liberados, exigir, cancelado)
            if tool_id == "browser.type":
                return self._digitar(args, contaminado, exigir, cancelado)
        except NavegadorFalhou as erro:
            raise ValueError(f"a página não deixou: {erro.mensagem or erro.codigo}") from None
        except NavegadorIndisponivel as erro:
            raise ValueError(str(erro)) from None
        raise ValueError(f"{tool_id} sem corpo")  # pragma: no cover — o executor filtra antes

    # --- leitura ------------------------------------------------------------------------
    def _aba(self, args: Mapping[str, Any]) -> tuple[int, str, str]:
        """A aba **já resolvida** (id fixo): a que o código inspeciona é a em que ele age."""
        aba = self.cliente.aba(args.get("tab_id"))
        identificador = aba.get("id")
        if not isinstance(identificador, int):
            raise ValueError("não há aba para agir")
        return identificador, str(aba.get("url", "")), str(aba.get("titulo", ""))

    def _abas(self) -> dict[str, Any]:
        abas = self.cliente.abas()
        return {
            "total": len(abas),
            "abas": [
                {
                    "tab_id": a.get("id"),
                    "ativa": bool(a.get("ativa")),
                    "dominio": dominio(str(a.get("url", ""))),
                    "titulo": _curto(a.get("titulo", ""), LIMITE_DO_TITULO),
                }
                for a in abas[:LIMITE_DAS_ABAS]
            ],
        }

    def _ler(self, args: Mapping[str, Any], exigir: Exigir) -> dict[str, Any]:
        tab_id, url, _ = self._aba(args)
        avaliacao = risco.avaliar_leitura(url)
        if avaliacao.confirmar:
            exigir(f"ler a página {dominio(url)}", avaliacao.confirmar)
        pagina = self.cliente.ler(tab_id)
        texto = str(pagina.get("textoVisivel", ""))
        links = list(pagina.get("links", []))
        datas = list(pagina.get("datas", []))
        return {
            "tab_id": tab_id,
            "url": _curto(pagina.get("url", url), 300),
            "titulo": _curto(pagina.get("titulo", ""), LIMITE_DO_TITULO),
            "texto": texto[:LIMITE_DO_TEXTO],
            "truncado": len(texto) > LIMITE_DO_TEXTO or len(links) > LIMITE_DOS_LINKS,
            "links": [
                {
                    "texto": _curto(link.get("texto", ""), 80),
                    "href": _curto(link.get("href", ""), 160),
                    **({"data": _curto(link["data"], 40)} if link.get("data") else {}),
                }
                for link in links[:LIMITE_DOS_LINKS]
                if isinstance(link, dict)
            ],
            "datas": [
                {"texto": _curto(d.get("texto", ""), 60), "data": _curto(d.get("data", ""), 40)}
                for d in datas[:LIMITE_DAS_DATAS]
                if isinstance(d, dict)
            ],
        }

    # --- ação ---------------------------------------------------------------------------
    def _navegar(
        self,
        args: Mapping[str, Any],
        contaminado: bool,
        liberados: frozenset[str],
        exigir: Exigir,
    ) -> dict[str, Any]:
        try:
            url = validar_url(str(args["url"]))
        except UrlRecusada as erro:
            raise ValueError(str(erro)) from None
        tab_id, _, _ = self._aba(args)
        avaliacao = risco.avaliar_navegacao(url, contaminado=contaminado, liberados=liberados)
        if avaliacao.confirmar:
            exigir(f"navegar para {dominio(url)}", avaliacao.confirmar)
        aba = self.cliente.navegar(tab_id, url).get("aba", {})
        return {"tab_id": tab_id, "url": _curto(aba.get("url", url), 300), "dominio": dominio(url)}

    def _rolar(self, args: Mapping[str, Any]) -> dict[str, Any]:
        tab_id, _, _ = self._aba(args)
        pixels = int(args.get("pixels", PIXELS_PADRAO))
        return {"tab_id": tab_id, **self.cliente.rolar(tab_id, pixels)}

    def _clicar(
        self,
        args: Mapping[str, Any],
        contaminado: bool,
        liberados: frozenset[str],
        exigir: Exigir,
        cancelado: Callable[[], bool],
    ) -> dict[str, Any]:
        tab_id, url, _ = self._aba(args)
        alvo = str(args["alvo"])
        dados = self.cliente.inspecionar(tab_id, alvo)
        avaliacao = risco.avaliar_clique(
            url, dados, alvo, contaminado=contaminado, liberados=liberados
        )
        if avaliacao.confirmar:
            exigir(f"clicar em «{_curto(alvo, 80)}» em {dominio(url)}", avaliacao.confirmar)
        if cancelado():
            raise AcaoRecusada("interrompido antes do clique")
        feito = self.cliente.clicar(tab_id, alvo)
        return {"tab_id": tab_id, "clicado": bool(feito.get("clicado")), "alvo": _curto(alvo, 80)}

    def _digitar(
        self,
        args: Mapping[str, Any],
        contaminado: bool,
        exigir: Exigir,
        cancelado: Callable[[], bool],
    ) -> dict[str, Any]:
        tab_id, url, _ = self._aba(args)
        alvo, texto = str(args["alvo"]), str(args["texto"])
        dados = self.cliente.inspecionar(tab_id, alvo)
        if not dados.get("campo"):
            raise ValueError(f"«{_curto(alvo, 80)}» não é um campo de texto")
        avaliacao = risco.avaliar_digitacao(url, dados, alvo, texto, contaminado=contaminado)
        if avaliacao.recusa:
            raise ValueError(avaliacao.recusa)
        if avaliacao.confirmar:
            exigir(
                f"digitar {len(texto)} caracteres em «{_curto(alvo, 80)}» em {dominio(url)}",
                avaliacao.confirmar,
            )
        if cancelado():
            raise AcaoRecusada("interrompido antes de digitar")
        feito = self.cliente.digitar(tab_id, alvo, texto, limpar=bool(args.get("limpar", False)))
        return {
            "tab_id": tab_id,
            "digitado": int(feito.get("digitado", 0)),
            "alvo": _curto(alvo, 80),
        }
