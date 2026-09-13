# Plano 02 — Mensageria com 2 Perfis (JARVIS vs Usuário)

## Estado Atual

- WhatsApp: `pywhatkit` abre WhatsApp Web/Desktop **na conta do usuário**. Não há separação de identidade.
- Instagram: `instagrapi` faz login com credenciais do usuário (sessão em `temp/instagram_session.json`).
- Discord: foco hoje em controlar o cliente desktop pessoal (Electron) via `janela_ctrl.py` — nada de bot independente.
- Telegram, Gmail: não integrados.

## Problema

- Tudo que o JARVIS envia hoje sai como se fosse o usuário. Não dá para deixar o JARVIS rodando 24/7 respondendo gente — ele invadiria as conversas pessoais.
- Sem isolamento de cookies/tokens entre o "JARVIS-bot" e a conta do usuário.
- Sem opção de toggle "responda em meu nome" vs "responda como você mesmo".

## Plano

### Conceito — dois perfis distintos

```
profiles/
├── jarvis/           ← contas próprias do bot
│   ├── discord/      (bot token, guild list)
│   ├── whatsapp/     (sessão WhatsApp Business API ou wppconnect/whatsapp-web.js c/ número dedicado)
│   ├── instagram/    (conta IG bot)
│   ├── telegram/     (bot token via @BotFather)
│   └── gmail/        (conta Google bot)
└── user/             ← opt-in: JARVIS opera em nome do usuário
    ├── discord/      (user token — NÃO RECOMENDADO, ToS — usar apenas read via app autorizado)
    ├── whatsapp/     (sessão WA Web isolada, browser próprio do plano 04)
    ├── instagram/    (sessão isolada de instagrapi)
    └── gmail/        (OAuth2 do usuário)
```

### Camada de abstração — `messaging/`

Interface comum:

```python
class MessageBackend(Protocol):
    profile: Literal["jarvis", "user"]
    platform: Literal["discord", "whatsapp", "instagram", "telegram", "gmail"]
    def send(self, dest: str, content: str) -> SendResult: ...
    def read_inbox(self, since: datetime) -> list[Message]: ...
    def list_contacts(self) -> list[Contact]: ...
    def reply(self, msg_id: str, content: str) -> SendResult: ...
```

Cada backend (`DiscordBotBackend`, `DiscordUserBackend`, `WhatsAppWAWebBackend`, etc.) implementa a interface, declara qual perfil suporta e quais permissões precisa.

### Roteamento

- Comando do usuário: "manda mensagem para o Pedro" →
  1. `messaging_router` consulta o toggle `MSG_DEFAULT_PROFILE` em config (`jarvis` ou `user`).
  2. Se ambíguo (ex: contato existe nos dois), pergunta: "Quer que eu mande do meu perfil ou do seu, Senhor?"
- Comando "responde no Discord como JARVIS" → força `profile=jarvis`.
- Comando "manda do meu Instagram" → força `profile=user`.

### Cofre por perfil

- Cada perfil tem seu próprio cofre (plano 03): `credentials/profiles/jarvis/`, `credentials/profiles/user/`.
- Tokens nunca cruzam.

### WhatsApp — opções técnicas

| Opção | Perfil | Prós | Contras |
|-------|--------|------|---------|
| `wppconnect` / `whatsapp-web.js` em browser próprio | jarvis ou user | Funciona com nº comum, isolado | Node.js sidecar, depende de QR code |
| Cloud API oficial (Meta) | jarvis | Estável, oficial | Precisa nº comercial + aprovação |
| `pywhatkit` (atual) | user | Funciona já | Usa WA do usuário, intrusivo |

Recomendação: **manter `pywhatkit` como fallback no perfil user**; adicionar `wppconnect` sidecar opcional (toggle off) para o perfil JARVIS.

## Decisões pendentes

1. **Discord user token**: ToS proíbe selfbots. Recomendação: para perfil user, JARVIS apenas **lê via app OAuth autorizado** (não envia). Para enviar, sempre perfil JARVIS (bot oficial).
2. **WhatsApp perfil JARVIS**: número dedicado ou modo cloud API? Recomendação inicial: `wppconnect` com número dedicado (mais barato).
3. **Default**: ao instalar sem configurar nada, qual perfil ativo? Recomendação: nenhum — toggles em OFF; pessoa habilita o que quiser.

## Riscos

- Discord selfbot = banimento da conta. Linha clara: nunca usar token de user p/ enviar.
- WhatsApp não-oficial = risco de banimento do número. Documentar para o instalador.
- Múltiplas sessões no mesmo browser engine pode esgotar memória — pool gerenciado (plano 04).

## Referências de código

- [comandos/msg_sender.py](../../comandos/msg_sender.py) — WA + IG atuais
- [comandos/notif_ctrl.py](../../comandos/notif_ctrl.py) — recepção
- [comandos/discord_ctrl.py](../../comandos/discord_ctrl.py) — controle do client desktop atual

## Histórico

- 2026-05-25 — Plano criado.
