"""A aba «chamadas» da configuração (ADR-0074) — o TOTP que reconhece o dono e os limites.

Decisão do dono (2026-11-17): TOTP configurável pelo app. A aba:

- **gera** o segredo (160 bits) e o guarda onde moram as chaves do app (o chaveiro do sistema;
  a variável `JARVIS_TOTP_DA_CHAMADA`, se exportada, ganha);
- **mostra uma vez** o QR (desenhado pelo `segno`, BSD, puro Python), a URI `otpauth://` e a
  chave em grupos, para o dono cadastrar no app autenticador; ao tocar «já cadastrei» (ou ao
  sair da aba), some e não volta — o segredo nunca é lido de novo para desenhar a tela;
- **confere** um código (RFC 6238, janela ±1, anti-reuso): o código conferido aqui fica gasto,
  como numa chamada;
- grava os limites e os textos em `chamada.toml` (0600) a cada mudança.

O valor do segredo não vai a log, trilha, frase de estado nem arquivo do projeto."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from jarvis.chamada.config import (
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
            "coacao_ligada": bool(c.palavra_de_coacao),
            "retencao_do_recado_dias": c.retencao_do_recado_dias,
            "retencao_da_memoria_dias": c.retencao_da_memoria_dias,
            "lembrar_interlocutor": c.lembrar_interlocutor,
            "usa_fone": c.usa_fone,
            "canal_de_confirmacao": c.canal_de_confirmacao,
        }

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
        if not hasattr(atual, campo) or campo == "palavra_de_coacao":
            if campo == "palavra_de_coacao":
                novo_valor: Any = valor.strip()
            else:
                self._dizer(f"não deu: ajuste desconhecido ({campo})")
                return
        else:
            antigo = getattr(atual, campo)
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
        nome = "palavra de coação" if campo == "palavra_de_coacao" else campo.replace("_", " ")
        self._dizer(f"{nome}: gravado")


__all__ = ["PonteDaChamada"]
