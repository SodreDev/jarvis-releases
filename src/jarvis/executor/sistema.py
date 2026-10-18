"""Hora, estado da máquina, volume e brilho — o que um assistente de voz consulta o tempo todo.

Tudo tipado e sem shell. Leitura do sistema vai direto em `/proc` e `/sys` (a raiz é injetável: o
teste monta uma árvore falsa); volume e brilho chamam o desktop por `comandos.py` (lançador
injetável). Onde a máquina não tem o que se pede (sem bateria, sem `wpctl`), a resposta diz isso em
vez de inventar um número.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from jarvis.executor.comandos import ComandoIndisponivel, Lancador, Saida

DIAS: Final = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MESES: Final = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
SINK: Final = "@DEFAULT_AUDIO_SINK@"
PASSO_DA_AMOSTRA_DE_CPU_S: Final = 0.15


# --- hora -----------------------------------------------------------------------------------
def hora_agora(agora: Callable[[], datetime]) -> dict[str, Any]:
    """A data e a hora locais, já escritas do jeito que se fala."""
    t = agora().astimezone()
    return {
        "iso": t.isoformat(timespec="seconds"),
        "data_por_extenso": f"{DIAS[t.weekday()]}, {t.day} de {MESES[t.month - 1]} de {t.year}",
        "hora": t.strftime("%H:%M"),
        "fuso": t.tzname() or "",
        "dia_da_semana": DIAS[t.weekday()],
    }


# --- estado da máquina ----------------------------------------------------------------------
def _ler(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _bateria(raiz: Path) -> dict[str, Any] | None:
    pasta = raiz / "sys/class/power_supply"
    if not pasta.is_dir():
        return None
    for item in sorted(pasta.iterdir()):
        if _ler(item / "type") != "Battery":
            continue
        capacidade = _ler(item / "capacity")
        if not capacidade.isdigit():
            continue
        tomada = any(
            _ler(o / "online") == "1"
            for o in pasta.iterdir()
            if _ler(o / "type") in ("Mains", "USB")
        )
        return {
            "porcentagem": int(capacidade),
            "estado": _ler(item / "status") or "desconhecido",
            "na_tomada": tomada,
        }
    return None


def _rede(raiz: Path) -> dict[str, Any]:
    pasta = raiz / "sys/class/net"
    ativas: list[dict[str, str]] = []
    if pasta.is_dir():
        for item in sorted(pasta.iterdir()):
            if item.name == "lo" or _ler(item / "operstate") != "up":
                continue
            tipo = "wifi" if (item / "wireless").exists() else "cabo"
            ativas.append({"interface": item.name, "tipo": tipo})
    return {"conectada": bool(ativas), "interfaces": ativas}


def _memoria(raiz: Path) -> dict[str, Any] | None:
    valores: dict[str, int] = {}
    for linha in _ler(raiz / "proc/meminfo").splitlines():
        m = re.match(r"(\w+):\s+(\d+) kB", linha)
        if m:
            valores[m.group(1)] = int(m.group(2))
    total, livre = valores.get("MemTotal"), valores.get("MemAvailable")
    if not total or livre is None:
        return None
    usada = total - livre
    return {
        "total_gb": round(total / 1048576, 1),
        "usada_gb": round(usada / 1048576, 1),
        "usada_pct": round(100 * usada / total),
    }


def _tempos_da_cpu(raiz: Path) -> tuple[int, int] | None:
    primeira = _ler(raiz / "proc/stat").splitlines()[:1]
    if not primeira or not primeira[0].startswith("cpu "):
        return None
    partes = [int(x) for x in primeira[0].split()[1:8]]
    ocioso = partes[3] + partes[4]
    return sum(partes), ocioso


def _cpu(raiz: Path, dormir: Callable[[float], None]) -> dict[str, Any] | None:
    antes = _tempos_da_cpu(raiz)
    if antes is None:
        return None
    dormir(PASSO_DA_AMOSTRA_DE_CPU_S)
    depois = _tempos_da_cpu(raiz)
    nucleos = os.cpu_count() or 1
    if depois is None or depois[0] == antes[0]:
        return {"nucleos": nucleos}
    total, ocioso = depois[0] - antes[0], depois[1] - antes[1]
    return {"uso_pct": round(100 * (total - ocioso) / total), "nucleos": nucleos}


def estado_da_maquina(
    *, raiz: Path = Path("/"), lar: Path, dormir: Callable[[float], None] = time.sleep
) -> dict[str, Any]:
    """Bateria, rede, CPU, RAM e disco. O que a máquina não tem, não aparece (nada inventado)."""
    saida: dict[str, Any] = {"rede": _rede(raiz)}
    for chave, valor in (
        ("bateria", _bateria(raiz)),
        ("cpu", _cpu(raiz, dormir)),
        ("memoria", _memoria(raiz)),
    ):
        if valor is not None:
            saida[chave] = valor
    try:
        uso = shutil.disk_usage(lar)
        saida["disco"] = {
            "livre_gb": round(uso.free / 1e9, 1),
            "total_gb": round(uso.total / 1e9, 1),
            "usado_pct": round(100 * uso.used / uso.total),
        }
    except OSError:
        pass
    if "bateria" not in saida:
        saida["observacao"] = "esta máquina não tem bateria"
    return saida


# --- volume (wpctl, com pactl de reserva) ---------------------------------------------------------
def _volume_de_wpctl(texto: str) -> tuple[int, bool] | None:
    m = re.search(r"Volume:\s*([\d.]+)", texto)
    return (round(float(m.group(1)) * 100), "[MUTED]" in texto) if m else None


def volume_atual(lancar: Lancador) -> dict[str, Any]:
    try:
        saida = lancar(["wpctl", "get-volume", SINK], 3.0, None)
        lido = _volume_de_wpctl(saida.saida) if saida.ok else None
        if lido is not None:
            return {"volume_pct": lido[0], "mudo": lido[1]}
    except ComandoIndisponivel:
        pass
    saida = lancar(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], 3.0, None)
    m = re.search(r"(\d+)%", saida.saida)
    if not saida.ok or m is None:
        raise ComandoIndisponivel("não consegui ler o volume (nem wpctl nem pactl responderam)")
    mudo = "yes" in lancar(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], 3.0, None).saida
    return {"volume_pct": int(m.group(1)), "mudo": mudo}


def definir_volume(
    lancar: Lancador,
    *,
    nivel: int | None = None,
    delta: int | None = None,
    mudo: bool | None = None,
) -> dict[str, Any]:
    """Nível 0–100 **ou** delta ±, e/ou mudo. Nunca acima de 100% (alto-falante não é desafio)."""
    if nivel is None and delta is None and mudo is None:
        raise ValueError("diga o `nivel` (0 a 100), um `delta` (+/-) ou `mudo`")
    if nivel is not None and delta is not None:
        raise ValueError("use `nivel` ou `delta`, não os dois")
    if nivel is not None or delta is not None:
        atual = volume_atual(lancar)["volume_pct"] if nivel is None else 0
        alvo = max(0, min(100, nivel if nivel is not None else atual + int(delta or 0)))
        try:
            saida = lancar(
                ["wpctl", "set-volume", "-l", "1.0", SINK, f"{alvo / 100:.2f}"], 3.0, None
            )
            feito = saida.ok
        except ComandoIndisponivel:
            feito = False
        if not feito:
            saida = lancar(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{alvo}%"], 3.0, None)
            if not saida.ok:
                raise ComandoIndisponivel(f"não consegui mudar o volume: {saida.erro.strip()[:80]}")
    if mudo is not None:
        try:
            lancar(["wpctl", "set-mute", SINK, "1" if mudo else "0"], 3.0, None)
        except ComandoIndisponivel:
            lancar(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if mudo else "0"], 3.0, None)
    return volume_atual(lancar)


# --- brilho (KDE/PowerDevil por D-Bus, com brightnessctl de reserva) ---------------
PD: Final = (
    "--session",
    "--dest",
    "org.kde.Solid.PowerManagement",
    "--object-path",
    "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
)
PD_METODO: Final = "org.kde.Solid.PowerManagement.Actions.BrightnessControl."


def _inteiro_do_gdbus(saida: Saida) -> int | None:
    m = re.search(r"\(?\s*(?:int32\s+)?(\d+)\s*,?\s*\)?", saida.saida)
    return int(m.group(1)) if saida.ok and m else None


def definir_brilho(
    lancar: Lancador, *, nivel: int | None = None, delta: int | None = None
) -> dict[str, Any]:
    if (nivel is None) == (delta is None):
        raise ValueError("diga o `nivel` (0 a 100) ou um `delta` (+/-), um dos dois")
    try:
        maximo = _inteiro_do_gdbus(
            lancar(["gdbus", "call", *PD, "--method", PD_METODO + "brightnessMax"], 3.0, None)
        )
        atual = _inteiro_do_gdbus(
            lancar(["gdbus", "call", *PD, "--method", PD_METODO + "brightness"], 3.0, None)
        )
        if maximo and atual is not None:
            alvo_pct = max(
                1,
                min(
                    100,
                    nivel if nivel is not None else round(100 * atual / maximo) + int(delta or 0),
                ),
            )
            bruto = max(1, round(maximo * alvo_pct / 100))
            feito = lancar(
                ["gdbus", "call", *PD, "--method", PD_METODO + "setBrightness", str(bruto)],
                3.0,
                None,
            )
            if feito.ok:
                return {"brilho_pct": alvo_pct}
    except ComandoIndisponivel:
        pass
    alvo = (
        f"{max(1, min(100, nivel))}%"
        if nivel is not None
        else f"{abs(int(delta or 0))}%{'+' if (delta or 0) > 0 else '-'}"
    )
    saida = lancar(["brightnessctl", "set", alvo], 3.0, None)
    if not saida.ok:
        raise ComandoIndisponivel(
            "não consegui mudar o brilho (PowerDevil e brightnessctl não responderam)"
        )
    m = re.search(r"\((\d+)%\)", saida.saida)
    return {"brilho_pct": int(m.group(1)) if m else nivel if nivel is not None else -1}
