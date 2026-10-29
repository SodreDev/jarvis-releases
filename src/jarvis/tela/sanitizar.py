"""A allowlist do HTML que vai à tela (ADR-0055): o subconjunto do texto rico do Qt, sem nada que
busque rede, rode código ou mande dado.

Allowlist, e não "tirar o perigoso": o perigoso é aberto (cada versão de navegador ganha um vetor
novo); o que o Qt desenha é fechado — 56 tags e ~50 propriedades CSS
(<https://doc.qt.io/qt-6/richtext-html-subset.html>, lido em 2026-10-29). O que não está aqui não
passa; `HtmlSeguro.removidos` diz o que saiu, em códigos, para o modelo corrigir.

Medido nesta máquina (PySide6 6.9.3, `tests/unit/tela/test_sanitizar.py` e o teste da janela): o
`Text` do QML em RichText **busca na rede** o `<img src>`, o `url()` do atributo `style` e o do
`<style>`; o `<style>` do documento é honrado, com seletor de tipo, classe e id; link só é seguido
no clique — e aqui ele vira texto. O renderizador não tem motor de script: `<script>` nunca rodaria,
e mesmo assim sai, com o conteúdo.

O HTML é **lido** pelo `html.parser` da biblioteca padrão e **reescrito** daqui: o texto sai com
escape (`&lt;script&gt;` vindo de uma página continua sendo texto na tela), cada atributo é
conferido pela forma que o Qt aceita e o CSS é refeito declaração por declaração. Nada do original
passa sem ser reescrito.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Final

LIMITE_DE_ENTRADA: Final = 100_000
"""Caracteres de HTML de uma vez: uma tabela de centenas de linhas cabe folgada."""
LIMITE_DE_PROFUNDIDADE: Final = 40
LIMITE_DE_REGRAS: Final = 200
LIMITE_DE_DECLARACOES: Final = 40
LIMITE_DO_VALOR: Final = 160
LIMITE_DO_SELETOR: Final = 120

_BLOCO: Final = frozenset({"align", "dir"})
_CELULA: Final = frozenset({"width", "bgcolor", "colspan", "rowspan", "align", "valign", "nowrap"})
_NADA: Final[frozenset[str]] = frozenset()
GLOBAIS: Final = frozenset({"class", "id", "style"})
"""Atributos que toda tag permitida aceita: a classe e o id para o `<style>`, e o estilo inline."""

TAGS: Final[dict[str, frozenset[str]]] = {
    **{tag: _BLOCO for tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "dl", "dt")},
    **{
        tag: _NADA
        for tag in (
            "span", "b", "strong", "i", "em", "u", "s", "del", "small", "big", "sub", "sup",
            "code", "tt", "kbd", "samp", "var", "cite", "dfn", "nobr", "blockquote", "pre",
            "address", "center", "li", "dd", "thead", "tbody", "tfoot", "br",
        )
    },
    "hr": frozenset({"width"}),
    "ul": frozenset({"type"}),
    "ol": frozenset({"type", "start"}),
    "table": frozenset(
        {"border", "cellspacing", "cellpadding", "width", "height", "align", "bgcolor"}
    ),
    "tr": frozenset({"bgcolor", "align", "valign"}),
    "td": _CELULA,
    "th": _CELULA,
    "font": frozenset({"color", "size", "face"}),
}  # fmt: skip
"""Tag permitida → atributos dela (além dos `GLOBAIS`). É o subconjunto do Qt sem `a` e `img`."""
VAZIAS: Final = frozenset({"br", "hr"})

RENOMEADAS: Final[dict[str, str]] = {
    "a": "span", "section": "div", "article": "div", "main": "div", "header": "div",
    "footer": "div", "nav": "div", "aside": "div", "figure": "div", "details": "div",
    "fieldset": "div", "form": "div", "figcaption": "p", "caption": "p", "summary": "p",
    "legend": "p", "mark": "span", "abbr": "span", "q": "span", "label": "span", "time": "span",
    "marquee": "span", "strike": "s", "ins": "u",
}  # fmt: skip
"""Tag que o Qt não desenha mas cujo texto vale: troca pela vizinha que ele desenha. O `<a>` vira
texto (sem `href`, nada a seguir); o `<form>` vira caixa (sem `action`, nada a enviar)."""

TRANSPARENTES: Final = frozenset({"html", "head", "body", "tbody"})
"""A moldura do documento: some, e o conteúdo fica (o `<style>` do `<head>` inclusive)."""

DESCARTADAS: Final[dict[str, str]] = {
    "script": "script", "noscript": "script", "template": "script", "iframe": "quadro",
    "frame": "quadro", "frameset": "quadro", "noframes": "quadro", "object": "quadro",
    "embed": "quadro", "applet": "quadro", "svg": "svg", "math": "svg", "textarea": "campo",
    "select": "campo", "option": "campo", "optgroup": "campo", "datalist": "campo",
    "button": "campo", "audio": "midia", "video": "midia", "canvas": "midia", "picture": "midia",
    "map": "midia", "title": "meta", "xmp": "script", "plaintext": "script", "dialog": "campo",
    "slot": "script", "portal": "quadro", "noembed": "quadro",
}  # fmt: skip
"""Tag que sai **com o conteúdo**, e o código do que saiu."""
DESCARTADAS_VAZIAS: Final[dict[str, str]] = {
    "img": "imagem", "image": "imagem", "input": "campo", "keygen": "campo", "link": "meta",
    "meta": "meta", "base": "meta", "source": "midia", "track": "midia", "wbr": "tag",
    "area": "midia", "param": "quadro", "col": "tag", "colgroup": "tag", "isindex": "campo",
}  # fmt: skip

PROPRIEDADES: Final = frozenset(
    {
        "color", "background-color", "background", "font", "font-family", "font-size",
        "font-weight", "font-style", "font-variant", "text-decoration", "text-transform",
        "text-indent", "text-align", "white-space", "word-spacing", "letter-spacing",
        "line-height", "vertical-align", "float", "list-style-type", "width", "height",
        "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
        "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
        "border", "border-top", "border-right", "border-bottom", "border-left",
        "border-color", "border-top-color", "border-right-color", "border-bottom-color",
        "border-left-color", "border-style", "border-top-style", "border-right-style",
        "border-bottom-style", "border-left-style", "border-width", "border-top-width",
        "border-right-width", "border-bottom-width", "border-left-width", "border-collapse",
        "border-spacing",
    }
)  # fmt: skip
"""As propriedades que o Qt desenha (e duas que ele ignora sem risco). Nenhuma busca recurso:
`background-image` e companhia ficam de fora pelo nome, e `url()` pelo valor."""
FUNCOES: Final = frozenset({"rgb", "rgba", "hsl", "hsla"})
"""Função em valor de CSS: só cor. `url()`, `expression()`, `attr()`, `var()`… não passam."""
PROIBIDO_NO_VALOR: Final = (
    "url", "expression", "javascript", "vbscript", "behavior", "binding", "import", "\\", "@",
    "<", ">", "{", "}", ";", "&", "=", "`", "!", "/*", "*/",
)  # fmt: skip

_VALOR: Final = re.compile(r"^[\w\s#%.,'\"()+/-]+$")
_FUNCAO: Final = re.compile(r"([A-Za-z_-]+)\s*\(")
_PROPRIEDADE: Final = re.compile(r"^[a-z][a-z-]{0,40}$")
_SELETOR: Final = re.compile(r"^[A-Za-z0-9_\-.#\s>+~*]+$")
COR: Final = re.compile(
    r"^(?:#[0-9a-fA-F]{3,8}|[A-Za-z]{3,24}|(?:rgb|rgba|hsl|hsla)\(\s*[\d.%\s,]+\))$"
)
"""Uma cor como o Qt lê: `#rgb`…`#rrggbbaa`, nome, ou `rgb()`/`hsl()` com números."""
_COR: Final = COR
_NUMERO: Final = re.compile(r"^\d{1,4}%?$")
_PEQUENO: Final = re.compile(r"^\d{1,2}$")
_INTEIRO: Final = re.compile(r"^\d{1,5}$")
_ID: Final = re.compile(r"^[A-Za-z_][\w-]{0,40}$")
_CLASSES: Final = re.compile(r"^[A-Za-z_][\w-]{0,40}(?:\s+[A-Za-z_][\w-]{0,40}){0,7}$")
_FACE: Final = re.compile(r"^[\w\s,'\"-]{1,80}$")
_TAMANHO_DA_FONTE: Final = re.compile(r"^[+-]?[1-7]$")
_COMENTARIO: Final = re.compile(r"/\*.*?\*/", re.S)
_ENUMERADOS: Final[dict[str, frozenset[str]]] = {
    "align": frozenset({"left", "right", "center", "justify"}),
    "valign": frozenset({"top", "middle", "bottom", "baseline"}),
    "dir": frozenset({"ltr", "rtl"}),
    "type": frozenset({"1", "a", "A", "i", "I", "disc", "circle", "square"}),
}


@dataclass(frozen=True, slots=True)
class HtmlSeguro:
    """O HTML reescrito: o corpo, a folha de estilo limpa, o fundo pedido e o que saiu."""

    corpo: str
    css: str = ""
    fundo: str = ""
    """A cor de fundo que o documento pediu (`<body bgcolor>`, `body { background-color }`): a
    janela pinta o módulo dela — é como o tema claro fica coerente (o Qt não pinta o `body`)."""
    removidos: tuple[str, ...] = ()
    """Códigos do que saiu (`script`, `imagem`, `url`, `evento`…), em ordem, sem repetição."""

    @property
    def documento(self) -> str:
        """O documento que a tela recebe. Sanitizá-lo de novo devolve ele mesmo."""
        estilo = f"<style>{self.css}</style>" if self.css else ""
        fundo = f' bgcolor="{self.fundo}"' if self.fundo else ""
        return f"<html><head>{estilo}</head><body{fundo}>{self.corpo}</body></html>"

    @property
    def vazio(self) -> bool:
        return not re.sub(r"<[^>]*>", "", self.corpo).strip()


GRADE_DA_TABELA: Final[tuple[tuple[str, str], ...]] = (
    ("border", "1"),
    ("cellspacing", "0"),
    ("cellpadding", "6"),
)
"""A grade fina que a tabela ganha quando não traz a dela. Medido offscreen (2026-10-29): o `Text`
do QML **não** desenha borda de célula pelo CSS (`td { border: … }`), só a do atributo `border` da
tabela, na cor do `border-color` dela; `border="0"` tira a grade."""


def sanitizar(bruto: str, *, tema: str = "", grade: bool = False) -> HtmlSeguro:
    """Reescreve `bruto` pela allowlist. `tema` é a folha do Jarvis (`jarvis.tela.tema`), que vai
    antes da do modelo — a dele vale por cima, como num navegador. `grade` dá à tabela sem `border`,
    `cellspacing` ou `cellpadding` os da `GRADE_DA_TABELA` (o resultado continua ponto fixo)."""
    removidos: list[str] = []
    if len(bruto) > LIMITE_DE_ENTRADA:
        bruto = bruto[:LIMITE_DE_ENTRADA]
        removidos.append("tamanho")
    limpador = _Limpador(removidos, grade=grade)
    limpador.feed(bruto)
    limpador.close()
    corpo = limpador.terminar()
    folhas = [_folha(tema, removidos, aceitar_fundo=False)[0]] if tema else []
    fundo = limpador.fundo
    for estilo in limpador.estilos:
        css, fundo_da_folha = _folha(estilo, removidos)
        folhas.append(css)
        fundo = fundo_da_folha or fundo
    if limpador.estilo_do_body:
        folhas.append(f"body {{ {limpador.estilo_do_body} }}")
    return HtmlSeguro(
        corpo=corpo,
        css=" ".join(f for f in folhas if f),
        fundo=fundo,
        removidos=tuple(dict.fromkeys(removidos)),
    )


# --- o HTML ---------------------------------------------------------------------------------------
@dataclass(slots=True)
class _Aberta:
    saida: str
    """A tag que foi escrita (depois de renomeada)."""
    original: str


class _Limpador(HTMLParser):
    """Lê o HTML do modelo e escreve só o que a allowlist aceita."""

    def __init__(self, removidos: list[str], *, grade: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.removidos = removidos
        self.grade = grade
        self.saida: list[str] = []
        self.abertas: list[_Aberta] = []
        self.estilos: list[str] = []
        self.fundo = ""
        self.estilo_do_body = ""
        self._descartada = ""
        self._aninhadas = 0
        self._no_estilo = False
        self._estilo_atual: list[str] = []

    # --- os eventos do parser ----------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        nome = tag.lower()
        if self._descartada:
            if nome == self._descartada:
                self._aninhadas += 1
            return
        if self._no_estilo:
            return
        if nome == "style":
            self._no_estilo = True
            self._estilo_atual = []
            return
        if nome in DESCARTADAS:
            self.removidos.append(DESCARTADAS[nome])
            self._descartada, self._aninhadas = nome, 1
            return
        if nome in DESCARTADAS_VAZIAS:
            self.removidos.append(DESCARTADAS_VAZIAS[nome])
            return
        if nome in TRANSPARENTES:
            if nome == "body":
                self._fundo_do_body(attrs)
            return
        saida = RENOMEADAS.get(nome, nome)
        if saida not in TAGS:
            self.removidos.append("tag")
            return  # tag desconhecida: some, o texto dela fica
        if nome in ("a", "form"):
            self.removidos.append("link" if nome == "a" else "formulario")
        if len(self.abertas) >= LIMITE_DE_PROFUNDIDADE and saida not in VAZIAS:
            self.removidos.append("profundidade")
            return
        self.saida.append(f"<{saida}{self._atributos(saida, attrs)}>")
        if saida not in VAZIAS:
            self.abertas.append(_Aberta(saida, nome))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        nome = tag.lower()
        self.handle_starttag(tag, attrs)
        if nome not in VAZIAS and RENOMEADAS.get(nome, nome) not in VAZIAS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        nome = tag.lower()
        if self._descartada:
            if nome == self._descartada:
                self._aninhadas -= 1
                if self._aninhadas <= 0:
                    self._descartada = ""
            return
        if nome == "style" and self._no_estilo:
            self._no_estilo = False
            self.estilos.append("".join(self._estilo_atual))
            return
        if self._no_estilo:
            return
        for posicao in range(len(self.abertas) - 1, -1, -1):
            if self.abertas[posicao].original == nome:
                # Fecha também o que ficou aberto dentro dela (HTML mal aninhado).
                while len(self.abertas) > posicao:
                    self.saida.append(f"</{self.abertas.pop().saida}>")
                return

    def handle_data(self, data: str) -> None:
        if self._descartada:
            return
        if self._no_estilo:
            self._estilo_atual.append(data)
            return
        self.saida.append(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        del data  # comentário não vai à tela

    def handle_decl(self, decl: str) -> None:
        del decl

    def handle_pi(self, data: str) -> None:
        del data

    def unknown_decl(self, data: str) -> None:
        del data

    def terminar(self) -> str:
        if self._no_estilo:  # `<style>` sem fechar: o que veio é a folha
            self.estilos.append("".join(self._estilo_atual))
            self._no_estilo = False
        while self.abertas:
            self.saida.append(f"</{self.abertas.pop().saida}>")
        return "".join(self.saida)

    # --- os atributos --------------------------------------------------------------------------
    def _atributos(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        permitidos = TAGS[tag] | GLOBAIS
        partes: list[str] = []
        vistos: set[str] = set()
        for bruto, valor in attrs:
            nome = bruto.lower()
            if nome in vistos:
                continue
            vistos.add(nome)
            if nome not in permitidos:
                self.removidos.append(_codigo_do_atributo(nome))
                continue
            limpo = self._valor(nome, valor or "")
            if limpo is None:
                continue
            partes.append(nome if limpo == "" else f'{nome}="{html.escape(limpo, quote=True)}"')
        if tag == "table" and self.grade:
            partes += [f'{nome}="{valor}"' for nome, valor in GRADE_DA_TABELA if nome not in vistos]
        return "".join(f" {p}" for p in partes)

    def _valor(self, nome: str, valor: str) -> str | None:
        """O valor do atributo na forma que o Qt aceita, `""` para atributo sem valor, ou `None`
        (sai)."""
        valor = valor.strip()
        if nome == "style":
            declaracoes = _declaracoes(valor, self.removidos)
            return declaracoes or None
        if nome == "nowrap":
            return ""
        if nome in _ENUMERADOS:
            aceito = valor if valor in _ENUMERADOS[nome] else valor.lower()
            return aceito if aceito in _ENUMERADOS[nome] else self._fora(nome)
        if nome in ("color", "bgcolor"):
            return valor if _COR.match(valor) else self._fora(nome)
        if nome in ("width", "height"):
            return valor if _NUMERO.match(valor) else self._fora(nome)
        if nome in ("border", "cellspacing", "cellpadding"):
            return valor if _PEQUENO.match(valor) else self._fora(nome)
        if nome in ("colspan", "rowspan"):
            return valor if _INTEIRO.match(valor) and 1 <= int(valor) <= 50 else self._fora(nome)
        if nome == "start":
            return valor if _INTEIRO.match(valor) else self._fora(nome)
        if nome == "size":
            return valor if _TAMANHO_DA_FONTE.match(valor) else self._fora(nome)
        if nome == "face":
            ok = _FACE.match(valor) and not _tem_proibido(valor)
            return valor if ok else self._fora(nome)
        if nome == "class":
            return " ".join(valor.split()) if _CLASSES.match(valor) else self._fora(nome)
        if nome == "id":
            return valor if _ID.match(valor) else self._fora(nome)
        return self._fora(nome)

    def _fora(self, nome: str) -> str | None:
        """O atributo existe na tag, mas o valor não tem a forma que o Qt aceita: sai (`None`)."""
        del nome
        self.removidos.append("atributo")
        return None

    def _fundo_do_body(self, attrs: list[tuple[str, str | None]]) -> None:
        """`<body bgcolor>` e o `style` do body: o fundo vai para a janela; a cor e a fonte, para
        uma regra `body` da folha."""
        for bruto, valor in attrs:
            nome, texto = bruto.lower(), (valor or "").strip()
            if nome == "bgcolor" and _COR.match(texto):
                self.fundo = texto
            elif nome == "style":
                restantes: list[str] = []
                for declaracao in _declaracoes(texto, self.removidos).split(";"):
                    propriedade, _, conteudo = declaracao.partition(":")
                    propriedade, conteudo = propriedade.strip(), conteudo.strip()
                    if not propriedade:
                        continue
                    if propriedade in ("background-color", "background") and _COR.match(conteudo):
                        self.fundo = conteudo
                    else:
                        restantes.append(f"{propriedade}: {conteudo}")
                self.estilo_do_body = "; ".join(restantes)
            elif nome in ("onload", "background") or nome.startswith("on"):
                self.removidos.append(_codigo_do_atributo(nome))


def _codigo_do_atributo(nome: str) -> str:
    if nome.startswith("on"):
        return "evento"
    if nome in ("href", "xlink:href", "action", "formaction"):
        return "link"
    if nome in ("src", "srcset", "background", "poster", "lowsrc", "dynsrc", "data"):
        return "imagem"
    return "atributo"


# --- o CSS ----------------------------------------------------------------------------------------
def _tem_proibido(valor: str) -> bool:
    baixo = valor.lower()
    return any(proibido in baixo for proibido in PROIBIDO_NO_VALOR)


def _valor_css(propriedade: str, valor: str, removidos: list[str]) -> str | None:
    valor = " ".join(valor.split())
    if not valor or len(valor) > LIMITE_DO_VALOR:
        removidos.append("css")
        return None
    if _tem_proibido(valor):
        removidos.append("url" if "url" in valor.lower() or "import" in valor.lower() else "css")
        return None
    if not _VALOR.match(valor):
        removidos.append("css")
        return None
    if any(f.lower() not in FUNCOES for f in _FUNCAO.findall(valor)):
        removidos.append("css")
        return None
    if propriedade == "background" and not _COR.match(valor):
        removidos.append("css")  # o atalho `background` só como cor; imagem nunca
        return None
    return valor


def _declaracoes(texto: str, removidos: list[str]) -> str:
    """`prop: valor; …` reescrito pela allowlist: o que não passa, sai."""
    texto = _sem_comentarios(texto)
    saida: list[str] = []
    for declaracao in texto.split(";")[: LIMITE_DE_DECLARACOES * 2]:
        if not declaracao.strip():
            continue
        propriedade, separador, valor = declaracao.partition(":")
        propriedade = propriedade.strip().lower()
        if not separador or not _PROPRIEDADE.match(propriedade):
            removidos.append("css")
            continue
        if propriedade not in PROPRIEDADES:
            removidos.append("url" if "image" in propriedade else "css")
            continue
        limpo = _valor_css(propriedade, valor, removidos)
        if limpo is None:
            continue
        nome = "background-color" if propriedade == "background" else propriedade
        saida.append(f"{nome}: {limpo}")
        if len(saida) >= LIMITE_DE_DECLARACOES:
            break
    return "; ".join(saida)


def _sem_comentarios(texto: str) -> str:
    texto = _COMENTARIO.sub(" ", texto)
    aberto = texto.find("/*")
    return texto if aberto < 0 else texto[:aberto]  # comentário sem fim: o resto é dele


def _folha(css: str, removidos: list[str], *, aceitar_fundo: bool = True) -> tuple[str, str]:
    """Uma folha `<style>` reescrita regra a regra: (o CSS limpo, o fundo do `body`). At-regra
    (`@import`, `@media`, `@font-face`…) sai inteira, com o bloco."""
    css = _sem_comentarios(css)
    regras: list[str] = []
    fundo = ""
    posicao = 0
    while posicao < len(css) and len(regras) < LIMITE_DE_REGRAS:
        while posicao < len(css) and css[posicao].isspace():
            posicao += 1
        abre = css.find("{", posicao)
        fim_de_instrucao = css.find(";", posicao)
        if (
            css.startswith("@", posicao)
            and fim_de_instrucao >= 0
            and (abre < 0 or fim_de_instrucao < abre)
        ):
            # At-regra sem bloco (`@import url(…);`, `@charset …;`): sai só ela.
            instrucao = css[posicao:fim_de_instrucao].lower()
            removidos.append("url" if "import" in instrucao else "regra_@")
            posicao = fim_de_instrucao + 1
            continue
        if abre < 0:
            break
        preludio = css[posicao:abre].strip()
        fecha, profundidade = abre + 1, 1
        while fecha < len(css) and profundidade:
            if css[fecha] == "{":
                profundidade += 1
            elif css[fecha] == "}":
                profundidade -= 1
            fecha += 1
        corpo = css[abre + 1 : fecha - 1] if profundidade == 0 else css[abre + 1 :]
        posicao = fecha
        if preludio.startswith("@") or "@" in preludio:
            removidos.append("url" if "import" in preludio.lower() else "regra_@")
            continue
        if "{" in corpo:  # bloco aninhado fora de at-regra: não é CSS que o Qt entenda
            removidos.append("css")
            continue
        seletores = _seletores(preludio, removidos)
        if not seletores:
            continue
        declaracoes = _declaracoes(corpo, removidos)
        if aceitar_fundo and seletores in ("body", "html"):
            restantes: list[str] = []
            for declaracao in declaracoes.split("; "):
                propriedade, _, valor = declaracao.partition(": ")
                if propriedade == "background-color" and _COR.match(valor):
                    fundo = valor
                elif declaracao:
                    restantes.append(declaracao)
            declaracoes = "; ".join(restantes)
        if declaracoes:
            regras.append(f"{seletores} {{ {declaracoes} }}")
    return " ".join(regras), fundo


def _seletores(preludio: str, removidos: list[str]) -> str:
    """Seletor de tipo, classe, id e descendente: o que o Qt aplica. Pseudo-classe (`:hover`),
    atributo (`[href]`) e função não passam."""
    aceitos: list[str] = []
    for seletor in preludio.split(",")[:10]:
        limpo = " ".join(seletor.split())
        if not limpo or len(limpo) > LIMITE_DO_SELETOR or not _SELETOR.match(limpo):
            removidos.append("seletor")
            continue
        aceitos.append(limpo.lower() if limpo.isalpha() else limpo)
    return ", ".join(aceitos)


__all__ = ["COR", "GRADE_DA_TABELA", "HtmlSeguro", "sanitizar"]
