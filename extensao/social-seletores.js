// Seletores do monitor das redes sociais (ADR-0060; regras em docs/redes-sociais-riscos.md §3).
// SÓ DADOS: um objeto literal, sem lógica (o teste confere que é JSON puro). Quando uma rede mudar
// a página, é aqui que se mexe, subindo a `versao`.
//
// Regras: papel (role), aria-label, atributo de dado estável e estrutura — nunca classe CSS
// ofuscada. Cada lista vai em ordem de preferência; o título da aba é o recuo de toda contagem.
// `login`: só existe na tela de entrar. `essenciais`: só existe logado — é o canário: sem nenhum
// deles e sem login, o formato é «desconhecido» e a rede só notifica. `carregando` (opcional): só
// existe na tela de carga — separa a página que ainda carrega da que mudou. `vocabularioDaAmostra`:
// as únicas palavras que a amostra de um contador ilegível guarda (sem acento, minúsculas); o
// resto vira «x». Interface em pt, en e es: os aria-label dos três idiomas.
globalThis.__jarvisSeletoresSociais = {
  "versao": 4,
  "vocabularioDaAmostra": ["whatsapp", "instagram", "facebook", "messenger", "tiktok", "discord", "mensagem", "mensagens", "nao", "lida", "lidas", "lido", "lidos", "marcada", "como", "conversa", "conversas", "unread", "message", "messages", "marked", "as", "chat", "chats", "mensaje", "mensajes", "no", "leido", "leidos", "leida", "leidas", "sin", "leer", "mil", "k", "mais", "more", "mas", "de", "e", "y", "and"],
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
      "carregando": ["progress", "[role='progressbar']", "#initial_startup", "#startup"],
      "essenciais": ["#pane-side", "[aria-label='Lista de conversas']", "[aria-label='Chat list']", "[aria-label='Lista de chats']", "#side"],
      "conversa": ["#pane-side [role='listitem']", "#pane-side [role='row']", "[aria-label='Lista de conversas'] [role='row']", "[aria-label='Chat list'] [role='row']", "[aria-label='Lista de chats'] [role='row']", "#side [role='listitem']", "#side [role='row']"],
      "nome": ["span[title]", "[dir='auto'][title]"],
      "selo": ["span[aria-label*='não lida']", "span[aria-label*='Não lida']", "span[aria-label*='unread']", "span[aria-label*='Unread']", "span[aria-label*='no leíd']", "span[aria-label*='sin leer']"],
      "cabecalho": ["#main header", "[role='main'] header"],
      "nomeDoCabecalho": ["span[title]", "[dir='auto']"],
      "grupo": ["[data-icon='default-group']", "[data-icon='group']"],
      "caixa": ["footer [contenteditable='true'][role='textbox']", "footer [contenteditable='true']"]
    },
    "instagram": {
      "hosts": ["www.instagram.com", "instagram.com"],
      "login": ["input[name='username']", "form#loginForm"],
      "essenciais": ["a[href='/direct/inbox/']", "svg[aria-label='Direct']", "[role='navigation']"],
      "conversa": ["[role='listitem']"],
      "nome": ["span[title]"],
      "selo": ["[aria-label*='não lida']", "[aria-label*='unread']", "[aria-label*='Unread']"]
    },
    "facebook": {
      "hosts": ["www.facebook.com", "facebook.com", "web.facebook.com"],
      "login": ["input[name='email'][type]", "button[name='login']", "#loginbutton"],
      "essenciais": ["[role='navigation']", "[aria-label='Messenger']", "[aria-label='Conversas']"],
      "conversa": ["[role='row']"],
      "nome": ["span[title]"],
      "selo": ["[aria-label*='não lida']", "[aria-label*='unread']", "[aria-label*='Unread']"]
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
