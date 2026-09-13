"""Peças comuns aos backends de plataforma."""
from .base import BackendBase, Probe
from .unavailable import Unavailable

__all__ = ["BackendBase", "Probe", "Unavailable"]
