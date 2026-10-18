"""Uma chamada de ferramenta, do pedido do modelo ao resultado devolvido ao cérebro (ADR-0028).

O modelo **propõe** (`tool_id` + argumentos nomeados); daqui para baixo, só código decide:

1. a tool tem de estar no catálogo **ligado** (manifesto + corpo aqui) e na allowlist do modo;
2. os argumentos passam pelo `input_schema` inteiro do manifesto — campo a mais é recusa;
3. o **PDP** decide (`allow | confirm | deny`), com o caminho resolvido pelo código;
4. `confirm` vira um pedido à janela (`Confirmar`), que **bloqueia** até o dono responder ou o
   prazo acabar — e prazo vencido **nega**. Só um "sim" do dono faz o PDP decidir de novo com
   `confirmado_pelo_dono=True`; nada que o modelo escreva chega a esse parâmetro;
5. o corpo roda sobre a raiz aberta no grant, consultando o cancelamento;
6. o resultado vai para a auditoria e volta ao cérebro como **dado de terceiros**, truncado.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import jsonschema

from jarvis.barramento.envelope import uuid7
from jarvis.executor import arquivos
from jarvis.executor.lancador import App, AppRecusado, RegistroDeApps, lancar
from jarvis.executor.navegadores import AbridorDeNavegador
from jarvis.executor.sites import Abridor, UrlRecusada, abrir_pelo_portal, dominio, validar_url
from jarvis.manifesto.validador import carregar_catalogo
from jarvis.memoryd.ferramentas import Chamada, FerramentasDeMemoria, NaoAutorizado
from jarvis.memoryd.livro import AlvoInexistente
from jarvis.politica.canonicalizacao import CaminhoRecusado, Sistema, canonicalizar
from jarvis.politica.descritor import AberturaRecusada, RaizAberta, abrir_raiz
from jarvis.politica.memoria import Proveniencia
from jarvis.politica.pdp import Decisao, Grant, Pdp, Pedido, Veredito
from jarvis.voz.interface import Onde

PRAZO_DE_CONFIRMACAO_S: Final = 30.0
LIMITE_PARA_O_MODELO: Final = 6000
"""Caracteres do resultado que voltam ao contexto do motor: o resto fica na auditoria."""
FERRAMENTAS_LIGADAS: Final = frozenset(
    {
        "files.list_dir",
        "files.read_text",
        "files.search_in_roots",
        "files.write_draft",
        "calendar.create_draft_event",
        "apps.launch",
        "sites.open",
        "browser.launch",
    }
)
"""As que têm corpo aqui. Manifesto sem corpo (lixeira, instalar) não aparece para o modelo."""
FERRAMENTAS_DE_MEMORIA: Final = frozenset(
    {
        "memoria.buscar",
        "memoria.buscar_historico",
        "memoria.ler_mensagem",
        "memoria.lembrar",
        "memoria.atualizar",
        "memoria.criar_no",
        "memoria.criar_aresta",
        "memoria.retratar",
        "memoria.apagar",
    }
)
"""As `memoria.*` (ADR-0026): o corpo é do `FerramentasDeMemoria`, e só existem para o modelo
quando há livro aberto (o histórico persistente) — sem ele, a persona não promete o que não há."""

Cancelado = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class Confirmacao:
    """O que a janela mostra ao dono. Texto puro, montado pelo código a partir dos argumentos."""

    id: str
    tool_id: str
    titulo: str
    detalhe: str
    motivo: str
    prazo_s: float


Confirmar = Callable[[Confirmacao], bool]
"""Bloqueia até o dono responder na janela. `False` também quando o prazo vence."""


def negar_sempre(_confirmacao: Confirmacao) -> bool:
    """Sem janela para perguntar, a resposta é não (P9: degradar, não improvisar)."""
    return False


@dataclass(frozen=True, slots=True)
class ResultadoDeFerramenta:
    tool_id: str
    status: str
    """`ok`, `negado`, `erro` ou `cancelado`."""
    dados: Mapping[str, Any] = field(default_factory=dict)
    motivo: str = ""
    call_id: str = ""

    def para_o_modelo(self) -> str:
        corpo: dict[str, Any] = {"tool_id": self.tool_id, "status": self.status}
        if self.motivo:
            corpo["motivo"] = self.motivo
        if self.dados:
            corpo["dados"] = self.dados
        texto = json.dumps(corpo, ensure_ascii=False)
        if len(texto) > LIMITE_PARA_O_MODELO:
            texto = texto[:LIMITE_PARA_O_MODELO] + " …[truncado]"
        return texto


@dataclass(slots=True)
class ExecutorDeFerramentas:
    pdp: Pdp
    lar: Path
    registro_de_apps: RegistroDeApps = field(
        default_factory=lambda: RegistroDeApps(autorizados={}, instalados=frozenset())
    )
    abrir_site: Abridor = abrir_pelo_portal
    navegadores: AbridorDeNavegador | None = None
    """Os navegadores que o dono configurou. Sem principal (ou sem esta peça), o site abre pelo
    portal, no padrão do desktop — como antes."""
    lancar_app: Callable[[App], int] = lancar
    sistema: Sistema = Sistema.POSIX
    prazo_de_confirmacao_s: float = PRAZO_DE_CONFIRMACAO_S
    manifestos: dict[str, dict[str, Any]] = field(default_factory=carregar_catalogo)
    memoria: FerramentasDeMemoria | None = None
    """O livro do dono, quando há (a conversa persistente). Liga as `memoria.*` ao modelo."""
    destino_onde: Onde = Onde.LOCAL
    destino_motor: str = ""
    """Quem vai ler o resultado: o D20 filtra o que da memória pode ir para este motor."""

    @property
    def pasta_do_jarvis(self) -> Path:
        if self.pdp.pasta_do_jarvis is None:
            raise AberturaRecusada("o PDP não tem pasta do Jarvis configurada")
        return self.pdp.pasta_do_jarvis

    def preparar(self) -> None:
        """Cria as pastas de rascunho **antes** de qualquer pedido: é configuração, não efeito."""
        (self.pasta_do_jarvis / arquivos.PASTA_DE_AGENDA).mkdir(parents=True, exist_ok=True)

    def catalogo_para_o_modelo(self) -> tuple[dict[str, Any], ...]:
        """O catálogo pequeno e fixo do modo (braço C0 da ADR-0024): o que o motor pode propor."""
        return tuple(
            {
                "id": tool_id,
                "titulo": str(self.manifestos[tool_id]["title"]),
                "descricao": self._descricao(tool_id),
                "argumentos": self.manifestos[tool_id]["input_schema"].get("properties", {}),
                "obrigatorios": self.manifestos[tool_id]["input_schema"].get("required", []),
            }
            for tool_id in self.pdp.allowlist()
            if self._ligada(tool_id)
        )

    def _ligada(self, tool_id: str) -> bool:
        """Tem corpo aqui, manifesto no catálogo e (se for de memória) um livro aberto."""
        if tool_id not in self.manifestos:
            return False
        if tool_id in FERRAMENTAS_DE_MEMORIA:
            return self.memoria is not None
        return tool_id in FERRAMENTAS_LIGADAS

    def _descricao(self, tool_id: str) -> str:
        texto = " ".join(str(self.manifestos[tool_id]["description"]).split())
        if tool_id == "browser.launch" and self.navegadores is not None:
            feitos = ", ".join(
                f"{f} (principal)" if f == self.navegadores.principal else f
                for f in self.navegadores.familias()
            )
            return f"{texto} Configurados agora: {feitos or 'nenhum'}."
        if tool_id != "apps.launch":
            return texto
        nomes = ", ".join(a.nome for a in self.registro_de_apps.autorizados.values())
        # O modelo não adivinha o que está instalado: sem a lista, ele chuta "Dolphin".
        return f"{texto} Autorizados agora: {nomes or 'nenhum'}."

    # --- a chamada --------------------------------------------------------------------------
    def executar(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        *,
        cancelado: Cancelado,
        confirmar: Confirmar = negar_sempre,
        session_id: str = "",
        call_id: str = "",
        proveniencia: Proveniencia | None = None,
    ) -> ResultadoDeFerramenta:
        chamada = call_id or f"c-{uuid7()}"
        if not self._ligada(tool_id):
            return ResultadoDeFerramenta(
                tool_id,
                "negado",
                motivo="essa ferramenta não existe no catálogo ligado",
                call_id=chamada,
            )
        argumentos = dict(args)
        try:
            jsonschema.validate(argumentos, self.manifestos[tool_id]["input_schema"])
            caminho = self._caminho_para_o_pdp(tool_id, argumentos)
        except jsonschema.ValidationError as erro:
            return ResultadoDeFerramenta(
                tool_id,
                "erro",
                motivo=f"argumentos fora do contrato: {erro.message}",
                call_id=chamada,
            )
        except (ValueError, CaminhoRecusado) as erro:
            return ResultadoDeFerramenta(tool_id, "erro", motivo=str(erro), call_id=chamada)

        if tool_id == "apps.launch":
            # O PDP compara o nome com o registro do dono; o executor aceita "Brave" para
            # "Brave Web Browser". Sem alinhar, app marcado chamado por nome parcial era negado
            # (com a mensagem errada). Resolvido, o nome que a política vê é o do app marcado.
            # Fora do registro, o nome fica como veio: o PDP nega e a sugestão sai abaixo.
            with contextlib.suppress(AppRecusado):
                argumentos["nome"] = self.registro_de_apps.resolver(str(argumentos["nome"])).nome
        if tool_id == "browser.launch" and self.navegadores is not None:
            dito = str(argumentos.get("navegador", "")).strip()
            familia = self.navegadores.resolver(dito) if dito else None
            if familia is not None:  # «Brave» → a família configurada, que é o que o PDP conhece
                argumentos["navegador"] = familia
        pedido = Pedido(
            tool_id=tool_id,
            args=argumentos,
            caminho=caminho,
            session_id=session_id,
            call_id=chamada,
            proveniencia=proveniencia,
        )
        decisao = self.pdp.decidir(pedido)
        if decisao.veredito is Veredito.CONFIRM:
            pergunta = Confirmacao(
                id=chamada,
                tool_id=tool_id,
                titulo=str(self.manifestos[tool_id]["title"]),
                detalhe=self._detalhe(tool_id, argumentos),
                motivo=decisao.motivo,
                prazo_s=self.prazo_de_confirmacao_s,
            )
            if cancelado() or not confirmar(pergunta):
                self.pdp.auditoria.anexar_resultado(
                    decisao.decision_id, "negado", "dono não confirmou"
                )
                return ResultadoDeFerramenta(
                    tool_id,
                    "negado",
                    motivo="o dono não confirmou (negou, ou o prazo acabou)",
                    call_id=chamada,
                )
            decisao = self.pdp.decidir(pedido, confirmado_pelo_dono=True)
        if decisao.veredito is not Veredito.ALLOW or decisao.grant is None:
            motivo = decisao.motivo
            if tool_id == "apps.launch":
                motivo = self._sugestao_de_app(str(argumentos["nome"]), motivo)
            return ResultadoDeFerramenta(tool_id, "negado", motivo=motivo, call_id=chamada)
        resultado = self._rodar(
            tool_id, argumentos, decisao, caminho, cancelado, chamada, proveniencia
        )
        self.pdp.auditoria.anexar_resultado(decisao.decision_id, resultado.status, resultado.motivo)
        return resultado

    def _rodar(
        self,
        tool_id: str,
        args: dict[str, Any],
        decisao: Decisao,
        caminho: str | None,
        cancelado: Cancelado,
        chamada: str,
        proveniencia: Proveniencia | None = None,
    ) -> ResultadoDeFerramenta:
        if cancelado():
            return ResultadoDeFerramenta(
                tool_id, "cancelado", motivo="interrompido", call_id=chamada
            )
        assert decisao.grant is not None
        try:
            if tool_id in FERRAMENTAS_DE_MEMORIA:
                dados = self._memoria(tool_id, args, decisao, proveniencia)
            else:
                dados = self._corpo(tool_id, args, decisao.grant, caminho, cancelado)
        except arquivos.Cancelada as erro:
            return ResultadoDeFerramenta(tool_id, "cancelado", motivo=str(erro), call_id=chamada)
        except (
            AberturaRecusada,
            AlvoInexistente,
            NaoAutorizado,
            OSError,
            ValueError,
            AppRecusado,
            UrlRecusada,
        ) as erro:
            return ResultadoDeFerramenta(tool_id, "erro", motivo=str(erro), call_id=chamada)
        return ResultadoDeFerramenta(tool_id, "ok", dados=dados, call_id=chamada)

    def _memoria(
        self,
        tool_id: str,
        args: dict[str, Any],
        decisao: Decisao,
        proveniencia: Proveniencia | None,
    ) -> dict[str, Any]:
        """Corpo das `memoria.*`: aqui a decisão já é `allow` (se houve confirmação, foi do dono)."""
        assert self.memoria is not None
        return self.memoria.executar(
            Chamada(
                tool_id=tool_id,
                args=args,
                decisao=decisao,
                proveniencia=proveniencia,
                destino_onde=self.destino_onde,
                destino_motor=self.destino_motor,
            )
        )

    def _corpo(
        self,
        tool_id: str,
        args: dict[str, Any],
        grant: Grant,
        caminho: str | None,
        cancelado: Cancelado,
    ) -> dict[str, Any]:
        if tool_id == "files.search_in_roots":
            return self._procurar(str(args["consulta"]), cancelado)
        if tool_id == "apps.launch":
            app = self.registro_de_apps.resolver(str(args["nome"]))
            return {"app": app.nome, "pid": self.lancar_app(app)}
        if tool_id == "browser.launch":
            if self.navegadores is None or not self.navegadores.navegadores:
                raise AppRecusado(
                    "nenhum navegador configurado: escolha o principal em Configuração → "
                    "Navegadores"
                )
            familia, pid = self.navegadores.abrir_sozinho(str(args.get("navegador", "")).strip())
            return {"navegador": familia, "pid": pid}
        if tool_id == "sites.open":
            url = validar_url(str(args["url"]))
            pedido = str(args.get("navegador", "")).strip()
            if self.navegadores is not None and (self.navegadores.principal or pedido):
                usado = self.navegadores.abrir(url, pedido)
                return {"url": url, "dominio": dominio(url), "navegador": usado}
            self.abrir_site(url)
            return {"url": url, "dominio": dominio(url)}
        assert caminho is not None
        relativo = self._relativo(grant, caminho)
        raiz = self.pdp.abrir_para(grant, relativo)
        if tool_id == "files.list_dir":
            return arquivos.listar(raiz, relativo, lar=self.lar, sistema=self.sistema)
        if tool_id == "files.read_text":
            return arquivos.ler_texto(raiz, relativo)
        if tool_id == "files.write_draft":
            nome = arquivos.nome_de_rascunho(str(args["nome"]))
            return arquivos.gravar_rascunho(raiz, nome, str(args["texto"]), pasta=relativo)
        if tool_id == "calendar.create_draft_event":
            ics = arquivos.evento_ics(
                str(args["titulo"]),
                str(args["inicio"]),
                duracao_min=int(args.get("duracao_min", 60)),
                local=str(args.get("local", "")),
            )
            nome = arquivos.nome_de_rascunho(str(args["titulo"]), extensao_padrao=".md")
            nome = nome.rsplit(".", 1)[0] + ".ics"
            return arquivos.gravar_rascunho(raiz, nome, ics, pasta=relativo)
        raise ValueError(f"{tool_id} sem corpo")  # pragma: no cover — FERRAMENTAS_LIGADAS cobre

    # --- caminhos -----------------------------------------------------------------------------
    def _caminho_para_o_pdp(self, tool_id: str, args: Mapping[str, Any]) -> str | None:
        """O caminho que o PDP julga. Para escrita, quem escolhe é o código — o modelo não passa
        caminho nenhum; para leitura, o do modelo, com `~` resolvido e nada de relativo."""
        if tool_id == "files.write_draft":
            return str(self.pasta_do_jarvis / arquivos.PASTA_DE_RASCUNHOS)
        if tool_id == "calendar.create_draft_event":
            return str(self.pasta_do_jarvis / arquivos.PASTA_DE_AGENDA)
        if tool_id in ("files.list_dir", "files.read_text"):
            bruto = str(args["path"]).strip()
            if bruto == "~" or bruto.startswith("~/"):
                bruto = str(self.lar) + bruto[1:]
            if not Path(bruto).is_absolute():
                raise ValueError(
                    f"caminho relativo ({bruto!r}): diga a pasta inteira, por exemplo ~/Documentos"
                )
            return bruto
        return None

    def _relativo(self, grant: Grant, caminho: str) -> str:
        texto = canonicalizar(caminho, self.sistema).texto
        raiz = grant.raiz.rstrip("/")
        return texto[len(raiz) :].lstrip("/") or "."

    def _procurar(self, consulta: str, cancelado: Cancelado) -> dict[str, Any]:
        abertas: list[RaizAberta] = []
        try:
            for raiz in self.pdp.raizes():
                if not Path(raiz.caminho.texto).is_dir():
                    continue
                try:
                    abertas.append(abrir_raiz(Path(raiz.caminho.texto)))
                except AberturaRecusada:
                    continue
            return arquivos.procurar(
                abertas, consulta, lar=self.lar, sistema=self.sistema, cancelado=cancelado
            )
        finally:
            for aberta in abertas:
                aberta.fechar()

    # --- texto para o dono --------------------------------------------------------------------
    def _detalhe(self, tool_id: str, args: Mapping[str, Any]) -> str:
        if tool_id == "files.write_draft":
            palavras = len(str(args["texto"]).split())
            return f"gravar o rascunho «{args['nome']}» na pasta do Jarvis ({palavras} palavras)"
        if tool_id == "calendar.create_draft_event":
            return f"criar o rascunho de evento «{args['titulo']}» em {args['inicio']}, sem convite"
        if tool_id == "sites.open":
            onde = str(args.get("navegador", "")).strip()
            if not onde and self.navegadores is not None and self.navegadores.principal:
                onde = self.navegadores.principal
            return (
                f"abrir {dominio(str(args['url'])) or args['url']} no "
                f"{'navegador ' + onde if onde else 'seu navegador'}"
            )
        if tool_id == "apps.launch":
            return f"abrir o aplicativo «{args['nome']}»"
        if tool_id in FERRAMENTAS_DE_MEMORIA:
            return f"{self.manifestos[tool_id]['title'].lower()} ({_resumo(args)})"
        if tool_id == "browser.launch":
            return f"abrir o navegador «{args.get('navegador') or 'principal'}»"
        return f"{tool_id} com {json.dumps(dict(args), ensure_ascii=False)[:160]}"

    def _sugestao_de_app(self, nome: str, motivo: str) -> str:
        try:
            self.registro_de_apps.resolver(nome)
        except AppRecusado as erro:
            return str(erro)
        return motivo


def _resumo(args: Mapping[str, Any]) -> str:
    """Os argumentos em uma linha para o dono ler na confirmação (texto puro, truncado)."""
    return json.dumps(dict(args), ensure_ascii=False)[:160]
