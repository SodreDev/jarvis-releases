// Seletores do monitor das redes sociais (ADR-0060; regras em docs/redes-sociais-riscos.md §3).
// SÓ DADOS: um objeto literal, sem lógica (o teste confere que é JSON puro). Quando uma rede mudar
// a página, é aqui que se mexe, subindo a `versao`.
//
// Regras: papel (role), aria-label, atributo de dado estável e estrutura — nunca classe CSS
// ofuscada. Cada lista vai em ordem de preferência; o título da aba é o recuo de toda contagem.
// `login`: só existe na tela de entrar. `essenciais`: só existe logado — é o canário: sem nenhum
// deles e sem login, o formato é «desconhecido» e a rede só notifica.
globalThis.__jarvisSeletoresSociais = {
  "versao": 1,
  "alertas": {
    "captcha": ["iframe[src*='captcha']", "iframe[title*='captcha']", "iframe[title*='CAPTCHA']", "[aria-label*='captcha']"],
    "onde": ["[role='alertdialog']", "[role='dialog']", "[role='alert']"],
    "textos": {
      "captcha": "captcha|não sou um robô|nao sou um robo|i'm not a robot",
      "verificacao": "confirme (que é você|sua identidade)|confirm (it's you|your identity)|código de (segurança|verificação)|security code|verification code|verifique sua conta|verify your account",
      "limitada": "conta (foi )?(limitada|bloqueada|suspensa|banida|restrita)|account (has been |was )?(limited|locked|suspended|banned|restricted)|temporariamente bloquead|temporarily (blocked|banned)",
      "atividade_incomum": "atividade (incomum|suspeita)|(unusual|suspicious) activity"
    }
  },
  "redes": {
    "whatsapp": {
      "hosts": ["web.whatsapp.com"],
      "login": ["canvas[aria-label]", "[data-ref]"],
      "essenciais": ["#pane-side", "[aria-label='Lista de conversas']", "[aria-label='Chat list']"],
      "conversa": ["#pane-side [role='listitem']", "#pane-side [role='row']"],
      "nome": ["span[title]", "[dir='auto'][title]"],
      "selo": ["span[aria-label*='não lida']", "span[aria-label*='unread']"]
    },
    "instagram": {
      "hosts": ["www.instagram.com", "instagram.com"],
      "login": ["input[name='username']", "form#loginForm"],
      "essenciais": ["a[href='/direct/inbox/']", "svg[aria-label='Direct']", "[role='navigation']"],
      "conversa": ["[role='listitem']"],
      "nome": ["span[title]"],
      "selo": ["[aria-label*='não lida']", "[aria-label*='unread']"]
    },
    "facebook": {
      "hosts": ["www.facebook.com", "facebook.com", "web.facebook.com"],
      "login": ["input[name='email'][type]", "button[name='login']", "#loginbutton"],
      "essenciais": ["[role='navigation']", "[aria-label='Messenger']", "[aria-label='Conversas']"],
      "conversa": ["[role='row']"],
      "nome": ["span[title]"],
      "selo": ["[aria-label*='não lida']", "[aria-label*='unread']"]
    },
    "tiktok": {
      "hosts": ["www.tiktok.com", "tiktok.com"],
      "login": ["[data-e2e='top-login-button']", "[data-e2e='login-modal']"],
      "essenciais": ["[data-e2e='profile-icon']", "[data-e2e='inbox-icon']", "[data-e2e='chat-list-item']"],
      "conversa": ["[data-e2e='chat-list-item']"],
      "nome": ["[data-e2e='chat-list-item-name']", "p[title]"],
      "selo": ["[data-e2e='unread-count']"]
    },
    "discord": {
      "hosts": ["discord.com", "ptb.discord.com", "canary.discord.com"],
      "login": ["input[name='email']", "input[name='password']"],
      "essenciais": ["[data-list-id='guildsnav']", "[data-list-id='private-channels']", "nav[aria-label]"],
      "conversa": ["[data-list-id='private-channels'] [role='listitem']", "[data-list-id='private-channels'] li"],
      "nome": ["a[aria-label]", "[aria-label]"],
      "selo": ["[aria-label*='menç']", "[aria-label*='mention']", "[aria-label*='não lida']", "[aria-label*='unread']"]
    }
  }
};
