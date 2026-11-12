"""O texto da resposta automática (ADR-0060, fatia D): o motor do Jarvis redige, instruído pelas
memórias fixas do dono; o código (`jarvis.social.envio.conteudo_barrado`) confere antes de sair.

O motor **não** lê a mensagem do contato (mapear o formato das mensagens é para depois): ele sabe
quem escreveu e o que o dono deixou dito para quando está ausente. A resposta é curta, sem
promessa, sem dinheiro, sem dado, sem link. Na dúvida o motor responde `NAO_ENVIAR` e o Jarvis
só notifica o dono."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from jarvis.s2.motor import Contexto, Mensagem, Modo, MotorDeConversa, Texto

NAO_ENVIAR: Final = "NAO_ENVIAR"
LIMITE: Final = 220
SISTEMA: Final = (
    "Você é o Jarvis, assistente do dono, escrevendo UMA resposta curta de WhatsApp em nome dele "
    "para um contato que mandou mensagem enquanto ele está ausente. Regras: português do Brasil; "
    f"no máximo {LIMITE} caracteres; tom do dono conforme as memórias abaixo; diga só que ele "
    "está ausente e o que as instruções dele mandam dizer; nunca prometa nada em nome dele, "
    "nunca fale de dinheiro, pagamento ou PIX, nunca passe telefone, documento, senha, código ou "
    "link, nunca peça dado. Varie a redação, sem copiar uma frase pronta. Responda só com o "
    f"texto da mensagem, sem aspas. Se as instruções não cobrirem este contato, responda "
    f"exatamente {NAO_ENVIAR}."
)


def redigir(
    motor: MotorDeConversa,
    nome: str,
    memorias: str,
    *,
    cancelado: Callable[[], bool] = lambda: False,
) -> str:
    """O texto a enviar, ou vazio (o motor recusou, falhou ou passou do limite)."""
    sistema = f"{SISTEMA}\n\n{memorias}" if memorias else SISTEMA
    pedido = f"O contato «{nome}» mandou mensagem no WhatsApp. Escreva a resposta."
    contexto = Contexto(sistema=sistema, mensagens=(Mensagem("dono", pedido),))
    partes: list[str] = []
    try:
        for delta in motor.gerar(contexto, Modo.RAPIDO, cancelado):
            if isinstance(delta, Texto):
                partes.append(delta.texto)
    except Exception:
        return ""
    texto = " ".join("".join(partes).split()).strip().strip("\"'«»“”").strip()
    if not texto or NAO_ENVIAR in texto or len(texto) > LIMITE:
        return ""
    return texto


__all__ = ["LIMITE", "NAO_ENVIAR", "SISTEMA", "redigir"]
