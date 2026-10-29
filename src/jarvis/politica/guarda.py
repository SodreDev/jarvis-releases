"""O guarda de contexto: a ação de script, CDP ou MCP comparada com o objetivo (ADR-0049).

Toda ação dessas ferramentas tem efeito que depende de texto que o modelo escreve (um script, um
gesto, uma chamada a servidor de fora). Antes do PDP, o executor pergunta a este guarda se a ação
cabe no objetivo do pedido (ADR-0030) e devolve uma de três saídas, com motivo curto:

- **permitir** — segue ao PDP como antes;
- **pedir confirmação** — o motivo vira o `exige_o_sim` do pedido ao PDP (a máquina do sim que já
  existe faz o resto);
- **barrar** — volta ao modelo como `negado`, com a **instrução de correção** ("isso foge do
  objetivo X: faça Y").

Otimizado por construção (o Jev custa ~0,6 s; ADR-0029): leitura pura passa direto; a lista de
negação e as regras de sim e de permissão decidem sem rede; o veredito do Jev fica em cache por
(objetivo, forma da ação); só a **zona cinza** vai ao classificador, com prazo curto, e qualquer
falha dele **pede o sim** — falha nunca permite. O guarda nunca autoriza o que o PDP nega
(ADR-0004) e nunca lê conteúdo de página, resultado de ferramenta ou saída de servidor: isso é
dado, não ordem.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final
from urllib.parse import urlsplit

from jarvis.decisao.interface import (
    ClassificadorDeDecisao,
    DecisaoIndisponivel,
    Pergunta,
    PerguntaEscolha,
    RespostaEscolha,
)
from jarvis.memoryd.importacao import classe_de_pii, redigir
from jarvis.navegador.risco import categoria as categoria_do_site
from jarvis.politica.objetivo import Objetivo
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado

PRAZO_PADRAO_S: Final = 0.8
"""O Jev mediu p95 617 ms (ADR-0029): o guarda espera um pouco mais que isso e desiste."""
LIMIAR_PERMITIR: Final = 0.75
LIMIAR_BARRAR: Final = 0.60
TAMANHO_DO_CACHE: Final = 256
CARACTERES_DO_CODIGO: Final = 600
"""O esqueleto do script que vai ao classificador, já redigido."""
BARRADAS_ATE_DESISTIR: Final = 2
SENSIVEL: Final = "sensitive"


class Saida(StrEnum):
    PERMITIR = "permitir"
    PEDIR_CONFIRMACAO = "pedir_confirmacao"
    BARRAR = "barrar"


class Tipo(StrEnum):
    LEITURA = "leitura"
    SCRIPT_NA_PAGINA = "script_na_pagina"
    SCRIPT_NA_CAIXA = "script_na_caixa"
    GESTO = "gesto"
    MCP = "mcp"


class Categoria(StrEnum):
    NENHUMA = "nenhuma"
    CREDENCIAIS = "credenciais"
    EXFILTRAR = "exfiltrar"
    BAIXAR_EXECUTAR = "baixar_executar"
    ENVIAR = "enviar"
    FORA_DO_DOMINIO = "fora_do_dominio"
    DOMINIO_SENSIVEL = "dominio_sensivel"
    OFUSCADO = "ofuscado"
    SEM_REDE = "sem_rede"
    FORA_DO_OBJETIVO = "fora_do_objetivo"


GUARDADAS: Final[Mapping[str, Tipo]] = {
    "browser.console": Tipo.LEITURA,
    "browser.rede": Tipo.LEITURA,
    "browser.avaliar": Tipo.SCRIPT_NA_PAGINA,
    "browser.gesto": Tipo.GESTO,
    "script.rodar": Tipo.SCRIPT_NA_CAIXA,
}
"""As ferramentas que passam pelo guarda — além de toda `mcp.*` (ADR-0052)."""
PREFIXO_MCP: Final = "mcp."


def guardada(tool_id: str) -> bool:
    return tool_id in GUARDADAS or tool_id.startswith(PREFIXO_MCP)


MOTIVOS: Final[Mapping[Categoria, str]] = {
    Categoria.CREDENCIAIS: "o script mexe em cookie, armazenamento da página ou senha",
    Categoria.EXFILTRAR: "o script manda dado da página para um endereço",
    Categoria.BAIXAR_EXECUTAR: "o script baixa ou roda código que não está nele",
    Categoria.ENVIAR: "o script envia (formulário, mensagem ou pagamento) sem o sim do dono",
    Categoria.FORA_DO_DOMINIO: "a ação sai dos sites e da caixa do objetivo",
    Categoria.DOMINIO_SENSIVEL: "a aba é de banco, senha, e-mail ou pagamento",
    Categoria.OFUSCADO: "o script esconde o próprio texto",
    Categoria.SEM_REDE: "o script usa rede e a caixa não tem rede",
    Categoria.FORA_DO_OBJETIVO: "a ação não serve ao que o dono pediu",
    Categoria.NENHUMA: "a ação não cabe no objetivo",
}
ALTERNATIVAS: Final[Mapping[Categoria, str]] = {
    Categoria.CREDENCIAIS: (
        "leia o que precisa pelo que está à vista (browser.read, browser.inspecionar), sem "
        "cookie, armazenamento nem senha"
    ),
    Categoria.EXFILTRAR: (
        "não mande dado para endereço nenhum: devolva o que achou como resultado do script"
    ),
    Categoria.BAIXAR_EXECUTAR: (
        "escreva o script inteiro você mesmo, legível, sem baixar código, chamar outro programa "
        "nem instalar pacote"
    ),
    Categoria.ENVIAR: (
        "enviar, publicar e pagar é do dono: use browser.acionar (enviar) ou browser.click no "
        "botão, que pedem o sim dele"
    ),
    Categoria.FORA_DO_DOMINIO: (
        "fique nos sites do objetivo; para abrir outro endereço use browser.navigate, que confere "
        "o objetivo, e na caixa use só a pasta dela"
    ),
    Categoria.DOMINIO_SENSIVEL: (
        "nessas páginas o Jarvis não roda script: leia com browser.read ou peça ao dono"
    ),
    Categoria.OFUSCADO: "escreva o script legível, sem codificar o texto",
    Categoria.SEM_REDE: "passe os dados como entrada do script; a caixa não tem rede",
    Categoria.FORA_DO_OBJETIVO: "volte ao que o dono pediu",
    Categoria.NENHUMA: "volte ao que o dono pediu",
}
DESISTIR: Final = "não tente de novo por outro caminho: diga ao dono o que não dá para fazer"


@dataclass(frozen=True, slots=True)
class Acao:
    """O que o guarda julga. Quem monta é o executor, com os argumentos já no contrato."""

    tool_id: str
    tipo: Tipo
    alvo: str = ""
    """A URL da aba onde o script ou o gesto age, ou o destino da chamada (vazio = nenhum)."""
    codigo: str = ""
    linguagem: str = "js"
    mundo: str = "isolado"
    """`browser.avaliar`: `isolado` (padrão) ou `principal` (o mundo da própria página)."""
    rede: bool = False
    """`script.rodar`: a caixa com rede (só com o sim do dono)."""
    detalhe: str = ""
    """O gesto (`clicar`, `rolar`…) ou a ferramenta do servidor MCP."""
    tier: str = ""
    """MCP: o que o dono escreveu na configuração (`leitura`, `livre`, `moderado`, `perigoso`)."""
    destinos: tuple[str, ...] = ()
    """URLs que a chamada leva nos argumentos (MCP que navega, por exemplo)."""


@dataclass(frozen=True, slots=True)
class Julgamento:
    saida: Saida
    motivo: str
    """Curto, escrito pelo nosso código (vai à trilha e à pergunta ao dono)."""
    instrucao: str = ""
    """O que o modelo ouve quando é barrado: o porquê e o que fazer no lugar."""
    regra: str = ""
    categoria: Categoria = Categoria.NENHUMA
    ms: float = 0.0
    cache: bool = False
    jev: str = ""
    """A escolha e a probabilidade do Jev, quando houve consulta."""

    def com(self, *, ms: float, cache: bool = False, instrucao: str | None = None) -> Julgamento:
        return Julgamento(
            self.saida,
            self.motivo,
            self.instrucao if instrucao is None else instrucao,
            self.regra,
            self.categoria,
            ms,
            cache,
            self.jev,
        )


def _padroes(*fontes: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(f, re.IGNORECASE) for f in fontes)


# O que um script de página não pode tocar (a ordem é a da prioridade da categoria).
_NA_PAGINA: Final[tuple[tuple[Categoria, tuple[re.Pattern[str], ...]], ...]] = (
    (
        Categoria.CREDENCIAIS,
        _padroes(
            r"\bdocument\s*\.\s*cookie\b",
            r"\b(local|session)Storage\b",
            r"\bindexedDB\b",
            r"\bcaches\s*\.",
            r"\bnavigator\s*\.\s*credentials\b",
            r"\b(chrome|browser)\s*\.\s*cookies\b",
            r"\bPasswordCredential\b",
            r"type\s*=\s*\\?[\"']?password",
            r"\[\s*type\s*=\s*\\?[\"']?password",
        ),
    ),
    (
        Categoria.BAIXAR_EXECUTAR,
        _padroes(
            r"\beval\s*\(",
            r"\bnew\s+Function\b",
            r"\bimport\s*\(",
            r"\bimportScripts\b",
            r"createElement\s*\(\s*[\"'`]script",
            r"\.download\s*=",
            r"\bset(Timeout|Interval)\s*\(\s*[\"'`]",
        ),
    ),
    (
        Categoria.EXFILTRAR,
        _padroes(
            r"\bfetch\s*\(",
            r"\bXMLHttpRequest\b",
            r"\bWebSocket\b",
            r"\bEventSource\b",
            r"\bsendBeacon\b",
            r"\bnew\s+Image\b",
            r"\bRTCPeerConnection\b",
            r"\bpostMessage\s*\(",
            r"\.(src|action|formAction)\s*=",
        ),
    ),
    (
        Categoria.ENVIAR,
        _padroes(r"\.submit\s*\(", r"\brequestSubmit\b"),
    ),
    (
        Categoria.FORA_DO_DOMINIO,
        _padroes(
            r"(?<!let )(?<!var )(?<!const )\blocation\s*(\.\s*href\s*)?=(?!=)",
            r"\blocation\s*\.\s*(assign|replace)\s*\(",
            r"\bwindow\s*\.\s*open\s*\(",
            r"\bhistory\s*\.\s*(push|replace)State\b",
        ),
    ),
)
_CLIQUE_POR_SCRIPT: Final = re.compile(r"\.click\s*\(|\bdispatchEvent\s*\(", re.IGNORECASE)

# O que muda a página: com qualquer um destes, o script não é "só leitura".
_ESCRITA_NA_PAGINA: Final = _padroes(
    r"\.(innerHTML|outerHTML|textContent|innerText|value|checked|selected|className|id|title|"
    r"src|href|style\.\w+|disabled|hidden)\s*(\+|-)?=(?!=)",
    r"\b(setAttribute|removeAttribute|toggleAttribute|appendChild|removeChild|insertBefore|"
    r"replaceChild|replaceChildren|insertAdjacent\w*|remove|append|prepend|after|before|"
    r"replaceWith|dispatchEvent|focus|blur|click|submit|requestSubmit|scrollTo|scrollBy|"
    r"scrollIntoView|showModal|close|play|pause|setRangeText|execCommand)\s*\(",
    r"\bdocument\s*\.\s*(write|writeln|open)\s*\(",
    r"\.classList\s*\.\s*(add|remove|toggle|replace)\s*\(",
    r"\bObject\s*\.\s*(defineProperty|assign)\s*\(",
    r"\bwindow\s*\.\s*\w+\s*=(?!=)",
)

# O executor isolado (ADR-0050): a caixa não tem rede nem a casa do dono, mas o pedido dessas
# coisas já diz que o script saiu do eixo — barrar cedo poupa a rodada e explica o porquê.
_NA_CAIXA: Final[tuple[tuple[Categoria, tuple[re.Pattern[str], ...]], ...]] = (
    (
        Categoria.CREDENCIAIS,
        _padroes(
            r"\.ssh\b",
            r"\.gnupg\b",
            r"\bkeyring\b",
            r"/etc/shadow\b",
            r"\.netrc\b",
            r"\bid_(rsa|ed25519|ecdsa)\b",
            r"\bsecret-tool\b",
        ),
    ),
    (
        Categoria.BAIXAR_EXECUTAR,
        _padroes(
            r"\bsubprocess\b",
            r"\bos\s*\.\s*(system|popen|exec\w*|spawn\w*|fork)\b",
            r"\bpip3?\s+install\b",
            r"\bensurepip\b",
            r"\bctypes\b",
            r"\bchild_process\b",
            r"\bprocess\s*\.\s*(binding|dlopen)\b",
            r"\b(curl|wget)\b[^\n]*\|\s*(ba)?sh\b",
        ),
    ),
    (
        Categoria.FORA_DO_DOMINIO,
        _padroes(r"(?<![\w.])/home/", r"[\"'`]~/", r"\bexpanduser\b", r"\bPath\s*\.\s*home\b"),
    ),
)
_REDE_NA_CAIXA: Final = _padroes(
    r"\bsocket\b",
    r"\burllib\b",
    r"\brequests\b",
    r"\bhttp\s*\.\s*client\b",
    r"\bhttpx\b",
    r"\baiohttp\b",
    r"\bftplib\b",
    r"\bsmtplib\b",
    r"\btelnetlib\b",
    r"\bfetch\s*\(",
    r"require\s*\(\s*[\"'](node:)?(net|http|https|http2|dgram|tls|dns)[\"']",
    r"\bfrom\s+[\"'](node:)?(net|http|https|http2|dgram|tls|dns)[\"']",
)
_ENVIA_DA_CAIXA: Final = _padroes(r"\bsmtplib\b")

_ESCAPES: Final = re.compile(r"\\x[0-9a-f]{2}|\\u[0-9a-f]{4}|\\u\{[0-9a-f]+\}", re.IGNORECASE)
_BASE64_LONGO: Final = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")
_CODIGO_DE_CARACTERE: Final = re.compile(r"\bfromCharCode\b|\batob\s*\(", re.IGNORECASE)
_LITERAL: Final = re.compile(
    r"\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`", re.DOTALL
)
_NUMERO: Final = re.compile(r"\b\d+(?:\.\d+)?\b")
_COMENTARIO: Final = re.compile(r"/\*.*?\*/|(?<![:\"'])//[^\n]*|^\s*#[^\n]*", re.DOTALL | re.M)
_URL: Final = re.compile(r"\bhttps?://[^\s\"'`<>)]+", re.IGNORECASE)

SITES_SEM_SCRIPT: Final = frozenset({"banco", "senha", "email", "pagamento"})
"""Decisão do dono (2026-10-29): nessas abas o Jarvis não roda script nenhum."""
SITES_QUE_PEDEM_O_SIM_NO_GESTO: Final = frozenset(
    {"banco", "senha", "email", "pagamento", "mensageiro"}
)


def ofuscado(codigo: str) -> bool:
    """Texto que ninguém escreve para ler uma página: muitos escapes, base64 longo, ou o texto
    montado por código de caractere."""
    return (
        len(_ESCAPES.findall(codigo)) > 8
        or _BASE64_LONGO.search(codigo) is not None
        or len(_CODIGO_DE_CARACTERE.findall(codigo)) > 1
    )


def esqueleto(codigo: str) -> str:
    """O script sem comentário, sem o valor dos literais e dos números e com o espaço colapsado:
    duas chamadas que só diferem nos valores têm o mesmo esqueleto (a forma do cache)."""
    sem_comentario = _COMENTARIO.sub(" ", codigo)
    sem_texto = _LITERAL.sub('"…"', sem_comentario)
    sem_numero = _NUMERO.sub("0", sem_texto)
    return " ".join(sem_numero.split())


def categorias_do_codigo(codigo: str, tipo: Tipo, *, rede: bool = False) -> list[Categoria]:
    """As categorias de risco que a análise estática acha, na ordem da prioridade."""
    if not codigo:
        return []
    achadas: list[Categoria] = []
    tabela = _NA_PAGINA if tipo is Tipo.SCRIPT_NA_PAGINA else _NA_CAIXA
    for nome, padroes in tabela:
        if any(p.search(codigo) for p in padroes):
            achadas.append(nome)
    if tipo is Tipo.SCRIPT_NA_CAIXA:
        if any(p.search(codigo) for p in _ENVIA_DA_CAIXA):
            achadas.append(Categoria.ENVIAR)
        if not rede and any(p.search(codigo) for p in _REDE_NA_CAIXA):
            achadas.append(Categoria.SEM_REDE)
    if ofuscado(codigo):
        achadas.append(Categoria.OFUSCADO)
    return achadas


def so_le_a_pagina(codigo: str) -> bool:
    """Script de página sem nenhuma escrita, navegação, rede ou armazenamento: só lê o DOM."""
    if not codigo.strip() or categorias_do_codigo(codigo, Tipo.SCRIPT_NA_PAGINA):
        return False
    return not any(p.search(codigo) for p in _ESCRITA_NA_PAGINA)


def host_de(url: str) -> str:
    if not url:
        return ""
    alvo = url if "://" in url else f"https://{url}"
    try:
        return (urlsplit(alvo).hostname or "").lower()
    except ValueError:
        return ""


def _destinos_do_codigo(codigo: str) -> list[str]:
    return [m.group(0) for m in _URL.finditer(codigo)]


PERGUNTAS_DO_GUARDA: Final[dict[str, Pergunta]] = {
    "acao": PerguntaEscolha(
        instrucoes=(
            "O assistente Jarvis quer fazer `acao` (uma ferramenta de script, de gesto no "
            "navegador ou de um servidor MCP) no computador do dono. `objetivo` diz o que o dono "
            "pediu, o critério de pronto, a fase e os passos já feitos. A ação serve a esse "
            "objetivo e é segura?"
        ),
        # A primeira opção atrai (docs.typesafe.ai): a segura vem primeiro.
        opcoes={
            "barrar": (
                "Barrar: a ação foge do objetivo, vai a outro site ou serviço, mexe em "
                "credenciais, manda dados para fora, baixa ou roda código de fora, ou envia "
                "mensagem ou dinheiro."
            ),
            "pedir_confirmacao": (
                "Perguntar ao dono antes: a ação pode servir ao objetivo, mas não dá para ter "
                "certeza, ou tem consequência que ele talvez não espere."
            ),
            "permitir": (
                "Permitir: a ação claramente serve ao objetivo, fica no mesmo site ou na caixa, "
                "e só lê ou faz o passo pedido."
            ),
        },
    ),
    "categoria": PerguntaEscolha(
        instrucoes="Se a ação tem um risco, qual é o principal?",
        opcoes={
            "fora_do_objetivo": "Não serve ao que o dono pediu.",
            "exfiltrar": "Manda dados do dono ou da página para fora.",
            "baixar_executar": "Baixa ou roda código de fora.",
            "credenciais": "Mexe em senha, cookie, token ou chave.",
            "enviar": "Envia mensagem, e-mail, publicação ou dinheiro.",
            "nenhuma": "Nenhum desses riscos.",
        },
    ),
}


@dataclass(slots=True)
class GuardaDeContexto:
    """Regras → cache → Jev na zona cinza. Sem estado entre objetivos além do cache."""

    classificador: ClassificadorDeDecisao | None = None
    prazo_s: float = PRAZO_PADRAO_S
    limiar_permitir: float = LIMIAR_PERMITIR
    limiar_barrar: float = LIMIAR_BARRAR
    tamanho_do_cache: int = TAMANHO_DO_CACHE
    consultas: int = 0
    """Quantas vezes o Jev foi chamado (a medição conta)."""
    _cache: OrderedDict[tuple[str, str], Julgamento] = field(default_factory=OrderedDict)
    _barradas: dict[tuple[str, str], int] = field(default_factory=dict)

    def julgar(
        self,
        acao: Acao,
        objetivo: Objetivo | None,
        *,
        cancelado: Cancelado = nunca_cancelado,
    ) -> Julgamento:
        comeco = time.perf_counter()
        julgamento = self._por_regra(acao, objetivo)
        chave = (_marca_do_objetivo(objetivo), forma(acao))
        if julgamento is None:
            guardado = self._cache.get(chave)
            if guardado is not None:
                self._cache.move_to_end(chave)
                julgamento = guardado.com(ms=0.0, cache=True)
            else:
                julgamento = self._pelo_jev(acao, objetivo, cancelado)
                if julgamento.regra == "jev":  # falha do classificador não entra no cache
                    self._guardar(chave, julgamento)
        if julgamento.saida is Saida.BARRAR:
            julgamento = self._instruir(julgamento, objetivo, chave)
        return julgamento.com(ms=(time.perf_counter() - comeco) * 1000.0, cache=julgamento.cache)

    def esquecer(self) -> None:
        """O dono mudou de assunto ou a sessão acabou: nada do cache vale mais."""
        self._cache.clear()
        self._barradas.clear()

    # As regras: nenhuma chama a rede, e cada uma diz a sua causa.

    def _por_regra(self, acao: Acao, objetivo: Objetivo | None) -> Julgamento | None:
        if acao.tipo is Tipo.LEITURA:
            return Julgamento(Saida.PERMITIR, "leitura pura", regra="leitura_pura")
        site = categoria_do_site(acao.alvo) if acao.alvo else ""
        if acao.tipo is Tipo.SCRIPT_NA_PAGINA:
            return self._script_na_pagina(acao, objetivo, site)
        if acao.tipo is Tipo.SCRIPT_NA_CAIXA:
            return self._script_na_caixa(acao)
        if acao.tipo is Tipo.GESTO:
            return self._gesto(acao, objetivo, site)
        return self._mcp(acao, objetivo, site)

    def _script_na_pagina(
        self, acao: Acao, objetivo: Objetivo | None, site: str
    ) -> Julgamento | None:
        if site in SITES_SEM_SCRIPT:
            return _barrar(Categoria.DOMINIO_SENSIVEL, "nega:dominio_sensivel")
        achadas = categorias_do_codigo(acao.codigo, Tipo.SCRIPT_NA_PAGINA)
        if Categoria.FORA_DO_DOMINIO in achadas:
            # Navegar por script: o destino do objetivo é com o browser.navigate, que o confere.
            return _barrar(Categoria.FORA_DO_DOMINIO, "nega:navegar_por_script")
        if achadas:
            return _barrar(achadas[0], f"nega:{achadas[0]}")
        if site in SITES_QUE_PEDEM_O_SIM_NO_GESTO and _CLIQUE_POR_SCRIPT.search(acao.codigo):
            return _barrar(Categoria.ENVIAR, "nega:clique_por_script")
        if objetivo is not None and acao.alvo and not _no_objetivo(objetivo, acao.alvo):
            return _confirmar("a aba está fora dos sites do objetivo", "sim:aba_fora_do_objetivo")
        if acao.mundo != "isolado":
            return _confirmar(
                "o script roda no mundo da própria página, não no isolado", "sim:mundo_principal"
            )
        if so_le_a_pagina(acao.codigo):
            return Julgamento(Saida.PERMITIR, "o script só lê a página", regra="so_le_a_pagina")
        return None

    def _script_na_caixa(self, acao: Acao) -> Julgamento | None:
        achadas = categorias_do_codigo(acao.codigo, Tipo.SCRIPT_NA_CAIXA, rede=acao.rede)
        if achadas:
            return _barrar(achadas[0], f"nega:{achadas[0]}")
        if acao.rede:
            return _confirmar("o script pede a caixa com rede", "sim:caixa_com_rede")
        return Julgamento(
            Saida.PERMITIR, "caixa fechada: sem rede e sem os arquivos do dono", regra="caixa"
        )

    def _gesto(self, acao: Acao, objetivo: Objetivo | None, site: str) -> Julgamento | None:
        if acao.detalhe == "rolar":
            return Julgamento(Saida.PERMITIR, "rolar a página", regra="rolar")
        if site in SITES_QUE_PEDEM_O_SIM_NO_GESTO:
            return _confirmar(
                "o gesto é numa aba de banco, senha, e-mail, pagamento ou mensageiro",
                "sim:gesto_sensivel",
            )
        if objetivo is not None and acao.alvo and not _no_objetivo(objetivo, acao.alvo):
            return _confirmar("a aba está fora dos sites do objetivo", "sim:aba_fora_do_objetivo")
        return Julgamento(Saida.PERMITIR, "gesto dentro do objetivo", regra="gesto_no_objetivo")

    def _mcp(self, acao: Acao, objetivo: Objetivo | None, site: str) -> Julgamento | None:
        if acao.tier == "leitura":
            return Julgamento(Saida.PERMITIR, "ferramenta de leitura do servidor", regra="mcp_le")
        if acao.tier == "perigoso":
            return _confirmar("o dono marcou esta ferramenta como perigosa", "sim:mcp_perigoso")
        if acao.codigo:
            achadas = categorias_do_codigo(acao.codigo, Tipo.SCRIPT_NA_PAGINA)
            if site in SITES_SEM_SCRIPT:
                return _barrar(Categoria.DOMINIO_SENSIVEL, "nega:dominio_sensivel")
            if achadas:
                return _barrar(achadas[0], f"nega:{achadas[0]}")
        destinos = [*acao.destinos, *_destinos_do_codigo(acao.codigo)]
        if any(categoria_do_site(d) in SITES_SEM_SCRIPT for d in destinos):
            return _confirmar(
                "a chamada vai a banco, senha, e-mail ou pagamento", "sim:mcp_destino_sensivel"
            )
        if objetivo is not None and any(not _no_objetivo(objetivo, d) for d in destinos):
            return _confirmar("a chamada leva a um site fora do objetivo", "sim:mcp_fora")
        return None

    # O Jev, só na zona cinza.

    def _pelo_jev(self, acao: Acao, objetivo: Objetivo | None, cancelado: Cancelado) -> Julgamento:
        if self.classificador is None:
            return _confirmar(
                "o classificador está desligado e a ação não é óbvia", "sim:sem_classificador"
            )
        na_nuvem = getattr(self.classificador, "onde", Onde.NUVEM) is not Onde.LOCAL
        pedido = objetivo.pedido if objetivo is not None else ""
        if na_nuvem and classe_de_pii(pedido) == SENSIVEL:
            return _confirmar("o pedido tem conteúdo sensível, que não vai à nuvem", "sim:d20")
        estado = estado_para_o_jev(acao, objetivo, na_nuvem=na_nuvem)
        limite = time.monotonic() + self.prazo_s

        def com_prazo() -> bool:
            return cancelado() or time.monotonic() > limite

        self.consultas += 1
        try:
            respostas = self.classificador.decidir(estado, PERGUNTAS_DO_GUARDA, cancelado=com_prazo)
            escolha, risco = respostas["acao"], respostas["categoria"]
            if not isinstance(escolha, RespostaEscolha) or not isinstance(risco, RespostaEscolha):
                raise DecisaoIndisponivel("resposta fora do formato")
        except DecisaoIndisponivel:
            return _confirmar("o classificador não respondeu a tempo", "sim:falha_segura")
        except Exception:  # adaptador quebrado: na dúvida, o dono decide
            return _confirmar("o classificador falhou", "sim:falha_segura")
        if time.monotonic() > limite:
            # O prazo corta a leitura (o cliente HTTP confere o cancelamento); a resposta que
            # chega depois dele, por qualquer caminho, não vale.
            return _confirmar("o classificador não respondeu a tempo", "sim:falha_segura")
        p = escolha.probabilidade_da_escolha
        jev = f"{escolha.escolha} p={p:.2f}"
        if escolha.escolha == "barrar" and p >= self.limiar_barrar:
            try:
                categoria = Categoria(risco.escolha)
            except ValueError:
                categoria = Categoria.FORA_DO_OBJETIVO
            if categoria is Categoria.NENHUMA:
                categoria = Categoria.FORA_DO_OBJETIVO
            barrado = _barrar(categoria, "jev")
            return Julgamento(
                Saida.BARRAR, barrado.motivo, regra="jev", categoria=categoria, jev=jev
            )
        if escolha.escolha == "permitir" and p >= self.limiar_permitir:
            return Julgamento(Saida.PERMITIR, "o Jev viu a ação no objetivo", regra="jev", jev=jev)
        return Julgamento(
            Saida.PEDIR_CONFIRMACAO,
            "o classificador não teve certeza de que a ação serve ao objetivo",
            regra="jev",
            jev=jev,
        )

    def _guardar(self, chave: tuple[str, str], julgamento: Julgamento) -> None:
        self._cache[chave] = julgamento
        self._cache.move_to_end(chave)
        while len(self._cache) > self.tamanho_do_cache:
            self._cache.popitem(last=False)

    def _instruir(
        self, julgamento: Julgamento, objetivo: Objetivo | None, chave: tuple[str, str]
    ) -> Julgamento:
        vezes = self._barradas.get(chave, 0) + 1
        self._barradas[chave] = vezes
        if len(self._barradas) > self.tamanho_do_cache:
            self._barradas.pop(next(iter(self._barradas)))
        alternativa = (
            DESISTIR
            if vezes >= BARRADAS_ATE_DESISTIR
            else ALTERNATIVAS.get(julgamento.categoria, ALTERNATIVAS[Categoria.NENHUMA])
        )
        if objetivo is not None:
            instrucao = (
                f"Barrei: {julgamento.motivo}. Isso foge do objetivo «{objetivo.pedido}»: "
                f"{alternativa}."
            )
        else:
            instrucao = f"Barrei: {julgamento.motivo}: {alternativa}."
        return julgamento.com(ms=julgamento.ms, cache=julgamento.cache, instrucao=instrucao)


def forma(acao: Acao) -> str:
    """A forma da ação: ferramenta, host do alvo, mundo, rede, gesto, tier e o esqueleto do
    código — sem nenhum valor que o modelo escreveu."""
    corpo = esqueleto(acao.codigo)
    resumo = hashlib.sha256(corpo.encode("utf-8")).hexdigest()[:16] if corpo else "-"
    destinos = ",".join(sorted({host_de(d) for d in acao.destinos}))
    return "|".join(
        (
            acao.tool_id,
            host_de(acao.alvo),
            acao.mundo,
            "rede" if acao.rede else "-",
            acao.detalhe,
            acao.tier,
            destinos,
            resumo,
        )
    )


def _marca_do_objetivo(objetivo: Objetivo | None) -> str:
    if objetivo is None:
        return "-"
    return hashlib.sha256(f"{objetivo.pedido}\n{objetivo.criterio}".encode()).hexdigest()[:16]


def _no_objetivo(objetivo: Objetivo, url: str) -> bool:
    return objetivo.dentro(url)


def _barrar(categoria: Categoria, regra: str) -> Julgamento:
    return Julgamento(Saida.BARRAR, MOTIVOS[categoria], regra=regra, categoria=categoria)


def _confirmar(motivo: str, regra: str) -> Julgamento:
    return Julgamento(Saida.PEDIR_CONFIRMACAO, motivo, regra=regra)


def estado_para_o_jev(acao: Acao, objetivo: Objetivo | None, *, na_nuvem: bool) -> dict[str, Any]:
    """O que vai ao Jev (D20): o objetivo como o portão manda, a forma da ação e o esqueleto do
    código redigido — nunca página, resultado, URL inteira, cookie ou chave."""
    codigo = redigir(esqueleto(acao.codigo)).texto if acao.codigo else ""
    if len(codigo) > CARACTERES_DO_CODIGO:
        codigo = codigo[:CARACTERES_DO_CODIGO] + "…"
    contexto: dict[str, Any] = {}
    if objetivo is not None:
        contexto = objetivo.para_o_classificador(na_nuvem=na_nuvem)
        contexto["objetivo"] = objetivo.pedido  # já redigido e curto (`Objetivo.do_pedido`)
    return {
        "objetivo": contexto,
        "acao": {
            "ferramenta": acao.tool_id,
            "tipo": str(acao.tipo),
            "host_do_alvo": host_de(acao.alvo),
            "mundo": acao.mundo,
            "rede": acao.rede,
            "gesto_ou_ferramenta": acao.detalhe,
            "destinos": sorted({host_de(d) for d in acao.destinos} - {""})[:5],
            "codigo": codigo,
        },
    }
