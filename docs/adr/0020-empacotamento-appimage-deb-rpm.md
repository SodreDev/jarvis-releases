# ADR-0020 — Um AppDir, três embalagens: AppImage, `.deb` e `.rpm`

**Data:** 2026-10-16 · **Estado:** aceita · **Decide:** dono
**Pedido:** o dono quer **instalar** o Jarvis: AppImage que roda em qualquer distro, `.deb`
para Debian/Ubuntu e `.rpm` para a máquina dele (Nobara/Fedora).
**Alcance:** o aplicativo de hoje — a janela da ADR-0019 e o laço de voz da F1. Não decide
publicação: nada de *release*, *tag*, *upload* ou *push* sem ordem do dono.

## Contexto

O que precisa caber num pacote não é só o nosso código: é Python 3.12 (a decisão D1), o Qt 6
das rodas do PySide6, `numpy`, `onnxruntime`, `ctranslate2`, `sounddevice` e meia dúzia de
dependências puras. Três fatos mandam no desenho:

1. **o Python do sistema não serve.** Fedora 44 traz 3.14, Debian 13 traz 3.13, Ubuntu 24.04
   traz 3.12 — e as rodas de que dependemos não existem para todas elas. Um pacote que
   dependa do interpretador da distro funciona numa e quebra nas outras;
2. **a obrigação do LGPL é de re-ligar** (ADR-0019): o Qt tem de ficar em `.so` **separados e
   substituíveis**. Isso elimina qualquer empacotador que funda tudo num executável só;
3. **peso de modelo não é programa.** A voz do piper tem 63,2 MB e um modelo de ASR tem
   centenas: enfiá-los nos três artefatos triplicaria o download para entregar um arquivo que
   a máquina do dono talvez já tenha.

## Decisão

**Um AppDir, montado uma vez, vira os três artefatos** (`tools/empacotar.py`):

- **Python relocável** instalado pelo `uv` (python-build-standalone) dentro de
  `usr/lib/jarvis/python` — mesmo interpretador em toda distro, independente do que ela traz;
- **dependências da trava**: `uv export --frozen` tira de `uv.lock` exatamente as rodas dos
  grupos `gui`, `voz`, `asr` e `dispositivo`, e `uv pip install` as põe lá dentro **como
  vieram** — nada é recompilado, nada é fundido, o Qt continua em `.so` próprios;
- **dados** (`licenses/`, `schemas/`, `tabelas/`, `catalogo/`, `NOTICE`, `LICENSE`) em
  `usr/share/jarvis`, achados em tempo de execução por `jarvis.dados` via `JARVIS_DADOS`;
- **textos de licença** (LGPL-3.0, GPL-3.0, BSD-3 do SecretStorage, Apache-2.0 nosso) em
  `usr/share/licenses/jarvis` — a obrigação de redistribuição da ADR-0019, cumprida em arquivo;
- **um lançador só** (`usr/bin/jarvis`), que descobre a raiz pelo próprio caminho: o mesmo
  script serve ao AppImage (via `AppRun`) e à instalação em `/usr`;
- **ícone e `.desktop`** instalados no padrão do freedesktop, para o aplicativo aparecer no
  menu com nome e ícone.

Depois disso, `appimagetool` embrulha o AppDir e o `nfpm` gera `.deb` e `.rpm` do **mesmo**
conteúdo. Montar três vezes seria manter três verdades.

## Ferramentas comparadas (licença verificada na origem em 2026-10-16)

| ferramenta | licença | o que resolveria | decisão |
|---|---|---|---|
| **uv + python-build-standalone** | uv Apache-2.0/MIT; o projeto do Python relocável, MPL-2.0 | interpretador portátil e instalação a partir da trava | **escolhida** — nada compila, as rodas entram como vieram, e a trava é a mesma do CI |
| **appimagetool** (AppImage) | MIT (`LICENSE` do repositório) | embrulha um AppDir num executável único | **escolhida** para o AppImage |
| **nfpm** | MIT (`LICENSE.md` do repositório) | `.deb` e `.rpm` da **mesma** receita, sem `dpkg-deb` nem `rpmbuild` | **escolhida** para os dois pacotes |
| PyInstaller | GPL-2.0-or-later **com exceção de bootloader** | congelar o aplicativo num diretório ou executável | **recusada**: a régua da ADR-0011 prefere permissiva, e o modo de congelar dificulta exatamente o que o LGPL exige — o dono poder **trocar** a biblioteca do Qt |
| Nuitka | Apache-2.0 | compilar o Python para C | **recusada no v0**: build longo, e o ganho (tamanho, partida) não paga o risco agora. Continua candidata |
| Briefcase (BeeWare) | BSD-3 | já gera AppImage, `.deb` e `.rpm` | **recusada**: traz o próprio fluxo de projeto e a própria opinião sobre Qt; é uma camada a mais entre a trava e o artefato |
| Flatpak / Snap | — | distribuição por loja, com runtime | **fora do pedido**: o dono pediu AppImage, `.deb` e `.rpm`; e ambos acrescentam um runtime que não controlamos |
| `dpkg-deb` + `rpmbuild` do sistema | GPL-2.0 | gerar os pacotes nativamente | **recusados**: copyleft forte como ferramenta de build é tolerável, mas exigiria duas receitas e duas distros de build; o nfpm faz os dois de uma receita, em MIT |
| linuxdeployqt | GPL-3.0 | juntar as dependências do Qt automaticamente | **recusada**: copyleft forte, e o que ela resolve (copiar `.so` do sistema) é justamente o que **não** queremos — ver o piso de glibc abaixo |

## O piso de glibc, e por que não empacotamos bibliotecas do sistema

As rodas do PySide6 6.9.3 são `manylinux_2_28` e o Python relocável é construído para glibc
2.17+: o piso do artefato é **glibc 2.28** (Debian 10+, Ubuntu 18.10+, RHEL/Alma 8+, Fedora
29+). Copiar `libxcb*`, `libGL` e companhia **desta** máquina para dentro do AppImage subiria
esse piso para o glibc do Fedora 44 — o oposto do que um AppImage promete. Então:

- no `.deb` e no `.rpm`, as bibliotecas de sistema que o Qt exige entram como **dependência
  declarada** (`libxcb-cursor0`, `libxkbcommon-x11-0`, `libgl1`, `fontconfig`… e os nomes
  equivalentes no Fedora): o gerenciador de pacotes resolve, que é o trabalho dele;
- no **AppImage**, elas são requisito da máquina. Está escrito no `COMO-TESTAR.md`, com o
  comando de instalação por distro, e é a limitação honesta desta decisão: "roda em qualquer
  distro" quer dizer "em qualquer distro com um desktop Qt/GTK normal instalado", não "numa
  imagem mínima sem nada".

## Verificação — cada artefato roda numa distro que não é esta

`tools/empacotar.py verificar` sobe três contêineres (`podman run --rm --name … --timeout …`,
nunca `kill` solto) e, em cada um, **executa o aplicativo**:

| artefato | distro | o que roda |
|---|---|---|
| AppImage | `debian:stable-slim` | extrai (`--appimage-extract`, porque contêiner não tem FUSE) e roda `--versao`, `--diagnostico` e `--capturar` |
| `.deb` | `debian:stable-slim` | instala com `apt-get install ./jarvis_*.deb` e roda o mesmo trio, mais a conferência do `.desktop` e do texto da LGPL |
| `.rpm` | `fedora:44` | instala com `dnf install` e roda o mesmo |

`--capturar` é o que torna a verificação séria: ele **desenha as cinco telas** em
`QT_QPA_PLATFORM=offscreen`. Um pacote que só respondesse `--versao` provaria que o Python
subiu; este prova que o Qt carregou, que o QML compilou e que os dados foram encontrados.

## Consequências

- **Mais fácil:** o dono instala e abre pelo menu, em três distros, sem tocar em Python;
- **Mais caro:** os artefatos são grandes (o Qt e o `onnxruntime` dominam), e o build depende
  de rede na primeira vez (Python relocável, rodas, `appimagetool`, `nfpm`);
- **Passa a ser obrigatório testar:** que o aplicativo acha os dados fora da árvore
  (`jarvis.dados`), que cada artefato **executa** na distro-alvo, e que os textos de licença
  chegaram dentro do pacote.

## Como invalidar esta decisão

- O tamanho virar problema para o dono: a saída é Nuitka ou um pacote por caminho de voz
  (sem ASR local), e os dois mexem só no `empacotar.py`;
- Alguma distro-alvo sair do piso de glibc 2.28, ou o PySide6 abandonar o `manylinux_2_28`:
  aí a decisão de versão da ADR-0019 é revisitada junto;
- O dono querer loja (Flatpak/Snap): o AppDir continua servindo de base, e o que muda é o
  embrulho.
