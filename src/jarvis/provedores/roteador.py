"""O motor do cérebro que segue os presets do dono (ADR-0056, seções 5–7).

O cérebro continua com um motor só (`Cerebro.motor`); este é ele. A cada pedido:

1. lê os presets que valem **agora** (`FonteDePresets`: a janela e a voz gravam o arquivo, e a
   troca vale no pedido seguinte, sem reabrir nada);
2. monta — e guarda — o motor do preset ativo do cérebro, pelo portão de chamar
   (`Provedores.motor`: licença, termos, interruptor da nuvem);
3. **com imagem** no contexto (a tela da aba, ADR-0032): se o modelo do cérebro vê, vai a ele; se
   não, e o preset ativo de visão vê, aquele pedido vai ao de visão; senão, a imagem fica de fora
   e o pedido segue só com texto — nunca a um provedor que o dono não ligou.

O preset que não pode rodar não troca de provedor sozinho: o turno termina com o motivo
(`Fim(ERRO)`), e o dono escolhe outro. "Vê" é `aceita_imagem`, que os motores declaram a partir
das capacidades conhecidas: não informado não conta.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from jarvis.provedores.bloqueio import bloqueio_do_preset
from jarvis.provedores.interface import Papel, ProvedorIndisponivel
from jarvis.provedores.nucleo import Provedores
from jarvis.provedores.presets import FonteDePresets, Preset
from jarvis.s2.motor import (
    Contexto,
    Delta,
    Fim,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    Texto,
    aceita_imagem,
)
from jarvis.voz.chaves import SegredoAusente
from jarvis.voz.interface import Cancelado, Onde
from jarvis.voz.registro import MotorRecusado

if TYPE_CHECKING:
    from jarvis.voz.config import Configuracao

RECUSAS = (MotorRecusado, ProvedorIndisponivel, SegredoAusente)


@dataclass(slots=True)
class MotorDosPresets:
    """Um `MotorDeConversa` que, a cada pedido, é o do preset ativo (ou o de visão)."""

    fonte: FonteDePresets
    provedores: Provedores
    ao_rotear: Callable[[str], None] | None = None
    """Avisado com o nome do motor quando um pedido vai ao preset de visão (a tela e o log)."""
    _motores: dict[tuple[str, str, str], MotorDeConversa] = field(default_factory=dict)
    _ultimo: MotorDeConversa | None = field(default=None, repr=False)

    @classmethod
    def da_configuracao(
        cls,
        configuracao: Configuracao,
        *,
        pasta_de_trabalho: Path,
        ambiente: Mapping[str, str] | None = None,
    ) -> MotorDosPresets:
        return cls(
            fonte=FonteDePresets(ambiente=ambiente, configuracao=configuracao),
            provedores=Provedores.da_configuracao(
                configuracao, pasta_de_trabalho=pasta_de_trabalho, ambiente=ambiente
            ),
        )

    def acompanhar_a_nuvem(self) -> None:
        """A nuvem ligada **agora** (a janela acabou de ligar ou desligar um provedor): vale já
        neste pedido. O motor de um provedor que foi desligado sai do cache — não chama mais."""
        if self.fonte.nuvem is None:
            return
        ligados, sem_termos = self.fonte.nuvem()
        antes = frozenset(self.provedores.ligados)
        if ligados == antes and sem_termos == frozenset(self.provedores.sem_termos):
            return
        self.provedores.ligados = ligados
        self.provedores.sem_termos = sem_termos
        for chave in [c for c in self._motores if c[0] in antes - ligados]:
            del self._motores[chave]

    def motor_do_preset(self, preset: Preset) -> MotorDeConversa:
        """O motor de um preset — montado uma vez por (provedor, modelo, esforço)."""
        self.acompanhar_a_nuvem()
        chave = (preset.provedor, preset.modelo, preset.esforco)
        motor = self._motores.get(chave)
        if motor is None:
            motor = self.provedores.motor(preset.provedor, preset.modelo, preset.esforco)
            self._motores[chave] = motor
        return motor

    def motor_do_papel(self, papel: str) -> MotorDeConversa | None:
        """O motor do preset ativo de um papel (`resumo`, `visao`), ou `None` se não há ou não
        pode rodar. Quem usa decide o que fazer sem ele."""
        preset = self.fonte.atuais().ativo(papel)
        if preset is None:
            return None
        try:
            return self.motor_do_preset(preset)
        except RECUSAS:
            return None

    def _ativo(self) -> MotorDeConversa | None:
        return self.motor_do_papel(Papel.CEREBRO)

    @property
    def nome(self) -> str:
        motor = self._ultimo or self._ativo()
        if motor is not None:
            return motor.nome
        preset = self.fonte.atuais().ativo(Papel.CEREBRO)
        return f"preset «{preset.nome}» (não pode rodar)" if preset else "nenhum preset ativo"

    @property
    def codigo(self) -> str:
        """O preset ativo do cérebro como código para a trilha (`conversa-groq/openai/gpt-oss-20b`):
        o `nome` é frase de gente («Groq · …»), e a trilha só aceita código — era sempre
        `[fora_da_forma]`, e não se sabia que provedor tinha rodado (2026-10-30)."""
        preset = self.fonte.atuais().ativo(Papel.CEREBRO)
        if preset is None:
            return "sem_preset"
        return re.sub(r"[^\w.:/-]", "_", f"{preset.provedor}/{preset.modelo or 'padrao'}")[:64]

    @property
    def onde(self) -> Onde:
        motor = self._ultimo or self._ativo()
        return motor.onde if motor is not None else Onde.LOCAL

    @property
    def aceita_imagem(self) -> bool:
        """Há rota que vê: o modelo do cérebro, ou o preset ativo de visão."""
        return any(
            motor is not None and aceita_imagem(motor)
            for motor in (self._ativo(), self.motor_do_papel(Papel.VISAO))
        )

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        preset = self.fonte.atuais().ativo(Papel.CEREBRO)
        if preset is None:
            yield Fim(MotivoDoFim.ERRO, "não há preset de cérebro ativo: escolha um na janela")
            return
        try:
            motor = self.motor_do_preset(preset)
        except RECUSAS as erro:
            # O que bloqueou, por quê e como destravar — dito curto em voz e inteiro na tela
            # (ADR-0056 §7; dono, 2026-10-30: «não deixou por causa de outros modos»).
            bloqueio = bloqueio_do_preset(preset, erro, self.provedores)
            yield Texto(bloqueio.curta())
            yield Fim(MotivoDoFim.ERRO, bloqueio.frase())
            return
        if contexto.imagens and not aceita_imagem(motor):
            visao = self.motor_do_papel(Papel.VISAO)
            if visao is not None and aceita_imagem(visao):
                motor = visao
                if self.ao_rotear is not None:
                    self.ao_rotear(visao.nome)
            else:
                contexto = replace(contexto, imagens=())
        self._ultimo = motor
        yield from motor.gerar(contexto, modo, cancelado)


__all__ = ["MotorDosPresets"]
