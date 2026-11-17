"""Retenção da memória de quem ligou e dos recados (ADR-0074; decisão do dono de 2026-11-17: até
90 dias, configurável). O vencido sai do DISCO ao abrir e ao salvar — relógio falso."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from jarvis.chamada.memoria import (
    DIA_S,
    RETENCAO_PADRAO_DIAS,
    MemoriaDosInterlocutores,
    Recados,
)

AGORA = 1_800_000_000.0


def _no_disco(caminho: Path) -> object:
    return json.loads(caminho.read_text(encoding="utf-8"))


def test_padrao_e_90_dias() -> None:
    assert RETENCAO_PADRAO_DIAS == 90
    assert MemoriaDosInterlocutores().retencao_dias() == 90
    assert Recados().retencao_dias() == 90


def test_nota_vencida_sai_do_disco_ao_abrir(tmp_path: Path) -> None:
    caminho = tmp_path / "chamada-interlocutores.json"
    relogio = [AGORA]
    memoria = MemoriaDosInterlocutores(caminho, relogio=lambda: relogio[0])
    memoria.lembrar("Ana", "a festa é sábado")
    relogio[0] += 60 * DIA_S
    memoria.lembrar("Ana", "levar o bolo")
    memoria.lembrar("Bruno", "volta a ligar")
    # 91 dias depois da primeira nota: ela venceu, as outras (31 dias) não.
    relogio[0] = AGORA + 91 * DIA_S
    reaberta = MemoriaDosInterlocutores(caminho, relogio=lambda: relogio[0])
    disco = _no_disco(caminho)
    assert isinstance(disco, dict)
    assert [n["nota"] for n in disco["ana"]] == ["levar o bolo"]
    assert [n["nota"] for n in reaberta.notas("Ana")] == ["levar o bolo"]
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o600
    # Mais 60 dias: tudo venceu; ao abrir, o arquivo fica vazio, sem o nome de ninguém.
    relogio[0] += 60 * DIA_S
    MemoriaDosInterlocutores(caminho, relogio=lambda: relogio[0])
    assert _no_disco(caminho) == {}


def test_nota_vencida_sai_ao_salvar_mesmo_sem_reabrir(tmp_path: Path) -> None:
    caminho = tmp_path / "m.json"
    relogio = [AGORA]
    memoria = MemoriaDosInterlocutores(caminho, relogio=lambda: relogio[0])
    memoria.lembrar("Ana", "antiga")
    relogio[0] += 100 * DIA_S
    memoria.lembrar("Carla", "nova")
    disco = _no_disco(caminho)
    assert isinstance(disco, dict) and set(disco) == {"carla"}


def test_retencao_configuravel_vale_na_hora(tmp_path: Path) -> None:
    caminho = tmp_path / "m.json"
    relogio = [AGORA]
    dias = [90]
    memoria = MemoriaDosInterlocutores(
        caminho, retencao_dias=lambda: dias[0], relogio=lambda: relogio[0]
    )
    memoria.lembrar("Ana", "nota")
    relogio[0] += 40 * DIA_S
    assert memoria.notas("Ana")
    dias[0] = 30  # o dono apertou na aba
    assert memoria.notas("Ana") == [], "o vencido nunca é devolvido"
    assert memoria.apagar_vencidas() == 1
    assert _no_disco(caminho) == {}


def test_recado_vencido_sai_do_disco_ao_abrir_e_ao_salvar(tmp_path: Path) -> None:
    caminho = tmp_path / "chamada-recados.json"
    relogio = [AGORA]
    recados = Recados(caminho, relogio=lambda: relogio[0])
    recados.guardar({"assunto": "orçamento", "texto": "ligar amanhã"})
    relogio[0] += 89 * DIA_S
    assert len(Recados(caminho, relogio=lambda: relogio[0]).todos()) == 1, "89 dias ainda vale"
    relogio[0] += 2 * DIA_S
    Recados(caminho, relogio=lambda: relogio[0])
    assert _no_disco(caminho) == {"recados": []}
    recados.guardar({"assunto": "novo", "texto": "x"})
    relogio[0] += 91 * DIA_S
    recados.guardar({"assunto": "mais novo", "texto": "y"})
    disco = _no_disco(caminho)
    assert isinstance(disco, dict)
    assert [r["assunto"] for r in disco["recados"]] == ["mais novo"]


def test_arquivo_sem_nada_vencido_nao_e_regravado(tmp_path: Path) -> None:
    caminho = tmp_path / "m.json"
    MemoriaDosInterlocutores(caminho, relogio=lambda: AGORA).lembrar("Ana", "x")
    antes = caminho.stat().st_mtime_ns
    assert MemoriaDosInterlocutores(caminho, relogio=lambda: AGORA + DIA_S).apagar_vencidas() == 0
    assert caminho.stat().st_mtime_ns == antes
