"""O que bloqueou um preset, por quê e como destravar — em português, sem mandar ler ADR.

O dono (2026-10-30) ligou o Groq num preset e o Jarvis «não deixou por causa de outros modos», sem
explicar: o turno acabava com «o preset «rápido» não pode rodar: motor 'conversa-groq' é de nuvem e
está desligado: … (ADR-0017 …)». Cada recusa do portão de chamar (`Provedores.motor`) vira aqui um
`Bloqueio` com três partes — **o que** bloqueou, **por que** existe a trava e **como** destravar
(o botão, o atalho ou a frase) — e uma versão curta para a voz. Nada aqui lê chave: a frase diz o
nome da variável, nunca o valor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from jarvis.provedores.interface import ProvedorIndisponivel
from jarvis.voz.chaves import SegredoAusente
from jarvis.voz.registro import MotorRecusado

if TYPE_CHECKING:
    from jarvis.provedores.nucleo import Provedores
    from jarvis.provedores.presets import Preset


@dataclass(frozen=True, slots=True)
class Bloqueio:
    o_que: str
    por_que: str
    como: str
    voz: str
    """A frase curta que vai à voz (a tela leva as três partes)."""
    codigo: str
    """Para a trilha e os testes: `nuvem_desligada`, `sem_chave`, `licenca`, `modelo_invalido`,
    `esforco_invalido`, `provedor_indisponivel`, `outro`."""

    def frase(self) -> str:
        return f"{self.o_que} Por quê: {self.por_que} Como destravar: {self.como}"

    def curta(self) -> str:
        return self.voz


def _nome_do_provedor(identificador: str, provedores: Provedores | None) -> str:
    if provedores is not None:
        try:
            motor = provedores.registro(identificador)
        except (MotorRecusado, KeyError, ValueError, OSError):
            motor = None
        if motor is not None and motor.servico:
            return motor.servico
    return identificador.removeprefix("conversa-").removeprefix("decisao-").capitalize()


def _variavel(identificador: str, provedores: Provedores | None) -> str:
    if provedores is None:
        return ""
    try:
        return provedores.registro(identificador).variavel_da_chave
    except (MotorRecusado, KeyError, ValueError, OSError):
        return ""


def bloqueio_do_preset(
    preset: Preset, erro: Exception, provedores: Provedores | None = None
) -> Bloqueio:
    """A recusa do portão (`MotorRecusado`, `SegredoAusente`, `ProvedorIndisponivel`) em frase."""
    nome = _nome_do_provedor(preset.provedor, provedores)
    texto = str(erro)
    baixo = texto.casefold()
    alvo = f"O preset «{preset.nome}» (cérebro, {nome})"
    voltar = "ou volte ao preset de antes: diga «usa o preset claude»."
    if isinstance(erro, SegredoAusente):
        variavel = _variavel(preset.provedor, provedores) or "a chave do provedor"
        return Bloqueio(
            o_que=f"{alvo} não rodou: falta a chave {variavel}.",
            por_que=(
                f"o {nome} só atende com a chave da sua conta, guardada no chaveiro do sistema."
            ),
            como=(
                f"Configuração → Chaves de API → {variavel} → Guardar (o Jarvis só confere se ela "
                f"existe; nunca a mostra), {voltar}"
            ),
            voz=f"Falta a chave do {nome}: guarde-a em Configuração, Chaves de API.",
            codigo="sem_chave",
        )
    if isinstance(erro, MotorRecusado) and "nuvem" in baixo and "desligad" in baixo:
        return Bloqueio(
            o_que=f"{alvo} não rodou: o {nome} está desligado nesta conversa.",
            por_que=(
                "provedor de nuvem nasce desligado, porque o que você fala sai da máquina para "
                f"o {nome}; ligar é escolha sua, depois de ler o aviso."
            ),
            como=(
                f"Configuração → resposta → toque em {nome} → «li o aviso — ligar {nome}» "
                f"(vale na hora, nesta conversa; «salvar configuração» guarda para as próximas), "
                f"{voltar}"
            ),
            voz=f"O {nome} está desligado: ligue em Configuração, resposta, depois do aviso.",
            codigo="nuvem_desligada",
        )
    if isinstance(erro, MotorRecusado) and "licen" in baixo:
        return Bloqueio(
            o_que=f"{alvo} não rodou: o {nome} não está liberado no registro deste Jarvis.",
            por_que=(
                "só chama provedor com licença e termos conferidos no registro "
                "(licenses/provedores-de-modelo.toml)."
            ),
            como=f"escolha outro provedor no preset, {voltar}",
            voz=f"O {nome} não está liberado neste Jarvis: escolha outro preset.",
            codigo="licenca",
        )
    if isinstance(erro, MotorRecusado) and "forma de um id" in baixo:
        return Bloqueio(
            o_que=f"{alvo} não rodou: o modelo «{preset.modelo[:40]}» não é um id de modelo.",
            por_que="o id vai na chamada ao provedor e tem de ter a forma dos ids dele.",
            como=f"Configuração → resposta → {nome} → escolha o modelo da lista, {voltar}",
            voz="O modelo desse preset não existe: escolha um da lista na janela.",
            codigo="modelo_invalido",
        )
    if isinstance(erro, MotorRecusado) and "esforço" in baixo:
        return Bloqueio(
            o_que=f"{alvo} não rodou: o esforço «{preset.esforco}» não existe para ele.",
            por_que="cada modelo aceita só alguns níveis de esforço.",
            como=f"Configuração → resposta → {nome} → escolha um esforço que ele aceita, {voltar}",
            voz="O esforço desse preset não vale para o modelo: troque na janela.",
            codigo="esforco_invalido",
        )
    if isinstance(erro, ProvedorIndisponivel):
        return Bloqueio(
            o_que=f"{alvo} não rodou: {texto[:160]}.",
            por_que="o provedor precisa estar instalado e acessível nesta máquina.",
            como=f"siga o que a frase pede ou escolha outro preset na janela, {voltar}",
            voz=f"O {nome} não está disponível agora: troque de preset.",
            codigo="provedor_indisponivel",
        )
    return Bloqueio(
        o_que=f"{alvo} não rodou: {texto[:160]}.",
        por_que="o portão de chamar recusou este provedor.",
        como=f"confira o provedor em Configuração → resposta, {voltar}",
        voz=f"O preset {preset.nome} não pôde rodar: veja o motivo na tela.",
        codigo="outro",
    )


__all__ = ["Bloqueio", "bloqueio_do_preset"]
