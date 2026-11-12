"""A aba «redes sociais» da configuração (ADR-0060) — a ponta Qt de `jarvis.social.config`.

Como a de acesso: cada clique grava `redes.toml` na hora (0600) e a frase de estado diz o que
aconteceu. Um cartão por rede, com a chave de monitorar, a de notificar, o estado que o monitor
informa e as últimas notificações daquela rede — sem vídeo nem captura, só estado."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from jarvis.social import memorias as fixas
from jarvis.social.config import (
    ConfiguracaoSocial,
    ConfiguracaoSocialInvalida,
    gravar,
    ler,
)
from jarvis.social.envio import (
    TETO_RIGIDO_POR_DIA,
    TETO_RIGIDO_POR_HORA,
    Pausas,
    Permitido,
)
from jarvis.social.redes import REDES, rede

EstadoDaRede = Callable[[str], dict[str, Any]]
"""O que o monitor sabe de uma rede: `estado` (id curto), `frase`, `naoLidas`, `notificacoes`."""


def sem_monitor(identificador: str) -> dict[str, Any]:
    """Antes de o monitor existir (ou com a conversa fechada): só o que o ajuste diz."""
    return {"estado": "", "frase": "", "naoLidas": 0, "notificacoes": []}


class PonteDasRedes(QObject):
    """O que o QML lê (`redes`, `navegadores`, `frase`) e o que ele pede (os slots)."""

    mudou = Signal()

    def __init__(
        self,
        *,
        caminho: Path,
        navegadores: Callable[[], Sequence[tuple[str, str]]],
        principal: Callable[[], str],
        estado: EstadoDaRede = sem_monitor,
        ao_mudar: Callable[[ConfiguracaoSocial], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._caminho = caminho
        self._navegadores = navegadores
        """(família, nome) dos navegadores que o Jarvis conhece (a aba «navegadores»)."""
        self._principal = principal
        self._estado = estado
        self.ao_mudar = ao_mudar
        """Avisa o monitor vivo (ele relê os ajustes sem reiniciar o Jarvis)."""
        self._frase = ""
        self.pausas = Pausas(caminho.parent / "redes-pausas.json")
        """As pausas de 24 h por sinal de alerta (fatia D): o dono vê e pode tirar aqui."""
        self.ao_parar_envios: Callable[[], None] | None = None
        """O «parar envios» do dono: além de gravar, corta o envio em curso (a Ponte liga)."""
        self._caminho_das_memorias = caminho.parent / fixas.ARQUIVO
        """As memórias fixas (ADR-0060, fatia C) moram ao lado do `redes.toml`."""
        try:
            self._memorias: tuple[fixas.MemoriaFixa, ...] = fixas.ler(self._caminho_das_memorias)
        except (fixas.MemoriaInvalida, OSError) as erro:
            self._memorias = ()
            self._frase = f"não deu: {fixas.ARQUIVO} recusado ({erro})"
        try:
            self._configuracao = ler(caminho)
        except (ConfiguracaoSocialInvalida, OSError) as erro:
            # Arquivo quebrado: a tela mostra o erro e trabalha com tudo desligado, sem regravar
            # por cima até o dono mexer (o primeiro clique grava um arquivo válido).
            self._configuracao = ConfiguracaoSocial()
            self._frase = f"não deu: {self._caminho.name} recusado ({erro}) — tudo desligado"

    @property
    def configuracao(self) -> ConfiguracaoSocial:
        return self._configuracao

    def trocar_estado(self, estado: EstadoDaRede) -> None:
        """O monitor nasce com a conversa; daí em diante a tela lê dele."""
        self._estado = estado
        self.mudou.emit()

    # --- o que a tela lê -----------------------------------------------------------------
    @Property(str, notify=mudou)
    def frase(self) -> str:
        return self._frase

    @Property(str, notify=mudou)
    def caminho(self) -> str:
        return str(self._caminho)

    @Property(list, notify=mudou)
    def redes(self) -> list[dict[str, Any]]:
        linhas = []
        for item in REDES:
            ajuste = self._configuracao.ajuste(item.id)
            estado = self._estado(item.id)
            linhas.append(
                {
                    "id": item.id,
                    "nome": item.nome,
                    "endereco": item.endereco,
                    "responde": item.responde,
                    "monitorar": ajuste.monitorar,
                    "notificar": ajuste.notificar,
                    "estado": estado.get("estado") or ("" if ajuste.monitorar else "desligada"),
                    "frase": estado.get("frase")
                    or (
                        "esperando a conversa abrir para ler a aba"
                        if ajuste.monitorar
                        else "desligada: o Jarvis não abre nem lê esta rede"
                    ),
                    "naoLidas": int(estado.get("naoLidas") or 0),
                    "notificacoes": list(estado.get("notificacoes") or []),
                }
            )
        return linhas

    @Property(str, notify=mudou)
    def navegadorPreferido(self) -> str:
        return self._configuracao.navegador_preferido

    @Property(list, notify=mudou)
    def navegadores(self) -> list[dict[str, Any]]:
        """O «principal» (vazio) primeiro, depois cada navegador conhecido."""
        escolhido = self._configuracao.navegador_preferido
        principal = self._principal()
        opcoes = [
            {
                "familia": "",
                "nome": f"o principal ({principal})" if principal else "o principal",
                "escolhido": escolhido == "",
            }
        ]
        vistas = {""}
        for familia, nome in self._navegadores():
            if familia in vistas:
                continue
            vistas.add(familia)
            opcoes.append({"familia": familia, "nome": nome, "escolhido": familia == escolhido})
        if escolhido not in vistas:  # escolhido à mão e já não detectado: continua visível
            opcoes.append({"familia": escolhido, "nome": escolhido, "escolhido": True})
        return opcoes

    @Property(dict, notify=mudou)
    def envio(self) -> dict[str, Any]:
        """O envio no WhatsApp (fatia D): a chave mestra, o ausente, os tetos, a lista e a pausa."""
        envio = self._configuracao.envio
        pausa = self.pausas.ativa("whatsapp", time.time())
        return {
            "automatico": envio.automatico,
            "ausente": envio.ausente,
            "porHora": envio.por_hora,
            "porDia": envio.por_dia,
            "tetoHora": TETO_RIGIDO_POR_HORA,
            "tetoDia": TETO_RIGIDO_POR_DIA,
            "intervaloMin": int(envio.intervalo_s // 60),
            "silencio": f"{envio.silencio[0]}h–{envio.silencio[1]}h",
            "permitidos": [{"nome": p.nome, "telefone": p.telefone} for p in envio.permitidos],
            "pausa": pausa,
        }

    @Property(list, notify=mudou)
    def memorias(self) -> list[dict[str, str]]:
        return [m.para_a_tela() for m in self._memorias]

    @Property(list, constant=True)
    def tiposDeMemoria(self) -> list[dict[str, str]]:
        return [{"id": tipo, "rotulo": rotulo} for tipo, rotulo in fixas.TIPOS.items()]

    # --- o que a tela pede ---------------------------------------------------------------
    def _aplicar(self, mudar: Callable[[ConfiguracaoSocial], ConfiguracaoSocial], ok: str) -> bool:
        try:
            nova = mudar(self._configuracao)
            gravar(nova, self._caminho)
        except (ConfiguracaoSocialInvalida, KeyError) as erro:
            self._frase = f"não deu: {erro}"
            self.mudou.emit()
            return False
        except OSError as erro:
            # Vale na sessão, como o acesso: o dono vê que não ficou no disco.
            self._configuracao = nova
            self._frase = f"{ok} — vale agora, mas não deu para salvar ({erro})"
        else:
            self._configuracao = nova
            self._frase = f"{ok} — salvo"
        if self.ao_mudar is not None:
            self.ao_mudar(self._configuracao)
        self.mudou.emit()
        return True

    @Slot(str, bool, result=bool)
    def definirMonitorar(self, identificador: str, ligado: bool) -> bool:
        nome = _nome(identificador)
        return self._aplicar(
            lambda c: c.com_rede(identificador, monitorar=ligado),
            f"{nome}: {'monitorando' if ligado else 'monitor desligado'}",
        )

    @Slot(str, bool, result=bool)
    def definirNotificar(self, identificador: str, ligado: bool) -> bool:
        nome = _nome(identificador)
        return self._aplicar(
            lambda c: c.com_rede(identificador, notificar=ligado),
            f"{nome}: {'avisa' if ligado else 'não avisa'} quando chegar mensagem",
        )

    @Slot(str, str, str, str, result=bool)
    def adicionarMemoria(self, tipo: str, nome: str, texto: str, telefone: str) -> bool:
        try:
            nova = fixas.nova(tipo, nome, texto, telefone)
        except fixas.MemoriaInvalida as erro:
            self._frase = f"não deu: {erro}"
            self.mudou.emit()
            return False
        return _gravar_memorias(self, (*self._memorias, nova), f"memória «{nova.nome}» guardada")

    @Slot(str, str, str, str, result=bool)
    def editarMemoria(self, identificador: str, nome: str, texto: str, telefone: str) -> bool:
        try:
            novas = fixas.editar(
                self._memorias, identificador, nome=nome, texto=texto, telefone=telefone
            )
        except fixas.MemoriaInvalida as erro:
            self._frase = f"não deu: {erro}"
            self.mudou.emit()
            return False
        return _gravar_memorias(self, novas, "memória atualizada")

    @Slot(str)
    def removerMemoria(self, identificador: str) -> None:
        novas = tuple(m for m in self._memorias if m.id != identificador)
        if len(novas) != len(self._memorias):
            _gravar_memorias(self, novas, "memória apagada")

    # --- o envio (fatia D) -------------------------------------------------------------
    @Slot(bool, result=bool)
    def definirEnvioAutomatico(self, ligado: bool) -> bool:
        """A chave mestra. Desligar também desliga o ausente: nada fica armado sem a chave."""
        return self._aplicar(
            lambda c: c.com_envio(automatico=ligado, ausente=c.envio.ausente and ligado),
            "envio automático no WhatsApp " + ("ligado" if ligado else "desligado"),
        )

    @Slot(bool, result=bool)
    def definirAusente(self, ausente: bool) -> bool:
        if ausente and not self._configuracao.envio.automatico:
            self._frase = "não deu: ligue o envio automático antes do modo ausente"
            self.mudou.emit()
            return False
        return self._aplicar(
            lambda c: c.com_envio(ausente=ausente),
            "modo ausente " + ("ligado: o Jarvis responde a lista" if ausente else "desligado"),
        )

    @Slot()
    def pararEnvios(self) -> None:
        """Parada imediata: desliga o ausente e o envio, grava e corta o que está no ar."""
        self._aplicar(
            lambda c: c.com_envio(automatico=False, ausente=False),
            "envios parados: o Jarvis só notifica",
        )
        if self.ao_parar_envios is not None:
            self.ao_parar_envios()

    @Slot(int, int, result=bool)
    def definirTeto(self, por_hora: int, por_dia: int) -> bool:
        return self._aplicar(
            lambda c: c.com_envio(por_hora=max(0, por_hora), por_dia=max(0, por_dia)),
            f"teto: {max(0, por_hora)} por hora, {max(0, por_dia)} por dia",
        )

    @Slot(str, str, result=bool)
    def adicionarPermitido(self, nome: str, telefone: str) -> bool:
        novo = Permitido(nome.strip(), telefone.strip())
        return self._aplicar(
            lambda c: c.com_envio(permitidos=(*c.envio.permitidos, novo)),
            f"{novo.nome} na lista permitida",
        )

    @Slot(str, str)
    def removerPermitido(self, nome: str, telefone: str) -> None:
        self._aplicar(
            lambda c: c.com_envio(
                permitidos=tuple(
                    p for p in c.envio.permitidos if (p.nome, p.telefone) != (nome, telefone)
                )
            ),
            f"{nome} fora da lista permitida",
        )

    @Slot()
    def tirarPausa(self) -> None:
        """Só o dono tira a pausa de 24 h antes do prazo."""
        try:
            self.pausas.tirar("whatsapp")
        except OSError as erro:
            self._frase = f"não deu: {erro}"
        else:
            self._frase = "pausa tirada: o envio volta a valer (com a lista e o ausente)"
        self.mudou.emit()

    @Slot(str, result=bool)
    def definirNavegadorPreferido(self, familia: str) -> bool:
        return self._aplicar(
            lambda c: c.com_navegador(familia),
            f"redes no navegador {familia}" if familia else "redes no navegador principal",
        )


def _gravar_memorias(ponte: PonteDasRedes, novas: tuple[fixas.MemoriaFixa, ...], ok: str) -> bool:
    try:
        fixas.gravar(novas, ponte._caminho_das_memorias)
    except fixas.MemoriaInvalida as erro:
        ponte._frase = f"não deu: {erro}"
        ponte.mudou.emit()
        return False
    except OSError as erro:
        ponte._memorias = novas
        ponte._frase = f"{ok} — vale agora, mas não deu para salvar ({erro})"
    else:
        ponte._memorias = novas
        ponte._frase = f"{ok} — salvo"
    ponte.mudou.emit()
    return True


def _nome(identificador: str) -> str:
    try:
        return rede(identificador).nome
    except KeyError:
        return identificador[:40]


__all__ = ["EstadoDaRede", "PonteDasRedes", "sem_monitor"]
