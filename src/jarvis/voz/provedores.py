"""Os motores vistos como o dono os escolhe: **provedor**, depois **modelo** (ADR-0017).

O registro tem um motor por linha, e é certo que tenha: a Groq cobra por modelo, então cada
modelo dela é um motor com preço e aviso próprios. Mas para quem escolhe, "Groq" é uma
decisão (o áudio sai para lá) e "turbo ou v3" é outra (preço e precisão). Uma lista plana de
ids mistura as duas — e foi assim que a janela deixou o dono sem achar onde se escolhe o
modelo.

Este módulo só **reagrupa** o que o registro e a configuração já dizem. Ele não liga nada,
não lê chave e não decide preço: escolher um modelo é escrever um campo da configuração, e
cada opção carrega qual campo e qual valor, para a tela e o terminal fazerem a mesma coisa.

Duas formas de modelo existem, e a opção esconde a diferença de quem desenha:

- **um motor por modelo** (Groq): escolher o modelo é escolher o motor — campo `asr`;
- **um motor com lista de modelos** (ElevenLabs): mesmo serviço, mesmos termos, mesmo
  interruptor — campo `modelo_elevenlabs`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from jarvis.voz.config import TTS_ELEVENLABS, Configuracao
from jarvis.voz.interface import Onde
from jarvis.voz.prontidao import o_que_falta
from jarvis.voz.registro import Motor, motores_de

CAMPO_DO_PAPEL: Final[dict[str, str]] = {
    "asr": "asr",
    "tts": "tts",
    "decisao": "enderecamento",
}
"""Papel do motor → campo da configuração que guarda o motor escolhido."""
CAMPOS_DO_PAPEL_ATUAL: Final[dict[str, Any]] = {
    papel: (lambda c, campo=campo: str(getattr(c, campo)))
    for papel, campo in CAMPO_DO_PAPEL.items()
}

CAMPO_DO_MODELO: Final[dict[str, str]] = {TTS_ELEVENLABS: "modelo_elevenlabs"}
"""Motor com lista de modelos → campo da configuração que guarda a escolha."""


@dataclass(frozen=True, slots=True)
class OpcaoDeModelo:
    """Um modelo que o dono pode escolher, e o campo que a escolha escreve."""

    modelo: str
    campo: str
    valor: str
    escolhido: bool
    nota: str = ""

    def para_dict(self) -> dict[str, Any]:
        return {
            "modelo": self.modelo,
            "campo": self.campo,
            "valor": self.valor,
            "escolhido": self.escolhido,
            "nota": self.nota,
        }


@dataclass(frozen=True, slots=True)
class Provedor:
    """Quem ouve ou quem fala, como o dono escolhe: um serviço (ou um motor local)."""

    chave: str
    nome: str
    papel: str
    onde: Onde
    motor: str
    """O motor que vale se o dono escolher este provedor agora."""
    escolhido: bool
    ligado: bool
    aviso: str
    variavel_da_chave: str
    modelos: tuple[OpcaoDeModelo, ...]
    falta: str = ""
    """O que falta para o motor vigente rodar agora (`jarvis.voz.prontidao`) — o mesmo que o
    laço usaria para recusar. Vazio = roda."""

    @property
    def na_nuvem(self) -> bool:
        return self.onde is Onde.NUVEM

    def para_dict(self) -> dict[str, Any]:
        return {
            "chave": self.chave,
            "nome": self.nome,
            "papel": self.papel,
            "onde": "nuvem" if self.na_nuvem else "local",
            "motor": self.motor,
            "escolhido": self.escolhido,
            "ligado": self.ligado,
            "aviso": self.aviso,
            "variavelDaChave": self.variavel_da_chave,
            "modelos": [opcao.para_dict() for opcao in self.modelos],
            "falta": self.falta,
        }


def _nome_do_servico(motor: Motor) -> str:
    """ "Microsoft (endpoint de read-aloud do Edge)" → "Microsoft": o parêntese é do aviso."""
    return motor.servico.split(" (")[0].strip() or motor.id


def _chave_do_grupo(motor: Motor) -> str:
    return f"nuvem:{_nome_do_servico(motor)}" if motor.onde is Onde.NUVEM else motor.id


def _preco_curto(motor: Motor) -> str:
    """ "US$ 0,04 por hora de áudio; mínimo de 10 s" → "US$ 0,04 por hora de áudio"."""
    return motor.preco.split(";")[0].strip()


def provedores(
    configuracao: Configuracao, papel: str, *, ambiente: Mapping[str, str] | None = None
) -> tuple[Provedor, ...]:
    """Os provedores de um papel (`asr`, `tts` ou `decisao`), na ordem do registro."""
    atual = CAMPOS_DO_PAPEL_ATUAL[papel](configuracao)
    grupos: dict[str, list[Motor]] = {}
    for motor in motores_de(papel):
        grupos.setdefault(_chave_do_grupo(motor), []).append(motor)

    saida: list[Provedor] = []
    for chave, motores in grupos.items():
        ids = [m.id for m in motores]
        ligados = [i for i in ids if i in configuracao.nuvem_ligada]
        # O motor que vale: o escolhido, se for deste grupo; senão um que o dono já ligou;
        # senão o primeiro do registro (na Groq, o turbo — o mais barato).
        vigente = atual if atual in ids else (ligados[0] if ligados else ids[0])
        motor = next(m for m in motores if m.id == vigente)
        if len(motores) > 1:
            opcoes = tuple(
                OpcaoDeModelo(
                    modelo=m.modelo,
                    campo=papel,
                    valor=m.id,
                    escolhido=m.id == vigente,
                    nota=_preco_curto(m),
                )
                for m in motores
            )
        elif motor.id in CAMPO_DO_MODELO:
            campo = CAMPO_DO_MODELO[motor.id]
            pedido = str(getattr(configuracao, campo)) or motor.modelo
            opcoes = tuple(
                OpcaoDeModelo(
                    modelo=modelo,
                    campo=campo,
                    valor="" if modelo == motor.modelo else modelo,
                    escolhido=modelo == pedido,
                    nota="padrão" if modelo == motor.modelo else "",
                )
                for modelo in motor.modelos_permitidos
            )
        else:
            opcoes = ()
        saida.append(
            Provedor(
                chave=chave,
                nome=_nome_do_servico(motor) if motor.onde is Onde.NUVEM else motor.id,
                papel=papel,
                onde=motor.onde,
                motor=vigente,
                escolhido=atual in ids,
                ligado=(
                    vigente in configuracao.uso_pessoal_aceito
                    if motor.de_uso_pessoal
                    else motor.onde is Onde.LOCAL or vigente in configuracao.nuvem_ligada
                ),
                aviso=motor.frase_de_aviso,
                variavel_da_chave=motor.variavel_da_chave,
                modelos=opcoes,
                falta=o_que_falta(vigente, configuracao, ambiente=ambiente),
            )
        )
    return tuple(saida)


def vozes_da_elevenlabs(ambiente: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """As vozes da conta do dono na ElevenLabs, como a tela as desenha.

    Existe para a janela não importar motor (ADR-0019, `test_fronteira`): ela pede a lista ao
    módulo de escolha, e é ele que fala com o motor. A chave vem de `ambiente` — o da janela
    já traz o chaveiro, em memória — e não aparece no que volta.
    """
    from jarvis.voz.elevenlabs import listar_vozes

    return [voz.para_dict() for voz in listar_vozes(ambiente=ambiente)]
