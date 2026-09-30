# 🚀 IgnoControl

> **Controle remoto web moderno e elegante para transformar seu smartphone em um controle multimídia e trackpad para o seu PC Linux.**

---

## 📱 O que o IgnoControl faz?

O **IgnoControl** cria uma interface web (com suporte a PWA) acessível por qualquer celular conectado na mesma rede Wi-Fi que o seu computador. Com ele você pode:

* ⏯️ **Controlar reprodução de mídia:** Play/Pause, avançar/retroceder vídeos (YouTube, Netflix, Spotify, VLC) via `playerctl` e atalhos de teclado.
* 🔊 **Controlar volume do sistema:** Aumentar, diminuir ou mutar áudio com precisão via PulseAudio / PipeWire.
* 🖱️ **Trackpad e Mouse:** Mover o cursor, clicar e rolar páginas diretamente pela tela do smartphone (funciona perfeitamente em **Wayland** e **X11** via `ydotool` / `xdotool`).
* 🖥️ **Ações de tela e energia:** Colocar monitores em suspensão (`dpms off`), tela cheia e desligar o computador à distância com confirmação de segurança.
* ⏱️ **Temporizador de desligamento (Sleep Timer):** Definir um tempo para o computador desligar automaticamente após terminar um episódio ou filme.
* 📲 **PWA Instalável:** Adicione o IgnoControl à tela inicial do seu celular para usá-lo como um app nativo em tela cheia.

---

## ⚡ Instalação Rápida (1 Comando)

Clone o repositório e execute o instalador:

```bash
git clone https://github.com/edufeq03/tvcontrol.git
cd tvcontrol
./install.sh
```

### O que o `install.sh` faz automaticamente para você?
1. **Detecta sua distribuição Linux:** Suporta `apt-get` (Debian, Ubuntu, Mint, Pop!_OS), `dnf` (Fedora), `pacman` (Arch, Manjaro) e `zypper` (openSUSE).
2. **Instala pacotes do sistema necessários:** `playerctl`, `ydotool`, `xdotool`, `pulseaudio-utils` e `libnotify-bin`.
3. **Configura o ambiente Python (`venv`):** Cria a pasta virtual isolada e instala `Flask` e gerador de `qrcode`.
4. **Configura o daemon do `ydotool` no Systemd:** Permite simulação de mouse e teclado mesmo sob Wayland sem necessitar de root nas ações.
5. **Cria atalhos do sistema:**
   * Adiciona o IgnoControl ao seu **Menu de Aplicativos** (`~/.local/share/applications/`).
   * Configura a **Inicialização Automática no Login** (`~/.config/autostart/`).
   * Cria um atalho na sua **Área de Trabalho** (se existir).

---

## 🎮 Como Usar

### 1. Iniciar ou Gerenciar o IgnoControl
* **Pelo sistema:** Ele já inicia sozinho ao ligar o PC / fazer login. Clicar no ícone **IgnoControl** (na Área de Trabalho ou Menu) abrirá a interface diretamente no seu navegador.
* **Comandos úteis via terminal (Systemd):**
  ```bash
  # Ver status do serviço
  systemctl --user status ignocontrol

  # Reiniciar o serviço (após alterar config.json)
  systemctl --user restart ignocontrol

  # Parar temporariamente
  systemctl --user stop ignocontrol
  ```
* **Pelo terminal com QR Code interativo:**
  ```bash
  ./venv/bin/python remote.py
  ```

### 2. Conectar pelo Celular
* Ao iniciar, o terminal exibirá um **QR Code**. Basta apontar a câmera do seu celular para abrir.
* Se o programa iniciar em segundo plano, uma **notificação no desktop** mostrará o endereço IP e a porta prontos para acesso.
* Você também pode acessar diretamente no navegador do celular:
  ```text
  http://<IP_DO_SEU_PC>:7000/?token=minhachave123
  ```

---

## ⚙️ Personalização

Você pode adicionar novos botões, alterar atalhos e comandos editando o arquivo `config.json` diretamente ou através da própria tela de configurações na interface web.

Exemplo de botão em `config.json`:
```json
{
  "id": "play",
  "label": "Play / Pause",
  "sub": "Alternar reprodução",
  "comando": "playerctl play-pause 2>/dev/null || xdotool key space",
  "icone": "play",
  "cor": "blue",
  "largura": "cheia",
  "tag": "Mídia",
  "confirmar": false,
  "ativo": true
}
```

---

## 🗑️ Desinstalação

Se desejar remover os atalhos, o serviço do `ydotool` e as configurações automáticas, basta rodar:

```bash
./install.sh --uninstall
```
