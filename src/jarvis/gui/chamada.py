"""A aba «chamadas» da configuração (ADR-0074) — o TOTP que reconhece o dono e os limites.

Decisão do dono (2026-11-17): TOTP configurável pelo app. A aba:

- **gera** o segredo (160 bits) e o guarda onde moram as chaves do app (o chaveiro do sistema;
  a variável `JARVIS_TOTP_DA_CHAMADA`, se exportada, ganha);
- **mostra uma vez** o QR (desenhado pelo `segno`, BSD, puro Python), a URI `otpauth://` e a
  chave em grupos, para o dono cadastrar no app autenticador; ao tocar «já cadastrei» (ou ao
  sair da aba), some e não volta — o segredo nunca é lido de novo para desenhar a tela;
- **confere** um código (RFC 6238, janela ±1, anti-reuso): o código conferido aqui fica gasto,
  como numa chamada;
- liga e desliga a chave mestra «chamadas ativas» (desligada por padrão: o dono liga depois de
  testar) e mostra as **ações à espera** do dono, com Confirmar e Recusar — a confirmação pela
  sessão do PC (`CentralDaChamada.confirmar_no_pc`), por clique e nunca por voz;
- grava os limites, os textos, o fone (sim/não/auto), o contato do dono no WhatsApp e o prazo
  da ação pendente em `chamada.toml` (0600) a cada mudança. A palavra de coação fica fora da aba
  (decisão do dono, 2026-11-17): só o gancho no arquivo.

O valor do segredo não vai a log, trilha, frase de estado nem arquivo do projeto."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from jarvis.chamada.central import CentralDaChamada
from jarvis.chamada.config import (
    WHATSAPP_DO_DONO,
    ConfiguracaoDaChamada,
    ConfiguracaoDaChamadaInvalida,
    gravar,
    ler,
)
from jarvis.chamada.totp import (
    ARQUIVO_DO_ESTADO,
    EstadoDoTotp,
    GuardaDoSegredo,
    Veredito,
    Verificador,
    gerar_segredo,
    uri_otpauth,
)

FRASES_DO_VEREDITO = {
    Veredito.ACEITO: "código aceito: o autenticador está certo (este código ficou gasto)",
    Veredito.ERRADO: "não deu: código errado (confira o relógio do celular)",
    Veredito.REUSADO: "não deu: este código já foi usado — espere o próximo",
    Veredito.FORMATO: "não deu: são 6 dígitos",
    Veredito.SEM_SEGREDO: "não deu: gere o segredo primeiro",
    Veredito.BLOQUEADO: "não deu: bloqueado por erros demais hoje — libere abaixo",
}


AJUSTES_DA_ABA = frozenset(
    {
        "chamadas_ativas",
        "duracao_para_aviso_min",
        "turnos",
        "frases_por_fala",
        "tentativas_de_codigo",
        "pode_dizer",
        "nunca_dizer",
        "retencao_do_recado_dias",
        "retencao_da_memoria_dias",
        "lembrar_interlocutor",
        "fone",
        "contato_do_dono_whatsapp",
        "acao_expira_min",
    }
)
"""O que a aba grava. A palavra de coação fica de fora (decisão do dono, 2026-11-17)."""


def qr_da_uri(uri: str) -> str:
    """O QR da URI em PNG (data URI), em memória: nunca vai ao disco. Sem o `segno` (o grupo
    `gui` não instalado), vazio — a URI e a chave continuam servindo."""
    try:
        import segno
    except ImportError:  # pragma: no cover — o grupo `gui` traz o segno
        return ""
    return str(segno.make(uri, error="m").png_data_uri(scale=6, border=4))


def _em_grupos(segredo: str) -> str:
    return " ".join(segredo[i : i + 4] for i in range(0, len(segredo), 4))


class PonteDaChamada(QObject):
    """O que o QML lê (`frase`, `configurado`, `uri`, `chave`, `ajustes`) e pede (os slots)."""

    mudou = Signal()
    acoesMudaram = Signal()

    def __init__(
        self,
        *,
        caminho: Path,
        guarda: GuardaDoSegredo,
        relogio: Callable[[], float] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._caminho = caminho
        self._guarda = guarda
        self._frase = ""
        self._uri = ""
        self._chave = ""
        self._qr = ""
        estado = EstadoDoTotp.ler(caminho.parent / ARQUIVO_DO_ESTADO)
        extras: dict[str, Any] = {} if relogio is None else {"relogio": relogio}
        self.verificador = Verificador(guarda=guarda, estado=estado, **extras)
        self.central: CentralDaChamada | None = None
        """A central (ADR-0074, fatia A): a ponte da janela a liga depois de montar."""
        try:
            self._configuracao = ler(caminho)
        except (ConfiguracaoDaChamadaInvalida, OSError) as erro:
            self._configuracao = ConfiguracaoDaChamada()
            self._frase = f"não deu: {caminho.name} recusado ({erro}) — usando os padrões"

    @property
    def configuracao(self) -> ConfiguracaoDaChamada:
        return self._configuracao

    # --- o que a tela lê -----------------------------------------------------------------
    @Property(str, notify=mudou)
    def frase(self) -> str:
        return self._frase

    @Property(bool, notify=mudou)
    def configurado(self) -> bool:
        return self.verificador.configurado()

    @Property(bool, notify=mudou)
    def bloqueado(self) -> bool:
        return self.verificador.bloqueado()

    @Property(str, notify=mudou)
    def uri(self) -> str:
        """Só entre «gerar» e «já cadastrei»: depois, vazio para sempre."""
        return self._uri

    @Property(str, notify=mudou)
    def chave(self) -> str:
        return self._chave

    @Property(str, notify=mudou)
    def qr(self) -> str:
        """O QR da URI como `data:image/png;base64,…` — só enquanto a URI aparece."""
        return self._qr

    @Property(dict, notify=mudou)
    def ajustes(self) -> dict[str, Any]:
        c = self._configuracao
        return {
            "duracao_para_aviso_min": c.duracao_para_aviso_min,
            "turnos": c.turnos,
            "frases_por_fala": c.frases_por_fala,
            "tentativas_de_codigo": c.tentativas_de_codigo,
            "pode_dizer": c.pode_dizer,
            "nunca_dizer": c.nunca_dizer,
            "retencao_do_recado_dias": c.retencao_do_recado_dias,
            "retencao_da_memoria_dias": c.retencao_da_memoria_dias,
            "lembrar_interlocutor": c.lembrar_interlocutor,
            "fone": c.fone,
            "contato_do_dono_whatsapp": c.contato_do_dono_whatsapp,
            "acao_expira_min": c.acao_expira_min,
            "canal_do_dono_ligado": WHATSAPP_DO_DONO in c.canais_de_confirmacao,
            "chamadas_ativas": c.chamadas_ativas,
        }

    @Property(list, notify=acoesMudaram)
    def pendentes(self) -> list[dict[str, Any]]:
        """As ações pedidas em chamadas à espera do dono (código, ação, de quem, prazo)."""
        if self.central is None:
            return []
        return [
            {
                "codigo": a["codigo"],
                "acao": a["acao"],
                "detalhes": a["detalhes"],
                "interlocutor": a["interlocutor"],
                "minutos": max(1, round(float(a["expira_em_s"]) / 60)),
            }
            for a in self.central.pendentes()
        ]

    @Slot(str)
    def confirmarAcao(self, codigo: str) -> None:
        self._decidir_acao(codigo, confirmar=True)

    @Slot(str)
    def recusarAcao(self, codigo: str) -> None:
        self._decidir_acao(codigo, confirmar=False)

    def _decidir_acao(self, codigo: str, *, confirmar: bool) -> None:
        if self.central is None:
            self._dizer("não deu: a central da chamada não está montada")
            return
        decidir = self.central.confirmar_no_pc if confirmar else self.central.recusar_no_pc
        decisao = decidir(codigo)
        self.acoesMudaram.emit()
        if decisao.aceita:
            self._dizer(f"ação {codigo} {decisao.motivo}: o Jarvis foi avisado")
        else:
            self._dizer(f"não deu: ação {codigo} — {decisao.motivo}")

    # --- o que a tela pede ---------------------------------------------------------------
    def _dizer(self, frase: str) -> None:
        self._frase = frase
        self.mudou.emit()

    @Slot()
    def gerarSegredo(self) -> None:
        segredo = gerar_segredo()
        try:
            self._guarda.gravar(segredo)
        except Exception as erro:  # sem chaveiro: diz, não grava noutro lugar
            self._uri = self._chave = self._qr = ""
            self._dizer(f"não deu: o segredo não foi guardado ({erro})")
            return
        # O passo usado e os erros eram do segredo antigo: começam do zero.
        self.verificador.estado.ultimo_passo = -1
        self.verificador.estado.erros = []
        self.verificador.estado.gravar()
        self._uri = uri_otpauth(segredo)
        self._chave = _em_grupos(segredo)
        self._qr = qr_da_uri(self._uri)
        self._dizer(
            "segredo novo guardado: cadastre agora no autenticador — ele não será mostrado de novo"
        )

    @Slot()
    def esconderSegredo(self) -> None:
        if self._uri or self._chave:
            self._uri = self._chave = self._qr = ""
            self._dizer("pronto: confira com um código do autenticador")

    @Slot(str)
    def conferirCodigo(self, codigo: str) -> None:
        self._dizer(FRASES_DO_VEREDITO[self.verificador.conferir(codigo)])

    @Slot()
    def apagarSegredo(self) -> None:
        try:
            self._guarda.apagar()
        except Exception as erro:
            self._dizer(f"não deu: {erro}")
            return
        self._uri = self._chave = self._qr = ""
        self._dizer("segredo apagado: ninguém é reconhecido como o dono numa chamada")

    @Slot()
    def liberarBloqueio(self) -> None:
        self.verificador.liberar()
        self._dizer("bloqueio liberado")

    @Slot(str, str)
    def definir(self, campo: str, valor: str) -> None:
        atual = self._configuracao
        if campo not in AJUSTES_DA_ABA:
            self._dizer(f"não deu: ajuste desconhecido ({campo})")
            return
        antigo = getattr(atual, campo)
        novo_valor: Any
        if isinstance(antigo, bool):
            novo_valor = valor.strip().lower() in ("1", "true", "sim")
        elif isinstance(antigo, int):
            try:
                novo_valor = int(valor.strip())
            except ValueError:
                self._dizer(f"não deu: {campo} tem de ser um número")
                return
        else:
            novo_valor = valor.strip()
        try:
            nova = replace(atual, **{campo: novo_valor})
            gravar(nova, self._caminho)
        except (ConfiguracaoDaChamadaInvalida, OSError) as erro:
            self._dizer(f"não deu: {erro}")
            return
        self._configuracao = nova
        self._dizer(f"{campo.replace('_', ' ')}: gravado")


__all__ = ["PonteDaChamada"]
