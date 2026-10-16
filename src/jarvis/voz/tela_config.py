"""Tela de configuração do `jarvis-voz`: o dono escolhe, e vê o que a escolha custa.

Por que uma tela e não só o TOML: a escolha que mais importa — ligar nuvem — é a que o dono
não pode fazer sem ler o aviso. Editar um arquivo não mostra aviso nenhum; esta tela mostra,
e **pergunta de novo** antes de gravar. É a regra de elevação da §5.5/P12 aplicada ao que ela
cobre de fato: ampliar alcance (mandar dado para fora) é escolha com o dono presente.

Três coisas que esta tela nunca faz:

1. **não mostra chave.** Ela lê o **nome** da variável no registro do motor e diz "definida"
   ou "ausente", com a linha de `export` para copiar. O valor não é lido, não é guardado e
   não aparece — nem truncado, nem mascarado (ver `jarvis.voz.chaves`);
2. **não grava segredo.** O que ela escreve passa pela mesma recusa da leitura;
3. **não liga nuvem sozinha.** Escolher um motor de nuvem **não** o liga: a tela mostra o
   aviso montado dos campos de termo e exige um "sim" digitado. Para o `tts-edge`, que não
   tem termos publicados, exige um segundo "sim" — e é esse que escreve `nuvem_sem_termos`.

A entrada e a saída são injetadas (`entrada`, `saida`), então a tela inteira é testável com
entrada simulada, sem terminal e sem gente.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.audio_io.erros import ErroDeAudio
from jarvis.voz.chaves import Chave
from jarvis.voz.config import (
    ESCUTAS,
    Configuracao,
    caminho_padrao,
    escrever,
    ler,
    validar,
)
from jarvis.voz.interface import Onde
from jarvis.voz.registro import Motor, motores_de
from jarvis.voz.s2_provisorio import nomes_de_gerador

Entrada = Callable[[str], str]
Saida = Callable[[str], None]

CONFIRMACAO: Final = "sim"
"""Digitado por extenso. "s" seria fácil demais para o que esta confirmação significa."""

PADRAO_DO_SISTEMA: Final = "(padrão do sistema)"


def _onde(motor: Motor) -> str:
    return "local" if motor.onde is Onde.LOCAL else "NUVEM"


@dataclass(slots=True)
class TelaDeConfiguracao:
    """O menu. Um laço, uma escolha por vez, nada implícito."""

    caminho: Path = field(default_factory=caminho_padrao)
    entrada: Entrada = input
    saida: Saida = print
    configuracao: Configuracao = field(default_factory=Configuracao)
    salvou: bool = False
    mudou: bool = False

    def __post_init__(self) -> None:
        self.configuracao = ler(self.caminho)

    # --- desenho ------------------------------------------------------------------------
    def _motor(self, identificador: str, papel: str) -> Motor | None:
        return next((m for m in motores_de(papel) if m.id == identificador), None)

    def _linha_de_motor(self, identificador: str, papel: str) -> str:
        motor = self._motor(identificador, papel)
        if motor is None:
            return f"{identificador} (não está no registro!)"
        ligado = motor.onde is Onde.LOCAL or identificador in self.configuracao.nuvem_ligada
        estado = "" if ligado else "  — escolhido, mas DESLIGADO (nuvem exige confirmação)"
        return f"{identificador}  [{_onde(motor)}]{estado}"

    def _linha_de_chaves(self) -> str:
        partes: list[str] = []
        for motor in motores_de(onde=Onde.NUVEM):
            if not motor.variavel_da_chave:
                continue
            estado = "definida" if Chave.presente(motor.variavel_da_chave) else "AUSENTE"
            partes.append(f"{motor.variavel_da_chave}: {estado}")
        return " · ".join(dict.fromkeys(partes)) or "nenhum motor de nuvem pede chave"

    def desenhar(self) -> None:
        configuracao = self.configuracao
        self.saida("")
        self.saida(f"Configuração do jarvis-voz — {self.caminho}")
        self.saida("")
        self.saida(f"  1. Ouvir (ASR) ........ {self._linha_de_motor(configuracao.asr, 'asr')}")
        self.saida(f"  2. Falar (TTS) ........ {self._linha_de_motor(configuracao.tts, 'tts')}")
        self.saida(f"  3. Voz ................ {configuracao.voz or '(nenhuma)'}")
        self.saida(f"  4. Modelo do ASR local  {configuracao.modelo_do_asr}")
        self.saida(f"  5. Resposta (S2) ...... {configuracao.s2}  [provisório até a F2, ADR-0018]")
        self.saida(f"  6. Microfone .......... {configuracao.entrada or PADRAO_DO_SISTEMA}")
        self.saida(f"  7. Alto-falante ....... {configuracao.saida or PADRAO_DO_SISTEMA}")
        self.saida(f"  8. Escuta ............. {configuracao.escuta}  (ptt = tecla, vad = voz)")
        self.saida(f"  9. Chaves de API ...... {self._linha_de_chaves()}")
        self.saida("")
        self.saida("  s. salvar e sair      q. sair sem salvar")

    # --- perguntas ----------------------------------------------------------------------
    def _perguntar(self, pergunta: str) -> str:
        return self.entrada(pergunta).strip()

    def _escolher_da_lista(self, titulo: str, opcoes: Sequence[str], atual: str) -> str | None:
        self.saida("")
        self.saida(titulo)
        for indice, opcao in enumerate(opcoes, start=1):
            marca = " (atual)" if opcao == atual else ""
            self.saida(f"  {indice}. {opcao}{marca}")
        resposta = self._perguntar("número (vazio = manter): ")
        if not resposta:
            return None
        if not resposta.isdigit() or not 1 <= int(resposta) <= len(opcoes):
            self.saida("  não existe essa opção.")
            return None
        return opcoes[int(resposta) - 1]

    def _confirmar_nuvem(self, motor: Motor) -> bool:
        """Mostra o aviso montado dos campos e exige "sim". É o portão com o dono presente."""
        self.saida("")
        self.saida("  ---------------------------------------------------------------")
        for linha in motor.frase_de_aviso.split(". "):
            if linha.strip():
                self.saida(f"  {linha.strip().rstrip('.')}.")
        self.saida("  ---------------------------------------------------------------")
        if self._perguntar(f'  Ligar {motor.id}? digite "{CONFIRMACAO}": ').lower() != CONFIRMACAO:
            self.saida("  não liguei. O motor fica escolhido e desligado.")
            return False
        if set(motor.campos_vazios) & {"uso_comercial", "retencao_declarada"}:
            self.saida("")
            self.saida(
                "  Este serviço NÃO publica termos para este uso: ninguém leu contrato "
                "nenhum, e não dá para saber o que ele faz com o seu texto."
            )
            segunda = self._perguntar(f'  Aceitar mesmo assim? digite "{CONFIRMACAO}": ')
            if segunda.lower() != CONFIRMACAO:
                self.saida("  não liguei.")
                return False
            self.configuracao = self.configuracao.com(
                nuvem_sem_termos=tuple(
                    dict.fromkeys((*self.configuracao.nuvem_sem_termos, motor.id))
                )
            )
        self.configuracao = self.configuracao.com(
            nuvem_ligada=tuple(dict.fromkeys((*self.configuracao.nuvem_ligada, motor.id)))
        )
        chave = motor.variavel_da_chave
        if chave and not Chave.presente(chave):
            self.saida(f"  Falta a chave. No seu shell:  export {chave}=...")
            self.saida("  (a chave nunca entra neste arquivo nem aparece nesta tela)")
        return True

    def _trocar_motor(self, papel: str) -> None:
        opcoes = [m.id for m in motores_de(papel)]
        atual = self.configuracao.asr if papel == "asr" else self.configuracao.tts
        rotulos = [f"{m.id}  [{_onde(m)}]" for m in motores_de(papel)]
        escolhido = self._escolher_da_lista(f"Motores de {papel.upper()}:", rotulos, "")
        if escolhido is None:
            return
        identificador = opcoes[rotulos.index(escolhido)]
        motor = self._motor(identificador, papel)
        assert motor is not None
        self.configuracao = self.configuracao.com(
            **({"asr": identificador} if papel == "asr" else {"tts": identificador})
        )
        self.mudou = self.mudou or identificador != atual
        if motor.onde is Onde.NUVEM and identificador not in self.configuracao.nuvem_ligada:
            self._confirmar_nuvem(motor)

    def _trocar_texto(self, campo: str, pergunta: str) -> None:
        atual = getattr(self.configuracao, campo)
        resposta = self._perguntar(f"{pergunta} (atual: {atual or PADRAO_DO_SISTEMA}): ")
        if not resposta:
            return
        valor = "" if resposta == "-" else resposta
        self.configuracao = self.configuracao.com(**{campo: valor})
        self.mudou = True

    def _escolher_dispositivo(self, campo: str, captura: bool) -> None:
        """Lista o que existe; sem lista (sem PortAudio), aceita índice ou nome digitado."""
        try:
            from jarvis.audio_io.dispositivo import listar_dispositivos

            achados = [d for d in listar_dispositivos() if (d.captura if captura else d.reproducao)]
        except ErroDeAudio as erro:
            self.saida("")
            self.saida(f"  não deu para listar dispositivos: {erro}")
            self._trocar_texto(campo, "  índice ou nome do dispositivo ('-' para o padrão)")
            return
        rotulos = [PADRAO_DO_SISTEMA, *[str(d) for d in achados]]
        escolhido = self._escolher_da_lista(
            "Microfones:" if captura else "Alto-falantes:", rotulos, ""
        )
        if escolhido is None:
            return
        valor = (
            ""
            if escolhido == PADRAO_DO_SISTEMA
            else str(achados[rotulos.index(escolhido) - 1].indice)
        )
        self.configuracao = self.configuracao.com(**{campo: valor})
        self.mudou = True

    def _mostrar_chaves(self) -> None:
        self.saida("")
        self.saida("  As chaves vêm do ambiente, nunca deste arquivo e nunca desta tela:")
        for motor in motores_de(onde=Onde.NUVEM):
            if not motor.variavel_da_chave:
                continue
            estado = "definida" if Chave.presente(motor.variavel_da_chave) else "AUSENTE"
            self.saida(
                f"    {motor.variavel_da_chave}: {estado}    (export {motor.variavel_da_chave}=...)"
            )
        self.saida("  O valor não é lido por esta tela e não aparece em log nenhum.")

    # --- laço ----------------------------------------------------------------------------
    def passo(self, escolha: str) -> bool:
        """Uma escolha. Devolve `False` quando a tela deve fechar."""
        if escolha == "1":
            self._trocar_motor("asr")
        elif escolha == "2":
            self._trocar_motor("tts")
        elif escolha == "3":
            self._trocar_texto("voz", "Voz (nome da voz local, ou voice_id da ElevenLabs)")
        elif escolha == "4":
            self._trocar_texto("modelo_do_asr", "Modelo do whisper local (tiny/base/small/…)")
        elif escolha == "5":
            escolhido = self._escolher_da_lista(
                "Quem responde (provisório até a F2):",
                list(nomes_de_gerador()),
                self.configuracao.s2,
            )
            if escolhido is not None:
                self.configuracao = self.configuracao.com(s2=escolhido)
                self.mudou = True
        elif escolha == "6":
            self._escolher_dispositivo("entrada", captura=True)
        elif escolha == "7":
            self._escolher_dispositivo("saida", captura=False)
        elif escolha == "8":
            escolhido = self._escolher_da_lista(
                "Como o Jarvis escuta:", list(ESCUTAS), self.configuracao.escuta
            )
            if escolhido is not None:
                self.configuracao = self.configuracao.com(escuta=escolhido)
                self.mudou = True
        elif escolha == "9":
            self._mostrar_chaves()
        elif escolha == "s":
            return not self._salvar()
        elif escolha == "q":
            if self.mudou:
                self.saida("  saindo sem salvar (as mudanças desta sessão se perdem).")
            return False
        else:
            self.saida("  escolha um número, 's' para salvar ou 'q' para sair.")
        return True

    def _salvar(self) -> bool:
        try:
            escrever(validar(self.configuracao), self.caminho)
        except (ValueError, OSError) as erro:
            self.saida(f"  não deu para salvar: {erro}")
            return False
        self.salvou = True
        self.saida(f"  salvo em {self.caminho}")
        return True

    def rodar(self) -> int:
        """O laço da tela. Devolve o código de saída do processo."""
        while True:
            self.desenhar()
            try:
                escolha = self._perguntar("> ").lower()
            except (EOFError, KeyboardInterrupt):
                self.saida("")
                return 0
            if not self.passo(escolha):
                return 0
