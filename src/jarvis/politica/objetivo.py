"""O objetivo do turno: o que o dono pediu, e até onde a navegação vai sem perguntar (2026-10-20).

O dono testou o app e ouviu "posso?" a cada passo de uma tarefa que ele mesmo tinha pedido
("abra o canal do Thiago Nigro"): depois de ler uma página o turno ficava *contaminado*, e abrir
link, digitar na busca e navegar passavam a pedir o sim. O pedido dele: só o muito crítico
pergunta; o que cabe no objetivo, não.

O objetivo nasce do **pedido do dono** — nunca do que o modelo ou uma página dizem — e guarda:

- os sites que o dono **citou**, pelo nome ("youtube") ou pelo domínio ("youtube.com");
- os domínios **alcançados** no caminho: páginas que o objetivo abriu, links delas, resultados de
  busca, abas abertas. A página que o objetivo mandou abrir pode levar a um domínio novo (o
  resultado da busca, o canal) sem pergunta.

O que continua perguntando, com objetivo ou sem: URL ou texto que leva **dado do dono ou segredo**
(chave, token, senha, e-mail, CPF, telefone, cartão) para domínio que ele não citou; e domínio
que não foi citado nem alcançado, num turno que leu conteúdo de terceiros — o caso do texto
injetado que diz "abra mal.example". Banco, pagamento, senha, enviar, apagar e instalar seguem
nas regras de sempre (risco dinâmico e tier perigoso), que este módulo não toca.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final
from urllib.parse import unquote_plus, urlsplit

from jarvis.memoryd.importacao import redigir
from jarvis.politica.abertura import dominio_registravel

CARACTERES_DO_PEDIDO: Final = 300
PASSOS_GUARDADOS: Final = 12
"""Os passos que o objetivo lembra (ferramenta e status, nunca dados): o resto é só contado."""


class Fase(StrEnum):
    """Em que ponto do objetivo está a chamada (Lote C, C2) — dita ao classificador."""

    PLANEJANDO = "planejando"
    """Antes da primeira ferramenta."""
    EXECUTANDO = "executando"
    VERIFICANDO = "verificando"
    """Uma leitura depois de um efeito: conferir o que foi feito."""
    CONCLUINDO = "concluindo"
    """A resposta final ao dono."""


class EstadoDoObjetivo(StrEnum):
    ABERTO = "aberto"
    EM_ANDAMENTO = "em_andamento"
    AGUARDANDO_O_DONO = "aguardando_o_dono"
    CONCLUIDO = "concluido"
    """O modelo deu a resposta final; que o critério foi cumprido, quem diz é o resultado lido."""
    FALHOU = "falhou"
    CANCELADO = "cancelado"


CRITERIO_PADRAO: Final = "o dono respondido com o que pediu, conferido no resultado"
CRITERIOS: Final[dict[str, str]] = {
    "navegador": "a página pedida aberta e conferida pela leitura (título, canal, conteúdo)",
    "entrada_virtual": "a ação feita e conferida na tela",
    "web": "a resposta achada numa fonte e conferida",
    "app": "o app aberto e em foco",
    "subagente": "a tarefa em segundo plano iniciada e o dono avisado",
    "sistema": "o ajuste feito e o resultado dito",
    "memoria": "anotado ou achado, e dito ao dono",
}
"""O critério de pronto pelo método do pedido (ADR-0035): o que conta como "ficou pronto"."""
CRITERIOS_POR_MOTIVO: Final[dict[str, str]] = {
    "fecha_janela": "a janela fechada e conferida: saiu da lista (ou o app ficou perguntando)",
    "encerra_app": "o app encerrado e conferido: os processos dele saíram",
    "encerra_o_jarvis": "o Jarvis encerrado, limpo",
}
"""Quando o motivo do método diz mais que o método (ADR-0041, ADR-0042): fechar não é abrir."""
METODOS_QUE_CONFEREM: Final = frozenset({"navegador", "entrada_virtual"})
"""Os métodos em que o efeito pode não acontecer sem erro nenhum (a aba não mudou, o clique caiu
fora): o objetivo só fica pronto depois de uma leitura que o confira (ADR-0038)."""
SEGREDOS_QUE_NAO_CONTAM_EM_URL: Final = frozenset({"hex_longo", "conteudo_de_env"})
"""Em URL, hexadecimal longo é quase sempre identificador de página (cache, assinatura de CDN) e
não segredo do dono: contaria como dado do dono e perguntaria à toa."""
_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CPF: Final = re.compile(r"(?<!\d)(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?!\d)")
_TELEFONE: Final = re.compile(
    r"(?:\+55\s?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4})|(?:\(\d{2}\)\s?9?\d{4}-?\d{4})"
)
_DIGITOS: Final = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def _cpf_valido(digitos: str) -> bool:
    if len(set(digitos)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d) * (tamanho + 1 - i) for i, d in enumerate(digitos[:tamanho]))
        if (soma * 10 % 11) % 10 != int(digitos[tamanho]):
            return False
    return True


def _luhn(digitos: str) -> bool:
    soma = 0
    for posicao, digito in enumerate(reversed(digitos)):
        n = int(digito)
        if posicao % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        soma += n
    return soma % 10 == 0


def dados_do_dono(texto: str, *, em_url: bool = False) -> list[str]:
    """Os tipos de dado pessoal ou segredo que o texto leva (vazio = nenhum). Em URL, o texto é
    decodificado antes (`%40` é `@`)."""
    claro = unquote_plus(texto) if em_url else texto
    achados = set(redigir(claro).achados)
    if em_url:
        achados -= SEGREDOS_QUE_NAO_CONTAM_EM_URL
    if _EMAIL.search(claro):
        achados.add("email")
    if any(_cpf_valido("".join(m.groups())) for m in _CPF.finditer(claro)):
        achados.add("cpf")
    if _TELEFONE.search(claro):
        achados.add("telefone")
    for corrida in _DIGITOS.finditer(claro):
        digitos = re.sub(r"[ -]", "", corrida.group())
        if 13 <= len(digitos) <= 19 and _luhn(digitos):
            achados.add("cartao")
    return sorted(achados)


def termos(texto: str) -> list[str]:
    """Palavras sem acento nem caixa; o ponto fica só por dentro (`youtube.com`)."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).casefold()
    return [t.strip(".") for t in re.sub(r"[^\w\s.]", " ", sem_acento).split() if t.strip(".")]


def _host(url_ou_host: str) -> str:
    partes = urlsplit(url_ou_host.strip())
    if partes.scheme and partes.hostname:
        return partes.hostname
    return url_ou_host.strip().lower()


@dataclass(slots=True)
class Objetivo:
    """O objetivo de um turno. Quem o cria é o código, com a fala do dono; quem o amplia é o
    código, com os endereços que as ferramentas do objetivo devolveram."""

    pedido: str
    """A fala do dono, redigida e curta: é o texto do objetivo."""
    _termos: frozenset[str] = frozenset()
    alcancados: set[str] = field(default_factory=set)
    """Domínios registráveis (`youtube.com`) que o caminho do objetivo alcançou."""
    criterio: str = CRITERIO_PADRAO
    """Como saber que ficou pronto (pelo método do pedido, `CRITERIOS`)."""
    estado: EstadoDoObjetivo = EstadoDoObjetivo.ABERTO
    fase: Fase = Fase.PLANEJANDO
    passos: list[tuple[str, str]] = field(default_factory=list)
    """`(ferramenta, status)` dos últimos passos — nunca argumento nem resultado."""
    total_de_passos: int = 0
    pede_conferencia: bool = False
    """O método do pedido é um dos `METODOS_QUE_CONFEREM`."""
    efeitos_tentados: int = 0
    """Passos com efeito (navegar, clicar, abrir, mudar) que foram tentados, deram certo ou não."""
    _efeito_feito: bool = False
    _conferido: bool = False
    """Uma leitura que deu certo veio depois do último efeito que deu certo."""

    @classmethod
    def do_pedido(cls, fala: str, metodo: str = "", motivo: str = "") -> Objetivo:
        limpo = " ".join(redigir(fala).texto.split())
        curto = limpo if len(limpo) <= CARACTERES_DO_PEDIDO else limpo[:CARACTERES_DO_PEDIDO] + "…"
        return cls(
            pedido=curto,
            _termos=frozenset(termos(fala)),
            criterio=CRITERIOS_POR_MOTIVO.get(motivo) or CRITERIOS.get(metodo, CRITERIO_PADRAO),
            pede_conferencia=metodo in METODOS_QUE_CONFEREM,
        )

    def registrar(self, tool_id: str, status: str, *, leitura: bool) -> None:
        """Um passo concluído: muda a fase (ler depois de um efeito é verificar) e o estado."""
        self.total_de_passos += 1
        self.passos = [*self.passos, (tool_id, status)][-PASSOS_GUARDADOS:]
        if status == "pendente":
            self.estado = EstadoDoObjetivo.AGUARDANDO_O_DONO
            return
        self.estado = EstadoDoObjetivo.EM_ANDAMENTO
        if not leitura:
            self.efeitos_tentados += 1
        if leitura and self._efeito_feito:
            self.fase = Fase.VERIFICANDO
        else:
            self.fase = Fase.EXECUTANDO
        if not leitura and status == "ok":
            self._efeito_feito = True
            self._conferido = False  # efeito novo pede leitura nova
        elif leitura and status == "ok" and self._efeito_feito:
            self._conferido = True

    @property
    def efeito_feito(self) -> bool:
        """Algum passo com efeito deu certo."""
        return self._efeito_feito

    @property
    def falta_conferir(self) -> bool:
        """O método pede conferência, houve efeito (navegar, clicar, digitar) e a última coisa
        feita não foi uma leitura que o conferisse: dizer "abri" agora seria dizer sem ter visto
        (ADR-0038)."""
        return self.pede_conferencia and self._efeito_feito and not self._conferido

    def concluir(self, estado: EstadoDoObjetivo) -> None:
        """O fim do turno ou da tarefa: a resposta final (concluindo) ou o motivo de parar."""
        self.fase = Fase.CONCLUINDO
        if self.estado is not EstadoDoObjetivo.AGUARDANDO_O_DONO:
            self.estado = estado

    def para_o_classificador(self, *, na_nuvem: bool) -> dict[str, Any]:
        """O contexto do objetivo para o portão (Jev): critério, fase, estado e os passos feitos.
        Na nuvem o texto do pedido não vai de novo (já vai redigido em `pedido_do_dono`, D20)."""
        contexto: dict[str, Any] = {
            "criterio_de_pronto": self.criterio,
            "fase": str(self.fase),
            "estado": str(self.estado),
            "passos_feitos": [f"{t}:{s}" for t, s in self.passos[-8:]],
            "total_de_passos": self.total_de_passos,
        }
        if not na_nuvem:
            contexto["objetivo"] = self.pedido
        return contexto

    def citado(self, url_ou_host: str) -> bool:
        """O dono disse o nome ou o domínio deste site (e o host é ele ou um subdomínio dele)."""
        registravel = dominio_registravel(_host(url_ou_host))
        if not registravel:
            return False
        return registravel in self._termos or registravel.split(".")[0] in self._termos

    def dentro(self, url_ou_host: str) -> bool:
        registravel = dominio_registravel(_host(url_ou_host))
        return bool(registravel) and (self.citado(registravel) or registravel in self.alcancados)

    def alcancar(self, enderecos: Iterable[str]) -> None:
        for endereco in enderecos:
            registravel = dominio_registravel(_host(str(endereco)))
            if registravel:
                self.alcancados.add(registravel)

    def leva_dado_do_dono(self, url: str) -> list[str]:
        """Os dados do dono que a URL leva para um domínio que ele **não citou** (vazio = nada)."""
        return [] if self.citado(url) else dados_do_dono(url, em_url=True)


def enderecos_do_resultado(dados: object) -> list[str]:
    """Os endereços que um resultado de ferramenta traz: `url` e `dominio` no topo, `href` e `url`
    de links, resultados, vídeos, abas e dos elementos do mapa da página. Só endereço — o texto do
    resultado não é lido."""
    achados: list[str] = []

    def visitar(valor: object, profundidade: int) -> None:
        if profundidade > 3:
            return
        if isinstance(valor, dict):
            for chave in ("url", "href", "dominio", "destinoDoLink"):
                endereco = valor.get(chave)
                if isinstance(endereco, str) and endereco:
                    achados.append(endereco)
            for chave in ("links", "resultados", "videos", "abas", "aba", "elementos"):
                if chave in valor:
                    visitar(valor[chave], profundidade + 1)
        elif isinstance(valor, list):
            for item in valor[:200]:
                visitar(item, profundidade + 1)

    visitar(dados, 0)
    return achados
