"""O navegador do dono sob controle do Jarvis (ADR-0027): extensão, host nativo e cliente.

A cadeia inteira não abre porta de rede:

    Jarvis ──(socket Unix, 0600, pasta 0700)── host nativo ──(stdio)── navegador ── extensão

O navegador é quem **lança** o host (Native Messaging), então o host é o lado que escuta e o
Jarvis é o cliente. Tudo que volta da página é **dado de terceiro**: nunca instrução.
"""
