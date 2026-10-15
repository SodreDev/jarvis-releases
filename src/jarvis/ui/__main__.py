"""O processo `ui` (SPEC §2): o que o dono vê e o que ele manda no microfone.

Duas responsabilidades, e nenhuma delas é decidir:

- **confirmação de risco alto** não é automática e nem por voz (SPEC §2): aqui o esqueleto
  registra o pedido, e quem confirma é o dono;
- **PTT, indicador e *kill switch*** (cartão F1-13): a `ui` escreve o que o dono pediu e mostra
  o que a fonte **está** fazendo — nunca o que ela mesma pediu. A regra e o porquê estão em
  `jarvis.ui.painel`.

O botão da tela, num esqueleto sem tela, é um arquivo: `ui-botao` com uma palavra
(`escuta`, `ptt` ou `desligado`). Não é atalho de teste nem porta de fundo — é o mesmo
mecanismo da pasta de sessão que o `pronto` e o `sessao` usam, e é o que deixa o cartão provar
o *kill switch* de fora do processo enquanto a tela de verdade não existe.
"""

from __future__ import annotations

import json
import sys

from jarvis.barramento.envelope import Envelope, Tipo
from jarvis.microfone import Modo
from jarvis.processo import Processo, analisador
from jarvis.relogio import RelogioDoSistema
from jarvis.ui.atalhos import atalho_do_ambiente
from jarvis.ui.painel import PainelDoMicrofone

ARQUIVO_BOTAO = "ui-botao"
PERIODO_S = 0.02


def reagir(processo: Processo, envelope: Envelope, _veredito: str) -> list[Envelope]:
    if envelope.type is Tipo.POLICY_DECISION and str(envelope.payload["verdict"]) == "confirm":
        pedido = {
            "call_id": str(envelope.payload["call_id"]),
            "motivo": str(envelope.payload["reason"]),
            "epoch": envelope.epoch,
        }
        with (processo.raiz / "ui-confirmacoes.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(pedido, ensure_ascii=False) + "\n")
    return []


def ler_botao(painel: PainelDoMicrofone) -> None:
    """Aplica o botão da tela, se alguém o tocou. Palavra inválida não muda nada."""
    caminho = painel.raiz / ARQUIVO_BOTAO
    try:
        bruto = caminho.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return
    if not bruto:
        return
    try:
        modo = Modo(bruto)
    except ValueError:
        return
    if modo is Modo.DESLIGADO:
        painel.desligar()
        return
    painel.ligar()
    painel.modo = modo


def main(argv: list[str] | None = None) -> int:
    analisa = analisador("ui")
    analisa.add_argument(
        "--microfone",
        action="store_true",
        help="mostra o indicador de microfone e manda o PTT/kill switch (cartão F1-13)",
    )
    analisa.add_argument(
        "--modo",
        choices=[str(m) for m in Modo],
        default=str(Modo.PTT),
        help="modo inicial do microfone; depois disso quem manda é o botão da tela",
    )
    args = analisa.parse_args(argv)
    relogio = RelogioDoSistema()
    processo = Processo(nome="ui", raiz=args.raiz, reacao=reagir)
    processo.abrir()
    if not args.microfone:
        # Sem microfone a `ui` é o esqueleto do F0-03: só reage ao barramento.
        try:
            processo.rodar(timeout=args.timeout)
        finally:
            processo.fechar()
        return 0

    painel = PainelDoMicrofone(
        raiz=args.raiz, atalho=atalho_do_ambiente(raiz=args.raiz), modo=Modo(args.modo)
    )
    painel.abrir()
    limite = None if args.timeout is None else relogio.mono_ns() + int(args.timeout * 1e9)
    try:
        while limite is None or relogio.mono_ns() < limite:
            ler_botao(painel)
            painel.tick()
            painel.escrever_tela()
            for envelope, veredito in processo.recebidos(timeout=0.0):
                for resposta in reagir(processo, envelope, veredito):
                    processo.publicar(resposta)
            relogio.dormir(PERIODO_S)
    finally:
        painel.fechar()
        processo.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
