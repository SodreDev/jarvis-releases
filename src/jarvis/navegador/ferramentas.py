"""O corpo das tools `browser.*` (ADR-0027): o que roda depois que o PDP deixou passar.

O executor chama `CorposDoNavegador.executar` com o que ele **já validou** (schema do manifesto e
decisão do PDP sobre o tier estático). Aqui entra o risco **dinâmico**: antes de clicar, digitar ou
acionar, o alvo é inspecionado e o código decide se aquilo é perigoso; se for, `exigir` pergunta ao
dono — é a mesma janela e o mesmo PDP de qualquer tool perigosa, e nada que a página ou o modelo
escrevam chega a esse "sim". Tudo o que volta da página é dado de terceiro, truncado.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from typing import Any, Final

from jarvis.navegador import risco
from jarvis.navegador.cliente import ClienteDoNavegador, NavegadorFalhou, NavegadorIndisponivel
from jarvis.politica.abertura import UrlRecusada, dominio, validar_url
from jarvis.politica.objetivo import Objetivo

FERRAMENTAS_DO_NAVEGADOR: Final = frozenset(
    {
        "browser.tabs",
        "browser.read",
        "browser.click",
        "browser.type",
        "browser.scroll",
        "browser.navigate",
        "browser.inspecionar",
        "browser.acionar",
    }
)
FERRAMENTA_DE_CONFIRMACAO: Final = "browser.acao_sensivel"
"""Manifesto `perigoso` que o **código** consulta no PDP; o modelo nunca a vê nem a chama."""
FERRAMENTA_DE_ESTADO: Final = "browser.estado"
"""Livre e fora de `FERRAMENTAS_DO_NAVEGADOR`: existe com o controle desligado e não fala com a
extensão — o corpo é o `jarvis.navegador.estado`, não este cliente."""

LIMITE_DAS_ABAS: Final = 40
LIMITE_DO_TEXTO: Final = 3_500
LIMITE_DOS_LINKS: Final = 10
LIMITE_DAS_DATAS: Final = 8
LIMITE_DO_TITULO: Final = 120
PIXELS_PADRAO: Final = 600
LIMITE_DO_MAPA: Final = 30
"""Elementos do mapa que voltam ao modelo (o resultado inteiro cabe em ~6000 caracteres): o resto
se pede com `tipo` e `texto`, e o total vai junto."""
LIMITE_DOS_SCRIPTS: Final = 10
PAPEIS_DE_CAMPO: Final = frozenset({"textbox", "searchbox", "combobox"})
PAPEIS_DE_BOTAO: Final = frozenset(
    {"button", "menuitem", "tab", "checkbox", "radio", "switch", "option"}
)
FRASE_DA_ACAO: Final[dict[str, str]] = {
    "clicar": "clicar em",
    "focar": "pôr o foco em",
    "passar_o_mouse": "passar o mouse em",
    "tecla": "apertar uma tecla em",
    "enviar": "enviar o formulário de",
    "selecionar": "escolher uma opção em",
}


class AcaoRecusada(Exception):
    """O dono disse não (ou o prazo acabou), ou a política recusou: a ação **não** aconteceu."""


Exigir = Callable[[str, str], None]
"""`(detalhe, motivo)`: pergunta ao dono e volta se ele disse sim; levanta `AcaoRecusada`."""


def _curto(valor: object, limite: int) -> str:
    texto = " ".join(str(valor).split())
    return texto if len(texto) <= limite else texto[:limite] + "…"


def _alvo_ou_ref(args: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """O elemento pelo texto visível (`alvo`) ou pela referência do mapa (`ref`): um dos dois."""
    alvo, ref = args.get("alvo"), args.get("ref")
    if bool(alvo) == bool(ref):
        raise ValueError(
            "diga o elemento pelo texto (alvo) ou pela referência do mapa (ref), um dos dois"
        )
    return (str(alvo) if alvo else None), (str(ref) if ref else None)


def _nome(alvo: str | None, dados: Mapping[str, Any]) -> str:
    """Como o elemento é chamado na pergunta ao dono e no risco: o texto que o modelo disse ou o
    rótulo que a página dá — nunca o valor de um campo."""
    return alvo or str(dados.get("rotulo") or "") or "o elemento"


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).casefold()


def _elemento_para_o_modelo(elemento: Mapping[str, Any]) -> dict[str, Any]:
    """Só o que ajuda a escolher e a ligar à tela: o que é falso ou vazio fica de fora."""
    saida: dict[str, Any] = {
        "ref": elemento.get("ref"),
        "papel": elemento.get("papel"),
        "rotulo": _curto(elemento.get("rotulo", ""), 80),
        "caixa": elemento.get("caixa"),
    }
    for chave in ("nome", "tipo", "expandido"):
        if elemento.get(chave):
            saida[chave] = _curto(elemento[chave], 40)
    if elemento.get("href"):
        saida["href"] = _curto(elemento["href"], 120)
    seletor = str(elemento.get("seletor") or "")
    if seletor and len(seletor) <= 80:
        saida["seletor"] = seletor
    for chave in ("desabilitado", "marcado"):
        if elemento.get(chave):
            saida[chave] = True
    if not elemento.get("naTela", True):
        saida["fora_da_tela"] = True
    if elemento.get("campoDeBusca"):
        saida["busca"] = True
    for chave, limite in (("manipuladores", 6), ("chama", 4), ("scripts", 4)):
        valores = elemento.get(chave)
        if isinstance(valores, list) and valores:
            saida[chave] = [_curto(v, 40) for v in valores[:limite]]
    return saida


def _do_tipo(elemento: Mapping[str, Any], tipo: str) -> bool:
    papel = str(elemento.get("papel", ""))
    if tipo == "campos":
        return bool(elemento.get("campo")) or papel in PAPEIS_DE_CAMPO
    if tipo == "botoes":
        return papel in PAPEIS_DE_BOTAO
    if tipo == "links":
        return papel == "link"
    return True


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
        objetivo: Objetivo | None = None,
    ) -> dict[str, Any]:
        try:
            if tool_id == "browser.tabs":
                return self._abas()
            if tool_id == "browser.read":
                return self._ler(args, exigir)
            if tool_id == "browser.navigate":
                return self._navegar(args, contaminado, liberados, exigir, objetivo)
            if tool_id == "browser.scroll":
                return self._rolar(args)
            if tool_id == "browser.click":
                return self._clicar(args, contaminado, liberados, exigir, cancelado, objetivo)
            if tool_id == "browser.type":
                return self._digitar(args, contaminado, exigir, cancelado, objetivo)
            if tool_id == "browser.inspecionar":
                return self._inspecionar(args, exigir)
            if tool_id == "browser.acionar":
                return self._acionar(args, contaminado, liberados, exigir, cancelado, objetivo)
        except NavegadorFalhou as erro:
            # O código entre parênteses é o da extensão (alvo_ausente, campo_sensivel…): ajuda o
            # modelo a escolher outro caminho e é o que a trilha de diagnóstico guarda.
            raise ValueError(
                f"a página não deixou ({erro.codigo}): {erro.mensagem or erro.codigo}"
            ) from None
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

    def _inspecionar(self, args: Mapping[str, Any], exigir: Exigir) -> dict[str, Any]:
        """O mapa da página (ADR-0032): elementos interativos com `ref`, papel, rótulo, estado,
        caixa em pixels da captura e manipuladores visíveis; e, se pedido, os scripts, ligados
        aos elementos pelo id (`s1`…). Tudo é dado de terceiros, como a leitura."""
        tab_id, url, _ = self._aba(args)
        avaliacao = risco.avaliar_leitura(url)
        if avaliacao.confirmar:
            exigir(f"inspecionar a página {dominio(url)}", avaliacao.confirmar)
        mapa = self.cliente.mapear(tab_id)
        tipo = str(args.get("tipo", "tudo"))
        procurado = _sem_acento(str(args.get("texto", "")).strip())
        elementos = [
            e
            for e in mapa.get("elementos", [])
            if isinstance(e, dict)
            and _do_tipo(e, tipo)
            and (
                not procurado
                or procurado
                in _sem_acento(f"{e.get('rotulo', '')} {e.get('nome', '')} {e.get('href', '')}")
            )
        ]
        scripts = [s for s in mapa.get("scripts", []) if isinstance(s, dict)]
        com_scripts = bool(args.get("scripts", False))
        limite = LIMITE_DO_MAPA // 2 if com_scripts else LIMITE_DO_MAPA
        saida: dict[str, Any] = {
            "tab_id": tab_id,
            "instantaneo": mapa.get("instantaneo"),
            "url": _curto(mapa.get("url", url), 300),
            "titulo": _curto(mapa.get("titulo", ""), LIMITE_DO_TITULO),
            "dpr": mapa.get("dpr"),
            "viewport": mapa.get("viewport"),
            "rolagem": mapa.get("rolagem"),
            "total_na_pagina": mapa.get("total"),
            "achados": len(elementos),
            "elementos": [_elemento_para_o_modelo(e) for e in elementos[:limite]],
            "scripts_na_pagina": len(scripts),
        }
        if com_scripts:
            saida["scripts"] = [
                {
                    "id": s.get("id"),
                    "src": _curto(s.get("src", ""), 120) or "inline",
                    "tamanho": s.get("tamanho"),
                    **({"resumo": _curto(s["resumo"], 100)} if s.get("resumo") else {}),
                    **({"define": list(s["define"])[:6]} if s.get("define") else {}),
                }
                for s in scripts[:LIMITE_DOS_SCRIPTS]
            ]
        return saida

    # --- ação ---------------------------------------------------------------------------
    def _navegar(
        self,
        args: Mapping[str, Any],
        contaminado: bool,
        liberados: frozenset[str],
        exigir: Exigir,
        objetivo: Objetivo | None = None,
    ) -> dict[str, Any]:
        try:
            url = validar_url(str(args["url"]))
        except UrlRecusada as erro:
            raise ValueError(str(erro)) from None
        nova_aba = bool(args.get("nova_aba", False))
        # A aba atual é o padrão (dono, 2026-10-20): link aberto em aba nova a cada passo enchia o
        # navegador. Aba nova só quando o dono pede.
        tab_id = None if nova_aba else self._aba(args)[0]
        avaliacao = risco.avaliar_navegacao(
            url, contaminado=contaminado, liberados=liberados, objetivo=objetivo
        )
        if avaliacao.confirmar:
            exigir(f"navegar para {dominio(url)}", avaliacao.confirmar)
        if tab_id is None:
            aba = dict(self.cliente.abrir(url).get("aba", {}))
            tab_id = aba.get("id") if isinstance(aba.get("id"), int) else None
        else:
            aba = dict(self.cliente.navegar(tab_id, url).get("aba", {}))
        return {
            "tab_id": tab_id,
            "url": _curto(aba.get("url", url), 300),
            "dominio": dominio(url),
            "nova_aba": nova_aba,
        }

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
        objetivo: Objetivo | None = None,
    ) -> dict[str, Any]:
        tab_id, url, _ = self._aba(args)
        alvo, ref = _alvo_ou_ref(args)
        dados = self.cliente.inspecionar(tab_id, alvo, ref=ref)
        nome = _nome(alvo, dados)
        avaliacao = risco.avaliar_clique(
            url, dados, nome, contaminado=contaminado, liberados=liberados, objetivo=objetivo
        )
        if avaliacao.confirmar:
            exigir(f"clicar em «{_curto(nome, 80)}» em {dominio(url)}", avaliacao.confirmar)
        if cancelado():
            raise AcaoRecusada("interrompido antes do clique")
        feito = self.cliente.clicar(tab_id, alvo, ref=ref)
        return {"tab_id": tab_id, "clicado": bool(feito.get("clicado")), "alvo": _curto(nome, 80)}

    def _acionar(
        self,
        args: Mapping[str, Any],
        contaminado: bool,
        liberados: frozenset[str],
        exigir: Exigir,
        cancelado: Callable[[], bool],
        objetivo: Objetivo | None = None,
    ) -> dict[str, Any]:
        """A ação do DOM quando o clique simples não basta (ADR-0032): o mesmo risco do clique,
        com o «enviar» e o Enter num campo contando como envio do formulário."""
        tab_id, url, _ = self._aba(args)
        alvo, ref = _alvo_ou_ref(args)
        acao = str(args["acao"])
        tecla = str(args.get("tecla", ""))
        valor = args.get("valor")
        dados = self.cliente.inspecionar(tab_id, alvo, ref=ref)
        nome = _nome(alvo, dados)
        avaliacao = risco.avaliar_acionamento(
            url,
            dados,
            nome,
            acao,
            tecla=tecla,
            contaminado=contaminado,
            liberados=liberados,
            objetivo=objetivo,
        )
        if avaliacao.recusa:
            raise ValueError(avaliacao.recusa)
        if avaliacao.confirmar:
            exigir(
                f"{FRASE_DA_ACAO.get(acao, acao)} «{_curto(nome, 80)}» em {dominio(url)}",
                avaliacao.confirmar,
            )
        if cancelado():
            raise AcaoRecusada("interrompido antes de acionar")
        feito = self.cliente.acionar(
            tab_id,
            acao,
            alvo,
            ref=ref,
            tecla=tecla or None,
            valor=str(valor) if valor else None,
        )
        return {
            "tab_id": tab_id,
            "acionado": acao,
            "alvo": _curto(nome, 80),
            "enviado": bool(feito.get("enviado")),
        }

    def _digitar(
        self,
        args: Mapping[str, Any],
        contaminado: bool,
        exigir: Exigir,
        cancelado: Callable[[], bool],
        objetivo: Objetivo | None = None,
    ) -> dict[str, Any]:
        tab_id, url, _ = self._aba(args)
        alvo, ref = _alvo_ou_ref(args)
        texto = str(args["texto"])
        dados = self.cliente.inspecionar(tab_id, alvo, ref=ref)
        nome = _nome(alvo, dados)
        if not dados.get("campo"):
            raise ValueError(f"«{_curto(nome, 80)}» não é um campo de texto")
        avaliacao = risco.avaliar_digitacao(
            url, dados, nome, texto, contaminado=contaminado, objetivo=objetivo
        )
        if avaliacao.recusa:
            raise ValueError(avaliacao.recusa)
        if avaliacao.confirmar:
            exigir(
                f"digitar {len(texto)} caracteres em «{_curto(nome, 80)}» em {dominio(url)}",
                avaliacao.confirmar,
            )
        if cancelado():
            raise AcaoRecusada("interrompido antes de digitar")
        feito = self.cliente.digitar(
            tab_id, alvo, texto, limpar=bool(args.get("limpar", False)), ref=ref
        )
        return {
            "tab_id": tab_id,
            "digitado": int(feito.get("digitado", 0)),
            "alvo": _curto(nome, 80),
        }
