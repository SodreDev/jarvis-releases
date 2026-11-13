"""O vocabulário fechado entre o Jarvis e a extensão (extensao/background.js).

Só estes métodos existem, cada um com os parâmetros que aceita. Não há `eval`, CDP nem
seletor CSS: o alvo de uma ação é o **texto ou rótulo visível** do elemento ou a **referência**
(`ref`) que o mapa da própria página devolveu (`page.map`, ADR-0032), e o que se faz com ele é
uma ação de uma lista fechada (`page.act`); `page.capture` traz a tela da aba com o mapa do mesmo
instante; `page.readUrl` lê um endereço numa aba de fundo, que fecha no fim (a busca na web,
ADR-0033); `tabs.navigate` e `tabs.open` só voltam depois de conferir que a aba saiu do lugar e a
página abriu, e `tabs.show` põe uma aba à vista do dono (auditoria de 2026-10-21). A aba nova e a de
fundo nascem na janela do dono (`fundo`: em segundo plano, sem tirar o foco); a janela própria do
Jarvis só com `modo: automacao_social` (ADR-0036, emenda de 2026-10-21). O host valida de novo o
que o cliente já validou — o socket é uma fronteira, e a extensão não confia em ninguém.

O **controle** (ADR-0027 regra 4): cada pedido que mexe numa aba leva a concessão do objetivo que o
fez (`controle`); a extensão mostra o indicador "no controle" nas abas dela até o Jarvis soltar
(`controle.soltar`), o dono apertar PARAR (na faixa da página ou na barra do navegador) ou o Jarvis
sumir. PARAR revoga a concessão — a extensão recusa o que vier dela depois — e vira um **evento**
que o host entrega a quem assinou (`eventos.assinar`): é por ele que o turno e a tarefa param.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from jarvis.social.redes import IDS as REDES_SOCIAIS

NOME_DO_HOST: Final = "br.com.granafacil.jarvis"
ID_CHROMIUM: Final = "eainnehpangdlhmjenljnbfkjjeckoli"
ID_FIREFOX: Final = "jarvis-browser@granafacil.local"
ORIGEM_CHROMIUM: Final = f"chrome-extension://{ID_CHROMIUM}/"

LIMITE_DO_PEDIDO: Final = 1_000_000
"""O navegador recusa mensagem do host para a extensão acima de 1 MB."""
LIMITE_DA_RESPOSTA: Final = 8 * 1024 * 1024
LIMITE_DA_URL: Final = 2_048
LIMITE_DO_ALVO: Final = 500
LIMITE_DO_TEXTO: Final = 10_000
LIMITE_DO_DESLOCAMENTO: Final = 2_000
PADRAO_DO_ID: Final = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
PADRAO_DA_REF: Final = re.compile(r"[a-z0-9]{1,16}\.[0-9]{1,4}")
"""`<instantâneo>.<n>`: o instantâneo leva a marca da página que o mapeou (`content.js`)."""
ACOES: Final = frozenset({"clicar", "focar", "passar_o_mouse", "tecla", "enviar", "selecionar"})
TECLAS: Final = frozenset({"Enter", "Escape", "Tab", "ArrowDown", "ArrowUp"})
LIMITE_DO_VALOR: Final = 200
MUNDOS: Final = frozenset({"isolado", "principal"})
"""`page.eval` roda no mundo **isolado** (padrão) ou no **principal** da página (ADR-0051)."""
GESTOS: Final = frozenset({"clicar", "arrastar", "digitar", "rolar"})
"""Os gestos físicos por CDP (`Input.*`): o clique/arrasto/digitação/rolagem de verdade."""
LIMITE_DO_CODIGO: Final = 20_000
"""O JavaScript de `page.eval` (igual ao teto do `script.rodar`, ADR-0050)."""
MODO_AUTOMACAO_SOCIAL: Final = "automacao_social"
MODOS: Final = frozenset({MODO_AUTOMACAO_SOCIAL})
"""`tabs.open` e `page.readUrl`: o único caminho para a janela própria do Jarvis (ADR-0036, emenda
de 2026-10-21) — reservado à automação de redes sociais, e-mail e agenda, que ainda não existe.
Sem `modo`, a aba nova nasce na janela do dono; com `fundo`, em segundo plano, sem tirar o foco."""
PADRAO_DA_CONCESSAO: Final = re.compile(r"[a-z0-9]{8,32}")
"""A concessão de controle de um objetivo: aleatória, gerada pelo Jarvis (`navegador.controle`)."""
EVENTOS: Final = frozenset({"parar", "social"})
"""`parar` (o dono apertou PARAR) e `social` (o estado de uma rede, ADR-0060)."""
ORIGENS_DA_PARADA: Final = frozenset({"faixa", "barra"})
"""Onde o dono apertou PARAR: na faixa desenhada na página, ou no botão da extensão na barra."""
MAXIMO_DE_CONCESSOES: Final = 32
VERSAO_DA_PONTE: Final = 5
"""O contrato de métodos entre o Jarvis, o host e a extensão. Sobe a cada método novo, junto com
`VERSAO_DA_PONTE` de extensao/background.js (o teste confere). A 2 é a do CDP (ADR-0051) mais
`ponte.versao`: a extensão que não responde a ela, ou responde menos, é a de antes — o dono ouve
para recarregá-la, em vez de ver as ferramentas novas falharem uma a uma (2026-10-30). A 3
traz o monitor das redes sociais (ADR-0060): `social.abrir`, `social.estado` e o evento `social`.
A 5 (2026-11-13) traz no estado da rede a `pista` (carregando, sem lista, contador ilegível) e a
`amostra` sanitizada do contador que não se reconheceu: o host de antes recusaria esses campos."""
VERSAO: Final = "ponte.versao"
"""Respondido pela extensão: a versão dela, a do manifesto e se tem as permissões do CDP."""
VERSAO_DO_HOST: Final = "host.versao"
"""Respondido pelo próprio host, sem ir à extensão: a versão da ponte que o host conhece e o pid.
Host de antes recusa o método (não está no vocabulário dele): é o host velho de um navegador que
não relançou a extensão desde a atualização."""
ASSINAR: Final = "eventos.assinar"
"""Atendido pelo próprio host, que segura a conexão e escreve nela os eventos da extensão."""
COM_CONTROLE: Final = frozenset(
    {
        "tabs.navigate",
        "tabs.open",
        "tabs.show",
        "tabs.close",
        "page.read",
        "page.map",
        "page.capture",
        "page.inspect",
        "page.click",
        "page.type",
        "page.act",
        "page.scroll",
        "page.console",
        "page.network",
        "page.eval",
        "page.gesture",
    }
)
"""Pedidos que mexem numa aba (ou a leem): levam a concessão, e a aba mostra o indicador."""

METODOS: Final[dict[str, dict[str, type]]] = {
    # método → parâmetro → tipo (`int` nunca aceita booleano)
    "tabs.list": {},
    "windows.focused": {},
    "tabs.current": {"tabId": int},
    "tabs.navigate": {"tabId": int, "url": str, "controle": str},
    "tabs.open": {"url": str, "fundo": bool, "modo": str, "controle": str},
    "tabs.show": {"tabId": int, "controle": str},
    "tabs.close": {"tabId": int, "controle": str},
    "page.read": {"tabId": int, "controle": str},
    "page.map": {"tabId": int, "controle": str},
    "page.capture": {"tabId": int, "controle": str},
    "page.readUrl": {"url": str, "modo": str},
    "page.inspect": {"tabId": int, "alvo": str, "ref": str, "controle": str},
    "page.click": {"tabId": int, "alvo": str, "ref": str, "controle": str},
    "page.type": {
        "tabId": int,
        "alvo": str,
        "ref": str,
        "texto": str,
        "limpar": bool,
        "controle": str,
    },
    "page.act": {
        "tabId": int,
        "alvo": str,
        "ref": str,
        "acao": str,
        "tecla": str,
        "valor": str,
        "controle": str,
    },
    "page.scroll": {"tabId": int, "pixels": int, "controle": str},
    # O navegador por CDP (ADR-0051): console, rede, avaliar JS e gestos físicos.
    "page.console": {"tabId": int, "controle": str},
    "page.network": {"tabId": int, "controle": str},
    "page.eval": {"tabId": int, "codigo": str, "mundo": str, "controle": str},
    "page.gesture": {
        "tabId": int,
        "gesto": str,
        "alvo": str,
        "ref": str,
        "texto": str,
        "pixels": int,
        "controle": str,
    },
    "controle.soltar": {"controle": str},
    "controle.manter": {"controle": str},
    "controle.parar": {},
    "controle.estado": {},
    # O monitor das redes sociais (ADR-0060), só leitura: a extensão sabe o endereço e os hosts
    # de cada rede; o Jarvis só diz qual. Não levam concessão: não agem na página.
    "social.abrir": {"rede": str},
    "social.estado": {"rede": str},
    # O envio (fatia D), só no WhatsApp e só depois do guardião do código (jarvis.social.envio).
    "social.cabecalho": {"rede": str},
    "social.abrirConversa": {"rede": str, "nome": str},
    "social.digitar": {"rede": str, "texto": str, "atrasos": list},
    "social.enviar": {"rede": str},
    "social.soltar": {"rede": str},
    VERSAO: {},
    VERSAO_DO_HOST: {},
    ASSINAR: {},
}
PRAZO_PADRAO_S: Final = 25.0
"""O teto de um pedido que espera a página (navegar, abrir, ler um endereço, a tela, um gesto)."""
PRAZO_CURTO_S: Final = 8.0
"""O teto de um pedido que só consulta a extensão ou age num elemento já na página: passou disso,
a extensão travou — esperar 25 s com o dono olhando é o "travou" de 2026-10-30."""
PRAZOS_CURTOS: Final = frozenset(
    {
        "tabs.list",
        "tabs.current",
        "tabs.show",
        "tabs.close",
        "windows.focused",
        "page.read",
        "page.map",
        "page.inspect",
        "page.click",
        "page.type",
        "page.act",
        "page.scroll",
        "page.console",
        "page.network",
        "controle.soltar",
        "controle.manter",
        "controle.parar",
        "controle.estado",
        "social.abrir",
        "social.estado",
        "social.cabecalho",
        "social.abrirConversa",
        "social.digitar",
        "social.enviar",
        "social.soltar",
        VERSAO,
        VERSAO_DO_HOST,
    }
)


def prazo_do_metodo(metodo: str) -> float:
    """Quanto o Jarvis espera a resposta deste método antes de desistir dele (o host tem o seu)."""
    return PRAZO_CURTO_S if metodo in PRAZOS_CURTOS else PRAZO_PADRAO_S


OBRIGATORIOS: Final[dict[str, frozenset[str]]] = {
    "tabs.navigate": frozenset({"url"}),
    "tabs.open": frozenset({"url"}),
    "tabs.show": frozenset({"tabId"}),
    "tabs.close": frozenset({"tabId"}),
    "controle.soltar": frozenset({"controle"}),
    "controle.manter": frozenset({"controle"}),
    "page.readUrl": frozenset({"url"}),
    "page.type": frozenset({"texto"}),
    "page.act": frozenset({"acao"}),
    "page.eval": frozenset({"codigo"}),
    "page.gesture": frozenset({"gesto"}),
    "social.abrir": frozenset({"rede"}),
    "social.estado": frozenset({"rede"}),
    "social.cabecalho": frozenset({"rede"}),
    "social.abrirConversa": frozenset({"rede", "nome"}),
    "social.digitar": frozenset({"rede", "texto", "atrasos"}),
    "social.enviar": frozenset({"rede"}),
    "social.soltar": frozenset({"rede"}),
}
COM_ALVO: Final = frozenset({"page.inspect", "page.click", "page.type", "page.act"})
"""Métodos que agem num elemento: exatamente um de `alvo` (texto visível) ou `ref` (do mapa)."""


class PedidoInvalido(ValueError):
    """O pedido não cabe no vocabulário. A mensagem diz o campo."""


@dataclass(frozen=True, slots=True)
class PedidoDaPonte:
    id: str
    method: str
    params: dict[str, Any]

    def como_objeto(self) -> dict[str, Any]:
        return {"id": self.id, "method": self.method, "params": self.params}


def _url_http(valor: str) -> None:
    if len(valor) > LIMITE_DA_URL or any(c in valor for c in "\r\n\t\x00 "):
        raise PedidoInvalido("url longa demais ou com espaço/controle")
    partes = urlsplit(valor)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise PedidoInvalido("a navegação é só para http ou https")
    if partes.username or partes.password:
        raise PedidoInvalido("url com credencial embutida é recusada")


def _tamanho(nome: str, valor: str, maximo: int) -> None:
    if len(valor) > maximo:
        raise PedidoInvalido(f"{nome} passa de {maximo} caracteres")


ENVIO_SOCIAL: Final = frozenset(
    {"social.cabecalho", "social.abrirConversa", "social.digitar", "social.enviar"}
)
REDES_COM_ENVIO: Final = frozenset({"whatsapp"})
MAXIMO_DE_TECLAS: Final = 80
MAXIMO_DO_ATRASO_MS: Final = 2_000


def _teclas(texto: str, atrasos: list[Any]) -> None:
    if not texto or len(texto) > MAXIMO_DE_TECLAS:
        raise PedidoInvalido(f"social.digitar: de 1 a {MAXIMO_DE_TECLAS} caracteres por pedido")
    if len(atrasos) != len(texto) or not all(
        isinstance(a, int) and not isinstance(a, bool) and 0 <= a <= MAXIMO_DO_ATRASO_MS
        for a in atrasos
    ):
        raise PedidoInvalido("social.digitar: um atraso (0..2000 ms) por caractere")
    if any(c in texto for c in "\r\n\x00"):
        raise PedidoInvalido("social.digitar: sem quebra de linha (o Enter é o social.enviar)")


def validar_pedido(bruto: object) -> PedidoDaPonte:
    if not isinstance(bruto, dict):
        raise PedidoInvalido("o pedido tem de ser um objeto")
    identificador, metodo, params = bruto.get("id"), bruto.get("method"), bruto.get("params", {})
    if not isinstance(identificador, str) or not PADRAO_DO_ID.fullmatch(identificador):
        raise PedidoInvalido("id ausente ou fora de [A-Za-z0-9_.:-]{1,80}")
    if not isinstance(metodo, str) or metodo not in METODOS:
        raise PedidoInvalido("método fora do vocabulário do navegador")
    if not isinstance(params, dict):
        raise PedidoInvalido("params tem de ser um objeto")
    aceitos = METODOS[metodo]
    for nome, valor in params.items():
        tipo = aceitos.get(nome)
        if tipo is None:
            raise PedidoInvalido(f"{metodo}: parâmetro fora do contrato: {nome}")
        if not isinstance(valor, tipo) or (tipo is int and isinstance(valor, bool)):
            raise PedidoInvalido(f"{metodo}: {nome} com tipo errado")
    faltando = OBRIGATORIOS.get(metodo, frozenset()) - set(params)
    if faltando:
        raise PedidoInvalido(f"{metodo}: falta {sorted(faltando)}")
    if "tabId" in params and params["tabId"] < 0:
        raise PedidoInvalido("tabId negativo")
    if "url" in params:
        _url_http(params["url"])
    if metodo in COM_ALVO and ("alvo" in params) == ("ref" in params):
        raise PedidoInvalido(f"{metodo}: diga o alvo pelo texto (alvo) ou pela referência (ref)")
    if "alvo" in params:
        if not params["alvo"].strip():
            raise PedidoInvalido("alvo vazio")
        _tamanho("alvo", params["alvo"], LIMITE_DO_ALVO)
    if "ref" in params and not PADRAO_DA_REF.fullmatch(params["ref"]):
        raise PedidoInvalido("ref fora do formato do mapa da página")
    if "acao" in params and params["acao"] not in ACOES:
        raise PedidoInvalido(f"ação fora da lista: {sorted(ACOES)}")
    if params.get("acao") == "tecla" and params.get("tecla") not in TECLAS:
        raise PedidoInvalido(f"tecla fora da lista: {sorted(TECLAS)}")
    if params.get("acao") == "selecionar" and not params.get("valor"):
        raise PedidoInvalido("selecionar pede o valor (o texto da opção)")
    if "valor" in params:
        _tamanho("valor", params["valor"], LIMITE_DO_VALOR)
    if "modo" in params and params["modo"] not in MODOS:
        raise PedidoInvalido(f"modo fora da lista: {sorted(MODOS)}")
    if "mundo" in params and params["mundo"] not in MUNDOS:
        raise PedidoInvalido(f"mundo fora da lista: {sorted(MUNDOS)}")
    if "gesto" in params and params["gesto"] not in GESTOS:
        raise PedidoInvalido(f"gesto fora da lista: {sorted(GESTOS)}")
    if "codigo" in params:
        _tamanho("codigo", params["codigo"], LIMITE_DO_CODIGO)
        if "\x00" in params["codigo"]:
            raise PedidoInvalido("codigo com byte nulo")
    if "controle" in params and not PADRAO_DA_CONCESSAO.fullmatch(params["controle"]):
        raise PedidoInvalido("controle fora do formato da concessão")
    if "texto" in params:
        _tamanho("texto", params["texto"], LIMITE_DO_TEXTO)
    if "rede" in params and params["rede"] not in REDES_SOCIAIS:
        raise PedidoInvalido(f"rede fora da lista: {sorted(REDES_SOCIAIS)}")
    if metodo in ENVIO_SOCIAL and params.get("rede") not in REDES_COM_ENVIO:
        raise PedidoInvalido("o envio existe só no WhatsApp")
    if metodo == "social.abrirConversa" and not 0 < len(params["nome"].strip()) <= LIMITE_DO_NOME:
        raise PedidoInvalido("nome do contato vazio ou longo")
    if metodo == "social.digitar":
        _teclas(params["texto"], params["atrasos"])
    if "pixels" in params and abs(params["pixels"]) > LIMITE_DO_DESLOCAMENTO:
        raise PedidoInvalido(f"pixels passa de {LIMITE_DO_DESLOCAMENTO}")
    return PedidoDaPonte(identificador, metodo, dict(params))


def validar_resposta(bruta: object) -> dict[str, Any]:
    """`{id, ok, result}` ou `{id, ok: false, error: {codigo, mensagem}}` — nada além disso."""
    if not isinstance(bruta, dict):
        raise PedidoInvalido("a resposta tem de ser um objeto")
    identificador = bruta.get("id")
    if identificador is not None and not (
        isinstance(identificador, str) and PADRAO_DO_ID.fullmatch(identificador)
    ):
        raise PedidoInvalido("id da resposta inválido")
    ok = bruta.get("ok")
    if not isinstance(ok, bool):
        raise PedidoInvalido("ok ausente")
    if ok:
        resultado = bruta.get("result")
        if not isinstance(resultado, dict):
            raise PedidoInvalido("result ausente")
        return {"id": identificador, "ok": True, "result": resultado}
    erro = bruta.get("error")
    if not isinstance(erro, dict):
        raise PedidoInvalido("error ausente")
    return {
        "id": identificador,
        "ok": False,
        "error": {
            "codigo": str(erro.get("codigo", "falha"))[:60],
            "mensagem": str(erro.get("mensagem", ""))[:300],
        },
    }


FORMATOS_SOCIAIS: Final = frozenset({"conhecido", "desconhecido"})
PISTAS_SOCIAIS: Final = frozenset({"", "carregando", "sem_lista", "contador_ilegivel"})
"""Por que o contador não saiu limpo: a página ainda carrega, a lista de conversas não está lá (a
página mudou), ou um contador veio num formato que o `social.js` não reconhece."""
LIMITE_DA_AMOSTRA: Final = 60
MAXIMO_DE_CONVERSAS: Final = 20
LIMITE_DO_NOME: Final = 80
MAXIMO_DE_NAO_LIDAS: Final = 9_999
ALERTAS_SOCIAIS: Final = frozenset({"", "captcha", "verificacao", "limitada", "atividade_incomum"})
"""Os sinais de alerta que a página mostra (docs/redes-sociais-riscos.md §6); vazio = nenhum."""
_CHAVES_DO_SOCIAL: Final = frozenset(
    {"evento", "rede", "logado", "naoLidas", "conversas", "formato", "alerta", "pista", "amostra"}
)
_INVISIVEIS: Final = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
"""Controle, largura zero e inversão de direção: o `social.js` já tira; quem traz é recusado."""


def _contagem(valor: object, nome: str) -> int:
    if (
        not isinstance(valor, int)
        or isinstance(valor, bool)
        or not 0 <= valor <= MAXIMO_DE_NAO_LIDAS
    ):
        raise PedidoInvalido(f"{nome} fora de 0..{MAXIMO_DE_NAO_LIDAS}")
    return valor


def validar_estado_social(bruto: object) -> dict[str, Any]:
    """O estado de uma rede (ADR-0060), do evento `social` ou da resposta de `social.estado`:
    `{rede, logado, naoLidas, conversas: [{nome, naoLidas}], formato, alerta, pista, amostra}` —
    nada além disso (`pista` e `amostra` são opcionais: a extensão de antes não os manda). Os
    nomes são de terceiros: curtos, sem caractere de controle nem de inversão de direção."""
    if not isinstance(bruto, dict):
        raise PedidoInvalido("o estado da rede tem de ser um objeto")
    fora = sorted(set(bruto) - _CHAVES_DO_SOCIAL)
    if fora:
        raise PedidoInvalido(f"estado da rede com campo fora do contrato: {fora}")
    rede = bruto.get("rede")
    if rede not in REDES_SOCIAIS:
        raise PedidoInvalido("rede fora da lista")
    logado = bruto.get("logado")
    if not isinstance(logado, bool):
        raise PedidoInvalido("logado tem de ser true ou false")
    formato = bruto.get("formato", "conhecido")
    if formato not in FORMATOS_SOCIAIS:
        raise PedidoInvalido("formato fora da lista")
    alerta = bruto.get("alerta", "")
    if alerta not in ALERTAS_SOCIAIS:
        raise PedidoInvalido("alerta fora da lista")
    pista = bruto.get("pista", "")
    if pista not in PISTAS_SOCIAIS:
        raise PedidoInvalido("pista fora da lista")
    amostra = bruto.get("amostra", "")
    if (
        not isinstance(amostra, str)
        or len(amostra) > LIMITE_DA_AMOSTRA
        or _INVISIVEIS.search(amostra)
    ):
        raise PedidoInvalido(f"amostra: texto de até {LIMITE_DA_AMOSTRA} caracteres, sem controle")
    conversas = bruto.get("conversas", [])
    if not isinstance(conversas, list) or len(conversas) > MAXIMO_DE_CONVERSAS:
        raise PedidoInvalido(f"conversas: lista de até {MAXIMO_DE_CONVERSAS}")
    limpas = []
    for conversa in conversas:
        if not isinstance(conversa, dict) or set(conversa) != {"nome", "naoLidas"}:
            raise PedidoInvalido("conversa fora do contrato {nome, naoLidas}")
        nome = conversa["nome"]
        if (
            not isinstance(nome, str)
            or not nome.strip()
            or len(nome) > LIMITE_DO_NOME
            or _INVISIVEIS.search(nome)
        ):
            raise PedidoInvalido("nome da conversa vazio, longo ou com caractere de controle")
        limpas.append({"nome": nome, "naoLidas": _contagem(conversa["naoLidas"], "naoLidas")})
    return {
        "evento": "social",
        "rede": str(rede),
        "logado": logado,
        "naoLidas": _contagem(bruto.get("naoLidas"), "naoLidas"),
        "conversas": limpas,
        "formato": str(formato),
        "alerta": str(alerta),
        "pista": str(pista),
        "amostra": amostra,
    }


def validar_evento(bruto: object) -> dict[str, Any]:
    """Um evento que a extensão manda por conta própria (não é resposta): o PARAR do dono,
    `{evento: "parar", concessoes: [...], origem: "faixa" | "barra"}`, e o estado de uma rede
    social (`validar_estado_social`) — nada além disso."""
    if not isinstance(bruto, dict) or bruto.get("evento") not in EVENTOS:
        raise PedidoInvalido("evento fora da lista")
    if bruto["evento"] == "social":
        return validar_estado_social(bruto)
    concessoes = bruto.get("concessoes", [])
    if (
        not isinstance(concessoes, list)
        or len(concessoes) > MAXIMO_DE_CONCESSOES
        or not all(isinstance(c, str) and PADRAO_DA_CONCESSAO.fullmatch(c) for c in concessoes)
    ):
        raise PedidoInvalido("concessões do evento fora do formato")
    origem = bruto.get("origem")
    if origem not in ORIGENS_DA_PARADA:
        raise PedidoInvalido("origem da parada fora da lista")
    return {"evento": str(bruto["evento"]), "concessoes": list(concessoes), "origem": origem}
