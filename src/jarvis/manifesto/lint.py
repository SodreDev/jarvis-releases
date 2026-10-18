"""Lint de catálogo: as regras da §4 e da ADR-0010 em forma executável (cartão F0-07).

O que o lint recusa, e por quê:

* **id de canivete suíço** (`*.run_command`, `*.do_anything`, `*.exec`, `shell.*`…): a §4
  proíbe tool cujo poder depende do texto que o modelo escreve;
* **promoção de MCP sem política nossa**: `risk_class`, `confirmation`, `data_egress` e
  `access_level_min` são nossos (ADR-0010 item 5), e `shell_exec`/`ssh_exec`/`cli_send` são
  proibidos de promover (item 8) — a proibição não se contorna chamando por MCP;
* **catálogo largo demais**: mais de 10 tools por namespace ou mais de 12 por turno (§4);
* **descrição que não passa no teste do estagiário**: sem dizer quando usar e o que não faz.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from jarvis.manifesto.validador import (
    IDS_PROIBIDOS,
    PASTA_CATALOGO,
    TETO_POR_NAMESPACE,
    TOOLS_PROIBIDAS_DE_PROMOVER,
    ManifestoInvalido,
    carregar_manifesto,
)

PADROES_PROIBIDOS: Final[tuple[re.Pattern[str], ...]] = tuple(re.compile(p) for p in IDS_PROIBIDOS)
PALAVRAS_DE_CANIVETE: Final[tuple[str, ...]] = (
    "qualquer comando",
    "comando arbitrário",
    "linha de comando",
    "shell",
    "argv livre",
    "o que o usuário pedir",
)
PADRAO_DE_AUTOCONFIRMACAO: Final = re.compile(
    r"confirm|autoriz|aprov|forc[ae]|sudo|bypass|sem_pergunt|pular|override|permiss", re.IGNORECASE
)
"""Nome de argumento que parece dar ao **modelo** o poder de se autorizar. A confirmação do dono é
um parâmetro do executor, preenchido só depois do "sim" na janela — nenhuma tool o recebe."""
CAMPOS_DE_POLITICA_NOSSOS: Final[tuple[str, ...]] = (
    "risk_class",
    "confirmation",
    "data_egress",
    "access_level_min",
)


@dataclass(frozen=True, slots=True)
class Achado:
    """Um problema de catálogo. `regra` é o que citar na revisão."""

    arquivo: str
    id: str
    regra: str
    mensagem: str

    def __str__(self) -> str:
        return f"{self.arquivo} [{self.regra}] {self.id}: {self.mensagem}"


def lintar_manifesto(manifesto: dict[str, Any], arquivo: str) -> list[Achado]:
    identificador = str(manifesto["id"])
    achados: list[Achado] = []

    for padrao in PADROES_PROIBIDOS:
        if padrao.search(identificador):
            achados.append(
                Achado(
                    arquivo,
                    identificador,
                    "canivete-suico",
                    f"id casa com padrão proibido {padrao.pattern!r} (§4)",
                )
            )
    descricao = str(manifesto["description"]).casefold()
    for palavra in PALAVRAS_DE_CANIVETE:
        if palavra in descricao and "nunca" not in descricao and "não" not in descricao:
            achados.append(
                Achado(
                    arquivo,
                    identificador,
                    "canivete-suico",
                    f"descrição promete {palavra!r} (§4: abrir app é tipado, não linha de comando)",
                )
            )
    if len(descricao.split()) < 15 or ("não" not in descricao and "nunca" not in descricao):
        achados.append(
            Achado(
                arquivo,
                identificador,
                "teste-do-estagiario",
                "descrição precisa dizer quando usar E o que a tool não faz (§4)",
            )
        )

    for nome in manifesto["input_schema"].get("properties", {}):
        if PADRAO_DE_AUTOCONFIRMACAO.search(str(nome)):
            achados.append(
                Achado(
                    arquivo,
                    identificador,
                    "autoconfirmacao",
                    f"argumento {nome!r} parece deixar o modelo confirmar ou contornar a política: "
                    "só o dono confirma, na janela",
                )
            )

    origem = manifesto.get("mcp_origin")
    if origem is not None:
        achados += _lintar_promocao_mcp(manifesto, origem, arquivo, identificador)

    return achados


def _lintar_promocao_mcp(
    manifesto: dict[str, Any], origem: dict[str, Any], arquivo: str, identificador: str
) -> list[Achado]:
    """ADR-0010 itens 5 e 8: promoção precisa de política nossa e tem lista de proibidas."""
    achados: list[Achado] = []
    remota = str(origem.get("remote_tool", ""))
    if remota in TOOLS_PROIBIDAS_DE_PROMOVER:
        achados.append(
            Achado(
                arquivo,
                identificador,
                "mcp-proibida",
                f"{remota!r} é proibida de promover (ADR-0010 item 8): a proibição de "
                "canivete suíço não se contorna chamando por MCP",
            )
        )
    anotacao = origem.get("anotacao_do_servidor", {})
    if isinstance(anotacao, dict):
        for campo in CAMPOS_DE_POLITICA_NOSSOS:
            if campo in anotacao:
                achados.append(
                    Achado(
                        arquivo,
                        identificador,
                        "mcp-politica-remota",
                        f"a anotação do servidor traz {campo!r}: política é nossa, a anotação "
                        "entra como comentário (ADR-0010 item 5)",
                    )
                )
    if str(manifesto.get("trust_input")) != "untrusted":
        achados.append(
            Achado(arquivo, identificador, "mcp-trust", "saída de MCP é sempre untrusted (item 7)")
        )
    if manifesto.get("risk_class") == "leitura" and str(manifesto["data_egress"]).startswith(
        "network:"
    ):
        achados.append(
            Achado(
                arquivo,
                identificador,
                "mcp-egress",
                "tool remota com egress de rede não é 'leitura' (item 9)",
            )
        )
    return achados


def lintar_catalogo(pasta: Path = PASTA_CATALOGO) -> list[Achado]:
    """Lint do catálogo inteiro: por manifesto e as regras que só existem no conjunto."""
    achados: list[Achado] = []
    manifestos: dict[str, dict[str, Any]] = {}
    for arquivo in sorted(pasta.glob("*.yaml")):
        try:
            manifesto = carregar_manifesto(arquivo)
        except ManifestoInvalido as erro:
            achados.append(Achado(arquivo.name, "?", "invalido", str(erro)))
            continue
        manifestos[str(manifesto["id"])] = manifesto
        achados += lintar_manifesto(manifesto, arquivo.name)

    por_namespace: dict[str, int] = {}
    for identificador in manifestos:
        namespace = identificador.split(".")[0]
        por_namespace[namespace] = por_namespace.get(namespace, 0) + 1
    for namespace, quantas in sorted(por_namespace.items()):
        if quantas > TETO_POR_NAMESPACE:
            achados.append(
                Achado(
                    "(catálogo)",
                    namespace,
                    "catalogo-largo",
                    f"{quantas} tools no namespace {namespace!r}, teto é {TETO_POR_NAMESPACE} (§4)",
                )
            )

    # P12: nenhuma capacidade mexe em nível de acesso ou elevação (varredura do catálogo).
    for identificador, manifesto in manifestos.items():
        alvo = " ".join(
            [identificador, str(manifesto["capability"]), str(manifesto["title"])]
        ).casefold()
        if any(p in alvo for p in ("access_level", "nivel_de_acesso", "elevation", "elevacao")):
            achados.append(
                Achado(
                    f"{identificador}.yaml",
                    identificador,
                    "controle-de-acesso",
                    "nenhuma capacidade muda nível ou elevação (P12, §5.5)",
                )
            )
    return achados
