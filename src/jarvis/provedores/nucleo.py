"""O registro, o catálogo e o portão juntos, do jeito que uma sessão do Jarvis os usa (ADR-0056).

`Provedores` é o que o aplicativo, a janela e o roteador do cérebro seguram: ele lista (com cache),
diz o que um modelo faz e monta o motor de um provedor — passando, para chamar, pelo portão da
ADR-0017 (licença, termos, interruptor da nuvem). O modelo pedido só precisa ter a forma de um id:
a lista é longa e muda toda semana, então quem julga se ele existe é o provedor, e a recusa dele
volta ao dono como recusa ("o provedor recusou o modelo"), nunca como outro modelo.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from jarvis.provedores.catalogo import Catalogo, Listagem, pasta_do_cache
from jarvis.provedores.interface import (
    ESFORCOS,
    FORMA_DO_ID,
    Capacidades,
    ProvedorDeModelos,
)
from jarvis.provedores.registro import (
    ARQUIVO,
    CLAUDE_CLI,
    COMPATIVEL_LOCAL,
    COMPATIVEL_NUVEM,
    ECO,
    RegraDeCapacidade,
    abrir,
    capacidades_do_registro,
    exigir,
    ler_provedores,
    ler_regras,
    provedor_registrado,
)
from jarvis.s2.motor import MotorDeConversa
from jarvis.voz.registro import Motor, MotorRecusado, motor_registrado

if TYPE_CHECKING:
    from jarvis.voz.config import Configuracao


def ligados_da_configuracao(configuracao: Configuracao) -> frozenset[str]:
    """Os provedores de nuvem que o dono ligou. `s2 = "claude"` sempre foi a escolha do dono de
    mandar a conversa para a CLI do Claude (a tela diz `[nuvem]`), então ela conta como ligada."""
    ligados = set(configuracao.nuvem_ligada)
    if configuracao.s2 == "claude":
        ligados.add(CLAUDE_CLI)
    return frozenset(ligados)


def escolha_da_configuracao(configuracao: Configuracao) -> tuple[str, str]:
    """`(provedor, modelo)` da escolha antiga: `s2` e `modelo_do_s2`."""
    if configuracao.s2 == "claude":
        modelo = configuracao.modelo_do_s2
        return CLAUDE_CLI, modelo if FORMA_DO_ID.fullmatch(modelo) else ""
    return ECO, ""


@dataclass(slots=True)
class Provedores:
    ligados: Collection[str] = frozenset()
    """Os provedores de nuvem que o dono ligou (`nuvem_ligada`, e a CLI do Claude com
    `s2 = "claude"`). Vazio = só os locais chamam."""
    sem_termos: Collection[str] = frozenset()
    ambiente: Mapping[str, str] | None = None
    pasta_de_trabalho: Path = field(default_factory=lambda: Path("conversa"))
    """A pasta **vazia** onde as CLIs rodam (ADR-0018, regra 1)."""
    catalogo: Catalogo | None = None
    bases: Mapping[str, str] = field(default_factory=dict)
    """Provedor → a base que o dono escreveu (os compatíveis). Ausente = a do registro."""
    arquivo: Path = ARQUIVO
    _regras: tuple[RegraDeCapacidade, ...] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.catalogo is None:
            self.catalogo = Catalogo(pasta_do_cache(self.ambiente))

    @classmethod
    def da_configuracao(
        cls,
        configuracao: Configuracao,
        *,
        pasta_de_trabalho: Path,
        ambiente: Mapping[str, str] | None = None,
        catalogo: Catalogo | None = None,
    ) -> Provedores:
        return cls(
            ligados=ligados_da_configuracao(configuracao),
            sem_termos=frozenset(configuracao.nuvem_sem_termos),
            ambiente=ambiente,
            pasta_de_trabalho=pasta_de_trabalho,
            catalogo=catalogo,
            bases={
                identificador: base
                for identificador, base in (
                    (COMPATIVEL_LOCAL, configuracao.base_compativel_local),
                    (COMPATIVEL_NUVEM, configuracao.base_compativel_nuvem),
                )
                if base
            },
        )

    def registrados(self) -> tuple[Motor, ...]:
        return ler_provedores(self.arquivo)

    def registro(self, identificador: str) -> Motor:
        motor = provedor_registrado(identificador, arquivo=self.arquivo)
        if motor is None:
            raise MotorRecusado(
                f"provedor {identificador!r} não está no registro de provedores de modelo"
            )
        return motor

    def regras(self) -> tuple[RegraDeCapacidade, ...]:
        if self._regras is None:
            self._regras = ler_regras(self.arquivo)
        return self._regras

    def abrir(self, identificador: str) -> ProvedorDeModelos:
        base = self.bases.get(identificador)
        return abrir(
            identificador,
            ambiente=self.ambiente,
            pasta_de_trabalho=self.pasta_de_trabalho,
            arquivo=self.arquivo,
            extras={"base": base} if base else None,
        )

    def ligado(self, identificador: str) -> bool:
        """Pode chamar agora: local, ou de nuvem que o dono ligou. Vale também para o Jev, que é
        do registro de motores (`decisao-jev-openrouter`)."""
        motor = provedor_registrado(identificador, arquivo=self.arquivo) or motor_registrado(
            identificador
        )
        if motor is None:
            return False
        return not motor.na_nuvem or motor.ligado or identificador in self.ligados

    def listar(self, identificador: str, *, forcar: bool = False) -> Listagem:
        """A lista que vale agora (ao vivo, guardada ou do registro — `catalogo`)."""
        assert self.catalogo is not None
        return self.catalogo.listar(
            self.abrir(identificador), self.registro(identificador), self.regras(), forcar=forcar
        )

    def sem_rede(self, identificador: str) -> Listagem:
        assert self.catalogo is not None
        return self.catalogo.sem_rede(self.registro(identificador), self.regras())

    def capacidades(self, identificador: str, modelo: str) -> Capacidades:
        """O que se sabe do modelo sem abrir socket: a lista guardada, completada pelo registro."""
        conhecido = self.sem_rede(identificador).modelo(modelo)
        if conhecido is not None:
            return conhecido.capacidades
        return capacidades_do_registro(identificador, modelo, self.regras())

    def motor(self, identificador: str, modelo: str = "", esforco: str = "") -> MotorDeConversa:
        """O motor de conversa deste provedor — depois do portão de chamar (ADR-0017)."""
        exigir(
            identificador, ligados=self.ligados, sem_termos=self.sem_termos, arquivo=self.arquivo
        )
        if modelo and not FORMA_DO_ID.fullmatch(modelo):
            raise MotorRecusado(f"o modelo {modelo[:40]!r} não tem a forma de um id de modelo")
        if esforco and esforco not in ESFORCOS:
            raise MotorRecusado(f"esforço {esforco!r} não existe ({', '.join(ESFORCOS)})")
        provedor = self.abrir(identificador)
        escolhido = modelo or self.registro(identificador).modelo
        return provedor.motor(modelo, esforco, self.capacidades(identificador, escolhido))


__all__ = ["Provedores", "escolha_da_configuracao", "ligados_da_configuracao"]
