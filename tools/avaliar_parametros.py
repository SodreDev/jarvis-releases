"""Avalia se o Jarvis DECIDE os parâmetros das ações por conta própria (ADR-0071).

O caso do dono (2026-11-16): «o contato da minha mãe é literalmente mãe salve para não esquecer
depois» virou «Vou abrir a conversa "mãe salve para não esquecer depois"»: o modelo repassou a fala
como parâmetro e ignorou o «salve». Os testes e2e passavam porque o motor deles era roteirizado.
Este avaliador põe o motor que se escolher contra o corpus `tools/corpus_parametros.toml` e mede:

- **parâmetro certo**: a conversa aberta/enviada é a esperada, a mensagem foi redigida, o argumento
  tem o valor e não a fala copiada (`proibido_em_argumento`);
- **memória**: «salva/anota/lembra» chamou `memoria.lembrar` (ou `criar_no`/`criar_aresta`) com o
  fato, e ele está no livro;
- **pergunta quando ambíguo**: nada enviado, nenhuma conversa errada aberta, e uma pergunta ao dono;
- **plano**: o `<<pensar>>` antes da 1ª ferramenta, e quantas vezes foi cobrado;
- **latência**: 1º token de cada chamada ao motor, 1ª fala do turno, chamadas e tokens.

NADA REAL É TOCADO. O cérebro, o executor, o PDP, o gestor de tarefas e o motor do objetivo são os
de produção. A extensão é uma página FALSA do WhatsApp (estado e DOM em memória), a memória é um
livro em RAM, e todo corpo que não é a página falsa nem a memória (apps, janelas, sistema, script,
delegação, entrada virtual, abrir site) é simulado e só devolve `{"simulado": true}`. Navegador,
contas, voz e áudio do dono ficam de fora.

Motores:

- `--motor ideal` (padrão): falso, faz o que o caso espera. Prova o avaliador (deve dar 100%).
- `--motor copiao`: falso, repete o bug do print (sem plano, a fala como parâmetro). Prova que o
  avaliador pega a falha (deve dar perto de 0%).
- `--motor real`: o provedor que o app usa (`~/.config/jarvis/jarvis-voz.toml` e os presets do
  dono), com a chave só do ambiente — este script nunca lê nem imprime chave. **Gasta crédito:**
  só com o OK do dono. `--sem-raciocinio-escondido` usa o `claude -p` direto com
  `MAX_THINKING_TOKENS=0` (o interruptor do item 8), para medir a diferença.

Uso:

    uv run --frozen python -m tools.avaliar_parametros                 # fakes, sem rede
    uv run --frozen python -m tools.avaliar_parametros --motor copiao
    uv run --frozen python -m tools.avaliar_parametros --motor real \
        --saida docs/medicoes/parametros-do-modelo.md
    ... --caso print-do-dono --caso abre-discord                       # só alguns
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
import tomllib
import unicodedata
from collections.abc import Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

RAIZ: Final = Path(__file__).resolve().parent.parent
CORPUS: Final = RAIZ / "tools" / "corpus_parametros.toml"
VALIDACAO: Final = RAIZ / "tools" / "corpus_validacao.toml"
"""O conjunto separado, escrito depois do ajuste e nunca usado para ajustar (ADR-0071)."""
LACO: Final = RAIZ / "tools" / "corpus_laco.toml"
"""O conjunto novo do laço canônico (ADR-0072), com alvos fixados antes de rodar."""
WHATSAPP: Final = "https://web.whatsapp.com/"
ABA: Final = 7
CONVERSAS: Final = (
    "Mãe",
    "Pai",
    "Bruno",
    "Carla",
    "Ana Paula",
    "Ana Clara",
    "Trabalho",
    "Vó Lúcia",
)
ESPERA_DA_TAREFA_S: Final = {"ideal": 20.0, "copiao": 20.0, "real": 150.0}


def _memorias_fixas() -> tuple[Any, ...]:
    from jarvis.social.memorias import MemoriaFixa

    return (
        MemoriaFixa("m1", "contato", "Mãe", "minha mãe"),
        MemoriaFixa("m2", "contato", "Bruno", "meu irmão"),
    )


MEMORIAS_FIXAS: Final = _memorias_fixas()
"""As da página de memórias do app, as mesmas de `contatos` (nunca telefone)."""
BUSCAS: Final = frozenset({"memoria.buscar", "memoria.buscar_historico", "web.buscar"})
GRAVAM: Final = frozenset({"memoria.lembrar", "memoria.criar_no", "memoria.criar_aresta"})
SO_CONSULTAS: Final = frozenset(
    {"system.clock.now", "memoria.buscar", "memoria.buscar_historico", "script.rodar"}
)


def normal(texto: object) -> str:
    base = unicodedata.normalize("NFKD", str(texto).casefold())
    sem_acento = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", sem_acento).split())


# --- a página falsa do WhatsApp ------------------------------------------------------------------
class PaginaFalsa:
    """A extensão do Jarvis respondendo como uma aba do WhatsApp Web: lista de conversas, cabeçalho,
    campo e botão de enviar. Cada `page.map` é um instantâneo novo (os `ref` velhos caem)."""

    def __init__(self, recebidas: Mapping[str, str] | None = None) -> None:
        self.recebidas = dict(recebidas or {})
        """A última mensagem que cada pessoa mandou (o conjunto do laço, ADR-0072)."""
        self.aberta = ""
        self.abertas: list[str] = []
        self.rascunho = ""
        self.enviadas: dict[str, list[str]] = {nome: [] for nome in CONVERSAS}
        self.instantaneo = 0
        self.metodos: list[str] = []

    def _elementos(self) -> list[dict[str, Any]]:
        n = self.instantaneo
        saida: list[dict[str, Any]] = [
            {"ref": f"m{n}.{i}", "papel": "listitem", "rotulo": nome, "nome": nome}
            for i, nome in enumerate(CONVERSAS)
        ]
        if self.aberta:
            saida += [
                {"ref": f"m{n}.20", "papel": "heading", "rotulo": self.aberta},
                {
                    "ref": f"m{n}.21",
                    "papel": "textbox",
                    "rotulo": "Digite uma mensagem",
                    "campo": True,
                },
                {"ref": f"m{n}.22", "papel": "button", "rotulo": "Enviar"},
            ]
        return saida

    def _achar(self, params: Mapping[str, Any]) -> dict[str, Any] | str:
        ref, alvo = params.get("ref"), params.get("alvo")
        if ref:
            achado = next((e for e in self._elementos() if e["ref"] == ref), None)
            return achado if achado is not None else "ref_expirada"
        iguais = [e for e in self._elementos() if normal(e["rotulo"]) == normal(alvo or "")]
        if len(iguais) == 1:
            return iguais[0]
        return "alvo_ambiguo" if iguais else "alvo_ausente"

    def _aba(self) -> dict[str, Any]:
        return {"id": ABA, "janelaId": 1, "ativa": True, "url": WHATSAPP, "titulo": "WhatsApp"}

    def chamar(self, pedido: Any, navegador: str = "") -> dict[str, Any]:
        del navegador
        self.metodos.append(pedido.method)
        ok = {"id": pedido.id, "ok": True}
        p = pedido.params

        def erro(codigo: str, mensagem: str = "") -> dict[str, Any]:
            return {"id": pedido.id, "ok": False, "error": {"codigo": codigo, "mensagem": mensagem}}

        match pedido.method:
            case "tabs.list":
                return ok | {"result": {"abas": [self._aba()]}}
            case "tabs.current" | "tabs.show":
                return ok | {"result": {"aba": self._aba()}}
            case "tabs.navigate" | "tabs.open":
                # Como a extensão confere (cliente.navegar): saiu do lugar, carregou, respondeu.
                pagina = {"url": WHATSAPP, "titulo": "WhatsApp"}
                return ok | {
                    "result": {
                        "aba": self._aba(),
                        "comecou": True,
                        "carregou": True,
                        "pagina": pagina,
                        "janela": "dono",
                        "visivel": True,
                    }
                }
            case "page.eval":
                return ok | {"result": {"valor": None}}
            case "page.console" | "page.network":
                return ok | {"result": {"itens": []}}
            case "windows.focused":
                return ok | {"result": {"janelaId": 1, "abaAtivaId": ABA}}
            case "page.map":
                self.instantaneo += 1
                elementos = self._elementos()
                return ok | {
                    "result": {
                        "url": WHATSAPP,
                        "titulo": "WhatsApp",
                        "instantaneo": self.instantaneo,
                        "total": len(elementos),
                        "elementos": elementos,
                    }
                }
            case "page.read":
                cabecalho = f"Conversa com {self.aberta}. " if self.aberta else ""
                recebida = self.recebidas.get(self.aberta, "")
                ultimas = " ".join(
                    ([f"{self.aberta}: {recebida}"] if recebida else [])
                    + [f"Você: {m}" for m in self.enviadas.get(self.aberta, [])]
                )
                texto = f"{cabecalho}{ultimas}".strip() or "Conversas: " + ", ".join(CONVERSAS)
                return ok | {
                    "result": {
                        "url": WHATSAPP,
                        "titulo": "WhatsApp",
                        "textoVisivel": texto,
                        "links": [],
                        "datas": [],
                    }
                }
            case "page.inspect":
                achado = self._achar(p)
                return (
                    erro(achado, "não achei")
                    if isinstance(achado, str)
                    else ok | {"result": dict(achado)}
                )
            case "page.click" | "page.act" | "page.gesture":
                achado = self._achar(p)
                if isinstance(achado, str):
                    return erro(achado, "não achei")
                envia_do_campo = achado.get("campo") and (
                    p.get("acao") == "enviar" or p.get("tecla") == "Enter"
                )
                if envia_do_campo and self.rascunho:
                    # «enviar»/Enter no campo do chat manda, como no WhatsApp de verdade.
                    self.enviadas[self.aberta].append(self.rascunho)
                    self.rascunho = ""
                elif achado["papel"] == "listitem":
                    self.aberta, self.rascunho = str(achado["rotulo"]), ""
                    self.abertas.append(self.aberta)
                elif achado["rotulo"] == "Enviar" and self.rascunho:
                    self.enviadas[self.aberta].append(self.rascunho)
                    self.rascunho = ""
                self.instantaneo += 1
                return ok | {"result": {"clicado": True, "feito": True}}
            case "page.type":
                achado = self._achar(p)
                if isinstance(achado, str) or not achado.get("campo"):
                    return erro("nao_e_campo", "não é um campo")
                self.rascunho = str(p.get("texto", ""))
                return ok | {"result": {"digitado": len(self.rascunho)}}
            case "page.scroll":
                return ok | {"result": {"rolado": True}}
        return erro("metodo_invalido", f"a página falsa não conhece {pedido.method}")


# --- o executor de produção, com os corpos do sistema simulados --------------------------------
def executor_de_avaliacao(pasta: Path, pagina: PaginaFalsa, livro: Any) -> Any:
    from jarvis.executor.ferramentas import ExecutorDeFerramentas, ResultadoDeFerramenta
    from jarvis.memoryd.ferramentas import FerramentasDeMemoria
    from jarvis.navegador.cliente import ClienteDoNavegador
    from jarvis.navegador.ferramentas import CorposDoNavegador
    from jarvis.politica.auditoria import LogDeAuditoria
    from jarvis.politica.catalogo import carregar_catalogo
    from jarvis.politica.modos import Modo
    from jarvis.politica.pdp import Pdp
    from jarvis.politica.permissao import ModoDePermissao
    from jarvis.tarefas.gestor import GestorDeTarefas

    class ExecutorDeAvaliacao(ExecutorDeFerramentas):
        """O de produção; só os corpos que tocariam a máquina do dono viram simulação."""

        registro: list[tuple[str, dict[str, Any], str, str]]
        """Cada chamada que chegou ao executor: (ferramenta, argumentos, status, causa)."""
        erros: list[str]

        def avaliar(self, tool_id: str, args: Mapping[str, Any], **kw: Any) -> Any:
            avaliacao = super().avaliar(tool_id, args, **kw)
            if isinstance(avaliacao, ResultadoDeFerramenta):  # recusada antes de rodar
                self.registro.append((tool_id, dict(args), avaliacao.status, avaliacao.causa))
                self.erros.append(f"{tool_id} {dict(args)} → {avaliacao.motivo[:160]}")
            return avaliacao

        def concluir(self, avaliacao: Any, **kw: Any) -> ResultadoDeFerramenta:
            resultado = super().concluir(avaliacao, **kw)
            self.registro.append(
                (avaliacao.tool_id, dict(avaliacao.argumentos), resultado.status, resultado.causa)
            )
            if resultado.status != "ok":
                self.erros.append(
                    f"{avaliacao.tool_id} {dict(avaliacao.argumentos)} → {resultado.motivo[:160]}"
                )
            return resultado

        def _corpo(self, tool_id: str, *_a: Any, **_k: Any) -> dict[str, Any]:
            return {"simulado": True, "nota": f"{tool_id} simulado pelo avaliador"}

        def _entrada_virtual(self, tool_id: str, *_a: Any, **_k: Any) -> dict[str, Any]:
            return {"simulado": True}

    lar = pasta / "casa"
    lar.mkdir(parents=True, exist_ok=True)
    auditoria = LogDeAuditoria(pasta / "auditoria.sqlite")
    pdp = Pdp(
        catalogo=carregar_catalogo(),
        lar=lar,
        auditoria=auditoria,
        modo=Modo.PADRAO,
        pasta_do_jarvis=pasta / "area",
        permissao=ModoDePermissao.AUTOMATICO,  # o modo do dono: age sem pedir
    )
    executor = ExecutorDeAvaliacao(
        pdp=pdp,
        lar=lar,
        abrir_site=lambda _url: None,  # nunca o portal do desktop
        navegador=CorposDoNavegador(ClienteDoNavegador(pagina)),
    )
    executor.registro = []
    executor.erros = []
    executor.preparar()
    executor.memoria = FerramentasDeMemoria(livro=livro)
    executor.tarefas = GestorDeTarefas(executor=executor, confirmar=lambda _p, _c: True)
    return executor


# --- motores -----------------------------------------------------------------------------------
@dataclass(slots=True)
class Chamada:
    ms_primeiro: float | None
    ms_total: float
    tokens_entrada: int
    tokens_saida: int
    tarefa: bool


@dataclass(slots=True)
class MotorMedido:
    """Mede cada chamada (1º delta, total, tokens) sem mudar o que o motor faz."""

    motor: Any
    chamadas: list[Chamada] = field(default_factory=list)

    @property
    def nome(self) -> str:
        return str(self.motor.nome)

    @property
    def onde(self) -> Any:
        return self.motor.onde

    @property
    def aceita_imagem(self) -> bool:
        return getattr(self.motor, "aceita_imagem", False) is True

    def gerar(self, contexto: Any, modo: Any, cancelado: Any) -> Generator[Any, None, None]:
        from jarvis.s2.motor import Fim

        comeco = time.monotonic()
        primeiro: float | None = None
        uso: Mapping[str, int] = {}
        try:
            for delta in self.motor.gerar(contexto, modo, cancelado):
                if primeiro is None and not isinstance(delta, Fim):
                    primeiro = (time.monotonic() - comeco) * 1000.0
                if isinstance(delta, Fim):
                    uso = delta.uso
                yield delta
        finally:
            self.chamadas.append(
                Chamada(
                    primeiro,
                    (time.monotonic() - comeco) * 1000.0,
                    # A CLI do Claude informa input/output_tokens; o motor compatível (OpenRouter)
                    # já normaliza em entrada/saida (`compativel._uso`).
                    sum(int(v) for k, v in uso.items() if "input" in k or k == "entrada"),
                    int(uso.get("output_tokens", uso.get("saida", 0))),
                    "Você é o subagente" in contexto.sistema,
                )
            )


def _resultados(contexto: Any) -> list[dict[str, Any]]:
    saida = []
    for m in contexto.mensagens:
        if m.papel == "ferramenta":
            try:
                saida.append(json.loads(m.texto.split(" …[truncado]")[0]))
            except ValueError:
                saida.append({"tool_id": "?", "status": "?"})
    return saida


def _ref(resultado: Mapping[str, Any], papel: str, rotulo: str) -> str | None:
    for e in resultado.get("dados", {}).get("elementos", []):
        if e.get("papel") == papel and (not rotulo or normal(e.get("rotulo")) == normal(rotulo)):
            return str(e["ref"])
    return None


def _cabecalho(resultado: Mapping[str, Any]) -> str:
    return next(
        (
            str(e.get("rotulo"))
            for e in resultado.get("dados", {}).get("elementos", [])
            if e.get("papel") == "heading"
        ),
        "",
    )


def motor_ideal(caso: Mapping[str, Any]) -> Any:
    """Falso: faz o que o caso espera — plano, memória, envio redigido, pergunta."""
    from jarvis.s2.motor import PedidoDeTool, Raciocinio
    from jarvis.s2.motor_roteirizado import MotorRoteirizado

    espera = str(caso["espera"])
    conversa = str(caso.get("conversa", ""))
    mensagem = "Oi! " + " ".join(caso.get("mensagem_contem", [])) + ", te falo já."
    fato = str(caso.get("memoria_texto", ""))  # o trecho exato da fala (ADR-0026, regra 3)

    def responder(ctx: Any) -> Sequence[Any] | str:
        feitos = _resultados(ctx)
        if "Você é o subagente" in ctx.sistema:
            return _subagente(feitos)
        gravou = any(r.get("tool_id") in GRAVAM and r.get("status") == "ok" for r in feitos)
        quer_memoria = bool(caso.get("memoria_contem"))
        if quer_memoria and not gravou:
            return [
                Raciocinio(f"Guardar: {fato} → memoria.lembrar."),
                PedidoDeTool("memoria.lembrar", {"texto": fato}),
            ]
        if espera in ("delegacao", "permissao") and not feitos:
            ferramenta = str(caso["ferramenta"]).split("|")[0]
            args = dict(caso.get("ideal_args", {}))
            return [Raciocinio(f"Fazer: {ferramenta} {args}."), PedidoDeTool(ferramenta, args)]
        if espera in ("envio", "clique", "envio_e_memoria", "leitura"):
            return [
                Raciocinio(f"Abrir a conversa «{conversa}» no WhatsApp."),
                "Vou ver.",
                PedidoDeTool("browser.inspecionar", {"tab_id": ABA}),
            ]
        if espera == "ferramenta":
            if feitos and feitos[-1].get("tool_id") not in GRAVAM:
                return "Pronto."
            ferramenta = str(caso["ferramenta"]).split("|")[0]
            args: dict[str, Any] = {}
            if caso.get("argumento") == "url":
                args["url"] = f"https://www.{caso['contem']}.com/"
            elif caso.get("argumento"):
                args[str(caso["argumento"])] = str(caso["contem"]).title()
            if ferramenta == "system.volume.set":
                args["nivel"] = 30
            args.update(caso.get("ideal_args", {}))
            return [Raciocinio(f"Fazer: {ferramenta} {args}."), PedidoDeTool(ferramenta, args)]
        if espera == "pergunta":
            return "Não achei esse contato com certeza na lista: qual deles você quer?"
        if gravou:
            return "Guardei."
        return "Tudo certo por aqui!"

    def _subagente(feitos: list[dict[str, Any]]) -> Sequence[Any] | str:
        ultimo = feitos[-1] if feitos else {}
        if espera == "delegacao":
            return "Achei: o resultado da busca está pronto."
        if espera not in ("envio", "clique", "envio_e_memoria", "leitura"):
            return "Pronto."  # a ação de um passo já foi (ou foi negada): o fim da tarefa
        if espera == "leitura" and ultimo.get("tool_id") == "browser.read":
            recebida = dict(caso.get("recebidas", {})).get(conversa, "")
            return f"{conversa} mandou: {recebida}."
        so_abrir = espera == "clique" or bool(caso.get("so_abrir"))
        lida = ultimo.get("tool_id") == "browser.inspecionar" and _cabecalho(ultimo) == conversa
        if espera == "leitura" and lida:
            return [PedidoDeTool("browser.read", {"tab_id": ABA})]
        if ultimo.get("tool_id") == "browser.inspecionar" and ultimo.get("status") == "ok":
            if _cabecalho(ultimo) != conversa:
                ref = _ref(ultimo, "listitem", conversa)
                return [
                    PedidoDeTool("browser.click", {"tab_id": ABA, "ref": ref, "esperado": conversa})
                ]
            if so_abrir:
                return f"Abri a conversa da {conversa}."
            campo = _ref(ultimo, "textbox", "")
            return [PedidoDeTool("browser.type", {"tab_id": ABA, "ref": campo, "texto": mensagem})]
        if ultimo.get("tool_id") == "browser.type" and ultimo.get("status") == "ok":
            anterior = next(
                r for r in reversed(feitos) if r.get("tool_id") == "browser.inspecionar"
            )
            return [
                PedidoDeTool(
                    "browser.click", {"tab_id": ABA, "ref": _ref(anterior, "button", "Enviar")}
                )
            ]
        if ultimo.get("tool_id") == "browser.click" and ultimo.get("status") == "ok":
            if ultimo.get("dados", {}).get("enviado"):
                return [PedidoDeTool("browser.read", {"tab_id": ABA})]
            return [PedidoDeTool("browser.inspecionar", {"tab_id": ABA})]
        if ultimo.get("tool_id") == "browser.read":
            return "Mandei."
        return [PedidoDeTool("browser.inspecionar", {"tab_id": ABA})]

    return MotorRoteirizado(resposta=responder)


def motor_copiao(caso: Mapping[str, Any]) -> Any:
    """Falso: o bug do print — sem plano, a fala do dono vira o parâmetro."""
    from jarvis.s2.motor import PedidoDeTool
    from jarvis.s2.motor_roteirizado import MotorRoteirizado

    fala = str(caso["fala"])

    def responder(ctx: Any) -> Sequence[Any] | str:
        feitos = _resultados(ctx)
        if len(feitos) >= 3:
            return "Abri."
        if "Você é o subagente" in ctx.sistema or feitos:
            return [PedidoDeTool("browser.click", {"tab_id": ABA, "alvo": fala})]
        return [
            f"Vou abrir a conversa «{fala}».",
            PedidoDeTool("browser.click", {"tab_id": ABA, "alvo": fala}),
        ]

    return MotorRoteirizado(resposta=responder)


def motor_real(pasta: Path, *, sem_raciocinio: bool, provedor: str = "", modelo: str = "") -> Any:
    """O provedor que o app usa, como o app o monta (sem ler chave: o ambiente é o do processo).

    Com `provedor`, monta esse provedor do registro com o `modelo` dado, pelo mesmo portão de
    sempre (`Provedores.motor`): o interruptor da nuvem é ligado SÓ em memória, para esta
    avaliação que o dono autorizou — a configuração dele não é gravada."""
    import dataclasses

    from jarvis.voz.app import motor_de_conversa
    from jarvis.voz.config import ler

    configuracao = ler()
    if provedor:
        from jarvis.provedores.nucleo import Provedores

        ligada = dataclasses.replace(
            configuracao, nuvem_ligada=(*configuracao.nuvem_ligada, provedor)
        )
        (pasta / "conversa").mkdir(parents=True, exist_ok=True)
        return Provedores.da_configuracao(ligada, pasta_de_trabalho=pasta / "conversa").motor(
            provedor, modelo, "low"
        )
    if sem_raciocinio:
        from jarvis.s2.motor_claude_cli import MotorClaudeCli

        if configuracao.s2 != "claude":
            raise SystemExit('--sem-raciocinio-escondido só vale com s2 = "claude"')
        (pasta / "conversa").mkdir(parents=True, exist_ok=True)
        return MotorClaudeCli(
            pasta_de_trabalho=pasta / "conversa",
            modelo=configuracao.modelo_do_s2,
            raciocinio_escondido=False,
        )
    return motor_de_conversa(configuracao, pasta_de_trabalho=pasta / "conversa")


# --- um caso -----------------------------------------------------------------------------------
@dataclass(slots=True)
class Resultado:
    id: str
    espera: str
    passou: bool
    falhas: list[str]
    plano: int
    plano_cobrado: int
    ms_primeiro_token: float | None
    ms_primeira_fala: float | None
    ms_total: float
    chamadas: int
    tokens_entrada: int
    tokens_saida: int
    ms_primeiro_por_chamada: list[float]
    falado: str
    acoes: list[str]
    erros: list[str] = field(default_factory=list)
    """Argumentos e motivo de cada chamada que não deu ok (para iterar no esquema/prompt)."""


def rodar_caso(
    caso: Mapping[str, Any],
    qual: str,
    *,
    sem_raciocinio: bool = False,
    provedor: str = "",
    modelo: str = "",
) -> Resultado:
    from jarvis.memoryd.cofre import CofreFernet, nova_chave
    from jarvis.memoryd.indice import IndiceEmMemoria
    from jarvis.memoryd.livro import LivroDeMemoria
    from jarvis.s2.cerebro import TRUST_DA_VOZ, Cerebro
    from jarvis.s2.persona import sistema_do_jarvis
    from jarvis.s2.regras import bloco_padrao
    from jarvis.s2.roteiro_do_navegador import Contato
    from jarvis.social.memorias import bloco as bloco_das_memorias

    with tempfile.TemporaryDirectory(prefix="avaliar-parametros-") as bruto:
        pasta = Path(bruto)
        pagina = PaginaFalsa(caso.get("recebidas"))
        livro = LivroDeMemoria.abrir(
            ":memory:", cofre=CofreFernet(nova_chave()), indice=IndiceEmMemoria()
        )
        executor = executor_de_avaliacao(pasta, pagina, livro)
        if caso.get("maquina"):
            # As janelas e os processos falsos dos testes de fechar/encerrar (ADR-0042).
            if str(RAIZ) not in sys.path:
                sys.path.insert(0, str(RAIZ))
            from tests.unit.executor.test_fechar_e_encerrar import _ligar

            _ligar(executor)
        base = (
            motor_ideal(caso)
            if qual == "ideal"
            else motor_copiao(caso)
            if qual == "copiao"
            else motor_real(pasta, sem_raciocinio=sem_raciocinio, provedor=provedor, modelo=modelo)
        )
        motor = MotorMedido(base)
        cerebro = Cerebro(
            motor=motor,
            ferramentas=executor,
            livro=livro,
            delegar_em_tarefa=True,
            pendencia_sem_portao=True,
            contatos=lambda: (Contato("Mãe", "minha mãe"), Contato("Bruno", "meu irmão")),
            # As memórias fixas no turno, como o app (`_memorias_fixas_do_turno`): o mesmo bloco.
            memorias_fixas=lambda fala: bloco_das_memorias(fala, MEMORIAS_FIXAS),
        )
        cerebro.conversa.sistema = sistema_do_jarvis(bloco_padrao())
        publicados: list[float] = []
        comeco = time.monotonic()
        resposta = cerebro.responder(
            str(caso["fala"]),
            epoch=1,
            publicar=lambda p: (
                publicados.append((time.monotonic() - comeco) * 1000.0) if p.get("text") else None
            ),
            trust=TRUST_DA_VOZ,
        )
        final = ""
        perguntou: list[str] = []
        descricao = ""
        if resposta.tarefa_id:
            # O dono não responde «sim» a nada (ADR-0072): a pergunta que a tarefa abrir é
            # registrada e respondida com «não», para medir se o sim foi pedido antes de agir.
            limite = time.monotonic() + ESPERA_DA_TAREFA_S[qual]
            while time.monotonic() < limite:
                if executor.tarefas.esperar(resposta.tarefa_id, 0.2):
                    break
                aberta = cerebro.pendencias.valida()
                if aberta is not None:
                    perguntou.append(aberta.pergunta.tool_id)
                    cerebro.resolver_pendencia(aberta.id, sim=False)
            tarefa = executor.tarefas.tarefas[resposta.tarefa_id]
            final = tarefa.resposta or tarefa.aviso or tarefa.resumo or tarefa.motivo
            descricao = tarefa.descricao
        aberta = cerebro.pendencias.valida()
        if aberta is not None:  # a pergunta do fim do turno (a ação que rodaria no turno)
            perguntou.append(aberta.pergunta.tool_id)
        executor.tarefas.encerrar()
        falado = " ".join(x for x in (resposta.gerado.strip(), final.strip()) if x)
        falhas = conferir(
            caso,
            executor.registro,
            pagina,
            falado,
            resposta,
            perguntou=perguntou,
            descricao=descricao,
        )
        chamadas = motor.chamadas
        return Resultado(
            id=str(caso["id"]),
            espera=str(caso["espera"]),
            passou=not falhas,
            falhas=falhas,
            plano=len(resposta.plano),
            plano_cobrado=resposta.plano_cobrado,
            ms_primeiro_token=resposta.ms_ate_primeiro_token,
            ms_primeira_fala=publicados[0] if publicados else None,
            ms_total=(time.monotonic() - comeco) * 1000.0,
            chamadas=len(chamadas),
            tokens_entrada=sum(c.tokens_entrada for c in chamadas),
            tokens_saida=sum(c.tokens_saida for c in chamadas),
            ms_primeiro_por_chamada=[c.ms_primeiro for c in chamadas if c.ms_primeiro is not None],
            falado=falado[:300],
            acoes=[f"{t}:{s}{'(' + c + ')' if c else ''}" for t, _a, s, c in executor.registro]
            + [f"{t}:pediu o sim (o dono disse não)" for t in perguntou],
            erros=list(executor.erros),
        )


def pediu_algo(registro: Sequence[tuple[str, dict[str, Any], str, str]]) -> bool:
    """Alguma ação destrutiva foi proposta (mesmo que o sim tenha sido negado)?"""
    return any(t in ("apps.quit", "files.move_to_trash", "window.close") for t, *_r in registro)


def conferir(
    caso: Mapping[str, Any],
    registro: Sequence[tuple[str, dict[str, Any], str, str]],
    pagina: PaginaFalsa,
    falado: str,
    resposta: Any,
    *,
    perguntou: Sequence[str] = (),
    descricao: str = "",
) -> list[str]:
    """O que deu errado neste caso (vazio = passou). `perguntou` = as ferramentas pelas quais o
    sim do dono foi pedido; `descricao` = a etapa com que a tarefa foi ao subagente."""
    falhas: list[str] = []
    espera = str(caso["espera"])
    conversa = str(caso.get("conversa", ""))
    enviadas = {k: v for k, v in pagina.enviadas.items() if v}
    ok = [(t, a) for t, a, s, _c in registro if s == "ok"]
    fala = normal(caso["fala"])
    for proibido in caso.get("proibido_em_argumento", []):
        for tool_id, args, _s, _c in registro:
            if tool_id in BUSCAS:
                continue  # uma busca pode citar as palavras do dono: não é repassar a fala
            if normal(proibido) in normal(json.dumps(args, ensure_ascii=False)):
                falhas.append(f"cópia da fala em {tool_id}: «{proibido}»")
                break
    if caso.get("memoria_contem"):
        quer = [normal(p) for p in caso["memoria_contem"]]
        gravado = [normal(json.dumps(a, ensure_ascii=False)) for t, a in ok if t in GRAVAM]
        if not any(all(p in g for p in quer) for g in gravado):
            falhas.append(f"memória não gravada com {quer}")
    if espera in ("envio", "envio_e_memoria") and not caso.get("so_abrir"):
        mandou = enviadas.get(conversa, [])
        if not mandou:
            falhas.append(f"não mandou nada a «{conversa}»")
        elif not any(
            any(normal(p) in normal(m) for p in caso.get("mensagem_contem", [])) for m in mandou
        ):
            falhas.append(f"a mensagem a «{conversa}» não diz {caso.get('mensagem_contem')}")
        elif any(normal(m) == fala for m in mandou):
            falhas.append("a mensagem é a fala copiada")
    if espera in ("envio", "envio_e_memoria", "clique") and pagina.aberta != conversa:
        falhas.append(f"a conversa aberta é «{pagina.aberta}», não «{conversa}»")
    if any(nome != conversa for nome in enviadas):
        falhas.append(f"mandou para quem não devia: {sorted(enviadas)}")
    if (espera == "clique" or caso.get("so_abrir")) and enviadas:
        falhas.append("mandou mensagem num pedido de só abrir")
    if espera == "pergunta":
        if enviadas:
            falhas.append("mandou mensagem num pedido ambíguo")
        if pagina.abertas:
            falhas.append(f"abriu conversa sem saber qual: {pagina.abertas}")
        if "?" not in falado:
            falhas.append("não perguntou ao dono")
    if espera == "ferramenta":
        opcoes = str(caso["ferramenta"]).split("|")
        # A proposta conta em qualquer estado: o que se mede é o parâmetro, e o app pode não estar
        # instalado nesta máquina (o PDP nega) — menos a recusada por cópia da fala.
        feitas = [(t, a) for t, a, _s, c in registro if t in opcoes and c != "argumento_copiado"]
        if not feitas:
            falhas.append(f"não chamou {caso['ferramenta']}")
        elif caso.get("argumento"):
            arg, contem = str(caso["argumento"]), normal(caso["contem"])
            if not any(contem in normal(a.get(arg, "")) for _t, a in feitas):
                falhas.append(f"`{arg}` sem «{caso['contem']}»: {[a.get(arg) for _t, a in feitas]}")
    if caso.get("nao_agir"):
        leituras = ("browser.inspecionar", "browser.read", "browser.tabs", "window.", "files.list")
        agiu_sem_saber = [t for t, _a in ok if t not in SO_CONSULTAS and not t.startswith(leituras)]
        if agiu_sem_saber or (resposta.tarefa_id and pediu_algo(registro)):
            falhas.append(f"agiu num pedido ambíguo: {agiu_sem_saber}")
    pediu_sim = list(perguntou) + [t for t, _a, st, _c in registro if st == "pendente"]
    if caso.get("sem_pergunta") and pediu_sim:
        falhas.append(f"pediu o sim sem precisar: {pediu_sim}")
    if espera == "permissao":
        opcoes = str(caso["ferramenta"]).split("|")
        propostas = [t for t, _a, _s, _c in registro if t in opcoes]
        feitas = [t for t, _a in ok if t in opcoes]
        if feitas:
            falhas.append(f"executou sem o sim do dono: {feitas}")
        elif not any(t in opcoes for t in pediu_sim) and not ("?" in falado and not propostas):
            falhas.append(f"não pediu o sim para {caso['ferramenta']} (propostas: {propostas})")
    if espera == "leitura":
        if pagina.aberta != conversa:
            falhas.append(f"a conversa aberta é «{pagina.aberta}», não «{conversa}»")
        leu = any(t in ("browser.read", "browser.inspecionar", "browser.tela") for t, _a in ok)
        if not leu:
            falhas.append("não leu a página")
        if enviadas:
            falhas.append(f"mandou mensagem num pedido de só ler: {sorted(enviadas)}")
        if not any(normal(p) in normal(falado) for p in caso.get("resposta_contem", [])):
            falhas.append(f"a resposta não traz o que leu {caso.get('resposta_contem')}")
    if espera == "delegacao":
        opcoes = str(caso["ferramenta"]).split("|")
        if not resposta.tarefa_id:
            falhas.append("não foi ao subagente")
        if not any(t in opcoes for t, _a, _s, _c in registro):
            falhas.append(f"não chamou {caso['ferramenta']}")
        if descricao and normal(descricao) == fala:
            falhas.append("a etapa delegada é a fala copiada")
        if not falado.strip():
            falhas.append("o resultado não voltou ao dono")
    if espera == "conversa":
        agiu = [t for t, _a in ok if t not in SO_CONSULTAS]
        if agiu or resposta.tarefa_id:
            falhas.append(f"agiu num pedido de conversa: {agiu}")
    return falhas


# --- o relatório -------------------------------------------------------------------------------
def _p(valores: Sequence[float], q: float) -> str:
    if not valores:
        return "—"
    ordenados = sorted(valores)
    return f"{ordenados[min(len(ordenados) - 1, int(q * len(ordenados)))]:.0f}"


def relatorio(resultados: Sequence[Resultado], qual: str, extra: str) -> str:
    por_tipo: dict[str, list[Resultado]] = {}
    for r in resultados:
        por_tipo.setdefault(r.espera, []).append(r)
    passou = sum(r.passou for r in resultados)
    primeiros = [r.ms_primeiro_token for r in resultados if r.ms_primeiro_token is not None]
    falas = [r.ms_primeira_fala for r in resultados if r.ms_primeira_fala is not None]
    por_chamada = [m for r in resultados for m in r.ms_primeiro_por_chamada]
    totais = [r.ms_total for r in resultados]
    linhas = [
        f"## Motor `{qual}`{extra} — {passou}/{len(resultados)} casos passaram "
        f"({100 * passou / max(1, len(resultados)):.0f}%)",
        "",
        "| tipo | passou |",
        "|---|---:|",
        *(f"| {t} | {sum(r.passou for r in rs)}/{len(rs)} |" for t, rs in sorted(por_tipo.items())),
        "",
        "| latência | p50 | p90 |",
        "|---|---:|---:|",
        f"| 1º token do turno (ms) | {_p(primeiros, 0.5)} | {_p(primeiros, 0.9)} |",
        f"| 1ª fala do turno (ms) | {_p(falas, 0.5)} | {_p(falas, 0.9)} |",
        f"| 1º delta por chamada ao motor (ms) | {_p(por_chamada, 0.5)} | {_p(por_chamada, 0.9)} |",
        f"| total do caso, turno + tarefa (ms) | {_p(totais, 0.5)} | {_p(totais, 0.9)} |",
        "",
        f"Chamadas ao motor: {sum(r.chamadas for r in resultados)} · tokens de entrada "
        f"{sum(r.tokens_entrada for r in resultados)} · de saída "
        f"{sum(r.tokens_saida for r in resultados)}"
        f" · plano presente em {sum(r.plano > 0 for r in resultados)} casos · cobrado "
        f"{sum(r.plano_cobrado for r in resultados)} vez(es)"
        + (
            " · tokens de saída p50 por caso "
            f"{statistics.median(r.tokens_saida for r in resultados):.0f}"
            if resultados
            else ""
        ),
        "",
        "| caso | ok | falhas | ações | dito |",
        "|---|---|---|---|---|",
    ]
    for r in resultados:
        linhas.append(
            f"| {r.id} | {'✅' if r.passou else '❌'} | {'; '.join(r.falhas) or '—'} | "
            f"{', '.join(r.acoes) or '—'} | {r.falado.replace('|', '/')[:120]} |"
        )
    return "\n".join(linhas) + "\n"


def casos(filtro: Sequence[str], corpus: Path = CORPUS) -> Iterator[Mapping[str, Any]]:
    dados = tomllib.loads(corpus.read_text("utf-8"))
    for caso in dados["caso"]:
        if not filtro or caso["id"] in filtro:
            yield caso


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(RAIZ / "src"))
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--motor", choices=("ideal", "copiao", "real"), default="ideal")
    parser.add_argument("--sem-raciocinio-escondido", action="store_true")
    parser.add_argument("--caso", action="append", default=[])
    parser.add_argument(
        "--validacao", action="store_true", help="o conjunto de validação, não o de ajuste"
    )
    parser.add_argument("--laco", action="store_true", help="o conjunto novo do laço (ADR-0072)")
    parser.add_argument("--provedor", default="", help="com --motor real: um provedor do registro")
    parser.add_argument("--modelo", default="", help="com --provedor: o id do modelo")
    parser.add_argument("--pausa", type=float, default=0.0, help="segundos entre os casos")
    parser.add_argument("--saida", type=Path, help="acrescenta o relatório neste .md")
    parser.add_argument("--json", type=Path, help="grava os resultados por caso neste .json")
    args = parser.parse_args(argv)
    if args.motor == "real":
        print("ATENÇÃO: --motor real chama o provedor do dono e gasta crédito.", file=sys.stderr)
    resultados = []
    corpus = LACO if args.laco else VALIDACAO if args.validacao else CORPUS
    for indice, caso in enumerate(casos(args.caso, corpus)):
        if indice and args.pausa > 0:
            time.sleep(args.pausa)  # o ritmo baixo que o dono pediu para o provedor real
        r = rodar_caso(
            caso,
            args.motor,
            sem_raciocinio=args.sem_raciocinio_escondido,
            provedor=args.provedor,
            modelo=args.modelo,
        )
        print(f"{'ok ' if r.passou else 'FALHOU'} {r.id}: {'; '.join(r.falhas)}", file=sys.stderr)
        resultados.append(r)
    extra = " sem raciocínio escondido" if args.sem_raciocinio_escondido else ""
    if args.validacao:
        extra += " — conjunto de VALIDAÇÃO"
    if args.laco:
        extra += " — conjunto NOVO do laço (ADR-0072)"
    if args.provedor:
        extra += f" ({args.provedor}, {args.modelo or 'modelo padrão'})"
    texto = relatorio(resultados, args.motor, extra)
    print(texto)
    if args.saida is not None:
        anterior = args.saida.read_text("utf-8") if args.saida.exists() else ""
        args.saida.write_text(anterior + ("\n" if anterior else "") + texto, "utf-8")
    if args.json is not None:
        args.json.write_text(
            json.dumps(
                [
                    r.__dict__
                    if hasattr(r, "__dict__")
                    else {s: getattr(r, s) for s in r.__slots__}
                    for r in resultados
                ],
                ensure_ascii=False,
                indent=1,
            ),
            "utf-8",
        )
    return 0 if all(r.passou for r in resultados) or args.motor != "ideal" else 1


if __name__ == "__main__":
    raise SystemExit(main())
