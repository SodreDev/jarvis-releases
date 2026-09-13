# comandos/system_ctrl.py — J.A.R.V.I.S.
# Controles do sistema, screenshot, volume, clipboard, timer, clima, processos, histórico
# -*- coding: utf-8 -*-

import json
import math
import datetime
import os
import platform
import subprocess
import threading

from config import PATHS

_HISTORICO_FILE = PATHS["historico"]

# ─────────────────────────────────────────────────────────────────────────────
# DESLIGAMENTO / SISTEMA
# ─────────────────────────────────────────────────────────────────────────────

def desligar(delay: int = 10) -> str:
    if platform.system() == "Windows":
        subprocess.Popen(["shutdown", "/s", "/t", str(delay)], shell=False)
    else:
        subprocess.Popen(["shutdown", "-h", f"+{delay // 60 or 1}"], shell=False)
    return f"Computador será desligado em {delay} segundos, Senhor."


def reiniciar(delay: int = 10) -> str:
    if platform.system() == "Windows":
        subprocess.Popen(["shutdown", "/r", "/t", str(delay)], shell=False)
    else:
        subprocess.Popen(["shutdown", "-r", f"+{delay // 60 or 1}"], shell=False)
    return f"Reiniciando em {delay} segundos, Senhor."


def cancelar_desligamento() -> str:
    if platform.system() == "Windows":
        subprocess.Popen(["shutdown", "/a"], shell=False)
    return "Desligamento cancelado, Senhor."


def bloquear_tela() -> str:
    if platform.system() == "Windows":
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"], shell=False)
    elif platform.system() == "Darwin":
        subprocess.Popen(["pmset", "displaysleepnow"], shell=False)
    return "Tela bloqueada, Senhor."


def modo_sleep() -> str:
    if platform.system() == "Windows":
        # SetSuspendState: hibernate=0, forceFlag=1, wakeupEventsDisabled=0
        subprocess.Popen(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], shell=False
        )
    elif platform.system() == "Darwin":
        subprocess.Popen(["pmset", "sleepnow"], shell=False)
    return "Entrando em modo de espera, Senhor."


# ─────────────────────────────────────────────────────────────────────────────
# SCREENSHOT
# ─────────────────────────────────────────────────────────────────────────────

def tirar_screenshot(pasta: str = "screenshots") -> tuple[str, str]:
    os.makedirs(pasta, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(pasta, f"jarvis_{ts}.png")
    try:
        import pyautogui
        pyautogui.screenshot(caminho)
    except Exception:
        try:
            from PIL import ImageGrab
            ImageGrab.grab().save(caminho)
        except Exception as e:
            return "", f"Falha ao capturar tela: {e}"
    # Abre a pasta no Explorer
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["explorer", "/select,", os.path.abspath(caminho)], shell=False)
    except Exception:
        pass
    return caminho, f"Screenshot salvo em '{caminho}', Senhor."


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME DO SISTEMA (Windows — pycaw)
# ─────────────────────────────────────────────────────────────────────────────

def _get_audio_volume():
    """Obtém a interface de volume do sistema (robusta para diferentes versões pycaw)."""
    import comtypes
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    # Garante COM inicializado nesta thread (essencial quando chamado de threads)
    try:
        comtypes.CoInitialize()
    except OSError:
        pass  # Já inicializado

    speakers = AudioUtilities.GetSpeakers()

    # Compatibilidade: pycaw pode retornar IMMDevice (COM) ou AudioDevice wrapper
    if not hasattr(speakers, 'Activate'):
        dev = getattr(speakers, '_dev', None)
        if dev is not None and hasattr(dev, 'Activate'):
            speakers = dev
        else:
            raise RuntimeError(
                f"Dispositivo de áudio incompatível: {type(speakers).__name__}"
            )

    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def set_volume(nivel: int) -> str:
    nivel = max(0, min(100, nivel))
    try:
        vol = _get_audio_volume()
        vol.SetMasterVolumeLevelScalar(nivel / 100.0, None)
        return f"Volume do sistema ajustado para {nivel}%, Senhor."
    except Exception as e:
        return f"Não foi possível ajustar o volume: {e}"


def get_volume() -> str:
    try:
        vol = _get_audio_volume()
        pct = int(vol.GetMasterVolumeLevelScalar() * 100)
        return f"Volume atual do sistema: {pct}%, Senhor."
    except Exception as e:
        return f"Não foi possível obter o volume: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# VOLUME DO MICROFONE (Windows — pycaw)
# ─────────────────────────────────────────────────────────────────────────────

def _get_mic_volume():
    """Obtém a interface de volume do microfone padrão (input device)."""
    import comtypes
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    try:
        comtypes.CoInitialize()
    except OSError:
        pass

    mic = AudioUtilities.GetMicrophone()
    if mic is None:
        raise RuntimeError("Nenhum microfone encontrado no sistema.")

    if not hasattr(mic, 'Activate'):
        dev = getattr(mic, '_dev', None)
        if dev is not None and hasattr(dev, 'Activate'):
            mic = dev
        else:
            raise RuntimeError(
                f"Dispositivo de microfone incompatível: {type(mic).__name__}"
            )

    interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def set_mic_volume(nivel: int) -> str:
    """Define o volume do microfone (0–100%)."""
    nivel = max(0, min(100, nivel))
    try:
        vol = _get_mic_volume()
        vol.SetMasterVolumeLevelScalar(nivel / 100.0, None)
        return f"Volume do microfone ajustado para {nivel}%, Senhor."
    except Exception as e:
        return f"Não foi possível ajustar o volume do microfone: {e}"


def get_mic_volume() -> str:
    """Retorna o volume atual do microfone."""
    try:
        vol = _get_mic_volume()
        pct = int(vol.GetMasterVolumeLevelScalar() * 100)
        return f"Volume atual do microfone: {pct}%, Senhor."
    except Exception as e:
        return f"Não foi possível obter o volume do microfone: {e}"


def maximizar_mic() -> str:
    """Maximiza o volume do microfone para 100%."""
    return set_mic_volume(100)


def desativar_ajuste_automatico_mic() -> str:
    """Desativa o ajuste automático de volume do microfone no Windows.

    Age em duas frentes:
    1. Registry: desliga a redução automática do Communications (Painel de Controle > Som > Comunicações)
    2. Maximiza o volume do microfone imediatamente
    """
    import winreg

    msgs = []

    # 1. Registry: HKCU\SOFTWARE\Microsoft\Multimedia\Audio
    # NoDGVol: 0=Reduce 80%, 1=Reduce 50%, 2=Do nothing, 3=Mute
    # Queremos 3 (Do nothing = não mexer no volume)
    try:
        key_path = r"SOFTWARE\Microsoft\Multimedia\Audio"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0,
                                winreg.KEY_SET_VALUE) as key:
            # Valor 3 = "Do nothing" (não reduzir volume durante comunicações)
            winreg.SetValueEx(key, "UserDuckingPreference", 0, winreg.REG_DWORD, 3)
        msgs.append("Ajuste automático de volume desativado no registro do Windows")
    except Exception as e:
        msgs.append(f"Falha ao alterar registro: {e}")

    # 2. Maximizar volume do microfone
    try:
        vol = _get_mic_volume()
        vol.SetMasterVolumeLevelScalar(1.0, None)
        msgs.append("volume do microfone maximizado para 100%")
    except Exception as e:
        msgs.append(f"falha ao maximizar microfone: {e}")

    return ". ".join(msgs) + ", Senhor."


def garantir_mic_maximo() -> None:
    """Chamada silenciosa: garante mic em 100%. Não retorna mensagem."""
    try:
        vol = _get_mic_volume()
        current = vol.GetMasterVolumeLevelScalar()
        if current < 0.99:
            vol.SetMasterVolumeLevelScalar(1.0, None)
            print(f"[MIC] Volume estava em {int(current*100)}% — restaurado para 100%")
    except Exception:
        pass  # silencioso


# ─────────────────────────────────────────────────────────────────────────────
# CLIPBOARD
# ─────────────────────────────────────────────────────────────────────────────

def get_clipboard() -> str:
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception:
        return ""


def set_clipboard(texto: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(texto)
        return "Copiado para a área de transferência, Senhor."
    except Exception as e:
        return f"Não foi possível copiar: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# TIMER / LEMBRETE
# ─────────────────────────────────────────────────────────────────────────────

_timers: dict[str, dict] = {}   # id → {"timer": threading.Timer, "label": str, "fim": datetime}
_timer_lock = threading.Lock()


def iniciar_timer(segundos: int, label: str, callback) -> tuple[str, str]:
    """
    Inicia um timer. Quando disparar, chama callback(mensagem).
    Retorna (mensagem_confirmação, timer_id).
    """
    timer_id = f"t{len(_timers) + 1}"
    fim = datetime.datetime.now() + datetime.timedelta(seconds=segundos)

    def _disparar():
        with _timer_lock:
            _timers.pop(timer_id, None)
        callback(f"⏰ Timer concluído: '{label}', Senhor.")

    t = threading.Timer(segundos, _disparar)
    t.daemon = True

    with _timer_lock:
        _timers[timer_id] = {"timer": t, "label": label, "fim": fim}
    t.start()

    if segundos >= 3600:
        h, m = divmod(segundos // 60, 60)
        dur = f"{h}h{m:02d}min" if m else f"{h}h"
    elif segundos >= 60:
        dur = f"{segundos // 60} min"
    else:
        dur = f"{segundos}s"

    return f"Timer de {dur} iniciado: '{label}', Senhor.", timer_id


def cancelar_timers() -> str:
    with _timer_lock:
        for d in _timers.values():
            d["timer"].cancel()
        n = len(_timers)
        _timers.clear()
    return f"{n} timer(s) cancelado(s), Senhor." if n else "Nenhum timer ativo, Senhor."


def timers_ativos() -> list[dict]:
    """Retorna lista de timers ativos com tempo restante em segundos."""
    agora = datetime.datetime.now()
    ativos = []
    with _timer_lock:
        for tid, d in list(_timers.items()):
            restante = max(0, int((d["fim"] - agora).total_seconds()))
            ativos.append({"id": tid, "label": d["label"], "restante": restante})
    return ativos


# ─────────────────────────────────────────────────────────────────────────────
# CLIMA (Open-Meteo — sem API key)
# ─────────────────────────────────────────────────────────────────────────────

_WMO: dict[int, str] = {
    0: "☀️ Céu limpo", 1: "🌤️ Principalmente limpo", 2: "⛅ Parcialmente nublado",
    3: "☁️ Nublado", 45: "🌫️ Névoa", 48: "🌫️ Névoa com gelo",
    51: "🌦️ Chuvisco leve", 53: "🌦️ Chuvisco moderado", 55: "🌧️ Chuvisco intenso",
    61: "🌧️ Chuva leve", 63: "🌧️ Chuva moderada", 65: "🌧️ Chuva forte",
    71: "❄️ Neve leve", 73: "❄️ Neve moderada", 75: "❄️ Neve forte",
    80: "🌦️ Pancadas leves", 81: "🌧️ Pancadas moderadas", 82: "⛈️ Pancadas fortes",
    95: "⛈️ Trovoada", 96: "⛈️ Trovoada c/ granizo", 99: "⛈️ Trovoada severa",
}


def get_clima(cidade: str) -> dict | str:
    try:
        import urllib.request
        import urllib.parse
        import json as _json

        # 1. Geocoding
        geo_url = (
            f"https://geocoding-api.open-meteo.com/v1/search"
            f"?name={urllib.parse.quote(cidade)}&count=1&language=pt&format=json"
        )
        with urllib.request.urlopen(geo_url, timeout=6) as r:
            geo = _json.loads(r.read())

        results = geo.get("results")
        if not results:
            return f"Cidade '{cidade}' não encontrada, Senhor."

        loc = results[0]
        lat, lon = loc["latitude"], loc["longitude"]
        nome = loc.get("name", cidade)
        pais = loc.get("country", "")

        # 2. Previsão atual
        fc_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            f"weather_code,wind_speed_10m,precipitation"
            f"&timezone=auto"
        )
        with urllib.request.urlopen(fc_url, timeout=6) as r:
            fc = _json.loads(r.read())

        curr = fc.get("current", {})
        return {
            "cidade": nome,
            "pais": pais,
            "temp": curr.get("temperature_2m", "?"),
            "feels": curr.get("apparent_temperature", "?"),
            "hum": curr.get("relative_humidity_2m", "?"),
            "wind": curr.get("wind_speed_10m", "?"),
            "chuva": curr.get("precipitation", 0),
            "cond": _WMO.get(curr.get("weather_code", 0), "Condição desconhecida"),
        }
    except Exception as e:
        return f"Não foi possível obter o clima: {e}"


def formatar_clima(dados) -> str:
    if isinstance(dados, str):
        return dados
    return (
        f"{dados['cond']} em {dados['cidade']}, {dados['pais']}\n"
        f"Temperatura: {dados['temp']}°C  (sensação {dados['feels']}°C)\n"
        f"Umidade: {dados['hum']}%   Vento: {dados['wind']} km/h"
        + (f"   Chuva: {dados['chuva']} mm" if dados['chuva'] else "")
    )


# ─────────────────────────────────────────────────────────────────────────────
# CALCULADORA SEGURA
# ─────────────────────────────────────────────────────────────────────────────

_SAFE_NAMES = {
    "sqrt": math.sqrt, "raiz": math.sqrt, "abs": abs,
    "pi": math.pi, "e": math.e,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "pow": math.pow,
    "ceil": math.ceil, "floor": math.floor, "round": round,
    "fatorial": math.factorial, "factorial": math.factorial,
}

_SAFE_CHARS = frozenset("0123456789+-*/().,% \t\n_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def calcular(expr: str) -> str:
    import re as _re  # Remove artigos/pronomes iniciais que o STT costuma incluir
    expr = _re.sub(r"^(?:a\s+|o\s+|da\s+|de\s+|do\s+)+", "", expr, flags=_re.I).strip()
    # Remove pontuação final
    expr = expr.rstrip("?!.,;").strip()
    # Substituições PT → Python
    expr = _re.sub(r"\b(?:a\s+)?raiz\s+quadrada\s+de\s+", "sqrt(", expr, flags=_re.I)
    expr = _re.sub(r"\braiz\s+(?:de\s+)?", "sqrt(", expr, flags=_re.I)
    expr = _re.sub(r"\bfatorial\s+(?:de\s+)?(\d+)", r"fatorial(\1)", expr, flags=_re.I)
    expr = _re.sub(r"\bpor\s+cento\b", "/100", expr, flags=_re.I)
    expr = _re.sub(r"\bvezes\b", "*", expr, flags=_re.I)
    expr = _re.sub(r"\bdividido\s+por\b", "/", expr, flags=_re.I)
    expr = _re.sub(r"\bmais\b", "+", expr, flags=_re.I)
    expr = _re.sub(r"\bmenos\b", "-", expr, flags=_re.I)
    expr = _re.sub(r"\bao\s+quadrado\b", "**2", expr, flags=_re.I)
    expr = _re.sub(r"\bao\s+cubo\b", "**3", expr, flags=_re.I)
    expr = _re.sub(r",", ".", expr)  # vírgula decimal

    # Fecha parênteses abertos por "raiz("
    opens = expr.count("(") - expr.count(")")
    expr += ")" * max(0, opens)

    # Validação de segurança
    if not all(c in _SAFE_CHARS for c in expr):
        return None  # Sinaliza que deve ir para a IA

    try:
        result = eval(expr, {"__builtins__": {}}, _SAFE_NAMES)  # noqa: S307
        if isinstance(result, float):
            result = round(result, 10)
            if result == int(result):
                result = int(result)
        return f"Resultado: {result}"
    except Exception:
        return None  # Sinaliza que deve ir para a IA


# ─────────────────────────────────────────────────────────────────────────────
# PROCESSOS (psutil)
# ─────────────────────────────────────────────────────────────────────────────

def listar_processos(top_n: int = 12) -> str:
    try:
        import psutil
        procs = sorted(
            psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
            key=lambda p: p.info.get("memory_percent") or 0,
            reverse=True,
        )[:top_n]
        linhas = [f"{'PID':>7}  {'CPU%':>5}  {'MEM%':>5}  PROCESSO"]
        linhas.append("─" * 42)
        for p in procs:
            linhas.append(
                f"{p.info['pid']:>7}  "
                f"{p.info.get('cpu_percent') or 0:>5.1f}  "
                f"{p.info.get('memory_percent') or 0:>5.1f}  "
                f"{p.info['name']}"
            )
        return "\n".join(linhas)
    except Exception as e:
        return f"Erro ao listar processos: {e}"


def matar_processo(nome: str) -> str:
    try:
        import psutil
        mortos = []
        for p in psutil.process_iter(["pid", "name"]):
            if nome.lower() in (p.info.get("name") or "").lower():
                try:
                    p.kill()
                    mortos.append(p.info["name"])
                except psutil.AccessDenied:
                    pass
        if mortos:
            return f"Processo(s) encerrado(s): {', '.join(set(mortos))}, Senhor."
        return f"Nenhum processo '{nome}' encontrado, Senhor."
    except Exception as e:
        return f"Erro ao encerrar processo: {e}"


def memoria_processo(nome: str) -> str:
    try:
        import psutil
        encontrados = []
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            if nome.lower() in (p.info.get("name") or "").lower():
                mb = (p.info.get("memory_info") or type("", (), {"rss": 0})()).rss / (1024 * 1024)
                encontrados.append(f"{p.info['name']} (PID {p.info['pid']}): {mb:.1f} MB")
        if encontrados:
            return "\n".join(encontrados)
        return f"Processo '{nome}' não encontrado em execução, Senhor."
    except Exception as e:
        return f"Erro: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# HISTÓRICO DE COMANDOS
# ─────────────────────────────────────────────────────────────────────────────

def salvar_comando(texto: str, origem: str = "texto") -> None:
    """Anexa o comando ao arquivo JSONL de histórico."""
    try:
        entrada = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "origem": origem,
            "texto": texto,
        }
        with open(_HISTORICO_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
    except Exception:
        pass


def historico_hoje(n: int = 20) -> str:
    hoje = datetime.date.today().isoformat()
    try:
        with open(_HISTORICO_FILE, "r", encoding="utf-8") as f:
            linhas = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return "Nenhum comando registrado ainda, Senhor."
    de_hoje = [l for l in linhas if l["ts"].startswith(hoje)][-n:]
    if not de_hoje:
        return "Nenhum comando registrado hoje, Senhor."
    resultado = [f"Comandos de hoje ({len(de_hoje)}):"]
    for i, l in enumerate(de_hoje, 1):
        hora = l["ts"][11:19]
        icone = "🎤" if l.get("origem") == "voz" else "⌨"
        resultado.append(f"  {i:>2}. [{hora}] {icone} {l['texto'][:80]}")
    return "\n".join(resultado)


def historico_ultimos(n: int = 10) -> str:
    try:
        with open(_HISTORICO_FILE, "r", encoding="utf-8") as f:
            linhas = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return "Nenhum comando registrado ainda, Senhor."
    ultimos = linhas[-n:]
    if not ultimos:
        return "Histórico vazio, Senhor."
    resultado = [f"Últimos {len(ultimos)} comandos:"]
    for i, l in enumerate(ultimos, 1):
        data_hora = l["ts"].replace("T", " ")
        icone = "🎤" if l.get("origem") == "voz" else "⌨"
        resultado.append(f"  {i:>2}. [{data_hora}] {icone} {l['texto'][:80]}")
    return "\n".join(resultado)

# ── Bateria ──────────────────────────────────────────────────────────────────

def get_bateria() -> str:
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return "Nenhuma bateria detectada neste dispositivo, senhor."
        p = int(b.percent)
        plugged = "conectado à tomada" if b.power_plugged else "desconectado"
        if b.power_plugged:
            status = "carregando" if p < 100 else "totalmente carregada"
        else:
            status = "descarregando"
        secs = b.secsleft
        if secs and secs > 0 and not b.power_plugged:
            h, m = divmod(secs // 60, 60)
            tempo = f", estimativa de {int(h)}h{int(m):02d}min restantes"
        else:
            tempo = ""
        return f"Bateria em {p}% — {status}, {plugged}{tempo}, senhor."
    except ImportError:
        return "Módulo psutil não instalado, senhor. Execute: pip install psutil"
    except Exception as e:
        return f"Erro ao verificar bateria: {e}"


# ── Rede / IP ────────────────────────────────────────────────────────────────

def get_rede_status() -> str:
    import socket
    linhas: list[str] = []
    # IP local
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_local = s.getsockname()[0]
        s.close()
        linhas.append(f"IP local: {ip_local}")
    except Exception:
        linhas.append("IP local: indisponível")

    # IP público — usa ipify (HTTPS)
    try:
        import urllib.request
        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:  # nosec
            ip_pub = r.read().decode().strip()
        linhas.append(f"IP público: {ip_pub}")
    except Exception:
        linhas.append("IP público: indisponível")

    # Hostname
    try:
        linhas.append(f"Hostname: {socket.gethostname()}")
    except Exception:
        pass

    return ", ".join(linhas) + ", senhor."


# ── Brilho ───────────────────────────────────────────────────────────────────

def get_brilho() -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"],
            capture_output=True, text=True, timeout=8
        )
        val = result.stdout.strip()
        if val.isdigit():
            return f"Brilho atual: {val}%, senhor."
        return "Não foi possível obter o brilho atual, senhor."
    except Exception as e:
        return f"Erro ao obter brilho: {e}"


def set_brilho(valor: int) -> str:
    valor = max(0, min(100, int(valor)))
    try:
        cmd = (
            f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
            f".WmiSetBrightness(1,{valor})"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, timeout=8)
        return f"Brilho ajustado para {valor}%, senhor."
    except Exception as e:
        return f"Erro ao ajustar brilho: {e}"


# ── Limpeza ──────────────────────────────────────────────────────────────────

def limpar_temp() -> str:
    import tempfile
    import shutil
    pasta = tempfile.gettempdir()
    removidos = 0
    erros = 0
    for item in os.listdir(pasta):
        caminho = os.path.join(pasta, item)
        try:
            if os.path.isfile(caminho) or os.path.islink(caminho):
                os.unlink(caminho)
                removidos += 1
            elif os.path.isdir(caminho):
                shutil.rmtree(caminho, ignore_errors=True)
                removidos += 1
        except Exception:
            erros += 1
    if erros:
        return f"Limpeza concluída: {removidos} itens removidos, {erros} não puderam ser excluídos, senhor."
    return f"Limpeza concluída: {removidos} itens removidos com sucesso, senhor."


def esvaziar_lixeira() -> str:
    import ctypes
    try:
        # SHEmptyRecycleBinW(hwnd, root, flags)
        # SHERB_NOCONFIRMATION|SHERB_NOPROGRESSUI|SHERB_NOSOUND = 0x00000007
        ret = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x00000007)
        if ret == 0:
            return "Lixeira esvaziada com sucesso, senhor."
        elif ret == -2147418113:  # 0x80004003 — já estava vazia
            return "A lixeira já estava vazia, senhor."
        else:
            return f"Lixeira esvaziada (código {ret}), senhor."
    except Exception as e:
        return f"Erro ao esvaziar lixeira: {e}"