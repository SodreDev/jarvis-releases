"""Cofre de credenciais do JARVIS — tiers JSON e AES-GCM."""

from .vault import Vault, VaultError, get_vault

__all__ = ["Vault", "VaultError", "get_vault"]
