"""Mede o prompt de sistema de um turno: persona, regras do dono e catálogo de ferramentas.

Uso (sem rede, sem o desktop do dono):

    uv run --frozen python -m tools.medir_prompt [--antes ARQUIVO_DA_PERSONA_ANTIGA] [--saida MD]

Monta um executor com todas as famílias de ferramenta ligadas (como numa sessão com navegador,
memória, tarefas, vocabulário e encerrar) e mede, em caracteres e em tokens, cada bloco do prompt
de sistema que vai ao motor em **todo** turno
(`jarvis.s2.motor_claude_cli.sistema_com_ferramentas`).
Os tokens são contados com o tokenizador do embedding da memória (multilingual-e5-small, o mesmo
SentencePiece do XLM-R, que fica no cache do Jarvis) — é uma aproximação: o tokenizador do Claude
não é público; a razão caracteres/token do português nele fica perto de 3,5–4. O dono julga a
latência do primeiro token (ADR-0045): o que cresce aqui cresce em cada pedido.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

RAIZ: Final = Path(__file__).resolve().parent.parent
TOKENIZADOR: Final = (
    Path.home()
    / ".cache"
    / "jarvis"
    / "modelos"
    / "intfloat--multilingual-e5-small"
    / "tokenizer.json"
)


@dataclass(frozen=True, slots=True)
class Bloco:
    nome: str
    texto: str


def contador() -> Callable[[str], int | None]:
    """Conta tokens com o tokenizador do e5, se ele estiver no cache; senão, `None`."""
    try:
        from tokenizers import Tokenizer
    except ImportError:
        return lambda _texto: None
    if not TOKENIZADOR.exists():
        return lambda _texto: None
    tokenizador = Tokenizer.from_file(str(TOKENIZADOR))
    return lambda texto: len(tokenizador.encode(texto, add_special_tokens=False).ids)


def executor_completo(pasta: Path) -> Any:
    """Um executor com as famílias ligadas: o que `_ligada` olha é só se a porta existe."""
    from jarvis.executor.ferramentas import Encerramento, ExecutorDeFerramentas
    from jarvis.executor.navegadores import AbridorDeNavegador
    from jarvis.navegador.cliente import ClienteDoNavegador
    from jarvis.navegador.ferramentas import CorposDoNavegador
    from jarvis.politica.auditoria import LogDeAuditoria
    from jarvis.politica.catalogo import carregar_catalogo
    from jarvis.politica.modos import Modo
    from jarvis.politica.pdp import Pdp

    lar = pasta / "casa"
    lar.mkdir(parents=True, exist_ok=True)
    auditoria = LogDeAuditoria(pasta / "auditoria.sqlite")
    pdp = Pdp(
        catalogo=carregar_catalogo(),
        lar=lar,
        auditoria=auditoria,
        modo=Modo.PADRAO,
        pasta_do_jarvis=pasta / "area",
        navegadores=frozenset({"brave"}),
        navegador_principal="brave",
    )
    sentinela = cast(Any, object())
    executor = ExecutorDeFerramentas(
        pdp=pdp,
        lar=lar,
        navegador=CorposDoNavegador(ClienteDoNavegador(sentinela)),
        navegadores=AbridorDeNavegador(navegadores={"brave": "/usr/bin/true"}, principal="brave"),
        estado_do_navegador=lambda: sentinela,
        encerramento=Encerramento(pendente=lambda: "", pedir=lambda: 0),
        motor_ve_imagem=lambda: True,
    )
    executor.memoria = sentinela
    executor.tarefas = sentinela
    executor.vocabulario = sentinela
    executor.entrada = sentinela
    executor.portas().agenda = sentinela
    executor.portas().tela = sentinela  # a janela aberta: as `tela.*` (ADR-0055)
    return executor


def blocos_da_tela(executor: Any) -> list[Bloco]:
    """O custo da tela do Jarvis (ADR-0055): as linhas das `tela.*` no catálogo (em todo turno com a
    janela aberta), o guia de design (só no turno que monta ou muda a tela) e a linha de estado
    (com uma exibição aberta)."""
    from jarvis.s2.motor_claude_cli import linha_da_ferramenta
    from jarvis.tela import PortaDaTela
    from jarvis.tela.guia import GUIA_DE_DESIGN, nota_da_tela

    linhas = [
        linha_da_ferramenta(f)
        for f in executor.catalogo_para_o_modelo()
        if str(f["id"]).startswith("tela.")
    ]
    porta = PortaDaTela(ao_mostrar=lambda _e: None, ao_fechar=lambda _i: None)
    porta.mostrar("<p>x</p>", identificador="compras")
    return [
        Bloco(
            f"catálogo: as {len(linhas)} linhas tela.* (todo turno, com a janela)",
            "\n".join(linhas),
        ),
        Bloco("guia de design (só no turno da tela)", GUIA_DE_DESIGN),
        Bloco(
            "linha das exibições abertas (com uma aberta)",
            nota_da_tela("e amanhã?", "", porta.abertas()),
        ),
    ]


INSTRUCAO_ANTIGA: Final = (
    "Você pode PROPOR ferramentas; quem decide se roda é o código do Jarvis. As simples rodam na "
    "hora; as pequenas e desfazíveis rodam e o Jarvis já avisa o dono em voz (o resultado traz "
    "`aviso_ao_dono`: não repita); só as perigosas pedem a confirmação do dono na tela. Para "
    "propor, responda com uma linha que começa exatamente com <<ferramenta>> seguida de um JSON "
    '{"tool_id": "...", "args": {...}} — uma linha por chamada, sem markdown, sem explicar o '
    'JSON. Antes da primeira ferramenta do pedido você pode dizer uma frase curta ("vou ver"), '
    "uma vez só; entre um passo e outro, nada em voz. O que for raciocínio (plano, o que "
    "conferir, o próximo passo) vai entre <<pensar>> e <</pensar>>: o dono não ouve nem vê, e ele "
    "volta para você no passo seguinte. Depois você recebe os resultados e, quando o pedido "
    "estiver pronto, responde ao dono, em voz, curto. Use só as ferramentas da lista, só com os "
    "argumentos dela, e nunca invente resultado. Caminhos: sempre a pasta inteira "
    "(~/Documentos/...). Ferramentas disponíveis agora:"
)
"""A instrução do catálogo antes da ADR-0047 (commit 016c0a6), copiada só para medir o antes."""


def blocos_do_tom() -> list[Bloco]:
    """A nota do tom de voz (ADR-0058): só existe no turno fora do neutro — o comum é nenhuma."""
    from jarvis.voz.tom import Energia, Entonacao, Evento, Ritmo, Tom, Volume

    pergunta = Tom(entonacao=Entonacao.PERGUNTA, volume=Volume.BAIXO)
    tudo = Tom(
        volume=Volume.SUSSURRO,
        entonacao=Entonacao.PERGUNTA,
        evento=Evento.RISADA,
        ritmo=Ritmo.RAPIDO,
        energia=Energia.ALTA,
    )
    return [
        Bloco("nota do tom no turno neutro (o caso comum)", Tom().linha()),
        Bloco("nota do tom: entonação de pergunta e voz baixa", pergunta.linha()),
        Bloco("nota do tom: as cinco dimensões fora do neutro (o pior caso)", tudo.linha()),
    ]


def sistema_antigo(sistema: str, ferramentas: Any) -> str:
    """O catálogo antes da ADR-0047: a descrição curta e o esquema JSON de cada argumento."""
    import json

    from jarvis.s2.motor_claude_cli import _curta

    linhas = [sistema, INSTRUCAO_ANTIGA]
    for ferramenta in ferramentas:
        argumentos = json.dumps(ferramenta.get("argumentos", {}), ensure_ascii=False)
        pedidos = ferramenta.get("obrigatorios")
        obrigatorios = ", ".join(str(o) for o in pedidos) if isinstance(pedidos, list) else ""
        linhas.append(
            f"- {ferramenta['id']}: {_curta(str(ferramenta['descricao']))} "
            f"Argumentos: {argumentos}. Obrigatórios: {obrigatorios or 'nenhum'}."
        )
    return "\n".join(linhas)


def blocos(persona: str, regras: str, executor: Any, *, antigo: bool = False) -> list[Bloco]:
    from jarvis.s2.motor_claude_cli import sistema_com_ferramentas

    catalogo = executor.catalogo_para_o_modelo()
    montar = sistema_antigo if antigo else sistema_com_ferramentas
    com_tudo = montar(f"{persona}\n\n{regras}".strip(), catalogo)
    so_catalogo = com_tudo[len(f"{persona}\n\n{regras}".strip()) :]
    saida = [Bloco("persona", persona)]
    if regras:
        saida.append(Bloco("regras do dono", regras))
    saida += [Bloco(f"catálogo ({len(catalogo)} ferramentas)", so_catalogo)]
    saida.append(Bloco("total do prompt de sistema", com_tudo))
    return saida


def tabela(titulo: str, itens: list[Bloco], contar: Callable[[str], int | None]) -> list[str]:
    linhas = [f"### {titulo}", "", "| bloco | caracteres | tokens (e5) |", "|---|---:|---:|"]
    for bloco in itens:
        tokens = contar(bloco.texto)
        linhas.append(
            f"| {bloco.nome} | {len(bloco.texto)} | {tokens if tokens is not None else '—'} |"
        )
    return [*linhas, ""]


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(RAIZ / "src"))
    from jarvis.s2.persona import ler
    from jarvis.s2.regras import bloco_padrao

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--antes", type=Path, help="persona antiga (.md com o cabeçalho)")
    parser.add_argument("--saida", type=Path, help="escreve a tabela neste .md")
    args = parser.parse_args(argv)

    import tempfile

    contar = contador()
    linhas: list[str] = []
    with tempfile.TemporaryDirectory(prefix="medir-prompt-") as pasta:
        executor = executor_completo(Path(pasta))
        if args.antes is not None:
            antigo = ler(args.antes)
            linhas += tabela(
                f"antes (persona v{antigo.versao}, sem regras, catálogo com o esquema JSON)",
                blocos(antigo.texto, "", executor, antigo=True),
                contar,
            )
        persona = ler()
        linhas += tabela(
            f"agora (persona v{persona.versao}, regras padrão, catálogo gerado)",
            blocos(persona.texto, bloco_padrao(), executor),
            contar,
        )
        linhas += tabela("a tela do Jarvis (ADR-0055)", blocos_da_tela(executor), contar)
        linhas += tabela("o tom de voz do dono (ADR-0058)", blocos_do_tom(), contar)
    texto = "\n".join(linhas)
    print(texto)
    if args.saida is not None:
        args.saida.write_text(texto + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
