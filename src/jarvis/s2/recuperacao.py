"""Recuperar de falha em vez de desistir (dono, 2026-10-30; emenda da ADR-0038).

O dono pedia algo no navegador, uma ferramenta falhava (a aba não abriu, o botão não foi achado, o
motor não respondeu a uma rodada) e a tarefa acabava ali: «Não consegui terminar o que você
pediu». Qualquer erro virava desistência. Agora, por cima do modelo:

- **o erro chega estruturado**: a ferramenta, o código da causa, o motivo curto, quantas tentativas
  deste passo já foram e o que já foi tentado — e a instrução de **replanejar por outro caminho**,
  com os caminhos que fazem sentido para aquela família de ferramenta (só os que estão ligados);
- **orçamento**: até `TENTATIVAS_POR_PASSO` falhas seguidas e `FALHAS_POR_TAREFA` no total; o
  laço da tarefa continua com o teto de passos e o prazo de sempre (ADR-0038);
- **sem repetir a mesma ação idêntica**: a mesma ferramenta com os mesmos argumentos que já falhou
  não roda de novo (só a falha passageira — prazo, ocupado — tem uma segunda chance); a proposta
  repetida volta ao motor como recusa, sem chegar ao executor;
- **resultado vazio também é falha**: a busca sem resultado e a página sem texto não confirmam o
  objetivo;
- **o PDP e o guarda continuam valendo em cada tentativa**: nada aqui executa — quem executa é o
  portão de sempre (`fluxo_de_acao`), uma proposta por vez;
- **desistir com honestidade**: esgotado o orçamento, a resposta é do código — o que deu errado e
  o que foi tentado, em frase de gente, nunca "abri".

A linha de cada replanejamento vai **à tela** (o canal de raciocínio, ADR-0031), nunca à voz.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final

from jarvis.s2.motor import PedidoDeTool

if TYPE_CHECKING:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta

TENTATIVAS_POR_PASSO: Final = 4
"""Falhas seguidas (sem nenhum passo que deu certo no meio) antes de desistir."""
FALHAS_POR_TAREFA: Final = 8
"""Falhas no total de uma tarefa: o teto de custo, mesmo com sucessos entre elas."""
ERROS_DO_MOTOR: Final = 2
"""Rodadas do motor que acabaram em erro ou prazo (a CLI que caiu, o serviço que recusou) que a
tarefa tenta de novo antes de desistir — antes, a primeira já derrubava a tarefa inteira."""
TRANSITORIAS: Final = frozenset(
    {"tempo_esgotado", "ocupado", "sem_resposta", "navegador_fechado", "erro_de_rede"}
)
"""Falhas que passam sozinhas: a mesma ação idêntica pode ser tentada **uma** vez mais."""
SEM_SAIDA: Final = frozenset({"dono_nao_confirmou", "extensao_desatualizada", "parado_pelo_dono"})
"""Falhas que nenhum outro caminho resolve agora: o dono disse não, mandou parar, ou precisa
recarregar a extensão. A tarefa acaba com a frase delas, sem gastar tentativa."""
VAZIO_SE: Final[Mapping[str, tuple[str, ...]]] = {
    "web.buscar": ("resultados",),
    "files.search_in_roots": ("achados",),
    "memoria.buscar": ("achados",),
    "memoria.buscar_historico": ("turnos", "achados"),
    "browser.read": ("textoVisivel", "texto", "links"),
}
"""Ferramenta → campos do resultado que, todos vazios, querem dizer "não achei nada"."""
CAMINHOS: Final[Mapping[str, tuple[str, ...]]] = {
    "browser.navigate": ("sites.open", "browser.launch", "web.buscar", "browser.tabs"),
    "browser.tabs": ("browser.launch", "sites.open"),
    "browser.click": (
        "browser.inspecionar",
        "browser.acionar",
        "browser.gesto",
        "browser.scroll",
        "browser.read",
    ),
    "browser.type": ("browser.inspecionar", "browser.click", "browser.gesto", "browser.acionar"),
    "browser.acionar": ("browser.inspecionar", "browser.click", "browser.gesto"),
    "browser.read": ("browser.scroll", "browser.inspecionar", "browser.tela", "web.ler"),
    "browser.inspecionar": ("browser.read", "browser.scroll", "browser.tela"),
    "browser.avaliar": ("browser.inspecionar", "browser.console", "browser.read"),
    "browser.gesto": ("browser.inspecionar", "browser.click", "browser.acionar"),
    "web.buscar": ("web.buscar", "browser.navigate", "web.ler"),
    "web.ler": ("browser.navigate", "browser.read", "web.buscar"),
    "sites.open": ("browser.navigate", "browser.launch", "web.buscar"),
    "apps.launch": ("window.list", "window.focus_app"),
    "window.focus_app": ("window.list", "apps.launch"),
    "files.read_text": ("files.search_in_roots", "files.list_dir"),
    "files.search_in_roots": ("files.list_dir", "files.search_in_roots"),
    "memoria.buscar": ("memoria.buscar_historico",),
}
"""Por onde mais dá para chegar ao mesmo objetivo quando uma ferramenta falha: em ordem de
preferência, e só as que existem nesta sessão entram na nota. (`web.buscar` pode ser ela mesma,
com outra consulta.)"""
DICAS: Final[Mapping[str, str]] = {
    "alvo_ausente": (
        "o elemento não foi achado pelo texto: inspecione a página e use a ref do mapa, role a "
        "página, ou procure outro rótulo"
    ),
    "aba_nao_mudou": "a aba não saiu do lugar: abra o site por outro caminho ou numa aba nova",
    "pagina_nao_abriu": "a página não abriu: confira o endereço, tente pela busca ou outro site",
    "campo_sensivel": "o campo é de senha ou pagamento: o Jarvis não digita nele — diga ao dono",
    "sem_navegador": "não há navegador com a extensão: abra-o (browser.launch ou sites.open)",
    "resultado_vazio": "não veio nada: mude a consulta, leia outro lugar ou role e leia de novo",
    "repetida": "essa mesma ação, com os mesmos argumentos, já falhou: escolha outro caminho",
    "pdp_negou": "a política negou esta ação: não insista nela; procure outro caminho permitido",
    "guarda_barrou": "o guarda barrou esta ação: não insista nela; procure outro caminho",
}
_CODIGO_NO_MOTIVO: Final = re.compile(r"\(([a-z][a-z_]{2,40})\)")
LIMITE_DO_MOTIVO: Final = 160


def codigo_da_falha(resultado: ResultadoDeFerramenta) -> str:
    """O código que diz por que o passo falhou: a `causa` do executor, ou — no erro genérico da
    ferramenta — o código da extensão entre parênteses no motivo, ou um código pelo texto."""
    causa = resultado.causa or ""
    if causa and causa != "erro_da_ferramenta":
        return causa
    motivo = resultado.motivo or ""
    achado = _CODIGO_NO_MOTIVO.search(motivo)
    if achado:
        return achado.group(1)
    baixo = motivo.casefold()
    if "não respondeu" in baixo or "tempo esgotado" in baixo or "timed out" in baixo:
        return "sem_resposta"
    if "nenhum navegador" in baixo:
        return "sem_navegador"
    if "desatualizada" in baixo:
        return "extensao_desatualizada"
    return causa or "erro_da_ferramenta"


def vazio(resultado: ResultadoDeFerramenta) -> bool:
    """O passo deu `ok` mas não trouxe nada (a busca sem resultado, a página sem texto)."""
    campos = VAZIO_SE.get(resultado.tool_id)
    if resultado.status != "ok" or not campos:
        return False
    presentes = [c for c in campos if c in resultado.dados]
    return bool(presentes) and all(not resultado.dados[c] for c in presentes)


def falhou(resultado: ResultadoDeFerramenta) -> bool:
    """O passo não serviu ao objetivo: erro, negado, prazo — ou ok sem nada."""
    if resultado.status in ("erro", "negado"):
        return True
    return vazio(resultado)


def assinatura(tool_id: str, args: Mapping[str, Any]) -> str:
    """A ação como ela é: a ferramenta e os argumentos, em ordem fixa."""
    try:
        corpo = json.dumps(dict(args), sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        corpo = repr(sorted(args.items()))
    return f"{tool_id} {corpo}"


@dataclass(frozen=True, slots=True)
class Tentativa:
    tool_id: str
    assinatura: str
    codigo: str
    motivo: str
    era: int = 0
    """Quantos passos tinham dado certo quando esta falhou: depois de um passo que muda o estado
    (rolar, clicar, navegar), a mesma ação já não é repetição — ler de novo depois de rolar é
    outro caminho."""

    @property
    def transitoria(self) -> bool:
        return self.codigo in TRANSITORIAS

    def em_frase(self) -> str:
        motivo = f": {self.motivo}" if self.motivo else ""
        return f"{self.tool_id} ({self.codigo}){motivo}"


@dataclass(slots=True)
class Recuperacao:
    """O que a tarefa já tentou e quanto ainda pode tentar. Um por tarefa (por objetivo)."""

    tentativas_por_passo: int = TENTATIVAS_POR_PASSO
    falhas_por_tarefa: int = FALHAS_POR_TAREFA
    erros_do_motor: int = ERROS_DO_MOTOR
    seguidas: int = 0
    total: int = 0
    motor_falhou: int = 0
    historico: list[Tentativa] = field(default_factory=list)
    sucessos: int = 0
    """Passos que deram certo até agora: a era de cada falha (`Tentativa.era`)."""
    _repeticoes: Counter[tuple[str, int]] = field(default_factory=Counter)
    _vistos: int = 0
    """Quantos resultados de `feitos` já passaram por `observar`."""

    def observar(self, feitos: Sequence[ResultadoDeFerramenta], pedidos: Sequence[str]) -> None:
        """Os resultados novos desde a última vez (`pedidos` = a assinatura de cada um, na mesma
        ordem): conta a falha, zera as seguidas no sucesso."""
        for indice in range(self._vistos, len(feitos)):
            resultado = feitos[indice]
            marca = pedidos[indice] if indice < len(pedidos) else resultado.tool_id
            if falhou(resultado):
                codigo = (
                    "resultado_vazio" if resultado.status == "ok" else codigo_da_falha(resultado)
                )
                self.registrar_falha(
                    Tentativa(resultado.tool_id, marca, codigo, _curto(resultado.motivo))
                )
            elif resultado.status == "ok":
                self.seguidas = 0
                self.sucessos += 1
        self._vistos = len(feitos)

    def registrar_falha(self, tentativa: Tentativa) -> None:
        if tentativa.era != self.sucessos:
            tentativa = replace(tentativa, era=self.sucessos)
        self.seguidas += 1
        self.total += 1
        self.historico.append(tentativa)
        self._repeticoes[(tentativa.assinatura, tentativa.era)] += 1

    def ultima(self) -> Tentativa | None:
        return self.historico[-1] if self.historico and self.seguidas else None

    def esgotou(self) -> bool:
        return self.seguidas >= self.tentativas_por_passo or self.total >= self.falhas_por_tarefa

    def sem_saida(self) -> Tentativa | None:
        """A última falha é uma que nenhum outro caminho resolve agora."""
        ultima = self.ultima()
        return ultima if ultima is not None and ultima.codigo in SEM_SAIDA else None

    def repetida(self, pedido: PedidoDeTool) -> Tentativa | None:
        """A proposta é a mesma ação que já falhou: recusada sem rodar (a passageira, uma vez só
        de novo)."""
        marca = assinatura(pedido.tool_id, pedido.args)
        anteriores = [
            t
            for t in self.historico
            if t.assinatura == marca and t.era == self.sucessos and t.codigo != "repetida"
        ]
        if not anteriores:
            return None  # nunca falhou, ou algo deu certo depois (o estado mudou)
        if anteriores[-1].transitoria and self._repeticoes[(marca, self.sucessos)] < 2:
            return None
        return anteriores[-1]

    def nota(self, disponiveis: Iterable[str]) -> str:
        """O erro estruturado e a instrução de replanejar, para a rodada seguinte do motor."""
        ultima = self.ultima()
        if ultima is None:
            return ""
        ids = set(disponiveis)
        caminhos = [c for c in CAMINHOS.get(ultima.tool_id, ()) if c in ids]
        dados: dict[str, Any] = {
            "falhou": ultima.tool_id,
            "causa": ultima.codigo,
            "motivo": ultima.motivo,
            "tentativa": self.seguidas,
            "de": self.tentativas_por_passo,
            "ja_tentado": [t.em_frase() for t in self.historico[-6:]],
        }
        if caminhos:
            dados["outros_caminhos"] = caminhos
        dica = DICAS.get(ultima.codigo, "")
        if ultima.transitoria:
            dica = "falha passageira: pode repetir a mesma ação uma vez; se falhar de novo, mude"
        return (
            "O ÚLTIMO PASSO NÃO DEU CERTO — REPLANEJE: "
            + json.dumps(dados, ensure_ascii=False)
            + ". Pense (no bloco de raciocínio) no porquê e tente OUTRO caminho para o mesmo "
            "objetivo: não repita a mesma ferramenta com os mesmos argumentos."
            + (f" Dica: {dica}." if dica else "")
            + " Só desista, explicando o que tentou e o que o dono pode fazer, quando não houver "
            "outro caminho razoável."
        )

    def linha_na_tela(self) -> str:
        """O replanejamento na tela (não na voz): o que falhou e que tentativa vem."""
        ultima = self.ultima()
        if ultima is None:
            return ""
        restam = max(0, self.tentativas_por_passo - self.seguidas)
        return (
            f"{ultima.tool_id} não deu ({ultima.codigo}"
            + (f": {ultima.motivo[:80]}" if ultima.motivo else "")
            + f"); tentando outro caminho — {restam} tentativa(s) restante(s)"
        )

    def explicacao(self, objetivo: str = "") -> str:
        """A desistência com honestidade: o que foi tentado, em frase de gente."""
        tentados = list(dict.fromkeys(t.em_frase() for t in self.historico[-4:]))
        alvo = f" {objetivo.rstrip('.')}" if objetivo else ""
        if not tentados:
            return f"Não consegui{alvo}."
        return f"Não consegui{alvo}. Tentei: {'; '.join(tentados)}."


def nota_do_turno(resultado: ResultadoDeFerramenta, disponiveis: Iterable[str]) -> str:
    """A nota de replanejar para a rodada seguinte **do turno**, quando o passo dele falhou (a
    tarefa tem a sua `Recuperacao`, com o histórico inteiro)."""
    if not falhou(resultado) or resultado.causa == "dono_nao_confirmou":
        return ""
    recuperacao = Recuperacao()
    recuperacao.observar((resultado,), (resultado.tool_id,))
    return recuperacao.nota(disponiveis)


def _curto(motivo: str) -> str:
    texto = " ".join((motivo or "").split())
    return texto if len(texto) <= LIMITE_DO_MOTIVO else texto[: LIMITE_DO_MOTIVO - 1] + "…"


__all__ = [
    "CAMINHOS",
    "ERROS_DO_MOTOR",
    "FALHAS_POR_TAREFA",
    "TENTATIVAS_POR_PASSO",
    "Recuperacao",
    "Tentativa",
    "assinatura",
    "codigo_da_falha",
    "falhou",
    "nota_do_turno",
    "vazio",
]
