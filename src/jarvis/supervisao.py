"""Sobe e desce os sete processos, por PID registrado (cartão F0-03).

Regra de ouro do projeto: **nunca** procurar processo por nome nem matar por padrão de linha
de comando. Este supervisor só conhece os `Popen` que ele mesmo criou, encerra pelo objeto e
confere o retorno. Nada aqui toca processo que não seja filho desta sessão.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PROCESSOS_CLIENTES: tuple[str, ...] = ("s2", "policy", "executor", "memoryd", "ui")
MODULO: dict[str, str] = {
    "agentd": "jarvis.agentd",
    "audio-io": "jarvis.audio_io",
    "s2": "jarvis.s2",
    "policy": "jarvis.policy",
    "executor": "jarvis.executor",
    "memoryd": "jarvis.memoryd",
    "ui": "jarvis.ui",
}


@dataclass(slots=True)
class Supervisor:
    """Ciclo de vida dos processos desta sessão, por PID registrado."""

    raiz: Path
    filhos: dict[str, subprocess.Popen[bytes]] = field(default_factory=dict)

    def iniciar(self, nome: str, *extras: str) -> subprocess.Popen[bytes]:
        if nome in self.filhos and self.filhos[nome].poll() is None:
            raise RuntimeError(f"{nome} já está rodando (pid {self.filhos[nome].pid})")
        argv = [sys.executable, "-m", MODULO[nome], "--raiz", str(self.raiz), *extras]
        filho = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # noqa: S603
        self.filhos[nome] = filho
        return filho

    def esperar_barramento(self, *, limite: float = 10.0) -> None:
        """Espera o corretor publicar o arquivo `pronto` — sem laço cego."""
        fim = time.monotonic() + limite
        pronto = self.raiz / "pronto"
        while time.monotonic() < fim:
            if pronto.exists() and (self.raiz / "sessao").exists():
                return
            time.sleep(0.05)
        raise TimeoutError(f"barramento não subiu em {limite}s (raiz {self.raiz})")

    def parar(self, nome: str, *, limite: float = 5.0) -> int | None:
        """Encerra um filho pelo PID registrado e confere que saiu."""
        filho = self.filhos.get(nome)
        if filho is None:
            return None
        if filho.poll() is None:
            filho.terminate()
            try:
                filho.wait(timeout=limite)
            except subprocess.TimeoutExpired:
                filho.kill()
                filho.wait(timeout=limite)
        return filho.returncode

    def parar_tudo(self) -> dict[str, int | None]:
        return {nome: self.parar(nome) for nome in list(self.filhos)}

    def vivo(self, nome: str) -> bool:
        filho = self.filhos.get(nome)
        return filho is not None and filho.poll() is None

    def saida(self, nome: str) -> str:
        """stdout+stderr do filho já encerrado, para aparecer no relatório de falha."""
        filho = self.filhos.get(nome)
        if filho is None:
            return ""
        fora, erro = filho.communicate(timeout=5) if filho.poll() is None else filho.communicate()
        return (fora or b"").decode("utf-8", "replace") + (erro or b"").decode("utf-8", "replace")
