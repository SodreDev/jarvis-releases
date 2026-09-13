# 🔐 credentials/

Esta pasta guarda **todos** os dados pessoais e credenciais do J.A.R.V.I.S.
A pasta inteira está no `.gitignore` — você pode commitar o projeto sem medo.

## Setup inicial

1. Copie o template:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Abra `.env` e preencha as chaves de API que você for usar (todas são
   opcionais — se uma estiver em branco, o módulo correspondente é desativado).
3. (Opcional) Se você já usa o JARVIS, o `main.py` migra automaticamente
   na primeira execução os arquivos legados da raiz (`contatos.json`,
   `alarmes.json`, etc.) para cá. Não precisa fazer nada.

## Arquivos que vivem aqui

| Arquivo                    | Conteúdo                                      |
|----------------------------|-----------------------------------------------|
| `.env`                     | Chaves de API e credenciais (Instagram, Discord, Spotify, etc.) |
| `contatos.json`            | Sua agenda de contatos                        |
| `alarmes.json`             | Alarmes ativos                                |
| `condicionais.json`        | Regras condicionais ("se X, faça Y")          |
| `jarvis_prefs.json`        | Suas preferências (modelos, cidade, mic, ...)|
| `jarvis_modo.json`         | Modos de personalidade ativos                 |
| `historico.jsonl`          | Histórico de comandos                         |
| `notif_history.jsonl`      | Histórico de notificações                     |
| `vision_cache.jsonl`       | Cache de análises visuais                     |
| `instagram_session.json`   | Cookie de sessão do Instagram (auto)          |
| `gmail_credentials.json`   | OAuth client secret do Gmail (você baixa)     |
| `gmail_token.json`         | Token OAuth do Gmail (auto)                   |

## Onde obter cada credencial

Veja os comentários dentro do próprio `.env.example` — cada bloco tem o
link direto para criar/copiar a chave.

## Segurança

- **Nunca** commite `.env` ou qualquer arquivo desta pasta.
- O `.gitignore` da raiz já bloqueia tudo aqui dentro, exceto este README,
  o template `.env.example` e o `.gitkeep`.
- Em frozen mode (`.exe`), esta pasta fica ao lado do executável, então
  você pode mover a pasta `dist/JARVIS/` para outro lugar mantendo suas
  credenciais.
