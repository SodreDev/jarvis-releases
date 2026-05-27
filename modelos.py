import os
import google.generativeai as genai

# Lê do ambiente (carregado via credentials/.env por core/env_loader).
_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not _API_KEY:
    raise SystemExit(
        "GEMINI_API_KEY ausente — configure em credentials/.env antes de rodar."
    )
genai.configure(api_key=_API_KEY)

print("Modelos disponíveis para geração de texto:")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)