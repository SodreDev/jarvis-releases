# comandos/cotacao_ctrl.py — J.A.R.V.I.S.
# Cotações: câmbio (AwesomeAPI), cripto (CoinGecko), geral
# -*- coding: utf-8 -*-

from __future__ import annotations
import urllib.request
import json

_AWESOME_URL = "https://economia.awesomeapi.com.br/json/last/{}"
_COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids={}&vs_currencies=brl,usd"
)

# Atalhos comuns
_MOEDAS = {
    "dolar": "USD-BRL",
    "dólar": "USD-BRL",
    "euro": "EUR-BRL",
    "libra": "GBP-BRL",
    "iene": "JPY-BRL",
    "yuan": "CNY-BRL",
    "peso": "ARS-BRL",
}

_CRIPTO = {
    "bitcoin": "bitcoin",
    "btc": "bitcoin",
    "ethereum": "ethereum",
    "eth": "ethereum",
    "solana": "solana",
    "sol": "solana",
    "dogecoin": "dogecoin",
    "doge": "dogecoin",
    "cardano": "cardano",
    "ada": "cardano",
    "bnb": "binancecoin",
}


def _fetch_json(url: str, timeout: int = 8) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def cotacao_moeda(nome: str) -> str:
    """Busca cotação de câmbio via AwesomeAPI."""
    chave = nome.strip().lower()

    # Tenta como cripto
    if chave in _CRIPTO:
        return cotacao_cripto(chave)

    par = _MOEDAS.get(chave, chave.upper() + "-BRL")
    try:
        data = _fetch_json(_AWESOME_URL.format(par))
        if not data:
            return f"Não encontrei cotação para '{nome}'."

        # AwesomeAPI retorna {"USDBRL": {...}}
        key = list(data.keys())[0]
        info = data[key]
        nome_moeda = info.get("name", par)
        bid = float(info["bid"])
        ask = float(info["ask"])
        variacao = info.get("pctChange", "?")
        hora = info.get("create_date", "")

        return (
            f"💱 {nome_moeda}\n"
            f"  Compra: R$ {bid:.4f}\n"
            f"  Venda:  R$ {ask:.4f}\n"
            f"  Variação: {variacao}%\n"
            f"  Atualizado: {hora}"
        )
    except Exception as e:
        return f"Erro ao buscar cotação de {nome}: {e}"


def cotacao_cripto(nome: str) -> str:
    """Busca preço de criptomoeda via CoinGecko."""
    chave = nome.strip().lower()
    coin_id = _CRIPTO.get(chave, chave)
    try:
        data = _fetch_json(_COINGECKO_URL.format(coin_id))
        if coin_id not in data:
            return f"Não encontrei a cripto '{nome}'."
        info = data[coin_id]
        brl = info.get("brl", 0)
        usd = info.get("usd", 0)
        return (
            f"🪙 {coin_id.title()}\n"
            f"  BRL: R$ {brl:,.2f}\n"
            f"  USD: $ {usd:,.2f}"
        )
    except Exception as e:
        return f"Erro ao buscar cotação de {nome}: {e}"


def cotacao_resumo() -> str:
    """Resumo rápido: Dólar, Euro, Bitcoin."""
    partes = []
    try:
        data = _fetch_json(_AWESOME_URL.format("USD-BRL,EUR-BRL"))
        for key in ["USDBRL", "EURBRL"]:
            if key in data:
                info = data[key]
                partes.append(
                    f"  {info['name']}: R$ {float(info['bid']):.4f} "
                    f"({info.get('pctChange', '?')}%)"
                )
    except Exception:
        partes.append("  Câmbio indisponível")
    try:
        data = _fetch_json(_COINGECKO_URL.format("bitcoin"))
        if "bitcoin" in data:
            brl = data["bitcoin"]["brl"]
            partes.append(f"  Bitcoin: R$ {brl:,.2f}")
    except Exception:
        partes.append("  Bitcoin indisponível")
    return "💱 Cotações:\n" + "\n".join(partes)
