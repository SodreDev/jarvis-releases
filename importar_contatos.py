"""
Importador de contatos VCF (vCard) → contatos.json — J.A.R.V.I.S.

USO:
  1. Exporte seus contatos do celular como arquivo .vcf
     - Android: Contatos → ⋮ → Exportar → arquivo .vcf
     - iPhone: iCloud.com → Contatos → ⚙ → Exportar vCard
     - Google: contacts.google.com → Exportar → vCard (.vcf)
  2. Copie o arquivo .vcf para a pasta do projeto
  3. Execute:  python importar_contatos.py contatos.vcf

O script lê todos os contatos com nome + telefone e salva no contatos.json.
Contatos sem telefone são ignorados. Contatos duplicados são atualizados.
"""

import json
import os
import re
import sys

CONTATOS_FILE = os.path.join(os.path.dirname(__file__), "contatos.json")
COUNTRY_CODE = "55"  # Brasil — altere se necessário


def _parse_vcf(filepath: str) -> list[dict]:
    """Lê um arquivo .vcf e retorna lista de {'nome': str, 'phones': [str]}."""
    contatos = []
    current = {"nome": "", "phones": []}

    with open(filepath, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()

            if line.upper() == "BEGIN:VCARD":
                current = {"nome": "", "phones": []}

            elif line.upper().startswith("FN:") or line.upper().startswith("FN;"):
                # FN = Formatted Name (nome completo como aparece na tela)
                nome = line.split(":", 1)[-1].strip()
                if nome:
                    current["nome"] = nome

            elif line.upper().startswith("TEL") and ":" in line:
                # TEL;TYPE=CELL:+5511999998888  ou  TEL:11999998888
                phone_raw = line.split(":", 1)[-1].strip()
                phone_digits = re.sub(r"\D", "", phone_raw)
                if len(phone_digits) >= 8:
                    current["phones"].append(phone_digits)

            elif line.upper() == "END:VCARD":
                if current["nome"] and current["phones"]:
                    contatos.append(current)

    return contatos


def _normalizar_phone(phone: str) -> str:
    """Normaliza telefone: remove não-dígitos, adiciona código de país."""
    digits = re.sub(r"\D", "", phone)
    if not digits.startswith(COUNTRY_CODE):
        digits = COUNTRY_CODE + digits
    return f"+{digits}"


def importar(vcf_path: str, preview: bool = True) -> int:
    """
    Importa contatos do VCF para contatos.json.
    Retorna quantidade de contatos importados.
    """
    if not os.path.isfile(vcf_path):
        print(f"❌ Arquivo não encontrado: {vcf_path}")
        return 0

    contatos_vcf = _parse_vcf(vcf_path)
    if not contatos_vcf:
        print("❌ Nenhum contato com nome + telefone encontrado no arquivo.")
        return 0

    # Carrega agenda existente (preserva contatos já salvos)
    db: dict = {}
    if os.path.isfile(CONTATOS_FILE):
        with open(CONTATOS_FILE, encoding="utf-8") as f:
            db = json.load(f)

    # Separa chaves de ajuda
    ajuda = {k: v for k, v in db.items() if k.startswith("_")}
    existentes = {k: v for k, v in db.items() if not k.startswith("_")}

    novos = 0
    atualizados = 0
    importados = {}

    for c in contatos_vcf:
        nome = c["nome"].strip().title()
        # Usa o primeiro telefone (geralmente o celular principal)
        phone = _normalizar_phone(c["phones"][0])

        if nome in existentes:
            if existentes[nome] != phone:
                atualizados += 1
        else:
            novos += 1

        importados[nome] = phone

    if preview:
        print(f"\n📋 Prévia da importação:")
        print(f"   Contatos encontrados no VCF: {len(contatos_vcf)}")
        print(f"   Já existentes na agenda:     {len(existentes)}")
        print(f"   Novos:                       {novos}")
        print(f"   Atualizados (nº diferente):  {atualizados}")
        print()

        # Mostra primeiros 15 como amostra
        amostra = list(importados.items())[:15]
        for nome, phone in amostra:
            tag = " (novo)" if nome not in existentes else " (atualizado)" if existentes.get(nome) != phone else ""
            print(f"   {nome}: {phone}{tag}")
        if len(importados) > 15:
            print(f"   ... e mais {len(importados) - 15} contatos.")

        print()
        resp = input("Confirma a importação? [S/n] ").strip().lower()
        if resp and resp not in ("s", "sim", "y", "yes"):
            print("❌ Importação cancelada.")
            return 0

    # Merge: contatos importados sobrescrevem existentes com mesmo nome
    existentes.update(importados)

    # Salva com chaves de ajuda preservadas
    with open(CONTATOS_FILE, "w", encoding="utf-8") as f:
        json.dump({**ajuda, **existentes}, f, ensure_ascii=False, indent=2)

    total = novos + atualizados
    print(f"\n✅ Importação concluída! {len(importados)} contatos no arquivo.")
    print(f"   {novos} novos, {atualizados} atualizados, {len(existentes) - len(importados)} mantidos.")
    print(f"   Salvo em: {CONTATOS_FILE}")
    return len(importados)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python importar_contatos.py <arquivo.vcf>")
        print()
        print("Como exportar seus contatos:")
        print("  Android : Contatos → ⋮ → Exportar → salva arquivo .vcf")
        print("  iPhone  : iCloud.com → Contatos → ⚙ → Exportar vCard")
        print("  Google  : contacts.google.com → Exportar → vCard (.vcf)")
        print()
        print("Depois copie o .vcf para esta pasta e execute:")
        print("  python importar_contatos.py contatos.vcf")
        sys.exit(1)

    vcf_file = sys.argv[1]
    importar(vcf_file)
