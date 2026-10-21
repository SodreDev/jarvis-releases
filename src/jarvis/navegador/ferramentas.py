"""O corpo das tools `browser.*` (ADR-0027): o que roda depois que o PDP deixou passar.

O executor chama `CorposDoNavegador.executar` com o que ele **já validou** (schema do manifesto e
decisão do PDP sobre o tier estático). Aqui entra o risco **dinâmico**: antes de clicar, digitar ou
acionar, o alvo é inspecionado e o código decide se aquilo é perigoso; se for, `exigir` pergunta ao
dono — é a mesma janela e o mesmo PDP de qualquer tool perigosa, e nada que a página ou o modelo
escrevam chega a esse "sim". Tudo o que volta da página é dado de terceiro, truncado.
"""

from __future__ import annotations

import threading
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from jarvis.imagem import CHAVE_DOS_ANEXOS, ImagemInvalida, da_url_de_dados
from jarvis.navegador import risco
from jarvis.navegador.cliente import ClienteDoNavegador, NavegadorFalhou, NavegadorIndisponivel
from jarvis.politica.abertura import UrlRecusada, dominio, validar_url
from jarvis.politica.metodo import quer_ver
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
        "browser.tela",
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
TRABALHOS_LEMBRADOS: Final = 16
"""Objetivos (o pedido do turno, os das tarefas) cujo trabalho no navegador fica lembrado."""


@dataclass(slots=True)
class Trabalho:
    """O que o Jarvis está fazendo no navegador por um objetivo (o pedido do turno ou o de uma
    tarefa, ADR-0030 emenda C2) — do código, nunca do modelo nem da página."""

    objetivo: Objetivo
    """Guardado por referência: o id do objeto não volta a valer para outro objetivo."""
    ver: bool
    """O dono quer ver o resultado (`quer_ver` da fala): a página termina à vista dele."""
    aba: int | None = None
    """A aba em que ele está trabalhando: a última que ele abriu, navegou ou em que agiu. A
    próxima `browser.*` sem `tab_id` age nela — e não na aba do dono que estiver à frente."""


class AcaoRecusada(Exception):
    """O dono disse não (ou o prazo acabou), ou a política recusou: a ação **não** aconteceu."""


Exigir = Callable[[str, str, str], None]
"""`(detalhe, motivo, causa)`: pergunta ao dono e volta se ele disse sim; levanta `AcaoRecusada`.
O detalhe e o motivo são a frase da janela; a causa é o código que a trilha grava."""


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
        self._trava = threading.Lock()
        self._trabalhos: dict[int, Trabalho] = {}

    def trabalho(self, objetivo: Objetivo | None) -> Trabalho | None:
        """O trabalho no navegador deste objetivo (o turno e cada tarefa têm o seu). Sem objetivo
        (sem fala do dono), nada é lembrado — o comportamento de antes."""
        if objetivo is None:
            return None
        with self._trava:
            achado = self._trabalhos.get(id(objetivo))
            if achado is None or achado.objetivo is not objetivo:
                achado = Trabalho(objetivo, ver=quer_ver(objetivo.pedido))
                self._trabalhos[id(objetivo)] = achado
                while len(self._trabalhos) > TRABALHOS_LEMBRADOS:
                    del self._trabalhos[next(iter(self._trabalhos))]
            return achado

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
        trabalho = self.trabalho(objetivo)
        try:
            if tool_id == "browser.tabs":
                return self._abas()
            if tool_id == "browser.navigate":
                return self._navegar(args, contaminado, liberados, exigir, objetivo, trabalho)
            args = self._na_aba_de_trabalho(args, trabalho)
            resultado: dict[str, Any] | None = None
            if tool_id == "browser.read":
                resultado = self._ler(args, exigir)
            elif tool_id == "browser.scroll":
                resultado = self._rolar(args)
            elif tool_id == "browser.click":
                resultado = self._clicar(args, contaminado, liberados, exigir, cancelado, objetivo)
            elif tool_id == "browser.type":
                resultado = self._digitar(args, contaminado, exigir, cancelado, objetivo)
            elif tool_id == "browser.inspecionar":
                resultado = self._inspecionar(args, exigir)
            elif tool_id == "browser.tela":
                resultado = self._tela(args, exigir)
            elif tool_id == "browser.acionar":
                resultado = self._acionar(args, contaminado, liberados, exigir, cancelado, objetivo)
            if resultado is not None:
                if trabalho is not None and isinstance(resultado.get("tab_id"), int):
                    trabalho.aba = resultado["tab_id"]
                return resultado
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

    def _na_aba_de_trabalho(
        self, args: Mapping[str, Any], trabalho: Trabalho | None
    ) -> Mapping[str, Any]:
        """Sem `tab_id`, a `browser.*` age na aba em que o Jarvis está trabalhando neste objetivo
        (a que ele abriu ou navegou, inclusive a de fundo), e não na aba do dono que estiver à
        frente — antes, ler depois de abrir algo em segundo plano lia a página errada. Se ela
        fechou, volta a valer a aba do dono."""
        if args.get("tab_id") is not None or trabalho is None or trabalho.aba is None:
            return args
        try:
            self.cliente.aba(trabalho.aba)
        except NavegadorFalhou:
            trabalho.aba = None
            return args
        return {**args, "tab_id": trabalho.aba}

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
            exigir(f"ler a página {dominio(url)}", avaliacao.confirmar, avaliacao.causa)
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
            exigir(f"inspecionar a página {dominio(url)}", avaliacao.confirmar, avaliacao.causa)
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

    def _tela(self, args: Mapping[str, Any], exigir: Exigir) -> dict[str, Any]:
        """A tela da aba (ADR-0032, emenda de 2026-10-20): a imagem vai como **anexo** — nunca no
        texto —, e o texto traz os três artefatos separados, tela, inspeção e scripts, com o mesmo
        instantâneo. As caixas dos elementos vêm em pixels desta imagem."""
        tab_id, url, _ = self._aba(args)
        avaliacao = risco.avaliar_leitura(url)
        if avaliacao.confirmar:
            exigir(f"ver a tela de {dominio(url)}", avaliacao.confirmar, avaliacao.causa)
        captura = self.cliente.capturar(tab_id)
        mapa = captura.get("mapa")
        mapa = mapa if isinstance(mapa, dict) else {}
        instantaneo = str(mapa.get("instantaneo") or "sem-mapa")
        try:
            imagem = da_url_de_dados(captura.get("imagem"), f"tela:{instantaneo}")
        except ImagemInvalida as erro:
            raise ValueError(str(erro)) from None
        dpr = float(mapa.get("dpr") or 1)
        viewport = mapa.get("viewport") if isinstance(mapa.get("viewport"), list) else []
        # A caixa do mapa é CSS × dpr; se a captura veio noutra escala, ela acompanha a imagem.
        escala = imagem.largura / (float(viewport[0]) * dpr) if viewport and viewport[0] else 1.0
        elementos = []
        for elemento in mapa.get("elementos", []):
            if not (isinstance(elemento, dict) and elemento.get("naTela")):
                continue
            caixa = elemento.get("caixa")
            if abs(escala - 1) > 0.02 and isinstance(caixa, list):
                elemento = {**elemento, "caixa": [round(float(v) * escala) for v in caixa]}
            elementos.append(elemento)
        scripts = [s for s in mapa.get("scripts", []) if isinstance(s, dict)]
        ligados = sorted(
            {str(s) for e in elementos for s in e.get("scripts", []) if isinstance(s, str)}
        )
        return {
            "tab_id": tab_id,
            "instantaneo": instantaneo,
            "url": _curto(mapa.get("url", url), 300),
            "titulo": _curto(mapa.get("titulo", ""), LIMITE_DO_TITULO),
            "tela": {
                "id": imagem.id,
                "formato": imagem.tipo,
                "largura": imagem.largura,
                "altura": imagem.altura,
                "proporcao": round(imagem.largura / imagem.altura, 3),
                "bytes": len(imagem.dados),
                "dpr": mapa.get("dpr"),
                "viewport": mapa.get("viewport"),
                "rolagem": mapa.get("rolagem"),
            },
            "inspecao": {
                "id": f"inspecao:{instantaneo}",
                "na_tela": len(elementos),
                "elementos": [_elemento_para_o_modelo(e) for e in elementos[:LIMITE_DO_MAPA]],
            },
            "scripts": {"id": f"scripts:{instantaneo}", "total": len(scripts), "ligados": ligados},
            CHAVE_DOS_ANEXOS: (imagem,),
        }

    # --- ação ---------------------------------------------------------------------------
    def _navegar(
        self,
        args: Mapping[str, Any],
        contaminado: bool,
        liberados: frozenset[str],
        exigir: Exigir,
        objetivo: Objetivo | None = None,
        trabalho: Trabalho | None = None,
    ) -> dict[str, Any]:
        try:
            url = validar_url(str(args["url"]))
        except UrlRecusada as erro:
            raise ValueError(str(erro)) from None
        nova_aba = bool(args.get("nova_aba", False))
        explicita = args.get("tab_id") is not None
        ver = trabalho is not None and trabalho.ver
        # Segundo plano (ADR-0036): a janela própria do Jarvis, atrás das do dono. É também o
        # caminho de todo trabalho que o dono não pediu para ver (pesquisar, ler, conferir: C3) —
        # antes ele trocava a página da aba que o dono estava usando. Com tab_id, navega aquela aba,
        # onde ela estiver.
        fundo = (
            not explicita
            and not nova_aba
            and (bool(args.get("segundo_plano", False)) or (trabalho is not None and not ver))
        )
        alvo: int | None = None
        if explicita:
            alvo = self._aba(args)[0]
        elif fundo:
            alvo = self._aba_de_fundo(trabalho)
        elif not nova_aba:
            # A aba atual é o padrão do que o dono quer ver (dono, 2026-10-20: link aberto em aba
            # nova a cada passo enchia o navegador) — a de trabalho, se este pedido já tem uma.
            alvo = self._aba(self._na_aba_de_trabalho(args, trabalho))[0]
        avaliacao = risco.avaliar_navegacao(
            url, contaminado=contaminado, liberados=liberados, objetivo=objetivo
        )
        if avaliacao.confirmar:
            exigir(f"navegar para {dominio(url)}", avaliacao.confirmar, avaliacao.causa)
        if alvo is None:
            feito = self.cliente.abrir(url, segundo_plano=fundo)
        else:
            feito = self.cliente.navegar(alvo, url)
        return self._conferido(url, feito, trabalho, ver=ver, nova=alvo is None)

    def _aba_de_fundo(self, trabalho: Trabalho | None) -> int | None:
        """A aba de trabalho deste pedido, se ela está na janela do Jarvis: navegar nela não enche a
        janela de abas. Sem ela, uma aba nova lá."""
        if trabalho is None or trabalho.aba is None:
            return None
        try:
            aba = self.cliente.aba(trabalho.aba)
        except NavegadorFalhou:
            trabalho.aba = None
            return None
        identificador = aba.get("id")
        if aba.get("janelaDoJarvis") and isinstance(identificador, int):
            return identificador
        return None

    def _conferido(
        self,
        url: str,
        feito: Mapping[str, Any],
        trabalho: Trabalho | None,
        *,
        ver: bool,
        nova: bool,
    ) -> dict[str, Any]:
        """O que a extensão conferiu depois de navegar (auditoria de 2026-10-21): o dono pediu "abra
        um vídeo no YouTube", a ferramenta disse ok em 25 ms com a URL de antes, e o navegador dele
        "continuou igual". Agora: a aba que não saiu do lugar e a página que não abriu são erro,
        dito como é; a URL é a da página nova; e, se o dono pediu para ver, a aba vem para a frente
        — o resultado diz se ficou à vista."""
        aba = dict(feito.get("aba") or {})
        tab_id = aba.get("id") if isinstance(aba.get("id"), int) else None
        if trabalho is not None and tab_id is not None:
            trabalho.aba = tab_id
        pedido = dominio(url)
        if not feito.get("comecou") and not feito.get("carregou"):
            onde = dominio(str(aba.get("url", ""))) or "onde estava"
            raise NavegadorFalhou(
                "aba_nao_mudou",
                f"a aba não saiu de {onde}: a página dela segurou a saída (pode estar pedindo ao "
                f"dono para confirmar) ou o navegador recusou {pedido}; nada mudou na tela",
            )
        pagina = feito.get("pagina")
        if feito.get("carregou") and not isinstance(pagina, dict):
            raise NavegadorFalhou(
                "pagina_nao_abriu",
                f"o navegador foi para {pedido}, mas a página não abriu (sem internet, erro do "
                "site ou página onde a extensão não entra)",
            )
        final = str((pagina or {}).get("url") or aba.get("url") or url)
        janela = "jarvis" if feito.get("janela") == "jarvis" else "dono"
        visivel = bool(feito.get("visivel"))
        if ver and tab_id is not None and not visivel:
            mostrado = self.cliente.mostrar(tab_id)
            visivel = bool(mostrado.get("visivel"))
            janela = "jarvis" if mostrado.get("janela") == "jarvis" else "dono"
        resultado: dict[str, Any] = {
            "tab_id": tab_id,
            "url": _curto(final, 300),
            "dominio": dominio(final),
            "nova_aba": nova,
            "janela": janela,
            "carregou": bool(feito.get("carregou")),
            "visivel": visivel,
        }
        if not resultado["carregou"]:
            resultado["situacao"] = "a página ainda está carregando: leia antes de dizer que abriu"
        elif ver and not visivel:
            resultado["situacao"] = (
                "a página abriu, mas o navegador não veio para a frente (o sistema segurou o "
                "foco): diga ao dono que ela está aberta na aba do navegador"
            )
        return resultado

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
            exigir(
                f"clicar em «{_curto(nome, 80)}» em {dominio(url)}",
                avaliacao.confirmar,
                avaliacao.causa,
            )
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
                avaliacao.causa,
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
                avaliacao.causa,
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
