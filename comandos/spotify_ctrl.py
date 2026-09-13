"""
Spotify Controller — J.A.R.V.I.S.
Controla o Spotify desktop via Web API (spotipy).

Fluxo:
1. Primeira execução → abre o navegador p/ autenticação OAuth
2. Servidor HTTP local captura o callback automaticamente
3. Token salvo em .spotify_cache → usos seguintes são silenciosos
4. Todos os comandos operam no dispositivo ativo (desktop Spotify)
"""

import os
import platform
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Escopo necessário para buscas e controle total de playback via Web API
_SCOPE = " ".join([
    "user-modify-playback-state",
    "user-read-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
])

_sp_client: spotipy.Spotify | None = None
_AUTH_PORT   = 8888
_REDIRECT_URI = f"http://127.0.0.1:{_AUTH_PORT}/callback"
_CACHE_PATH  = ".spotify_cache"
_creds: tuple | None = None          # (client_id, client_secret, redirect_uri) p/ re-login
_auth_mgr: SpotifyOAuth | None = None


def _eh_invalid_grant(e: Exception) -> bool:
    """True se o erro for refresh token expirado/revogado.

    A partir de 20/07/2026 o refresh token do Spotify expira em 6 meses; tentar
    refresh com token morto retorna invalid_grant. NÃO retentar — refazer login.
    """
    s = str(e).lower()
    return ("invalid_grant" in s or "refresh token revoked" in s
            or "token revoked" in s or "refresh token expired" in s)


def _descartar_token() -> None:
    """Descarta o token em cache (sem retentar um refresh morto) → força novo login."""
    global _sp_client
    _sp_client = None
    try:
        if os.path.exists(_CACHE_PATH):
            os.remove(_CACHE_PATH)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# SERVIDOR HTTP LOCAL PARA CAPTURAR O CALLBACK OAUTH
# ─────────────────────────────────────────────────────────────────────────────

_auth_code: str | None = None
_auth_error: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code, _auth_error
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _auth_code = params["code"][0]
            msg = b"<h2>Autorizado! Pode fechar esta aba.</h2>"
        elif "error" in params:
            _auth_error = params["error"][0]
            msg = b"<h2>Erro de autorizacao. Tente novamente.</h2>"
        else:
            msg = b"<h2>Aguardando...</h2>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(msg)

    def log_message(self, *args):
        pass  # silencia logs do servidor


def _aguardar_callback(timeout: int = 120) -> str:
    """Sobe o servidor local e aguarda o código de autorização."""
    global _auth_code, _auth_error
    _auth_code = None
    _auth_error = None

    server = HTTPServer(("127.0.0.1", _AUTH_PORT), _CallbackHandler)
    server.timeout = 2

    inicio = time.time()
    while time.time() - inicio < timeout:
        server.handle_request()
        if _auth_code:
            server.server_close()
            return _auth_code
        if _auth_error:
            server.server_close()
            raise RuntimeError(f"Spotify recusou: {_auth_error}")

    server.server_close()
    raise RuntimeError("Tempo esgotado aguardando autorização do Spotify.")


# ─────────────────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

def iniciar(client_id: str, client_secret: str, redirect_uri: str) -> spotipy.Spotify:
    """Cria (ou reutiliza) o cliente Spotify autenticado.

    Valida o token A CADA chamada (barato: o spotipy só faz refresh de rede
    quando o access token expira, ~1x/hora). Se o REFRESH token expirou
    (invalid_grant — mudança Spotify a partir de 20/07/2026), descarta o token
    em cache e refaz o sign-in (sem retentar o refresh morto), como exige o e-mail
    "Handle invalid_grant errors / Discard expired tokens".
    """
    global _sp_client, _creds, _auth_mgr
    _creds = (client_id, client_secret, redirect_uri)

    auth = _auth_mgr
    if auth is None:
        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=_REDIRECT_URI,   # sempre 127.0.0.1
            scope=_SCOPE,
            cache_path=_CACHE_PATH,
            open_browser=False,           # controlamos manualmente
        )
        _auth_mgr = auth

    # get_cached_token() refresca automaticamente se o access token expirou — e
    # levanta invalid_grant se o REFRESH token expirou (6 meses).
    token_info = None
    try:
        token_info = auth.get_cached_token()
    except Exception as e:
        if _eh_invalid_grant(e):
            print("[SPOTIFY] Refresh token expirado (invalid_grant) — refazendo login.")
            _descartar_token()
        else:
            raise

    if token_info and not auth.is_token_expired(token_info):
        if _sp_client is None:
            _sp_client = spotipy.Spotify(auth_manager=auth)
        return _sp_client

    # Sem token válido (1ª vez OU refresh token expirado) → sign-in completo.
    _sp_client = None
    auth_url = auth.get_authorize_url()
    print("[SPOTIFY] Abrindo navegador para autorização...")
    webbrowser.open(auth_url)
    print(f"[SPOTIFY] Aguardando callback em {_REDIRECT_URI} ...")

    # Captura o código via servidor local
    code = _aguardar_callback(timeout=120)
    auth.get_access_token(code, as_dict=False)

    _sp_client = spotipy.Spotify(auth_manager=auth)
    print("[SPOTIFY] Autenticado com sucesso!")
    return _sp_client


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────

def _abrir_app() -> None:
    """Abre o Spotify desktop."""
    sistema = platform.system()
    try:
        if sistema == "Windows":
            # tentativas em ordem de preferência
            caminhos = [
                os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "Spotify.exe"),
            ]
            aberto = False
            for caminho in caminhos:
                if os.path.isfile(caminho):
                    subprocess.Popen([caminho], shell=False)
                    aberto = True
                    break
            if not aberto:
                # fallback: via URI do Windows Store
                subprocess.Popen(
                    ["powershell", "-Command", "Start-Process spotify:"], shell=False
                )
        elif sistema == "Darwin":
            subprocess.Popen(["open", "-a", "Spotify"])
        time.sleep(4)   # aguarda o app abrir e registrar dispositivo
    except Exception as e:
        print(f"[SPOTIFY] Erro ao abrir app: {e}")


def _dispositivo(sp: spotipy.Spotify, forcar_abertura: bool = True) -> str | None:
    """
    Retorna o ID do dispositivo Spotify ativo.
    Se não encontrar, tenta abrir o app e aguarda até 10 s.
    """
    for tentativa in range(10):
        data = sp.devices()
        devs = data.get("devices", [])
        if devs:
            # Prefere tipo 'Computer' (desktop)
            for d in devs:
                if d.get("type", "").lower() == "computer":
                    return d["id"]
            return devs[0]["id"]
        if tentativa == 0 and forcar_abertura:
            _abrir_app()
        time.sleep(1)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# COMANDOS PÚBLICOS
# ─────────────────────────────────────────────────────────────────────────────
def _ativar_dispositivo(sp: spotipy.Spotify, device_id: str) -> None:
    """
    Transfere o playback para o dispositivo e garante que ele está ativo.
    Necessário antes de start_playback em dispositivos recém-abertos.
    """
    try:
        sp.transfer_playback(device_id=device_id, force_play=False)
        time.sleep(1)
    except Exception:
        pass  # transfer pode falhar se já ativo — ignora


def _start(sp: spotipy.Spotify, device_id: str, **kwargs) -> None:
    """
    Tenta start_playback. Levanta SpotifyException com mensagem útil
    se a conta for gratuita (403 Player command failed: Premium required).
    """
    try:
        sp.start_playback(device_id=device_id, **kwargs)
    except spotipy.exceptions.SpotifyException as e:
        if "premium" in str(e).lower() or "403" in str(e):
            raise RuntimeError(
                "Esta ação requer Spotify Premium, Senhor. "
                "Contas gratuitas não permitem controle remoto de playback."
            ) from e
        raise


def _uri_fallback(tipo: str, query: str) -> str:
    """
    Abre o Spotify desktop/app via URI de protocolo como fallback
    quando o controle por API não está disponível (ex.: conta gratuita).
    tipo: 'track' | 'playlist' | 'artist' | 'album' | 'search'
    """
    q = urllib.parse.quote(query)
    if tipo == "search":
        uri = f"spotify:search:{q}"
    else:
        uri = f"spotify:search:{q}"
    webbrowser.open(uri)
    return f"Abrindo '{query}' no Spotify, Senhor."


def tocar_musica(sp: spotipy.Spotify, query: str) -> str:
    """Busca e toca a primeira música correspondente."""
    results = sp.search(q=query, type="track", limit=1)
    tracks = results.get("tracks", {}).get("items", [])
    if not tracks:
        return f"Não encontrei a música '{query}', Senhor."
    track = tracks[0]
    device_id = _dispositivo(sp)
    if not device_id:
        return "Spotify não está disponível em nenhum dispositivo, Senhor."
    _ativar_dispositivo(sp, device_id)
    try:
        _start(sp, device_id, uris=[track["uri"]])
    except RuntimeError:
        return _uri_fallback("track", query)
    nome = track["name"]
    artista = track["artists"][0]["name"]
    return f"Tocando '{nome}' de {artista}, Senhor."


def tocar_playlist(sp: spotipy.Spotify, query: str) -> str:
    """Busca e toca a playlist mais relevante."""
    results = sp.search(q=query, type="playlist", limit=1)
    playlists = results.get("playlists", {}).get("items", [])
    if not playlists:
        return _uri_fallback("search", query)
    playlist = playlists[0]
    device_id = _dispositivo(sp)
    if not device_id:
        return "Spotify não está disponível em nenhum dispositivo, Senhor."
    _ativar_dispositivo(sp, device_id)
    try:
        _start(sp, device_id, context_uri=playlist["uri"])
    except RuntimeError:
        return _uri_fallback("playlist", query)
    return f"Tocando playlist '{playlist['name']}', Senhor."


def tocar_artista(sp: spotipy.Spotify, query: str) -> str:
    """Busca e toca músicas do artista."""
    results = sp.search(q=query, type="artist", limit=1)
    artists = results.get("artists", {}).get("items", [])
    if not artists:
        return f"Não encontrei o artista '{query}', Senhor."
    artist = artists[0]
    device_id = _dispositivo(sp)
    if not device_id:
        return "Spotify não está disponível em nenhum dispositivo, Senhor."
    _ativar_dispositivo(sp, device_id)
    try:
        _start(sp, device_id, context_uri=artist["uri"])
    except RuntimeError:
        return _uri_fallback("artist", query)
    return f"Tocando músicas de {artist['name']}, Senhor."


def tocar_album(sp: spotipy.Spotify, query: str) -> str:
    """Busca e toca o álbum mais relevante."""
    results = sp.search(q=query, type="album", limit=1)
    albums = results.get("albums", {}).get("items", [])
    if not albums:
        return f"Não encontrei o álbum '{query}', Senhor."
    album = albums[0]
    device_id = _dispositivo(sp)
    if not device_id:
        return "Spotify não está disponível em nenhum dispositivo, Senhor."
    _ativar_dispositivo(sp, device_id)
    try:
        _start(sp, device_id, context_uri=album["uri"])
    except RuntimeError:
        return _uri_fallback("album", query)
    nome = album["name"]
    artista = album["artists"][0]["name"]
    return f"Tocando o álbum '{nome}' de {artista}, Senhor."


def pausar(sp: spotipy.Spotify) -> str:
    try:
        sp.pause_playback()
        return "Playback pausado, Senhor."
    except Exception:
        return "Nada está tocando para pausar, Senhor."


def retomar(sp: spotipy.Spotify) -> str:
    device_id = _dispositivo(sp)
    try:
        sp.start_playback(device_id=device_id)
        return "Reprodução retomada, Senhor."
    except Exception:
        return "Não foi possível retomar, Senhor."


def proxima(sp: spotipy.Spotify) -> str:
    try:
        sp.next_track()
        time.sleep(0.5)
        return "Próxima faixa, Senhor."
    except Exception:
        return "Não foi possível avançar, Senhor."


def anterior(sp: spotipy.Spotify) -> str:
    try:
        sp.previous_track()
        time.sleep(0.5)
        return "Faixa anterior, Senhor."
    except Exception:
        return "Não foi possível voltar, Senhor."


def ajustar_volume(sp: spotipy.Spotify, nivel: int) -> str:
    nivel = max(0, min(100, nivel))
    try:
        device_id = _dispositivo(sp, forcar_abertura=False)
        sp.volume(nivel, device_id=device_id)
        return f"Volume ajustado para {nivel}%, Senhor."
    except Exception:
        return f"Não foi possível ajustar o volume, Senhor."


def obter_volume_atual(sp: spotipy.Spotify) -> int | None:
    """Retorna o volume atual do Spotify (0-100) ou None se indisponível."""
    try:
        pb = sp.current_playback()
        if pb and pb.get("device"):
            return pb["device"].get("volume_percent")
    except Exception:
        pass
    return None


def volume_relativo(sp: spotipy.Spotify, delta: int) -> str:
    """Ajusta o volume relativamente (+delta ou -delta). delta típico: ±10."""
    atual = obter_volume_atual(sp)
    if atual is None:
        atual = 50  # fallback razoável
    novo = max(0, min(100, atual + delta))
    return ajustar_volume(sp, novo)


def mutar(sp: spotipy.Spotify) -> str:
    """Define volume como 0 (mute)."""
    return ajustar_volume(sp, 0)


def desmutar(sp: spotipy.Spotify) -> str:
    """Restaura volume para 50% (unmute)."""
    return ajustar_volume(sp, 50)


def tocando_agora(sp: spotipy.Spotify) -> str:
    try:
        playing = sp.current_playback()
        if not playing or not playing.get("is_playing"):
            return "Nada está tocando no momento, Senhor."
        track = playing["item"]
        nome = track["name"]
        artista = track["artists"][0]["name"]
        album = track["album"]["name"]
        return f"Tocando agora: '{nome}' de {artista} ({album}), Senhor."
    except Exception:
        return "Não foi possível obter o estado do Spotify, Senhor."
