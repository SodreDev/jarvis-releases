# comandos/email_ctrl.py — J.A.R.V.I.S.
# Integração com Gmail via OAuth2 (google-api-python-client)
# Instalar: pip install google-auth google-auth-oauthlib google-auth-httplib2
#            google-api-python-client
# -*- coding: utf-8 -*-

from __future__ import annotations
import os
import json
import re
import base64
import datetime
from typing import Optional

# ── Caminhos de credenciais ()
from config import PATHS
_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
CREDENTIALS_FILE = PATHS["gmail_creds"]
TOKEN_FILE       = PATHS["gmail_token"]

# ── Escopos (leitura + envio, sem acesso a spam/trash por padrão) ────────────
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]

# ── Padrões para detectar emails automatizados / noreply ─────────────────────
_NOREPLY_PATTERNS = re.compile(
    r"noreply|no-reply|donotreply|do-not-reply|"
    r"notifications?@|mailer-daemon|postmaster|"
    r"newsletter@|info@|updates?@|alerts?@|"
    r"support@|help@|team@|hello@|hi@|welcome@",
    re.I,
)

# Domínios conhecidos de empresas (seus emails são informativos, não pessoais)
_EMPRESA_DOMAINS = {
    "microsoft.com", "google.com", "apple.com", "amazon.com", "netflix.com",
    "spotify.com", "github.com", "linkedin.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "paypal.com", "mercadopago.com", "nubank.com.br",
    "bradesco.com.br", "itau.com.br", "santander.com.br", "bb.com.br",
    "correios.com.br", "ifood.com.br", "rappi.com", "uber.com",
    "steamgames.com", "epicgames.com", "riotgames.com", "blizzard.com",
    "discord.com", "twitch.tv", "youtube.com", "tiktok.com",
    "shopee.com.br", "magalu.com.br", "americanas.com.br", "submarino.com.br",
}


def _get_service():
    """Cria e retorna o serviço Gmail. Faz OAuth na primeira vez."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise ImportError(
            "Instale as dependências: pip install google-auth google-auth-oauthlib "
            "google-auth-httplib2 google-api-python-client"
        )

    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"Arquivo de credenciais não encontrado: {CREDENTIALS_FILE}\n"
            "Baixe o json OAuth2 em: https://console.cloud.google.com/apis/credentials"
        )

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _is_automated(sender: str, subject: str = "") -> bool:
    """Retorna True se o email parece ser automático/empresa."""
    if _NOREPLY_PATTERNS.search(sender):
        return True
    # Checa domínio
    m = re.search(r"@([\w.\-]+)", sender)
    if m:
        domain = m.group(1).lower()
        if domain in _EMPRESA_DOMAINS:
            return True
        # Subdomínios de empresas conhecidas (mail.spotify.com, etc.)
        for known in _EMPRESA_DOMAINS:
            if domain.endswith("." + known):
                return True
    return False


def _decode_header_value(value: str) -> str:
    """Decodifica valores de cabeçalho encodados (RFC 2047)."""
    import email.header as _eh
    parts = _eh.decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _get_body(payload: dict) -> str:
    """Extrai o corpo de texto do payload da mensagem."""
    body = ""
    if payload.get("body", {}).get("data"):
        raw = payload["body"]["data"]
        body = base64.urlsafe_b64decode(raw).decode("utf-8", errors="replace")
    elif payload.get("parts"):
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    break
            # recursivo para multipart
            sub = _get_body(part)
            if sub:
                body = sub
                break
    # Remove excesso de espaços/quebras
    body = re.sub(r"\n{3,}", "\n\n", body.strip())
    return body[:1500]  # limita para TTS


def _format_date(internal_date_ms: str) -> str:
    try:
        ts = int(internal_date_ms) / 1000
        dt = datetime.datetime.fromtimestamp(ts)
        now = datetime.datetime.now()
        delta = now - dt
        if delta.days == 0:
            return f"hoje às {dt.strftime('%H:%M')}"
        elif delta.days == 1:
            return f"ontem às {dt.strftime('%H:%M')}"
        else:
            return dt.strftime("%d/%m às %H:%M")
    except Exception:
        return "data desconhecida"


# ── API Pública ──────────────────────────────────────────────────────────────

def ler_emails(
    n: int = 5,
    incluir_spam: bool = False,
    incluir_noreply: bool = False,
    incluir_promotional: bool = False,
    apenas_nao_lidos: bool = False,
) -> str:
    """
    Lê os últimos `n` emails da caixa de entrada.
    Por padrão filtra spam, promotional e noreply/empresas automáticas.
    """
    try:
        service = _get_service()
    except (ImportError, FileNotFoundError) as e:
        return f"Gmail não configurado: {e}"

    # Monta a query
    label_filter = "in:inbox"
    if not incluir_spam:
        label_filter += " -in:spam -in:trash"
    if not incluir_promotional:
        label_filter += " -category:promotions -category:updates -category:social"
    if apenas_nao_lidos:
        label_filter += " is:unread"

    try:
        result = service.users().messages().list(
            userId="me", q=label_filter, maxResults=n * 3
        ).execute()
        messages = result.get("messages", [])
    except Exception as e:
        return f"Erro ao acessar o Gmail: {e}"

    if not messages:
        return "Nenhum email encontrado na caixa de entrada, senhor."

    resumos = []
    contados = 0
    for msg_ref in messages:
        if contados >= n:
            break
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
        except Exception:
            continue

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        sender  = _decode_header_value(headers.get("From", "desconhecido"))
        subject = _decode_header_value(headers.get("Subject", "(sem assunto)"))
        date_s  = _format_date(msg.get("internalDate", "0"))
        labels  = msg.get("labelIds", [])
        unread  = "UNREAD" in labels

        # Filtra automatizados se não solicitado explicitamente
        if not incluir_noreply and _is_automated(sender, subject):
            continue

        tipo = "📧" if unread else "✉"
        resumos.append(f"{tipo} {date_s} | De: {sender[:50]} | Assunto: {subject[:80]}")
        contados += 1

    if not resumos:
        return "Nenhum email pessoal nos últimos recebidos, senhor."

    header = f"Últimos {len(resumos)} emails"
    if apenas_nao_lidos:
        header += " não lidos"
    return header + ":\n" + "\n".join(resumos)


def ler_email_completo(n_or_id: int | str = 1) -> str:
    """Lê o conteúdo completo do N-ésimo email mais recente."""
    try:
        service = _get_service()
    except (ImportError, FileNotFoundError) as e:
        return f"Gmail não configurado: {e}"

    try:
        result = service.users().messages().list(
            userId="me", q="in:inbox -in:spam", maxResults=int(n_or_id) + 5
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            return "Nenhum email encontrado, senhor."
        idx = int(n_or_id) - 1
        msg_id = messages[idx]["id"]
        msg = service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()
    except Exception as e:
        return f"Erro ao ler email: {e}"

    payload = msg.get("payload", {})
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
    sender  = _decode_header_value(headers.get("From", "desconhecido"))
    subject = _decode_header_value(headers.get("Subject", "(sem assunto)"))
    date_s  = _format_date(msg.get("internalDate", "0"))
    body    = _get_body(payload)

    return (
        f"Email recebido {date_s}\n"
        f"De: {sender}\n"
        f"Assunto: {subject}\n\n"
        f"{body or '(corpo vazio)'}"
    )


def enviar_email(destinatario: str, assunto: str, corpo: str) -> str:
    """Envia um email via Gmail."""
    try:
        service = _get_service()
    except (ImportError, FileNotFoundError) as e:
        return f"Gmail não configurado: {e}"

    import email.mime.text as _mt
    import email.mime.multipart as _mm

    msg = _mm.MIMEMultipart()
    msg["to"] = destinatario
    msg["subject"] = assunto
    msg.attach(_mt.MIMEText(corpo, "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    try:
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return f"Email enviado para {destinatario} com o assunto '{assunto}', senhor."
    except Exception as e:
        return f"Erro ao enviar email: {e}"


def contar_nao_lidos() -> str:
    """Retorna a contagem de emails não lidos."""
    try:
        service = _get_service()
        result = service.users().messages().list(
            userId="me", q="in:inbox is:unread"
        ).execute()
        total = result.get("resultSizeEstimate", 0)
        if total == 0:
            return "Nenhum email não lido na caixa de entrada, senhor."
        return f"Você tem {total} email{'s' if total > 1 else ''} não lido{'s' if total > 1 else ''}, senhor."
    except (ImportError, FileNotFoundError) as e:
        return f"Gmail não configurado: {e}"
    except Exception as e:
        return f"Erro ao verificar emails: {e}"


def ler_spam(n: int = 5) -> str:
    """Lê os últimos emails da pasta spam (somente se explicitamente solicitado)."""
    try:
        service = _get_service()
        result = service.users().messages().list(
            userId="me", q="in:spam", maxResults=n
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            return "Pasta de spam vazia, senhor."
        resumos = []
        for msg_ref in messages[:n]:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="metadata",
                metadataHeaders=["From", "Subject"]
            ).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            sender  = _decode_header_value(headers.get("From", "?"))
            subject = _decode_header_value(headers.get("Subject", "(sem assunto)"))
            resumos.append(f"🗑 De: {sender[:50]} | {subject[:80]}")
        return f"Spam ({len(resumos)}):\n" + "\n".join(resumos)
    except (ImportError, FileNotFoundError) as e:
        return f"Gmail não configurado: {e}"
    except Exception as e:
        return f"Erro ao ler spam: {e}"
