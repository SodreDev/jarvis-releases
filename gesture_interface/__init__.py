"""
Gesture Interface — módulo de interação gestual para o J.A.R.V.I.S.

Subcamadas:
    gesture_engine   — tracking + reconhecimento via MediaPipe Hands
    interaction      — modo classifier + event router
    desktop_control  — automação desktop (virtual desktops, janelas, atalhos)
    canvas2d         — overlay transparente para desenho gestual 2D
    workspace3d      — ambiente de modelagem 3D baseado em micro-partículas
    gesture_training — gravação e treino de gestos customizados
    voice_control    — integração com comandos de voz do Jarvis
    ui               — interface PyWebView (HTML / CSS / JS)
"""

__version__ = "1.0.0"
