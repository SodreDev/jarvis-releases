"""O caminho rápido: comando simples vai à ferramenta pela regra, sem esperar o modelo (dono,
2026-10-21: «precisa ser muito rápido»).

Na trilha do dono o primeiro token do motor (`claude -p`) leva de 2,5 a 9 s, e todo pedido com
ferramenta ainda virava tarefa — «Certo, já cuido disso.» antes, e a resposta de outra rodada do
motor depois. Para os comandos que têm **um caminho só** — abrir, fechar, encerrar ou focar um app
liberado; o que está em foco; as janelas; as abas; abrir um site; procurar no próprio site —, a
regra do código acha a ferramenta e os argumentos na fala, e o cérebro a chama **pelo mesmo caminho
de sempre**: PDP → Jev → objetivo → autorização explícita → pergunta ao dono. O caminho rápido não
decide nada que a política decidiria; só não espera o modelo propor. Deu certo e o pedido acabou:
a frase é do código. Erro, pergunta, ou pedido que continua (abrir o canal de alguém, ler as
notícias): o modelo segue dali, já com o resultado.

Conservador por construção: a fala **inteira** tem de caber na regra (nada de «abre o Discord e
manda um oi»), o app tem de resolver para um app liberado sem dúvida, o site tem de estar na
tabela (`jarvis.politica.sites`) ou ser um domínio dito, e a ferramenta tem de existir neste turno e
não estar fora pelo método do pedido (ADR-0035). Fora disso, `None`: o modelo decide, como antes.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from jarvis.politica.fechamento import Fechamento, fechamento
from jarvis.politica.metodo import quer_ver
from jarvis.politica.sites import SITES, Site


class Regra(StrEnum):
    ABRIR_APP = "abrir_app"
    ABRIR_NAVEGADOR = "abrir_navegador"
    FECHAR_JANELA = "fechar_janela"
    ENCERRAR_APP = "encerrar_app"
    FOCAR_APP = "focar_app"
    EM_FOCO = "em_foco"
    JANELAS = "janelas"
    ABAS = "abas"
    ABRIR_SITE = "abrir_site"
    BUSCAR_NO_SITE = "buscar_no_site"
    PRIMEIRO_PASSO_NO_SITE = "primeiro_passo_no_site"
    BUSCAR_NA_WEB = "buscar_na_web"


@dataclass(frozen=True, slots=True)
class Atalho:
    regra: Regra
    tool_id: str
    args: Mapping[str, Any]
    alvo: str = ""
    """O nome que vai na frase («Discord», «YouTube»)."""
    completo: bool = True
    """A frase do código fecha o pedido; `False` = é o primeiro passo, e o modelo segue."""
    termo: str = ""
    """O que se procurou no site (para a frase)."""


@dataclass(frozen=True, slots=True)
class ContextoDoAtalho:
    """O que o código sabe nesta sessão — nada vem do modelo."""

    disponivel: Callable[[str], bool]
    """A ferramenta existe neste turno e o método do pedido não a tirou."""
    app: Callable[[str], str | None]
    """O nome falado → o nome do app liberado, só quando resolve sem dúvida."""
    navegador_configurado: Callable[[str], str | None] = lambda _nome: None
    """O nome falado → a família do navegador configurado («brave»), ou `None`."""
    navegador: bool = False
    """O controle do navegador pela extensão está ligado."""
    motivo_do_metodo: str = ""
    """O motivo do roteador para esta fala (ADR-0035): a busca na web só pelo atalho quando ele
    disse `busca_generica` — «procura o arquivo X» não é busca na internet."""


# --- a fala limpa ----------------------------------------------------------------------------
_COMECO: Final = (
    r"^(?:(?:ei|oi|ok|hey|ola)\s+)?(?:jarvis\s+)?"
    r"(?:(?:por\s+favor|pfv|pode|voce\s+pode|consegue|da\s+pra|da\s+para|me|tem\s+como)\s+)*"
)
_FIM: Final = r"(?:\s+(?:por\s+favor|pfv|pra\s+mim|para\s+mim|ai|agora|rapidinho|ja|obrigado))+$"
_ART: Final = r"(?:(?:o|a|os|as|um|uma)\s+)?"
_NO: Final = r"(?:no|na|nos|nas|em|pelo|pela|do|da)"
_ABRIR: Final = (
    r"(?:abre|abra|abrir|abri|inicia|inicie|iniciar|executa|execute|executar|liga|ligue|ligar|"
    r"roda|rode)"
)
_ENTRAR: Final = r"(?:entra|entre|entrar|vai|va|acessa|acesse|acessar)"
_VER: Final = (
    r"(?:abre|abra|abrir|abri|mostra|mostre|mostrar|coloca|coloque|colocar|bota|bote|botar|poe|"
    r"ponha|toca|toque|tocar|passa|passe|assiste|assistir)"
)
_BUSCAR: Final = (
    r"(?:pesquisa|pesquise|pesquisar|procura|procure|procurar|busca|busque|buscar|acha|ache)"
)
_FOCAR: Final = (
    r"(?:foca|foque|focar|focaliza|focalize|traz|traga|(?:vai|va|muda|mude|troca|troque|volta|"
    r"volte)\s+(?:pro|pra|para\s+o|para\s+a|para))"
)
_FRENTE: Final = r"(?:\s+(?:pra|para)\s+(?:a\s+)?frente)?"
_EM_FOCO: Final = (
    r"^(?:(?:qual|que)\s+(?:e\s+)?(?:a\s+|o\s+)?(?:janela|app|aplicativo|programa)\s+(?:que\s+)?"
    r"(?:esta\s+|ta\s+|fica\s+)?(?:em\s+foco|ativ[ao]|na\s+frente|selecionad[ao])"
    r"(?:\s+(?:no|na)\s+(?:monitor|tela)\s+principal)?"
    r"|o\s+que\s+(?:esta|ta)\s+(?:em\s+foco|na\s+(?:tela|frente))"
    r"|(?:o\s+que|qual\s+janela|que\s+janela)\s+(?:esta|ta)\s+(?:no|na)\s+(?:monitor|tela)\s+"
    r"principal"
    r"|(?:qual|que)\s+janela\s+e\s+essa)$"
)
_JANELAS: Final = (
    r"^(?:(?:quais|que)\s+(?:sao\s+as\s+)?(?:janelas|apps|aplicativos|programas)\s+(?:que\s+)?"
    r"(?:estao\s+|tao\s+|tenho\s+|tem\s+|ha\s+)?abert[ao]s"
    r"|(?:lista|liste|listar|mostra|mostre)\s+(?:as\s+|todas\s+as\s+)?janelas(?:\s+abertas)?"
    r"|o\s+que\s+(?:esta|ta|tem)\s+aberto)$"
)
_ABAS: Final = (
    r"^(?:(?:quais|que)\s+(?:sao\s+as\s+)?(?:abas|guias)\s+(?:que\s+)?"
    r"(?:estao\s+|tao\s+|tenho\s+|tem\s+|ha\s+)?abertas(?:\s+no\s+navegador)?"
    r"|(?:lista|liste|listar|mostra|mostre)\s+(?:as\s+|todas\s+as\s+)?(?:abas|guias)"
    r"(?:\s+abertas)?(?:\s+do\s+navegador)?)$"
)
_FECHAR: Final = r"^(?:fecha|feche|fechar)\s+(?P<alvo>.+)$"
_ENCERRAR: Final = (
    r"^(?:mata|mate|matar|encerra|encerre|encerrar|finaliza|finalize|finalizar)\s+(?P<alvo>.+)$"
)
_INTEIRO: Final = (
    r"\s+(?:todo|toda|inteiro|inteira|de\s+vez|completamente|por\s+completo|o\s+processo|"
    r"os\s+processos|de\s+verdade)$"
)
_DA_FRENTE: Final = frozenset(
    {
        "", "janela", "a janela", "essa janela", "esta janela", "essa", "esse", "isso", "isto",
        "esse ai", "essa ai", "isso ai", "a janela atual", "janela atual", "a da frente",
        "o da frente", "essa aqui", "esse aqui", "a janela da frente",
    }
)  # fmt: skip
"""«Fecha a janela», «fecha esse aí»: a janela da frente (ADR-0042)."""
_DO_JARVIS: Final = frozenset({"jarvis", "o jarvis", "sistema", "o sistema", "assistente"})
_NAVEGADOR_SEM_NOME: Final = frozenset({"navegador", "browser", "navegador de internet"})
_TUDO: Final = frozenset({"tudo", "todas", "todos", "todas as janelas", "tudo isso"})
_BUSCA_NA_WEB: Final = (
    r"^(?:pesquisa|pesquise|pesquisar|busca|busque|buscar|procura|procure)\s+"
    r"(?:(?:na|pela)\s+(?:internet|web|net)\s+)?(?:por\s+|sobre\s+)?(?P<termo>.+?)"
    r"(?:\s+(?:na|pela)\s+(?:internet|web|net))?$"
)
_GENERICOS_DO_SITE: Final = (
    r"^(?:(?:o|a|os|as|um|uma)\s+)?(?:(?:ultimo|ultima|ultimos|ultimas|novo|nova|novos|novas|"
    r"mais\s+recentes?)\s+)?(?:canal|canais|video|videos|musica|musicas|clipe|clipes|perfil|"
    r"pagina|playlist|podcast|live|episodio|filme|serie)?(?:\s+(?:mais\s+recentes?|novos?|"
    r"novas?))?(?:\s+(?:do|da|de|dos|das|sobre))?\s*"
)
"""Tirado do começo do que se procura: «o canal do Primo Rico» → «Primo Rico»."""
_NOTICIAS: Final = (
    r"^(?:(?:quais|que)\s+(?:sao\s+)?|(?:fala|diz|le|leia|conta|resume|resuma)\s+)?"
    r"(?:as\s+)?(?:ultimas\s+)?(?:noticias|manchetes)\s+(?:de\s+hoje\s+)?(?:do|da|de|no|na)\s+"
)
LIMITE_DE_PALAVRAS_DO_ALVO: Final = 4


@dataclass(frozen=True, slots=True)
class _Fala:
    """A fala dobrada e limpa (`texto`), e de onde veio cada caractere dela na fala do dono: o
    que vai para uma URL (o que se procura) sai da fala **original**, com os acentos."""

    texto: str
    original: str
    mapa: tuple[int, ...]

    def trecho(self, inicio: int, fim: int) -> str:
        if inicio >= fim:
            return ""
        pedaco = self.original[self.mapa[inicio] : self.mapa[fim - 1] + 1]
        return pedaco.strip(" \t,.;:!?\"'«»")


def _dobrar_com_mapa(original: str) -> tuple[str, list[int]]:
    """O mesmo `dobrar` dos sites, guardando o índice de origem de cada caractere."""
    letras: list[str] = []
    origem: list[int] = []
    for i, c in enumerate(original):
        for d in unicodedata.normalize("NFD", c):
            if unicodedata.category(d) == "Mn":
                continue
            for e in d.casefold():
                letras.append(e)
                origem.append(i)
    trocado = re.sub(r"[^\w.\s-]|(?<!\w)\.|\.(?!\w)", " ", "".join(letras))  # um por um
    texto: list[str] = []
    mapa: list[int] = []
    for c, i in zip(trocado, origem, strict=True):
        if c.isspace():
            if texto and texto[-1] != " ":
                texto.append(" ")
                mapa.append(i)
        else:
            texto.append(c)
            mapa.append(i)
    while texto and texto[-1] == " ":
        texto.pop()
        mapa.pop()
    return "".join(texto), mapa


def _limpa(original: str) -> _Fala:
    texto, mapa = _dobrar_com_mapa(original)
    comeco = re.match(_COMECO, texto)
    inicio = comeco.end() if comeco is not None else 0
    fim_achado = re.search(_FIM, texto)
    fim = (
        fim_achado.start()
        if fim_achado is not None and fim_achado.start() >= inicio
        else len(texto)
    )
    while inicio < fim and texto[inicio] == " ":
        inicio += 1
    while fim > inicio and texto[fim - 1] == " ":
        fim -= 1
    return _Fala(texto[inicio:fim], original, tuple(mapa[inicio:fim]))


def limpar(fala: str) -> str:
    """A fala dobrada, sem a palavra de ativação nem a cortesia do começo e do fim."""
    return _limpa(fala).texto


def _nomes_dos_sites() -> str:
    nomes = sorted({n for s in SITES for n in (s.nome, *s.apelidos)}, key=len, reverse=True)
    return "|".join(re.escape(n) for n in nomes)


_SITE: Final = _nomes_dos_sites()


def _site(nome: str) -> Site | None:
    return next((s for s in SITES if nome in (s.nome, *s.apelidos)), None)


def _sem_artigo(texto: str) -> str:
    """Sem o artigo e sem a posse: «o meu Brave», «minha calculadora» (dono, 2026-10-25)."""
    sem = re.sub(r"^(?:o|a|os|as|um|uma|esse|essa|este|esta)\s+", "", texto).strip()
    return re.sub(r"^(?:meu|minha|meus|minhas|seu|sua|nosso|nossa)\s+", "", sem).strip()


_DE_CONTEXTO: Final = frozenset(
    {"e", "no", "na", "nos", "nas", "em", "com", "pelo", "pela", "pra", "para", "pro", "ou"}
)
"""Palavras que dizem que o alvo não é só o nome do app («o Discord no terminal», «o Steam com o
jogo»): aí o modelo decide. «de», «do» e «da» ficam (Gerenciador de Arquivos)."""


def _curto(alvo: str) -> bool:
    palavras = alvo.split()
    return 0 < len(palavras) <= LIMITE_DE_PALAVRAS_DO_ALVO and not _DE_CONTEXTO & set(palavras)


# --- a regra ---------------------------------------------------------------------------------
def achar(fala: str, contexto: ContextoDoAtalho) -> Atalho | None:
    """O atalho da fala, ou `None` quando ela não cabe inteira numa regra (o modelo decide)."""
    limpa = _limpa(fala)
    if not limpa.texto:
        return None
    for regra in (_consulta, _fechar, _no_site, _na_web, _focar, _abrir):
        achado = regra(limpa, fala, contexto)
        if achado is not None:
            return achado if contexto.disponivel(achado.tool_id) else None
    return None


def _consulta(limpa: _Fala, _fala: str, contexto: ContextoDoAtalho) -> Atalho | None:
    texto = limpa.texto
    if re.fullmatch(_EM_FOCO, texto):
        return Atalho(Regra.EM_FOCO, "window.focused", {})
    if re.fullmatch(_JANELAS, texto):
        return Atalho(Regra.JANELAS, "window.list", {})
    if re.fullmatch(_ABAS, texto) and contexto.navegador:
        return Atalho(Regra.ABAS, "browser.tabs", {})
    return None


def _fechar(limpa: _Fala, fala: str, _contexto: ContextoDoAtalho) -> Atalho | None:
    texto = limpa.texto
    tipo = fechamento(fala)
    if tipo is None:
        return None
    achado = re.fullmatch(_FECHAR, texto) or re.fullmatch(_ENCERRAR, texto)
    if achado is None:
        return None
    alvo = _sem_artigo(re.sub(_INTEIRO, "", achado.group("alvo")).strip())
    if alvo in _DO_JARVIS or alvo in _TUDO or {"aba", "guia"} & set(alvo.split()):
        return None  # encerrar o Jarvis é outro caso (ADR-0041); aba é do navegador
    if alvo in _DA_FRENTE or re.sub(_INTEIRO, "", achado.group("alvo")).strip() in _DA_FRENTE:
        args: dict[str, Any] = {}
        nome = ""
    elif _curto(alvo) and len(alvo) >= 2:
        # «O navegador» sem nome: quem resolve é o código (o em foco, o único aberto); a frase diz
        # o nome do que ele achou (ADR-0046).
        args, nome = {"app": alvo}, ("" if alvo in _NAVEGADOR_SEM_NOME else alvo)
    else:
        return None
    if tipo is Fechamento.APP:
        return Atalho(Regra.ENCERRAR_APP, "apps.quit", args, nome.title())
    return Atalho(Regra.FECHAR_JANELA, "window.close", args, nome.title())


def _no_site(limpa: _Fala, fala: str, contexto: ContextoDoAtalho) -> Atalho | None:
    texto = limpa.texto
    ferramenta = "browser.navigate" if contexto.navegador else "sites.open"

    def ir(regra: Regra, site: Site, termo: str = "", *, completo: bool = True) -> Atalho | None:
        if not completo and not contexto.navegador:
            return None  # o modelo segue pelas browser.*: sem extensão, ele decide sozinho
        url = site.endereco_da_busca(termo) if termo else site.inicio
        args: dict[str, Any] = {"url": url}
        if ferramenta == "browser.navigate" and not completo and not quer_ver(fala):
            args["segundo_plano"] = True  # ler para o dono, sem trocar o que ele vê
        return Atalho(regra, ferramenta, args, _nome_do_site(site), completo, termo)

    buscas = (
        rf"^{_BUSCAR}\s+(?:por\s+|sobre\s+)?(?P<termo>.+?)\s+{_NO}\s+{_ART}(?P<site>{_SITE})$",
        rf"^{_BUSCAR}\s+{_NO}\s+{_ART}(?P<site>{_SITE})\s+(?:por\s+|sobre\s+)?(?P<termo>.+)$",
        rf"^{_ABRIR}\s+{_ART}(?P<site>{_SITE})\s+e\s+{_BUSCAR}\s+(?:por\s+|sobre\s+)?"
        rf"(?P<termo>.+)$",
    )
    for padrao in buscas:
        achado = re.fullmatch(padrao, texto)
        site = _site(achado.group("site")) if achado else None
        if achado is not None and site is not None and site.busca:
            return ir(Regra.BUSCAR_NO_SITE, site, limpa.trecho(*achado.span("termo")))
    noticias = re.fullmatch(rf"{_NOTICIAS}{_ART}(?P<site>{_SITE})(?:\s+hoje)?", texto)
    if noticias is not None and (site := _site(noticias.group("site"))) is not None:
        return ir(Regra.PRIMEIRO_PASSO_NO_SITE, site, completo=quer_ver(fala))
    aberto = re.fullmatch(
        rf"^(?:{_ABRIR}|{_ENTRAR})\s+(?:{_NO}\s+|pro\s+|pra\s+)?{_ART}(?P<site>.+)$", texto
    )
    if aberto is not None:
        alvo = aberto.group("site").strip()
        site = _site(alvo)
        if site is not None:
            return ir(Regra.ABRIR_SITE, site)
        dominio = re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\.br)?", alvo)
        if dominio is not None:
            return ir(Regra.ABRIR_SITE, Site(alvo, f"https://{alvo}/"))
    algo = re.fullmatch(rf"^{_VER}\s+(?P<coisa>.+?)\s+{_NO}\s+{_ART}(?P<site>{_SITE})$", texto)
    if algo is not None and (site := _site(algo.group("site"))) is not None:
        generico = re.match(_GENERICOS_DO_SITE, algo.group("coisa"))
        inicio = algo.start("coisa") + (generico.end() if generico is not None else 0)
        termo = limpa.trecho(inicio, algo.end("coisa")) if site.busca else ""
        return ir(Regra.PRIMEIRO_PASSO_NO_SITE, site, termo, completo=False)
    return None


def _na_web(limpa: _Fala, _fala: str, contexto: ContextoDoAtalho) -> Atalho | None:
    """A busca genérica (dono, 2026-10-21): o código faz a busca direta já no primeiro passo, e o
    modelo só lê os resultados e responde — uma rodada a menos."""
    texto = limpa.texto
    if contexto.motivo_do_metodo != "busca_generica":
        return None
    achado = re.fullmatch(_BUSCA_NA_WEB, texto)
    if achado is None:
        return None
    termo = limpa.trecho(*achado.span("termo"))
    if not termo or len(termo) > 200:
        return None
    return Atalho(
        Regra.BUSCAR_NA_WEB, "web.buscar", {"consulta": termo}, completo=False, termo=termo
    )


def _nome_do_site(site: Site) -> str:
    if "." in site.nome:
        return site.nome  # um domínio dito («exemplo.com.br») sai como foi dito
    especiais = {"youtube": "YouTube", "github": "GitHub", "linkedin": "LinkedIn", "g1": "g1"}
    return especiais.get(site.nome, site.nome.title())


def _focar(limpa: _Fala, _fala: str, contexto: ContextoDoAtalho) -> Atalho | None:
    texto = limpa.texto
    achado = re.fullmatch(rf"^{_FOCAR}\s+{_ART}(?P<alvo>.+?){_FRENTE}$", texto)
    if achado is None:
        return None
    alvo = _sem_artigo(achado.group("alvo"))
    if not _curto(alvo) or _site(alvo) is not None:
        return None
    nome = contexto.app(alvo) or alvo.title()
    return Atalho(Regra.FOCAR_APP, "window.focus_app", {"app": alvo}, _curta(nome))


def _abrir(limpa: _Fala, _fala: str, contexto: ContextoDoAtalho) -> Atalho | None:
    texto = limpa.texto
    achado = re.fullmatch(rf"^{_ABRIR}\s+{_ART}(?P<alvo>.+)$", texto)
    if achado is None:
        return None
    alvo = _sem_artigo(achado.group("alvo"))
    if not _curto(alvo) or _site(alvo) is not None:
        return None
    familia = contexto.navegador_configurado(alvo)
    if familia is not None and contexto.disponivel("browser.launch"):
        return Atalho(
            Regra.ABRIR_NAVEGADOR, "browser.launch", {"navegador": familia}, familia.title()
        )
    nome = contexto.app(alvo)
    if nome is None:
        return None
    return Atalho(Regra.ABRIR_APP, "apps.launch", {"nome": nome}, _curta(nome))


def _curta(nome: str) -> str:
    """«Brave Web Browser» → «Brave»: o nome que se fala."""
    palavras = nome.split()
    return palavras[0] if len(palavras) > 2 else nome


_CONECTIVOS: Final = frozenset({"e", "depois", "entao", "tambem", "enquanto", "antes", "mas"})
"""O que liga uma segunda ação à primeira («abre o Discord e manda um oi»)."""
_CHAMADA: Final = r"^\s*(?:(?:ei|oi|ok|hey|ola|olá)[\s,]+)?jarvis\s*[,.!:]?\s*"


def fala_simples(fala: str) -> bool:
    """A fala pede uma coisa só: sem conectivo nem vírgula entre duas ações (dono, 2026-10-25).

    É o que deixa o turno acabar na frase do código depois de uma ação de um passo, sem outra
    rodada do motor: «fecha o navegador que está no outro monitor» é uma coisa só; «abre o Discord e
    o Spotify», «abre o Discord, manda um oi» não são. Na dúvida, não é simples (o motor segue)."""
    sem_chamada = re.sub(_CHAMADA, "", fala, flags=re.IGNORECASE)
    if "," in sem_chamada.strip().rstrip(".!?"):
        return False
    return not _CONECTIVOS & set(limpar(sem_chamada).split())


_REGRA_DA_FERRAMENTA: Final[Mapping[str, Regra]] = {
    "apps.launch": Regra.ABRIR_APP,
    "browser.launch": Regra.ABRIR_NAVEGADOR,
    "window.close": Regra.FECHAR_JANELA,
    "apps.quit": Regra.ENCERRAR_APP,
    "window.focus_app": Regra.FOCAR_APP,
}


FRASES_DA_TELA: Final[dict[str, str]] = {
    "tela.mostrar": "Pronto, está na tela.",
    "tela.fechar": "Fechei.",
}
"""A ação de um passo na janela do Jarvis (ADR-0055): curta, e o turno acaba nela."""


def frase_da_ferramenta(tool_id: str, args: Mapping[str, Any], dados: Mapping[str, Any]) -> str:
    """A frase do código para uma ação de um passo que **o motor** propôs e deu certo — a mesma do
    caminho rápido, para o dono ouvir o resultado já, e uma vez (dono, 2026-10-25). Vazia para o que
    não é ação de um passo (o motor responde) e quando o aviso da ferramenta já diz tudo."""
    if tool_id in FRASES_DA_TELA:
        return FRASES_DA_TELA[tool_id] if tool_id != "tela.fechar" or dados.get("fechadas") else ""
    if tool_id == "sites.open":
        endereco = re.match(r"^https?://(?:www\.)?([^/?#:]+)", str(args.get("url", "")))
        if endereco is None:
            return ""
        return frase(Atalho(Regra.ABRIR_SITE, tool_id, args, endereco.group(1)), dados)
    regra = _REGRA_DA_FERRAMENTA.get(tool_id)
    if regra is None:
        return ""
    bruto = dados.get("app") or args.get("nome") or args.get("app") or args.get("navegador") or ""
    nome = _curta(" ".join(str(bruto).split()))
    if "." in nome and " " not in nome:  # a classe da janela («org.kde.kate»)
        nome = nome.rsplit(".", 1)[-1]
    alvo = nome.title() if nome.islower() else nome
    if regra is Regra.FECHAR_JANELA and not args.get("app"):
        alvo = ""  # «fecha a janela»: a da frente, dita pelo nome do app que a frase acha
    return frase(Atalho(regra, tool_id, args, alvo), dados)


# --- a frase ---------------------------------------------------------------------------------
LIMITE_DO_TITULO_FALADO: Final = 60


def _titulo(texto: object) -> str:
    titulo = " ".join(str(texto or "").split())
    return titulo[:LIMITE_DO_TITULO_FALADO]


def _app_da_janela(janela: Mapping[str, Any]) -> str:
    classe = str(janela.get("app") or "")
    nome = classe.rsplit(".", 1)[-1].replace("-browser", "").replace("-", " ")
    return nome.title() if nome else "uma janela"


def frase(atalho: Atalho, dados: Mapping[str, Any]) -> str:
    """A resposta falada de um atalho que deu certo — curta, do código. Vazia quando o aviso da
    ferramenta (o de uma moderada, como «Encerrei o Discord.») já diz o que aconteceu."""
    match atalho.regra:
        case Regra.ABRIR_APP | Regra.ABRIR_NAVEGADOR:
            if dados.get("ja_aberto"):
                if dados.get("visivel"):
                    return f"O {atalho.alvo} já estava aberto: trouxe para a frente."
                return (
                    f"O {atalho.alvo} já estava aberto, mas o sistema não deixou trazê-lo para a "
                    "frente."
                )
            return f"Abrindo o {atalho.alvo}."
        case Regra.FECHAR_JANELA:
            nome = atalho.alvo or _app_da_janela(dados)
            if dados.get("fechada") is False:
                return (
                    f"Pedi para fechar o {nome}, mas a janela continua aberta: ele pode estar "
                    "perguntando se salva."
                )
            com_nome = atalho.alvo or atalho.args.get("app")
            return f"Fechei a janela do {nome}." if com_nome else "Fechei a janela."
        case Regra.ENCERRAR_APP:
            if dados.get("conferido") is False:
                return "Alguns processos dele não saíram ainda."
            return ""
        case Regra.FOCAR_APP:
            return f"Pronto, o {atalho.alvo} está na frente."
        case Regra.EM_FOCO:
            return _frase_do_foco(dados)
        case Regra.JANELAS:
            return _frase_das_janelas(dados)
        case Regra.ABAS:
            abas = [a for a in dados.get("abas") or [] if isinstance(a, Mapping)]
            vista = next((a for a in abas if a.get("estado") == "à vista"), None)
            frente = f" À vista: {_titulo(vista.get('titulo'))}." if vista else ""
            return f"{len(abas)} {'aba aberta' if len(abas) == 1 else 'abas abertas'}.{frente}"
        case Regra.ABRIR_SITE:
            if dados.get("visivel") is False and not dados.get("segundo_plano"):
                return f"Abri o {atalho.alvo}, mas o navegador não veio para a frente."
            return f"Abri o {atalho.alvo}."
        case Regra.BUSCAR_NO_SITE:
            onde = f"Abri a busca do {atalho.alvo} por {atalho.termo}"
            if dados.get("visivel") is False and not dados.get("segundo_plano"):
                return f"{onde}, mas o navegador não veio para a frente."
            return f"{onde}."
        case Regra.PRIMEIRO_PASSO_NO_SITE:
            if dados.get("segundo_plano") or dados.get("visivel") is False:
                return ""  # trabalho de fundo (ler as notícias): o motor responde com o que leu
            if atalho.termo:
                return f"Abri a busca do {atalho.alvo} por {atalho.termo}."
            return f"Abri o {atalho.alvo}."
        case Regra.BUSCAR_NA_WEB:
            return ""


def _frase_do_foco(dados: Mapping[str, Any]) -> str:
    foco = dados.get("foco")
    monitores = [m for m in dados.get("monitores") or [] if isinstance(m, Mapping)]
    principal = next((m for m in monitores if m.get("principal")), None)
    if not isinstance(foco, Mapping):
        partes = ["Nenhuma janela está ativa agora."]
    else:
        onde = ""
        if foco.get("monitor"):
            onde = " no monitor principal" if foco.get("principal") else " no outro monitor"
        partes = [f"Em foco: {_app_da_janela(foco)} — {_titulo(foco.get('titulo'))}{onde}."]
    frente = principal.get("na_frente") if principal is not None else None
    if isinstance(frente, Mapping) and (
        not isinstance(foco, Mapping) or frente.get("id") != foco.get("id")
    ):
        partes.append(
            f"Na frente do monitor principal está o {_app_da_janela(frente)} — "
            f"{_titulo(frente.get('titulo'))}."
        )
    return " ".join(partes)


def _frase_das_janelas(dados: Mapping[str, Any]) -> str:
    janelas = [j for j in dados.get("janelas") or [] if isinstance(j, Mapping)]
    if not janelas:
        return "Não vejo nenhuma janela de app aberta."
    nomes = list(dict.fromkeys(_app_da_janela(j) for j in janelas))
    if len(nomes) > 6:
        return f"Abertas: {', '.join(nomes[:6])} e mais {len(nomes) - 6}."
    if len(nomes) == 1:
        return f"Aberta: {nomes[0]}."
    return f"Abertas: {', '.join(nomes[:-1])} e {nomes[-1]}."
