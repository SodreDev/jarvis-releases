"""O catálogo do que a IA **pode** pôr na tela (ADR-0019, emenda) — e nada além disso.

É o mesmo desenho do catálogo de capacidades da SPEC §4, um andar acima: lá a pergunta é
"esta ação pode ser executada?"; aqui é "esta coisa pode aparecer na tela do dono?". A
resposta vem de um registro, não da criatividade de quem escreve a proposta.

Três regras, e cada uma fecha um buraco conhecido de interface conduzida por modelo:

1. **Só componente registrado.** A IA escolhe um `id` deste catálogo. Não existe componente
   "genérico que renderiza o que vier" — que é como uma tela acaba executando HTML ou JS
   escrito por um modelo (P1, P6). A exceção medida é o `conteudo` (ADR-0055): HTML, sim, mas só
   o que passa pela allowlist de `jarvis.tela.sanitizar` — sanitizado **de novo aqui**, na
   fronteira, e conferido por uma regra independente (`RECURSO`: nada que o Qt buscaria) —,
   desenhado pelo texto rico do Qt, que não tem motor de script.
2. **Só os campos declarados, com a forma declarada.** Cada componente diz que dados aceita;
   o resto é recusado com motivo. Um campo a mais não é tolerado "porque não atrapalha": é
   exatamente por campos tolerados que conteúdo vira instrução.
3. **O que encosta no desktop pede confirmação.** Navegador, terminal, arquivos e captura de
   tela são integrações com a máquina do dono (SPEC §5.4): o componente existe, a moldura
   existe, e **nada liga** sem o dono dizer que sim. Hoje todos mostram conteúdo de
   demonstração, rotulado como tal na moldura.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from jarvis.gui.acoes import Area
from jarvis.tela.sanitizar import COR, sanitizar

LIMITE_DE_ITENS: Final = 24
LIMITE_DE_TEXTO: Final = 1200
RECURSO: Final = re.compile(
    r"\b(?:src|href|action|background|poster|srcset|data)\s*=|url\s*\(|@import", re.IGNORECASE
)
"""O que faria o texto rico do Qt buscar algo fora (medido: `<img src>` e `url()` no CSS são
buscados): a segunda regra da fronteira do `conteudo`, independente da allowlist."""


class ComponenteNaoAutorizado(ValueError):
    """A IA pediu algo que não está no catálogo — ou com um campo que ele não tem."""


class Vista(StrEnum):
    """Como o módulo se desenha. A tela tem uma vista para cada uma, e só para estas."""

    LISTA = "lista"
    TEXTO = "texto"
    ITENS_COM_IMAGEM = "itens_com_imagem"
    CONSOLE = "console"
    TAREFAS = "tarefas"
    MEDIDORES = "medidores"
    CONVERSA = "conversa"
    CONFIGURACAO = "configuracao"
    DIAGNOSTICO = "diagnostico"
    NOTIFICACOES = "notificacoes"
    CONTEUDO = "conteudo"
    """O HTML limpo que o Jarvis montou (ADR-0055): a única vista com texto rico."""


class Forma(StrEnum):
    """A forma de um campo de dados. Validada antes de chegar à tela."""

    TEXTO = "texto"
    LINHAS = "linhas"
    ITENS = "itens"
    MEDIDAS = "medidas"
    AVISOS = "avisos"
    HTML_SEGURO = "html_seguro"
    """HTML que só entra depois de passar pela allowlist (`jarvis.tela.sanitizar`)."""
    COR = "cor"


CHAVES_DE_ITEM: Final[frozenset[str]] = frozenset(
    {"titulo", "detalhe", "fonte", "instante", "estado", "imagem", "id", "progresso"}
)
"""O que um item de lista pode ter. `imagem` é caminho de arquivo que a tela **só** lê se
existir — e nenhum componente de imagem nasce sem confirmação do dono. `id` e `progresso`
(texto, de 0 a 100) são do card de tarefas: o "parar" devolve o `id` à janela, que só o repassa
ao laço — parar é sempre permitido, então um `id` inventado não ganha poder nenhum."""

ESTADOS_DE_ITEM: Final[frozenset[str]] = frozenset(
    {"visto", "executando", "resultado", "espera", "falhou", "cancelada"}
)
"""Distinguir visto × em execução × resultado é pedido do dono, então é campo, não cor solta."""

CHAVES_DE_AVISO: Final[frozenset[str]] = frozenset(
    {"tipo", "origem", "resumo", "instante", "entrega", "confianca"}
)
"""Um aviso do card `notificacoes` (ADR-0025, regra 11): o que o evento `Notification` traz
de legível. `tipo` e `entrega` são fechados; `resumo` é texto puro, nunca instrução."""
TIPOS_DE_AVISO: Final[frozenset[str]] = frozenset(
    {"concluida", "falhou", "precisa_decisao", "evento"}
)
ENTREGAS_DE_AVISO: Final[frozenset[str]] = frozenset({"na_fila", "falado", "so_card", "calado"})
"""O que foi feito do aviso (ADR-0025, regras 13–15): esperando o piso livre, falado (tocou),
só card (não perturbe ou decisão do modelo) ou calado pelo modelo — que **continua** na lista:
nada some sem rastro."""
CONFIANCAS_DE_AVISO: Final[frozenset[str]] = frozenset({"propria", "terceiros"})
"""`terceiros` é resultado de tarefa ou de MCP (`trust: third_party`): a tela diz isso."""


@dataclass(frozen=True, slots=True)
class Componente:
    """Uma coisa que pode aparecer na tela."""

    id: str
    titulo: str
    vista: Vista
    area_padrao: Area
    minimo: tuple[int, int] = (2, 2)
    campos: Mapping[str, Forma] = field(default_factory=dict)
    sensivel: bool = False
    """Encosta na máquina do dono: só entra com confirmação dele (SPEC §5.4, P12)."""
    demonstracao: bool = False
    """Hoje só mostra conteúdo de exemplo. A moldura diz isso, para ninguém ler como real."""


def _area(coluna: int, linha: int, colunas: int, linhas: int) -> Area:
    return Area(coluna=coluna, linha=linha, colunas=colunas, linhas=linhas)


CATALOGO: Final[dict[str, Componente]] = {
    componente.id: componente
    for componente in (
        Componente(
            id="conversa",
            titulo="Conversa",
            vista=Vista.CONVERSA,
            area_padrao=_area(3, 6, 6, 2),
            minimo=(4, 2),
        ),
        Componente(
            id="noticias",
            titulo="Resultados",
            vista=Vista.ITENS_COM_IMAGEM,
            area_padrao=_area(0, 1, 4, 5),
            campos={"itens": Forma.ITENS},
            demonstracao=True,
        ),
        Componente(
            id="fontes",
            titulo="Fontes",
            vista=Vista.LISTA,
            area_padrao=_area(0, 1, 2, 5),
            campos={"itens": Forma.ITENS},
            demonstracao=True,
        ),
        Componente(
            id="resumo",
            titulo="Análise do Jarvis",
            vista=Vista.TEXTO,
            area_padrao=_area(8, 1, 4, 4),
            campos={"texto": Forma.TEXTO, "topicos": Forma.LINHAS},
            demonstracao=True,
        ),
        Componente(
            id="video",
            titulo="Vídeo",
            vista=Vista.ITENS_COM_IMAGEM,
            area_padrao=_area(4, 1, 4, 4),
            campos={"itens": Forma.ITENS},
            demonstracao=True,
        ),
        Componente(
            id="imagens",
            titulo="Imagens",
            vista=Vista.ITENS_COM_IMAGEM,
            area_padrao=_area(4, 1, 4, 3),
            campos={"itens": Forma.ITENS},
            demonstracao=True,
        ),
        Componente(
            id="screenshots",
            titulo="Capturas de tela",
            vista=Vista.ITENS_COM_IMAGEM,
            area_padrao=_area(6, 0, 3, 4),
            campos={"itens": Forma.ITENS},
            sensivel=True,
            demonstracao=True,
        ),
        Componente(
            id="navegador",
            titulo="Navegador",
            vista=Vista.TEXTO,
            area_padrao=_area(4, 0, 5, 6),
            campos={"texto": Forma.TEXTO, "topicos": Forma.LINHAS},
            sensivel=True,
            demonstracao=True,
        ),
        Componente(
            id="terminal",
            titulo="Console",
            vista=Vista.CONSOLE,
            area_padrao=_area(0, 4, 6, 4),
            campos={"linhas": Forma.LINHAS},
            sensivel=True,
            demonstracao=True,
        ),
        Componente(
            id="arquivos",
            titulo="Arquivos do projeto",
            vista=Vista.LISTA,
            area_padrao=_area(9, 0, 3, 5),
            campos={"itens": Forma.ITENS},
            sensivel=True,
            demonstracao=True,
        ),
        Componente(
            id="codigo",
            titulo="Código",
            vista=Vista.CONSOLE,
            area_padrao=_area(2, 0, 4, 6),
            campos={"linhas": Forma.LINHAS, "texto": Forma.TEXTO},
            demonstracao=True,
        ),
        Componente(
            id="tarefas",
            titulo="Tarefas",
            vista=Vista.TAREFAS,
            area_padrao=_area(0, 0, 2, 5),
            campos={"itens": Forma.ITENS},
            demonstracao=True,
        ),
        Componente(
            id="notificacoes",
            titulo="Notificações",
            vista=Vista.NOTIFICACOES,
            area_padrao=_area(9, 5, 3, 3),
            minimo=(3, 2),
            # Só a forma do card por enquanto (ADR-0025): a fila de verdade mora no `agentd` e
            # não está ligada aqui — o que aparece é demonstração, e a moldura diz isso.
            campos={"avisos": Forma.AVISOS},
            demonstracao=True,
        ),
        Componente(
            id="graficos",
            titulo="Uso de recursos",
            vista=Vista.MEDIDORES,
            area_padrao=_area(9, 5, 3, 3),
            campos={"medidas": Forma.MEDIDAS},
            demonstracao=True,
        ),
        Componente(
            id="configuracao",
            titulo="Configuração",
            vista=Vista.CONFIGURACAO,
            # Painel nasce pequeno numa faixa que nenhum modo reserva, e a janela o abre
            # maximizado: é o jeito de ele caber em qualquer composição sem empurrar nada.
            area_padrao=_area(0, 6, 6, 2),
            minimo=(4, 2),
        ),
        Componente(
            id="conteudo",
            titulo="Na tela",
            vista=Vista.CONTEUDO,
            # No centro, onde o dono olha: a lista, a tabela, o comparativo que ele pediu.
            area_padrao=_area(3, 1, 6, 5),
            minimo=(3, 2),
            campos={"html": Forma.HTML_SEGURO, "fundo": Forma.COR},
        ),
        Componente(
            id="diagnostico",
            titulo="Diagnóstico",
            vista=Vista.DIAGNOSTICO,
            area_padrao=_area(6, 6, 6, 2),
            minimo=(4, 2),
            campos={"licenca": Forma.TEXTO},
        ),
    )
}


def componente(identificador: str) -> Componente:
    """O componente do catálogo, ou a recusa dizendo o que existe."""
    achado = CATALOGO.get(identificador)
    if achado is None:
        raise ComponenteNaoAutorizado(
            f"componente {identificador!r} não está no catálogo. Autorizados: "
            f"{', '.join(sorted(CATALOGO))}"
        )
    return achado


def _item(bruto: Any, onde: str) -> dict[str, str]:
    if not isinstance(bruto, Mapping):
        raise ComponenteNaoAutorizado(f"{onde}: cada item é um mapa, veio {type(bruto).__name__}")
    estranhos = sorted(set(bruto) - CHAVES_DE_ITEM)
    if estranhos:
        raise ComponenteNaoAutorizado(
            f"{onde}: item com campo não autorizado ({', '.join(estranhos)}). Um item tem "
            f"{', '.join(sorted(CHAVES_DE_ITEM))}"
        )
    limpo: dict[str, str] = {}
    for chave, valor in bruto.items():
        if not isinstance(valor, str):
            raise ComponenteNaoAutorizado(f"{onde}.{chave}: esperava texto")
        limpo[str(chave)] = valor[:LIMITE_DE_TEXTO]
    estado = limpo.get("estado", "")
    if estado and estado not in ESTADOS_DE_ITEM:
        raise ComponenteNaoAutorizado(
            f"{onde}.estado: {estado!r} não existe. Os que existem: "
            f"{', '.join(sorted(ESTADOS_DE_ITEM))}"
        )
    return limpo


def _aviso(bruto: Any, onde: str) -> dict[str, str]:
    if not isinstance(bruto, Mapping):
        raise ComponenteNaoAutorizado(f"{onde}: cada aviso é um mapa, veio {type(bruto).__name__}")
    estranhos = sorted(set(bruto) - CHAVES_DE_AVISO)
    if estranhos:
        raise ComponenteNaoAutorizado(
            f"{onde}: aviso com campo não autorizado ({', '.join(estranhos)}). Um aviso tem "
            f"{', '.join(sorted(CHAVES_DE_AVISO))}"
        )
    limpo: dict[str, str] = {}
    for chave, valor in bruto.items():
        if not isinstance(valor, str):
            raise ComponenteNaoAutorizado(f"{onde}.{chave}: esperava texto")
        limpo[str(chave)] = valor[:LIMITE_DE_TEXTO]
    for chave, validos in (
        ("tipo", TIPOS_DE_AVISO),
        ("entrega", ENTREGAS_DE_AVISO),
        ("confianca", CONFIANCAS_DE_AVISO),
    ):
        valor = limpo.get(chave, "")
        if chave == "tipo" and not valor:
            raise ComponenteNaoAutorizado(f"{onde}.tipo: todo aviso tem tipo")
        if valor and valor not in validos:
            raise ComponenteNaoAutorizado(
                f"{onde}.{chave}: {valor!r} não existe. Os que existem: "
                f"{', '.join(sorted(validos))}"
            )
    if not limpo.get("resumo"):
        raise ComponenteNaoAutorizado(f"{onde}.resumo: aviso sem resumo não diz nada")
    return limpo


def _linhas(bruto: Any, onde: str) -> list[str]:
    if not isinstance(bruto, Sequence) or isinstance(bruto, str | bytes):
        raise ComponenteNaoAutorizado(f"{onde}: esperava uma lista de textos")
    if len(bruto) > LIMITE_DE_ITENS * 4:
        raise ComponenteNaoAutorizado(f"{onde}: lista longa demais para uma moldura de tela")
    linhas: list[str] = []
    for valor in bruto:
        if not isinstance(valor, str):
            raise ComponenteNaoAutorizado(f"{onde}: esperava texto, veio {type(valor).__name__}")
        linhas.append(valor[:LIMITE_DE_TEXTO])
    return linhas


def _medidas(bruto: Any, onde: str) -> list[dict[str, Any]]:
    if not isinstance(bruto, Sequence) or isinstance(bruto, str | bytes):
        raise ComponenteNaoAutorizado(f"{onde}: esperava uma lista de medidas")
    medidas: list[dict[str, Any]] = []
    for valor in bruto[:LIMITE_DE_ITENS]:
        if not isinstance(valor, Mapping) or set(valor) - {"rotulo", "fracao", "detalhe"}:
            raise ComponenteNaoAutorizado(
                f"{onde}: cada medida tem rotulo, fracao (0 a 1) e detalhe opcional"
            )
        try:
            fracao = float(valor.get("fracao", 0.0))
        except (TypeError, ValueError):
            raise ComponenteNaoAutorizado(f"{onde}.fracao: esperava número entre 0 e 1") from None
        medidas.append(
            {
                "rotulo": str(valor.get("rotulo", ""))[:LIMITE_DE_TEXTO],
                "fracao": min(max(fracao, 0.0), 1.0),
                "detalhe": str(valor.get("detalhe", ""))[:LIMITE_DE_TEXTO],
            }
        )
    return medidas


def validar_dados(alvo: Componente, dados: Mapping[str, Any]) -> dict[str, Any]:
    """Os dados que a IA mandou, do jeito que a vista espera — ou recusa com motivo."""
    estranhos = sorted(set(dados) - set(alvo.campos))
    if estranhos:
        raise ComponenteNaoAutorizado(
            f"{alvo.id}: campos que este componente não tem ({', '.join(estranhos)}). Ele "
            f"aceita: {', '.join(sorted(alvo.campos)) or 'nenhum dado'}"
        )
    limpos: dict[str, Any] = {}
    for campo, forma in alvo.campos.items():
        if campo not in dados:
            continue
        bruto = dados[campo]
        onde = f"{alvo.id}.{campo}"
        if forma is Forma.TEXTO:
            if not isinstance(bruto, str):
                raise ComponenteNaoAutorizado(f"{onde}: esperava texto")
            limpos[campo] = bruto[:LIMITE_DE_TEXTO]
        elif forma is Forma.LINHAS:
            limpos[campo] = _linhas(bruto, onde)
        elif forma is Forma.ITENS:
            if not isinstance(bruto, Sequence) or isinstance(bruto, str | bytes):
                raise ComponenteNaoAutorizado(f"{onde}: esperava uma lista de itens")
            limpos[campo] = [_item(item, onde) for item in bruto[:LIMITE_DE_ITENS]]
        elif forma is Forma.HTML_SEGURO:
            if not isinstance(bruto, str):
                raise ComponenteNaoAutorizado(f"{onde}: esperava HTML (texto)")
            # De novo, aqui: quem chegar à tela por outro caminho também passa pela allowlist. E
            # uma segunda regra, de outro jeito (uma negação, não a allowlist), confere que não
            # sobrou nada que o Qt buscaria na rede — se sobrar, é defeito do sanitizador, e a
            # tela recusa em vez de desenhar.
            documento = sanitizar(bruto).documento
            if RECURSO.search(documento):
                raise ComponenteNaoAutorizado(f"{onde}: o HTML ainda aponta para fora")
            limpos[campo] = documento
        elif forma is Forma.COR:
            if not isinstance(bruto, str) or (bruto and not COR.match(bruto)):
                raise ComponenteNaoAutorizado(f"{onde}: esperava uma cor (#rrggbb ou nome)")
            limpos[campo] = bruto
        elif forma is Forma.AVISOS:
            if not isinstance(bruto, Sequence) or isinstance(bruto, str | bytes):
                raise ComponenteNaoAutorizado(f"{onde}: esperava uma lista de avisos")
            limpos[campo] = [_aviso(aviso, onde) for aviso in bruto[:LIMITE_DE_ITENS]]
        else:
            limpos[campo] = _medidas(bruto, onde)
    return limpos
