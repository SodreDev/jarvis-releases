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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urlsplit

from jarvis.imagem import CHAVE_DOS_ANEXOS, ImagemInvalida, da_url_de_dados
from jarvis.navegador import risco
from jarvis.navegador.cliente import (
    SEM_ABA,
    ClienteDoNavegador,
    NavegadorFalhou,
    NavegadorIndisponivel,
)
from jarvis.navegador.controle import PARADO_PELO_DONO, Assinatura, ControleDoNavegador
from jarvis.politica import escopo
from jarvis.politica.abertura import UrlRecusada, dominio, validar_url
from jarvis.politica.metodo import quer_ver
from jarvis.politica.objetivo import EstadoDoObjetivo, Objetivo

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
        "browser.console",
        "browser.rede",
        "browser.avaliar",
        "browser.gesto",
        "browser.fechar_aba",
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
CATEGORIAS_QUE_NAO_SE_TROCA: Final = frozenset(
    {"senha", "banco", "pagamento", "mensageiro", "email"}
)
"""A aba do dono num destes sites não tem a página trocada por outra (a conversa, o extrato, a
compra no meio): o que ele pediu abre numa aba nova ao lado."""
TRABALHOS_LEMBRADOS: Final = 16
"""Objetivos (o pedido do turno, os das tarefas) cujo trabalho no navegador fica lembrado."""
ABAS_VAZIAS: Final = frozenset({"about:blank", "about:newtab", "about:home"})
INICIO_DAS_ABAS_VAZIAS: Final = (
    "chrome://newtab",
    "chrome://new-tab-page",
    "brave://newtab",
    "edge://newtab",
    "vivaldi://newtab",
    "chrome-search://local-ntp",
)
"""A «nova aba» do navegador: não é página de ninguém, então o pedido de ver a usa em vez de deixar
uma aba vazia ao lado da guia nova."""


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
    abertas: set[int] = field(default_factory=set)
    """As abas que este pedido abriu (à vista ou em segundo plano): só nelas o Jarvis navega de
    novo sem perguntar onde — a aba do dono com outro site não tem a página trocada."""
    mostrada: bool = False
    """A página do pedido já ficou à vista do dono: no fim, não se puxa o navegador de novo para a
    frente (o dono pode ter ido para outro programa)."""


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


def _endereco(url: str) -> str:
    """A URL para comparar abas: esquema e host em minúsculas, sem `#`, sem a barra final sozinha
    e sem o `www.`."""
    partes = urlsplit(url)
    host = (partes.hostname or "").lower().removeprefix("www.")
    porta = f":{partes.port}" if partes.port else ""
    caminho = partes.path if partes.path not in ("", "/") else ""
    consulta = f"?{partes.query}" if partes.query else ""
    return f"{partes.scheme.lower()}://{host}{porta}{caminho.rstrip('/')}{consulta}"


def _site(url: str) -> str:
    """O site da aba para o reuso: o host sem `www.` (music.youtube.com não é youtube.com)."""
    partes = urlsplit(url)
    porta = f":{partes.port}" if partes.port else ""
    return f"{(partes.hostname or '').lower().removeprefix('www.')}{porta}"


def _vazia(url: str) -> bool:
    """A aba está na «nova aba» do navegador (ou em branco): não há página do dono nela. URL que
    não se vê não conta como vazia."""
    limpa = url.strip().lower().split("#")[0].rstrip("/")
    return limpa in ABAS_VAZIAS or limpa.startswith(INICIO_DAS_ABAS_VAZIAS)


def _assinatura_do(cliente: ClienteDoNavegador) -> Callable[[], Assinatura] | None:
    """Os eventos da extensão (o PARAR do dono) pelo transporte que sabe assinar (o socket)."""
    assinar = getattr(cliente.transporte, "assinar", None)
    if not callable(assinar):
        return None

    def abrir() -> Assinatura:
        assinatura: Assinatura = assinar(cliente.navegador)
        return assinatura

    return abrir


CATEGORIAS_SEM_SCRIPT: Final = frozenset({"banco", "senha", "email", "pagamento"})
"""Nessas páginas o Jarvis não roda script nenhum (ADR-0049/0051, decisão do dono)."""


class CorposDoNavegador:
    def __init__(
        self, cliente: ClienteDoNavegador, controle: ControleDoNavegador | None = None
    ) -> None:
        self._base = cliente
        self.controle = controle or ControleDoNavegador(cliente, assinar=_assinatura_do(cliente))
        """O indicador e o PARAR (ADR-0027 regra 4): cada objetivo age sob uma concessão."""
        self._local = threading.local()
        self._trava = threading.Lock()
        self._trabalhos: dict[int, Trabalho] = {}
        self.trazer_a_frente: Callable[[str], bool] | None = None
        """O gerenciador de janelas (KWin) traz para a frente a janela do navegador que mostra a
        aba deste título, quando a extensão não conseguiu: no Wayland o navegador não pega o foco
        sozinho (dono, 2026-10-21). O app liga; sem ele, o resultado diz `visivel: false`."""

    @property
    def cliente(self) -> ClienteDoNavegador:
        """O cliente desta linha: dentro de `executar`, o que fala em nome da concessão do
        objetivo; fora dele, o de base."""
        atual: ClienteDoNavegador | None = getattr(self._local, "cliente", None)
        return atual or self._base

    @property
    def ao_parar(self) -> Callable[[Sequence[Objetivo]], None] | None:
        return self.controle.ao_parar

    @ao_parar.setter
    def ao_parar(self, funcao: Callable[[Sequence[Objetivo]], None] | None) -> None:
        self.controle.ao_parar = funcao

    @property
    def ao_mudar(self) -> Callable[[bool], None] | None:
        return self.controle.ao_mudar

    @ao_mudar.setter
    def ao_mudar(self, funcao: Callable[[bool], None] | None) -> None:
        self.controle.ao_mudar = funcao

    def parar(self) -> list[Objetivo]:
        """O PARAR da janela do Jarvis: solta todas as abas e cancela quem estava no controle."""
        return self.controle.parar()

    def _sob_controle(self, objetivo: Objetivo | None, trabalho: Trabalho | None) -> str:
        """A concessão do objetivo para este pedido; o dono já ter parado este objetivo é recusa."""
        ao_concluir = None
        if trabalho is not None and trabalho.ver:

            def ao_concluir(estado: EstadoDoObjetivo) -> None:
                self._mostrar_no_fim(trabalho, estado)

        try:
            return self.controle.concessao(objetivo, ao_concluir=ao_concluir)
        except PermissionError as erro:
            raise AcaoRecusada(f"{erro}: o Jarvis soltou o navegador neste pedido") from None

    def _mostrar_no_fim(self, trabalho: Trabalho, estado: EstadoDoObjetivo) -> None:
        """O dono pediu para ver e o pedido acabou bem, mas a página não ficou à vista (o trabalho
        terminou na janela do Jarvis ou numa aba de trás): ela vem para a frente agora."""
        if trabalho.mostrada or trabalho.aba is None or estado is not EstadoDoObjetivo.CONCLUIDO:
            return
        mostrado = self._base.mostrar(trabalho.aba)
        trabalho.mostrada = bool(mostrado.get("visivel"))

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
        concessao = None if tool_id == "browser.tabs" else self._sob_controle(objetivo, trabalho)
        self._local.cliente = self._base.sob(concessao)
        try:
            if tool_id == "browser.tabs":
                return self._abas()
            if tool_id == "browser.fechar_aba":
                return self._fechar_aba(args, exigir, objetivo, trabalho)
            if tool_id == "browser.navigate":
                navegado = self._navegar(args, contaminado, liberados, exigir, objetivo, trabalho)
                if concessao is not None:
                    self.controle.confirmar(concessao)
                return navegado
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
            elif tool_id == "browser.console":
                resultado = self._console(args)
            elif tool_id == "browser.rede":
                resultado = self._rede(args)
            elif tool_id == "browser.avaliar":
                resultado = self._avaliar(args, exigir, objetivo)
            elif tool_id == "browser.gesto":
                resultado = self._gesto(args, contaminado, liberados, exigir, cancelado, objetivo)
            if resultado is not None:
                if trabalho is not None and isinstance(resultado.get("tab_id"), int):
                    trabalho.aba = resultado["tab_id"]
                if concessao is not None:
                    self.controle.confirmar(concessao)
                return resultado
        except NavegadorFalhou as erro:
            if erro.codigo == PARADO_PELO_DONO and concessao is not None:
                # O dono apertou PARAR: a extensão recusou e o turno (ou a tarefa) para junto.
                self.controle.parado_pelo_dono([concessao])
                raise AcaoRecusada(
                    "o dono apertou parar no navegador: o Jarvis soltou as abas e não age mais "
                    "neste pedido"
                ) from None
            # O código entre parênteses é o da extensão (alvo_ausente, campo_sensivel…): ajuda o
            # modelo a escolher outro caminho e é o que a trilha de diagnóstico guarda.
            raise ValueError(
                f"a página não deixou ({erro.codigo}): {erro.mensagem or erro.codigo}"
            ) from None
        except NavegadorIndisponivel as erro:
            raise ValueError(str(erro)) from None
        finally:
            self._local.cliente = None
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

    def _fechar_aba(
        self,
        args: Mapping[str, Any],
        exigir: Exigir,
        objetivo: Objetivo | None,
        trabalho: Trabalho | None,
    ) -> dict[str, Any]:
        """Fecha uma aba (ADR-0057). Sem `tab_id`, a aba em que o Jarvis trabalha neste pedido. A
        que este pedido abriu, ou a do site que o dono citou, fecha sem pergunta — é parte do
        pedido; qualquer outra pede o sim dele (a aba dele pode ter coisa que ele não salvou)."""
        tab_id = args.get("tab_id")
        if not isinstance(tab_id, int):
            tab_id = trabalho.aba if trabalho is not None else None
        if not isinstance(tab_id, int):
            raise NavegadorFalhou("sem_aba", "não sei qual aba fechar: diga qual (o tab_id)")
        aba = self.cliente.aba(tab_id)
        url = str(aba.get("url") or "")
        titulo = " ".join(str(aba.get("titulo") or "").split())[:80]
        julgamento = escopo.julgar(
            "browser.fechar_aba",
            {"tab_id": tab_id},
            objetivo,
            abertas_pelo_pedido=trabalho.abertas if trabalho is not None else (),
            endereco_da_aba=url,
        )
        if not julgamento.contido:
            exigir(
                f"fechar a aba «{titulo or dominio(url) or tab_id}»",
                julgamento.motivo,
                "fora_do_escopo",
            )
        self.cliente.fechar_aba(tab_id)
        if trabalho is not None:
            trabalho.abertas.discard(tab_id)
            if trabalho.aba == tab_id:
                trabalho.aba = None
        return {"tab_id": tab_id, "dominio": dominio(url), "titulo": titulo, "fechada": True}

    def _abas(self) -> dict[str, Any]:
        """As abas abertas, com a janela e o estado de cada uma: à vista (a ativa da janela da
        frente), ativa noutra janela, em segundo plano, ou da janela do Jarvis. Qualquer uma pode
        ser lida ou controlada pelo `tab_id` — com as regras de sempre (banco, senha, enviar)."""
        abas = self.cliente.abas()
        try:
            em_foco = self.cliente.janela_em_foco().get("janelaId")
        except (NavegadorFalhou, NavegadorIndisponivel):
            em_foco = None
        janelas = sorted({a["janelaId"] for a in abas if isinstance(a.get("janelaId"), int)})

        def estado(aba: Mapping[str, Any]) -> str:
            if aba.get("janelaDoJarvis"):
                return "janela do Jarvis"
            if aba.get("ativa") and aba.get("janelaId") == em_foco:
                return "à vista"
            return "ativa noutra janela" if aba.get("ativa") else "segundo plano"

        return {
            "total": len(abas),
            "janelas": len(janelas),
            "abas": [
                {
                    "tab_id": a.get("id"),
                    "janela": janelas.index(a["janelaId"]) + 1
                    if a.get("janelaId") in janelas
                    else None,
                    "estado": estado(a),
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
    def mostrar_o_navegador(self) -> dict[str, Any]:
        """«Abre o navegador» com ele já aberto (dono, 2026-10-21): a aba atual da janela do dono
        vem para a frente — sem concessão, porque não é trabalho numa aba (não põe a faixa) — e
        nada abre outra janela. Navegador aberto sem janela nenhuma: `sem_janela` (aí abrir é
        abrir a janela dele). Sem extensão, `NavegadorIndisponivel` sobe."""
        try:
            aba = self._base.aba()
            identificador = aba.get("id")
            if not isinstance(identificador, int):
                return {"visivel": False}
            mostrado = self._base.mostrar(identificador)
        except NavegadorFalhou as erro:
            return {"visivel": False, **({"sem_janela": True} if erro.codigo == "sem_aba" else {})}
        titulo = str(dict(mostrado.get("aba") or {}).get("titulo") or aba.get("titulo") or "")
        return {"tab_id": identificador, "titulo": titulo, "visivel": bool(mostrado.get("visivel"))}

    def abrir_site(
        self, url: str, *, objetivo: Objetivo | None = None, nova_aba: bool = False
    ) -> dict[str, Any]:
        """O `sites.open` pela extensão: o dono pediu para abrir um site, então ele termina à vista,
        reaproveitando a aba que já tem o site (ADR-0027, emenda de 2026-10-21). O PDP já decidiu o
        `sites.open`; aqui não se pergunta de novo. Sem extensão, `NavegadorIndisponivel` sobe — e
        o navegador é aberto com a URL, como antes."""
        trabalho = self.trabalho(objetivo)
        concessao = self._sob_controle(objetivo, trabalho)
        self._local.cliente = self._base.sob(concessao)
        try:
            aberto = self._navegar(
                {"url": url, **({"nova_aba": True} if nova_aba else {})},
                contaminado=False,
                liberados=frozenset(),
                exigir=lambda *_: None,
                objetivo=objetivo,
                trabalho=trabalho,
                ver_sempre=True,
            )
            self.controle.confirmar(concessao)
            return aberto
        except NavegadorFalhou as erro:
            if erro.codigo == PARADO_PELO_DONO:
                self.controle.parado_pelo_dono([concessao])
                raise AcaoRecusada("o dono apertou parar no navegador") from None
            raise ValueError(
                f"a página não deixou ({erro.codigo}): {erro.mensagem or erro.codigo}"
            ) from None
        finally:
            self._local.cliente = None

    def _navegar(
        self,
        args: Mapping[str, Any],
        contaminado: bool,
        liberados: frozenset[str],
        exigir: Exigir,
        objetivo: Objetivo | None = None,
        trabalho: Trabalho | None = None,
        *,
        ver_sempre: bool = False,
    ) -> dict[str, Any]:
        try:
            url = validar_url(str(args["url"]))
        except UrlRecusada as erro:
            raise ValueError(str(erro)) from None
        nova_aba = bool(args.get("nova_aba", False))
        alvo_dito: int | None = None
        sumida: object = None
        if args.get("tab_id") is not None:
            try:
                alvo_dito = self._aba(args)[0]
            except NavegadorFalhou as erro:
                if erro.codigo != SEM_ABA:
                    raise
                # O modelo mandou o id de uma aba que não existe mais (a de uma busca, a de outra
                # sessão): o pedido é ir para a URL, e a aba era só o lugar. Antes isso voltava
                # erro, e cada correção custava uma rodada inteira do motor (trilha do dono,
                # 2026-10-21: duas navegações perdidas assim antes da que deu certo).
                sumida = args.get("tab_id")
                args = {chave: valor for chave, valor in args.items() if chave != "tab_id"}
        explicita = alvo_dito is not None
        ver = ver_sempre or (trabalho is not None and trabalho.ver)
        # Segundo plano: o trabalho que o dono não pediu para ver (pesquisar, ler, conferir) vai
        # numa aba em segundo plano NA JANELA DELE — sem `active`, sem tirar o foco nem trocar a
        # aba que ele está vendo. Nunca outra janela nem outra instância (ADR-0036, emenda de
        # 2026-10-21: a janela própria do Jarvis parecia outro Brave, e o vídeo abriu nela; ela
        # ficou para a automação social). Com tab_id, navega aquela aba, onde ela estiver.
        fundo = not explicita and (
            bool(args.get("segundo_plano", False)) or (trabalho is not None and not ver)
        )
        alvo: int | None = None
        reuso = ""
        if explicita:
            alvo = alvo_dito
        elif fundo:
            alvo = None if nova_aba else self._aba_de_fundo(trabalho)
        elif not nova_aba:
            # O que o dono vai ver: a aba que já tem a página ou o site (reuso); senão a aba que
            # este pedido abriu (dono, 2026-10-20: aba nova a cada passo enchia o navegador) ou uma
            # «nova aba» vazia; senão, guia nova na janela dele (dono, 2026-10-21) — a página da
            # aba que ele estava usando não é trocada.
            alvo, reuso = self._aba_para_ver(url, args, trabalho)
        if reuso in ("mesma_url", "mesmo_site_sensivel") and alvo is not None:
            return self._ja_aberta(url, alvo, trabalho, ver=ver, reuso=reuso)
        avaliacao = risco.avaliar_navegacao(
            url, contaminado=contaminado, liberados=liberados, objetivo=objetivo
        )
        if avaliacao.confirmar:
            exigir(f"navegar para {dominio(url)}", avaliacao.confirmar, avaliacao.causa)
        if alvo is None:
            feito = self.cliente.abrir(url, segundo_plano=fundo)
        else:
            feito = self.cliente.navegar(alvo, url)
        resultado = self._conferido(url, feito, trabalho, ver=ver, nova=alvo is None, fundo=fundo)
        if reuso:
            resultado["reutilizou"] = reuso
        if sumida is not None:
            resultado["aba_pedida_nao_existia"] = sumida
        return resultado

    def _aba_para_ver(
        self, url: str, args: Mapping[str, Any], trabalho: Trabalho | None
    ) -> tuple[int | None, str]:
        """Onde abrir o que o dono vai ver (pedido do dono, 2026-10-21): a aba que **já está** na
        URL pedida (só ativa, sem recarregar); senão uma aba do **mesmo site** (navega ela); senão
        a aba que este pedido abriu, ou a atual se ela é uma «nova aba» vazia; senão (`None`) uma
        **guia nova** na janela do dono — a aba dele com outro site não tem a página trocada. A aba
        em banco, senha, pagamento, mensageiro ou e-mail também não: do mesmo site, ela vem como
        está."""
        atual_id, atual_url, _ = self._aba(self._na_aba_de_trabalho(args, trabalho))
        try:
            abas = [
                a
                for a in self.cliente.abas()
                if isinstance(a.get("id"), int) and not a.get("janelaDoJarvis")
            ]
        except (NavegadorFalhou, NavegadorIndisponivel):
            abas = []

        def preferencia(aba: Mapping[str, Any]) -> tuple[bool, bool, float]:
            # A de trabalho (ou a atual) primeiro, depois as ativas, depois a usada por último.
            return (
                aba["id"] != atual_id,
                not aba.get("ativa"),
                -float(aba.get("ultimoAcesso") or 0),
            )

        mesma = sorted(
            (a for a in abas if _endereco(str(a.get("url", ""))) == _endereco(url)), key=preferencia
        )
        if mesma:
            return int(mesma[0]["id"]), "mesma_url"
        do_site = sorted(
            (a for a in abas if _site(str(a.get("url", ""))) == _site(url)), key=preferencia
        )
        if do_site:
            sensivel = risco.categoria(url) in CATEGORIAS_QUE_NAO_SE_TROCA
            return int(do_site[0]["id"]), "mesmo_site_sensivel" if sensivel else "mesmo_site"
        if risco.categoria(atual_url) in CATEGORIAS_QUE_NAO_SE_TROCA:
            return None, ""  # a conversa, o extrato, a compra do dono ficam: aba nova
        if (trabalho is not None and atual_id in trabalho.abertas) or _vazia(atual_url):
            return atual_id, ""
        return None, ""  # a página que o dono estava usando fica: guia nova ao lado

    def _ja_aberta(
        self, url: str, tab_id: int, trabalho: Trabalho | None, *, ver: bool, reuso: str
    ) -> dict[str, Any]:
        """A página pedida já está aberta numa aba do dono: nada é recarregado; se ele pediu para
        ver, a aba vem para a frente."""
        if ver:
            feito = self.cliente.mostrar(tab_id)
            aba = dict(feito.get("aba") or {})
            visivel = bool(feito.get("visivel"))
        else:
            aba = self.cliente.aba(tab_id)
            visivel = False
        if trabalho is not None:
            trabalho.aba = tab_id
            trabalho.mostrada = trabalho.mostrada or visivel
        final = str(aba.get("url") or url)
        resultado: dict[str, Any] = {
            "tab_id": tab_id,
            "url": _curto(final, 300),
            "dominio": dominio(final),
            "nova_aba": False,
            "janela": "dono",
            "carregou": True,
            "visivel": visivel,
            "reutilizou": reuso,
        }
        if reuso == "mesmo_site_sensivel":
            resultado["situacao"] = (
                f"a aba de {dominio(final)} do dono foi trazida como estava: página de banco, "
                "senha, pagamento, mensageiro ou e-mail não é trocada pelo Jarvis"
            )
        elif ver and not visivel:
            resultado["situacao"] = (
                "a página já estava aberta, mas o navegador não veio para a frente (o sistema "
                "segurou o foco): diga ao dono em que aba ela está"
            )
        return resultado

    def _aba_de_fundo(self, trabalho: Trabalho | None) -> int | None:
        """A aba de trabalho deste pedido, se foi ele que a abriu e ela continua em segundo plano
        (ou na janela do Jarvis, na automação social): navegar nela não enche de abas a janela do
        dono. Aba do dono, aba que ele trouxe para a frente ou aba fechada: uma nova, de fundo."""
        if trabalho is None or trabalho.aba is None or trabalho.aba not in trabalho.abertas:
            return None
        try:
            aba = self.cliente.aba(trabalho.aba)
        except NavegadorFalhou:
            trabalho.aba = None
            return None
        identificador = aba.get("id")
        if isinstance(identificador, int) and (aba.get("janelaDoJarvis") or not aba.get("ativa")):
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
        fundo: bool = False,
    ) -> dict[str, Any]:
        """O que a extensão conferiu depois de navegar (auditoria de 2026-10-21): o dono pediu "abra
        um vídeo no YouTube", a ferramenta disse ok em 25 ms com a URL de antes, e o navegador dele
        "continuou igual". Agora: a aba que não saiu do lugar e a página que não abriu são erro,
        dito como é; a URL é a da página nova; e, se o dono pediu para ver, a aba vem para a frente
        — o resultado diz se ficou à vista. O passo de fundo de um pedido de ver só vem para a
        frente no fim do pedido (`_mostrar_no_fim`), se nada dele ficou à vista."""
        aba = dict(feito.get("aba") or {})
        tab_id = aba.get("id") if isinstance(aba.get("id"), int) else None
        if trabalho is not None and tab_id is not None:
            trabalho.aba = tab_id
            if nova:
                trabalho.abertas.add(tab_id)
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
        if ver and not fundo and tab_id is not None and not visivel:
            mostrado = self.cliente.mostrar(tab_id)
            visivel = bool(mostrado.get("visivel"))
            janela = "jarvis" if mostrado.get("janela") == "jarvis" else "dono"
            if not visivel and self.trazer_a_frente is not None:
                titulo = str(dict(mostrado.get("aba") or {}).get("titulo", ""))
                visivel = self.trazer_a_frente(titulo)
        if trabalho is not None and ver:
            trabalho.mostrada = trabalho.mostrada or visivel
        resultado: dict[str, Any] = {
            "tab_id": tab_id,
            "url": _curto(final, 300),
            "dominio": dominio(final),
            "nova_aba": nova,
            "janela": janela,
            "carregou": bool(feito.get("carregou")),
            "visivel": visivel,
        }
        if fundo and not visivel:
            resultado["segundo_plano"] = True
        if not resultado["carregou"]:
            resultado["situacao"] = "a página ainda está carregando: leia antes de dizer que abriu"
        elif ver and not fundo and not visivel:
            resultado["situacao"] = (
                "a página abriu, mas o navegador não veio para a frente (o sistema segurou o "
                "foco): diga ao dono que ela está aberta na aba do navegador"
            )
        return resultado

    def _rolar(self, args: Mapping[str, Any]) -> dict[str, Any]:
        tab_id, _, _ = self._aba(args)
        pixels = int(args.get("pixels", PIXELS_PADRAO))
        return {"tab_id": tab_id, **self.cliente.rolar(tab_id, pixels)}

    # --- depuração por CDP (ADR-0051) ---------------------------------------------------
    def _console(self, args: Mapping[str, Any]) -> dict[str, Any]:
        tab_id, _, _ = self._aba(args)
        return {"tab_id": tab_id, **self.cliente.console(tab_id)}

    def _rede(self, args: Mapping[str, Any]) -> dict[str, Any]:
        tab_id, _, _ = self._aba(args)
        return {"tab_id": tab_id, **self.cliente.rede(tab_id)}

    def _avaliar(
        self, args: Mapping[str, Any], exigir: Exigir, objetivo: Objetivo | None
    ) -> dict[str, Any]:
        """Roda JavaScript no mundo isolado (padrão). O guarda (ADR-0049) já barrou o script fora
        do eixo antes do PDP; aqui fica a cerca que depende da URL da aba, que o guarda não tinha:
        domínio sensível é **bloqueado**, e a aba fora do objetivo pede o sim."""
        tab_id, url, _ = self._aba(args)
        categoria = risco.categoria(url)
        if categoria in CATEGORIAS_SEM_SCRIPT:
            rotulo = risco.ROTULO_DAS_CATEGORIAS.get(categoria, categoria)
            raise ValueError(
                f"não rodo script em {rotulo} ({dominio(url)}): leia com browser.read ou "
                "peça ao dono"
            )
        if objetivo is not None and not objetivo.dentro(url):
            exigir(
                f"rodar um script em {dominio(url)}, fora do objetivo",
                "a aba está fora dos sites do objetivo",
                "fora_do_objetivo",
            )
        mundo = str(args.get("mundo", "isolado"))
        feito = self.cliente.avaliar(tab_id, str(args["codigo"]), mundo=mundo)
        return {
            "tab_id": tab_id,
            "mundo": mundo,
            "valor": _curto(feito.get("valor"), LIMITE_DO_TEXTO),
            "cdp": bool(feito.get("cdp")),
            "recuo": feito.get("recuo"),
        }

    def _gesto(
        self,
        args: Mapping[str, Any],
        contaminado: bool,
        liberados: frozenset[str],
        exigir: Exigir,
        cancelado: Callable[[], bool],
        objetivo: Objetivo | None = None,
    ) -> dict[str, Any]:
        """Um gesto físico por CDP. Rolar é livre; clicar/arrastar/digitar passam pelo mesmo risco
        do clique (`jarvis.navegador.risco`), que o guarda deixou para o corpo (ADR-0051)."""
        gesto = str(args["gesto"])
        tab_id, url, _ = self._aba(args)
        if gesto == "rolar":
            feito = self.cliente.gesto(tab_id, gesto, pixels=int(args.get("pixels", PIXELS_PADRAO)))
            return {"tab_id": tab_id, "gesto": gesto, "feito": bool(feito.get("feito"))}
        alvo, ref = _alvo_ou_ref(args)
        dados = self.cliente.inspecionar(tab_id, alvo, ref=ref)
        nome = _nome(alvo, dados)
        texto = str(args.get("texto", "")) if gesto == "digitar" else ""
        if gesto == "digitar":
            avaliacao = risco.avaliar_digitacao(
                url, dados, nome, texto, contaminado=contaminado, objetivo=objetivo
            )
        else:
            avaliacao = risco.avaliar_clique(
                url, dados, nome, contaminado=contaminado, liberados=liberados, objetivo=objetivo
            )
        if avaliacao.recusa:
            raise ValueError(avaliacao.recusa)
        if avaliacao.confirmar:
            exigir(
                f"{gesto} «{_curto(nome, 80)}» em {dominio(url)}",
                avaliacao.confirmar,
                avaliacao.causa,
            )
        if cancelado():
            raise AcaoRecusada(f"interrompido antes de {gesto}")
        feito = self.cliente.gesto(tab_id, gesto, alvo=alvo, ref=ref, texto=texto or None)
        return {
            "tab_id": tab_id,
            "gesto": gesto,
            "alvo": _curto(nome, 80),
            "feito": bool(feito.get("feito")),
        }

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
