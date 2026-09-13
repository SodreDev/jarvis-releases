# comandos/unidades_ctrl.py — J.A.R.V.I.S.
# Conversão de unidades e temperaturas
# -*- coding: utf-8 -*-

from __future__ import annotations

# ── Tabelas de conversão (base = primeira unidade comum de cada categoria) ────

# Base: metro
_COMPRIMENTO: dict[str, float] = {
    "metro": 1.0, "metros": 1.0, "m": 1.0,
    "quilômetro": 1e3, "quilometro": 1e3, "quilômetros": 1e3, "quilometros": 1e3, "km": 1e3,
    "centímetro": 0.01, "centimetro": 0.01, "centímetros": 0.01, "cm": 0.01,
    "milímetro": 1e-3, "milimetro": 1e-3, "milímetros": 1e-3, "mm": 1e-3,
    "milha": 1609.344, "milhas": 1609.344, "mile": 1609.344, "miles": 1609.344,
    "jarda": 0.9144, "jardas": 0.9144, "yard": 0.9144, "yards": 0.9144,
    "pé": 0.3048, "pés": 0.3048, "foot": 0.3048, "feet": 0.3048, "ft": 0.3048,
    "polegada": 0.0254, "polegadas": 0.0254, "inch": 0.0254, "inches": 0.0254,
    "légua": 5556.0, "léguas": 5556.0,
    "nanômetro": 1e-9, "nanometro": 1e-9, "nm": 1e-9,
}

# Base: quilograma
_MASSA: dict[str, float] = {
    "quilograma": 1.0, "quilogramas": 1.0, "quilo": 1.0, "quilos": 1.0, "kg": 1.0,
    "grama": 1e-3, "gramas": 1e-3, "g": 1e-3,
    "miligrama": 1e-6, "miligramas": 1e-6, "mg": 1e-6,
    "tonelada": 1e3, "toneladas": 1e3, "ton": 1e3,
    "libra": 0.453592, "libras": 0.453592, "lb": 0.453592, "lbs": 0.453592,
    "onça": 0.028350, "onças": 0.028350, "oz": 0.028350,
    "arroba": 14.688, "arrobas": 14.688,
}

# Base: litro
_VOLUME: dict[str, float] = {
    "litro": 1.0, "litros": 1.0, "l": 1.0,
    "mililitro": 1e-3, "mililitros": 1e-3, "ml": 1e-3,
    "centilitro": 0.01, "centilitros": 0.01, "cl": 0.01,
    "galão": 3.78541, "galões": 3.78541, "gallon": 3.78541, "gallons": 3.78541,
    "xícara": 0.24, "xícaras": 0.24, "cup": 0.24, "cups": 0.24,
    "colher de sopa": 0.015, "tablespoon": 0.015, "tbsp": 0.015,
    "colher de chá": 0.005, "teaspoon": 0.005, "tsp": 0.005,
}

# Base: m/s
_VELOCIDADE: dict[str, float] = {
    "m/s": 1.0, "metro por segundo": 1.0, "metros por segundo": 1.0,
    "km/h": 1 / 3.6, "quilômetro por hora": 1 / 3.6, "quilometro por hora": 1 / 3.6,
    "mph": 0.44704, "milha por hora": 0.44704, "milhas por hora": 0.44704,
    "nó": 0.514444, "nós": 0.514444, "knot": 0.514444, "knots": 0.514444,
    "mach": 340.29,
}

# Base: m²
_AREA: dict[str, float] = {
    "m²": 1.0, "metro quadrado": 1.0, "metros quadrados": 1.0,
    "km²": 1e6, "quilômetro quadrado": 1e6, "quilômetros quadrados": 1e6,
    "cm²": 1e-4, "centímetro quadrado": 1e-4,
    "hectare": 1e4, "hectares": 1e4, "ha": 1e4,
    "acre": 4046.86, "acres": 4046.86,
    "alqueire": 24200.0, "alqueires": 24200.0,
}

_TABELAS = [_COMPRIMENTO, _MASSA, _VOLUME, _VELOCIDADE, _AREA]

# Alias de temperaturas
_CELSIUS    = {"celsius", "°c", "graus celsius", "c", "grau celsius", "celcius"}
_FAHRENHEIT = {"fahrenheit", "°f", "graus fahrenheit", "f", "grau fahrenheit"}
_KELVIN     = {"kelvin", "k", "kelvins"}


def _find_unit(nome: str) -> tuple[float, dict] | tuple[None, None]:
    n = nome.strip().lower()
    for tab in _TABELAS:
        if n in tab:
            return tab[n], tab
    return None, None


def _converter_temp(valor: float, de: str, para: str) -> float | None:
    d = de.lower().strip()
    p = para.lower().strip()

    # Normaliza para Celsius
    if d in _CELSIUS:
        c = valor
    elif d in _FAHRENHEIT:
        c = (valor - 32) * 5 / 9
    elif d in _KELVIN:
        c = valor - 273.15
    else:
        return None

    # Converte de Celsius para destino
    if p in _CELSIUS:
        return c
    elif p in _FAHRENHEIT:
        return c * 9 / 5 + 32
    elif p in _KELVIN:
        return c + 273.15
    return None


def converter(valor: float, de: str, para: str) -> str:
    """Converte `valor` de `de` para `para`. Retorna string formatada."""
    # Temperatura (caso especial)
    temp = _converter_temp(valor, de, para)
    if temp is not None:
        r = round(temp, 4)
        return f"{valor} {de} = **{r} {para}**, senhor."

    fator_de, tab_de     = _find_unit(de)
    fator_para, tab_para = _find_unit(para)

    if fator_de is None:
        return f"Unidade '{de}' não reconhecida, senhor."
    if fator_para is None:
        return f"Unidade '{para}' não reconhecida, senhor."
    if tab_de is not tab_para:
        return f"Não é possível converter {de} para {para} — são categorias diferentes, senhor."

    resultado = valor * fator_de / fator_para

    # Formatação inteligente
    if resultado == int(resultado):
        r_str = str(int(resultado))
    elif abs(resultado) < 0.0001:
        r_str = f"{resultado:.8f}".rstrip("0")
    elif abs(resultado) < 1:
        r_str = f"{resultado:.6f}".rstrip("0").rstrip(".")
    else:
        r_str = f"{resultado:.4f}".rstrip("0").rstrip(".")

    return f"{valor} {de} = **{r_str} {para}**, senhor."
