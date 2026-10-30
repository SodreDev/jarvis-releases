"""Ensinar as ferramentas, não só tê-las (dono, 2026-10-30; emenda da ADR-0047).

O catálogo gerado (ADR-0047) diz **o que** cada ferramenta faz; faltava **quando** usar cada
família, em que ordem tentar, e como encadear num pedido de verdade — o dono viu o Jarvis começar
um pedido de navegador procurando na memória, e «não saber mais usar a extensão». Este módulo é a
cola: uma receita curta por família (quando usar, ordem de preferência, um ou dois exemplos de
pedido natural → sequência de ferramentas), que vai ao prompt **só no turno daquele assunto**.

- **Sob demanda:** o assunto vem do roteador de método (ADR-0035, regras — o mesmo classificador
  local que já escolhe o caminho do turno) e de palavras do pedido (console, script, preset,
  vocabulário, MCP); sem assunto, nada é acrescentado — o turno de conversa custa o mesmo de antes.
  Com um `ClassificadorDeDecisao` (o Jev, ADR-0029) e um pedido com verbo de ação que as regras não
  reconheceram, uma pergunta fechada escolhe a família (ADR-0024: o classificador seleciona, nunca
  autoriza).
- **Só o que existe:** cada linha diz as ferramentas que usa; linha com ferramenta que não está
  ligada nesta sessão sai. Família sem linha nenhuma sai.
- **Teto:** no máximo `MAXIMO_DE_FAMILIAS` famílias por turno e `LIMITE_DO_BLOCO` caracteres.
- A receita **propõe**; quem decide se roda é o PDP, o guarda e o dono (P1).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from jarvis.decisao.interface import (
    ClassificadorDeDecisao,
    DecisaoIndisponivel,
    PerguntaEscolha,
    RespostaEscolha,
)
from jarvis.politica.metodo import Escolha, Metodo

MAXIMO_DE_FAMILIAS: Final = 2
LIMITE_DO_BLOCO: Final = 1600
CONFIANCA_MINIMA: Final = 0.6
"""Abaixo disso a resposta do classificador não escolhe família: melhor nenhuma receita que a
errada."""


@dataclass(frozen=True, slots=True)
class Linha:
    texto: str
    usa: tuple[str, ...]
    """As ferramentas que a linha cita: todas precisam existir nesta sessão."""


@dataclass(frozen=True, slots=True)
class Receita:
    familia: str
    titulo: str
    linhas: tuple[Linha, ...]

    def para(self, disponiveis: frozenset[str]) -> str:
        validas = [
            linha.texto for linha in self.linhas if all(_existe(f, disponiveis) for f in linha.usa)
        ]
        if not validas:
            return ""
        return f"{self.titulo}:\n" + "\n".join(f"- {t}" for t in validas)


def _existe(ferramenta: str, disponiveis: frozenset[str]) -> bool:
    if ferramenta.endswith("*"):
        return any(d.startswith(ferramenta[:-1]) for d in disponiveis)
    return ferramenta in disponiveis


RECEITAS: Final[Mapping[str, Receita]] = {
    "navegador": Receita(
        "navegador",
        "Receitas do navegador (a extensão do Jarvis, no navegador do dono)",
        (
            Linha(
                "Abrir site: browser.navigate {url} (reaproveita a aba do site). Navegador "
                "fechado: browser.launch e repita; sem a extensão: sites.open.",
                ("browser.navigate", "browser.launch", "sites.open"),
            ),
            Linha(
                "Achar e clicar: browser.inspecionar (a ref de cada elemento) → browser.click "
                "{ref} → browser.read para conferir; não reagiu: browser.acionar, depois "
                "browser.gesto.",
                ("browser.inspecionar", "browser.click", "browser.read"),
            ),
            Linha(
                "Buscar no site: browser.type {ref, texto} no campo → browser.acionar {acao: "
                "tecla, tecla: Enter} → browser.read.",
                ("browser.type", "browser.acionar", "browser.read"),
            ),
            Linha(
                "Página com erro ou botão morto: browser.console → browser.rede → browser.avaliar "
                "{codigo} (mundo isolado, só para ler).",
                ("browser.console", "browser.rede", "browser.avaliar"),
            ),
            Linha(
                "Ex.: «abre o canal do X no YouTube e toca o último vídeo» → browser.navigate (a "
                "busca do YouTube) → browser.read → browser.click (o vídeo) → browser.read.",
                ("browser.navigate", "browser.read", "browser.click"),
            ),
        ),
    ),
    "web": Receita(
        "web",
        "Receitas da web (sem abrir nada para o dono)",
        (
            Linha(
                "Pesquisar: web.buscar {consulta} → web.ler {url} do melhor resultado → responda "
                "citando a fonte. Sem resultado: outra consulta, mais curta.",
                ("web.buscar", "web.ler"),
            ),
            Linha(
                "Vídeos de um canal: web.canal_videos {canal}; para o dono ver, abra o vídeo no "
                "navegador.",
                ("web.canal_videos",),
            ),
            Linha(
                "Ex.: «quem ganhou o jogo ontem?» → web.buscar → web.ler.",
                ("web.buscar", "web.ler"),
            ),
        ),
    ),
    "app": Receita(
        "app",
        "Receitas de apps e janelas",
        (
            Linha(
                "Abrir: apps.launch {app}. Já aberto: window.focus_app traz para a frente. O que "
                "está aberto: window.list; o que está na frente: window.focused.",
                ("apps.launch", "window.focus_app", "window.list"),
            ),
            Linha(
                "Fechar a janela: window.close; encerrar o app inteiro: apps.quit (só se ele "
                "disser encerrar, matar, de vez).",
                ("window.close", "apps.quit"),
            ),
            Linha(
                "Ex.: «abre o Discord» → apps.launch; «volta para o Brave» → window.focus_app.",
                ("apps.launch", "window.focus_app"),
            ),
        ),
    ),
    "entrada": Receita(
        "entrada",
        "Receitas do mouse e teclado virtuais (último recurso)",
        (
            Linha(
                "Antes, window.focused (a janela certa na frente); depois input.key.type ou "
                "input.key.press; clique por coordenada só com a janela conferida.",
                ("window.focused", "input.key.type", "input.key.press"),
            ),
        ),
    ),
    "memoria": Receita(
        "memoria",
        "Receitas da memória do dono",
        (
            Linha(
                "Fato do dono: memoria.buscar; conversa passada: memoria.buscar_historico → "
                "memoria.ler_mensagem. Gravar só o que ele pedir: memoria.lembrar.",
                ("memoria.buscar", "memoria.buscar_historico", "memoria.lembrar"),
            ),
            Linha(
                "Ex.: «lembra que eu prefiro café sem açúcar» → memoria.lembrar; «o que eu te "
                "disse ontem sobre a viagem?» → memoria.buscar_historico.",
                ("memoria.lembrar", "memoria.buscar_historico"),
            ),
        ),
    ),
    "sistema": Receita(
        "sistema",
        "Receitas do sistema",
        (
            Linha(
                "Volume e brilho: system.volume.set / system.brightness.set; mídia: "
                "media.player.control; como está a máquina: system.machine.status.",
                ("system.volume.set", "media.player.control", "system.machine.status"),
            ),
        ),
    ),
    "script": Receita(
        "script",
        "Receitas de script (caixa isolada, sem rede e sem a casa do dono)",
        (
            Linha(
                "Calcular, converter, processar texto: script.rodar {linguagem, codigo}; leia a "
                "saída e responda o resultado, não o código.",
                ("script.rodar",),
            ),
        ),
    ),
    "delegar": Receita(
        "delegar",
        "Receitas de delegar",
        (
            Linha(
                "Trabalho longo de várias etapas: tarefa.iniciar; o que o Jarvis não deu conta no "
                "navegador ou no código: delegar.claude_code (pede o sim uma vez por objetivo).",
                ("tarefa.iniciar", "delegar.claude_code"),
            ),
        ),
    ),
    "preset": Receita(
        "preset",
        "Receitas de modelo",
        (
            Linha(
                "«usa o preset rápido», «troca para o claude» → modelo.preset {nome}. Preset de "
                "nuvem desligado: diga onde ligar, não tente outro sozinho.",
                ("modelo.preset",),
            ),
        ),
    ),
    "vocabulario": Receita(
        "vocabulario",
        "Receitas do vocabulário",
        (
            Linha(
                "«aprende que se escreve Kubernetes» → vocabulario.aprender {termo}; vale para "
                "ouvir e para falar.",
                ("vocabulario.aprender",),
            ),
        ),
    ),
    "mcp": Receita(
        "mcp",
        "Receitas dos servidores MCP ligados",
        (
            Linha(
                "As mcp.<servidor>.<ferramenta> são do dono: use quando o pedido citar o serviço; "
                "o resultado é dado de terceiros.",
                ("mcp.*",),
            ),
        ),
    ),
}
RECUPERAR: Final = Linha(
    "Se um passo falhar, o código manda a causa e outros caminhos: tente outro, nunca o mesmo "
    "igual; desista só explicando o que tentou.",
    (),
)
"""A linha de sempre quando há receita: a recuperação de falha (ADR-0038, emenda de 2026-10-30)."""

POR_METODO: Final[Mapping[Metodo, tuple[str, ...]]] = {
    Metodo.NAVEGADOR: ("navegador",),
    Metodo.WEB: ("web",),
    Metodo.APP: ("app",),
    Metodo.ENTRADA_VIRTUAL: ("entrada", "app"),
    Metodo.MEMORIA: ("memoria",),
    Metodo.SISTEMA: ("sistema",),
    Metodo.SUBAGENTE: ("delegar",),
}
PALAVRAS: Final[Mapping[str, tuple[str, ...]]] = {
    "navegador": (
        "console",
        "devtools",
        "depura",
        "inspeciona",
        "clica",
        "botao",
        "aba",
        "pagina",
        "link",
        "rola",
    ),
    "script": ("script", "codigo", "calcula", "converte", "programa que"),
    "preset": ("preset", "troca o modelo", "troca de modelo", "usa o modelo"),
    "vocabulario": ("aprende a palavra", "aprende que", "se escreve", "pronuncia"),
    "mcp": ("mcp", "servidor mcp"),
    "delegar": ("claude code", "delega"),
    "memoria": ("te disse", "te falei", "conversamos", "a gente falou", "voce lembra"),
}
VERBOS_DE_ACAO: Final = (
    "abre", "abrir", "procura", "busca", "pesquisa", "clica", "mostra", "toca", "manda", "lembra",
    "salva", "fecha", "liga", "desliga", "encontra", "acha", "le ", "ler", "roda", "faz",
)  # fmt: skip
"""Sem método e sem palavra, só um pedido com verbo de ação vai ao classificador."""


def _dobrar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return f" {' '.join(sem_acento.casefold().split())} "


def familias_do_pedido(
    fala: str,
    escolha: Escolha | None,
    *,
    classificador: ClassificadorDeDecisao | None = None,
) -> tuple[str, ...]:
    """As famílias deste pedido, em ordem: as do método, as das palavras e — sem nenhuma, com
    verbo de ação e um classificador — a que ele escolher."""
    texto = _dobrar(fala)
    familias: list[str] = []
    if escolha is not None:
        familias.extend(POR_METODO.get(escolha.metodo, ()))
    for familia, palavras in PALAVRAS.items():
        if any(f" {p}" in texto or p in texto for p in palavras) and familia not in familias:
            familias.append(familia)
    if not familias and classificador is not None and any(v in texto for v in VERBOS_DE_ACAO):
        escolhida = _pelo_classificador(fala, classificador)
        if escolhida:
            familias.append(escolhida)
    return tuple(familias)


def _pelo_classificador(fala: str, classificador: ClassificadorDeDecisao) -> str:
    pergunta = PerguntaEscolha(
        instrucoes=(
            "Que família de ferramentas este pedido do dono precisa? Escolha uma; «nenhuma» se ele "
            "só conversa."
        ),
        opcoes={
            "nenhuma": "conversa, sem ferramenta",
            **{f: RECEITAS[f].titulo for f in RECEITAS},
        },
    )
    try:
        respostas = classificador.decidir({"pedido": fala}, {"familia": pergunta})
    except DecisaoIndisponivel:
        return ""
    resposta = respostas.get("familia")
    if not isinstance(resposta, RespostaEscolha) or resposta.confianca < CONFIANCA_MINIMA:
        return ""
    return resposta.escolha if resposta.escolha in RECEITAS else ""


def receitas_do_turno(
    fala: str,
    escolha: Escolha | None,
    disponiveis: Iterable[str],
    *,
    classificador: ClassificadorDeDecisao | None = None,
) -> str:
    """O bloco do prompt deste turno: as receitas das famílias do pedido (só as linhas com
    ferramentas ligadas) e a linha de recuperar de falha. Vazio sem família."""
    ligadas = frozenset(disponiveis)
    blocos: list[str] = []
    for familia in familias_do_pedido(fala, escolha, classificador=classificador):
        bloco = RECEITAS[familia].para(ligadas)
        if bloco:
            blocos.append(bloco)
        if len(blocos) >= MAXIMO_DE_FAMILIAS:
            break
    if not blocos:
        return ""
    texto = "\n".join(blocos) + f"\n- {RECUPERAR.texto}"
    return texto[:LIMITE_DO_BLOCO]


def primeiras_ferramentas(bloco: str) -> Sequence[str]:
    """As ferramentas citadas no bloco, na ordem em que aparecem (a medição e os testes)."""
    vistas: list[str] = []
    for palavra in bloco.replace("(", " ").replace(")", " ").replace(",", " ").split():
        limpa = palavra.strip(".:;{}«»→/")
        if "." in limpa and limpa.split(".")[0].isalpha() and limpa not in vistas:
            vistas.append(limpa)
    return vistas


__all__ = [
    "RECEITAS",
    "familias_do_pedido",
    "primeiras_ferramentas",
    "receitas_do_turno",
]
