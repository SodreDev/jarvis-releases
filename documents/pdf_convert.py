# -*- coding: utf-8 -*-
"""documents.pdf_convert — Conversor NATIVO→PDF com fachada em camadas.

Converte .docx/.xlsx/.pptx (e similares) para PDF com alta fidelidade, tentando
backends em ordem de prioridade (roadmap/13, pesquisa multi-formato):

  1) MS Office COM (pywin32, já é dependência) — melhor fidelidade p/ arquivos
     Office, rápido, sem instalação extra. Válido aqui porque o JARVIS roda
     INTERATIVO na sessão do usuário (a restrição da Microsoft é só p/ serviços).
  2) LibreOffice 'soffice' headless — um binário converte DOCX/XLSX/PPTX→PDF,
     sem MS Office (mas ~150-300MB e fidelidade um pouco menor).
  3) (chamador decide o fallback — ex.: report_builder/pdf_engine p/ relatórios).

NÃO usa Chromium aqui (round-trip HTML perde fidelidade do arquivo nativo).
"""
from __future__ import annotations

import os
import sys
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path
from typing import Optional

# LibreOffice é single-instance / não thread-safe → serializa conversões.
_LO_LOCK = threading.Lock()

_WORD_EXT = {"docx", "doc", "rtf", "odt", "txt"}
_EXCEL_EXT = {"xlsx", "xls", "csv", "ods"}
_PPT_EXT = {"pptx", "ppt", "odp"}


def to_pdf(src_path: str, out_path: Optional[str] = None) -> str:
    """Converte um arquivo nativo → PDF. Retorna o caminho do PDF ou '' em falha."""
    src = os.path.abspath(src_path)
    if not os.path.exists(src):
        print(f"[PDF] arquivo não existe: {src}")
        return ""
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    if ext == "pdf":
        return src
    out = os.path.abspath(out_path) if out_path else (os.path.splitext(src)[0] + ".pdf")
    # 1) MS Office COM
    try:
        p = _via_com(src, out, ext)
        if p and os.path.exists(p):
            print(f"[PDF] convertido via MS Office COM → {os.path.basename(p)}")
            return p
    except Exception as e:
        print(f"[PDF] COM indisponível/falhou: {type(e).__name__}: {e}")
    # 2) LibreOffice
    try:
        p = _via_libreoffice(src, out)
        if p and os.path.exists(p):
            print(f"[PDF] convertido via LibreOffice → {os.path.basename(p)}")
            return p
    except Exception as e:
        print(f"[PDF] LibreOffice falhou: {type(e).__name__}: {e}")
    print("[PDF] Nenhum conversor disponível (instale MS Office OU LibreOffice).")
    return ""


def available_backend() -> str:
    """'com' | 'libreoffice' | 'none' — qual conversor está disponível."""
    if sys.platform == "win32":
        try:
            import win32com.client  # noqa: F401
            return "com"
        except Exception:
            pass
    return "libreoffice" if _find_soffice() else "none"


def _via_com(src: str, out: str, ext: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import win32com.client as _w32
        import pythoncom
    except Exception:
        return ""
    pythoncom.CoInitialize()
    try:
        if ext in _WORD_EXT:
            app = _w32.Dispatch("Word.Application")
            app.Visible = False
            try:
                doc = app.Documents.Open(src, ReadOnly=True)
                try:
                    if doc.TablesOfContents.Count:
                        doc.TablesOfContents(1).Update()
                except Exception:
                    pass
                doc.ExportAsFixedFormat(out, 17)   # wdExportFormatPDF
                doc.Close(False)
            finally:
                app.Quit()
        elif ext in _EXCEL_EXT:
            app = _w32.Dispatch("Excel.Application")
            app.Visible = False
            app.DisplayAlerts = False
            try:
                wb = app.Workbooks.Open(src, ReadOnly=True)
                wb.ExportAsFixedFormat(0, out)     # 0 = xlTypePDF
                wb.Close(False)
            finally:
                app.Quit()
        elif ext in _PPT_EXT:
            app = _w32.Dispatch("PowerPoint.Application")
            try:
                prs = app.Presentations.Open(src, WithWindow=False)
                prs.SaveAs(out, 32)                # 32 = ppSaveAsPDF
                prs.Close()
            finally:
                app.Quit()
        else:
            return ""
        return out if os.path.exists(out) else ""
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _find_soffice() -> str:
    c = shutil.which("soffice.com") or shutil.which("soffice")
    if c:
        return c
    cands = []
    for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
        if base:
            cands.append(os.path.join(base, "LibreOffice", "program", "soffice.com"))
    cands += ["/usr/bin/soffice", "/usr/bin/libreoffice",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    for p in cands:
        if os.path.exists(p):
            return p
    return ""


def _via_libreoffice(src: str, out: str, timeout: int = 120) -> str:
    soffice = _find_soffice()
    if not soffice:
        return ""
    outdir = os.path.dirname(out) or "."
    os.makedirs(outdir, exist_ok=True)
    with _LO_LOCK:
        # Perfil isolado via Path.as_uri() (NÃO 'file://'+path — bug de URI no Win).
        tmp_profile = tempfile.mkdtemp(prefix="jarvis_lo_")
        try:
            cmd = [
                soffice, "--headless", "--norestore", "--invisible", "--nodefault",
                f"-env:UserInstallation={Path(tmp_profile).as_uri()}",
                "--convert-to", "pdf", "--outdir", outdir, src,
            ]
            subprocess.run(cmd, timeout=timeout, capture_output=True)
        except Exception as e:
            print(f"[PDF] soffice erro: {e}")
        finally:
            shutil.rmtree(tmp_profile, ignore_errors=True)
    # LibreOffice grava <stem>.pdf no --outdir (não dá p/ renomear na mesma chamada)
    produced = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
    if os.path.exists(produced):
        if os.path.abspath(produced) != os.path.abspath(out):
            try:
                os.replace(produced, out)
                return out
            except Exception:
                return produced
        return out
    return ""


__all__ = ["to_pdf", "available_backend"]
