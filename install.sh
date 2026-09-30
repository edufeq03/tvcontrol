#!/usr/bin/env bash
# ==============================================================================
# IgnoControl - Instalador Universal & Configurador de Ambiente
# ==============================================================================

set -e

# Cores e Formatação
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # Sem Cor

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info() {
    echo -e "${CYAN}${BOLD}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}${BOLD}[OK]${NC} $1"
}

warn() {
    echo -e "${YELLOW}${BOLD}[AVISO]${NC} $1"
}

error() {
    echo -e "${RED}${BOLD}[ERRO]${NC} $1" >&2
}

banner() {
    echo -e "${PURPLE}${BOLD}"
    echo "========================================================"
    echo "       🚀 IgnoControl - Instalador Automático           "
    echo "========================================================"
    echo -e "${NC}"
}

# ------------------------------------------------------------------------------
# Desinstalação
# ------------------------------------------------------------------------------
uninstall() {
    banner
    info "Iniciando desinstalação do IgnoControl..."

    # Remover serviço de usuário do systemd
    if [ -f "$HOME/.config/systemd/user/ignocontrol.service" ]; then
        info "Desativando serviço de usuário..."
        systemctl --user stop ignocontrol.service 2>/dev/null || true
        systemctl --user disable ignocontrol.service 2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/ignocontrol.service"
        systemctl --user daemon-reload 2>/dev/null || true
        info "Serviço de usuário removido"
    fi

    # Remover do autostart
    if [ -f "$HOME/.config/autostart/ignocontrol.desktop" ]; then
        rm -f "$HOME/.config/autostart/ignocontrol.desktop"
        info "Removido de ~/.config/autostart"
    fi

    # Remover do menu de aplicativos
    if [ -f "$HOME/.local/share/applications/ignocontrol.desktop" ]; then
        rm -f "$HOME/.local/share/applications/ignocontrol.desktop"
        info "Removido de ~/.local/share/applications"
    fi

    # Remover da Área de Trabalho
    if [ -f "$HOME/Desktop/ignocontrol.desktop" ]; then
        rm -f "$HOME/Desktop/ignocontrol.desktop"
        info "Removido do Desktop"
    fi

    # Atualizar base de dados de desktops
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi

    # Parar e remover serviço do ydotool se o usuário desejar
    read -rp "Deseja também desativar e remover o serviço do ydotool? (s/N): " resp
    if [[ "$resp" =~ ^[sS]$ ]]; then
        info "Removendo serviço ydotool..."
        sudo systemctl stop ydotool 2>/dev/null || true
        sudo systemctl disable ydotool 2>/dev/null || true
        sudo rm -f /etc/systemd/system/ydotool.service
        sudo systemctl daemon-reload
        success "Serviço ydotool removido!"
    fi

    echo ""
    success "IgnoControl foi desinstalado com sucesso!"
    exit 0
}

# ------------------------------------------------------------------------------
# Processar argumentos
# ------------------------------------------------------------------------------
if [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
    echo "Uso: $0 [OPÇÕES]"
    echo ""
    echo "Opções:"
    echo "  --help, -h         Mostra esta mensagem de ajuda"
    echo "  --uninstall, -u    Desinstala atalhos, autostart e configurações"
    echo ""
    exit 0
fi

if [ "$1" == "--uninstall" ] || [ "$1" == "-u" ]; then
    uninstall
fi

# ------------------------------------------------------------------------------
# Verificação de Usuário
# ------------------------------------------------------------------------------
if [ "$EUID" -eq 0 ]; then
    error "Não execute este script diretamente com sudo ou como root!"
    error "Execute como seu usuário normal: ./install.sh"
    error "O script solicitará privilégios de sudo apenas quando necessário."
    exit 1
fi

banner

# ------------------------------------------------------------------------------
# 1. Instalação de Dependências do Sistema Operacional
# ------------------------------------------------------------------------------
info "[1/5] Detectando gerenciador de pacotes e instalando dependências do sistema..."

install_packages() {
    if command -v apt-get >/dev/null 2>&1; then
        info "Gerenciador detectado: apt-get (Debian / Ubuntu / Mint / Pop!_OS)"
        
        PKGS_TO_INSTALL=()
        for pkg in python3 python3-venv python3-pip playerctl ydotool xdotool pulseaudio-utils libnotify-bin; do
            if ! dpkg -s "$pkg" >/dev/null 2>&1; then
                PKGS_TO_INSTALL+=("$pkg")
            fi
        done

        if [ ${#PKGS_TO_INSTALL[@]} -ne 0 ]; then
            info "Instalando pacotes necessários: ${PKGS_TO_INSTALL[*]}"
            sudo apt-get update -qq
            sudo apt-get install -y "${PKGS_TO_INSTALL[@]}"
        else
            success "Todos os pacotes do sistema já estão instalados!"
        fi

    elif command -v dnf >/dev/null 2>&1; then
        info "Gerenciador detectado: dnf (Fedora / RHEL)"
        sudo dnf install -y python3 python3-pip playerctl ydotool xdotool pulseaudio-utils libnotify
    elif command -v pacman >/dev/null 2>&1; then
        info "Gerenciador detectado: pacman (Arch Linux / Manjaro)"
        sudo pacman -S --needed --noconfirm python python-pip playerctl ydotool xdotool libpulse libnotify
    elif command -v zypper >/dev/null 2>&1; then
        info "Gerenciador detectado: zypper (openSUSE)"
        sudo zypper install -y python3 python3-pip playerctl ydotool xdotool pulseaudio-utils libnotify-tools
    else
        warn "Gerenciador de pacotes não identificado automaticamente."
        warn "Certifique-se de ter instalado: python3, python3-venv, playerctl, ydotool, xdotool e pactl."
    fi
}

install_packages

# ------------------------------------------------------------------------------
# 2. Configuração do Ambiente Virtual Python (venv)
# ------------------------------------------------------------------------------
info "[2/5] Configurando ambiente virtual Python..."

VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    info "Criando ambiente virtual em $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

info "Instalando/atualizando dependências Python..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    "$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
    success "Dependências Python instaladas com sucesso!"
else
    warn "requirements.txt não encontrado em $SCRIPT_DIR!"
fi

# ------------------------------------------------------------------------------
# 3. Configuração do Serviço do ydotool (Systemd)
# ------------------------------------------------------------------------------
info "[3/5] Configurando serviço do ydotool (daemon de simulação de mouse/teclado)..."

if systemctl is-active --quiet ydotool 2>/dev/null; then
    success "Serviço ydotool já está configurado e em execução!"
else
    YDOTOOLD_BIN="$(command -v ydotoold || true)"
    if [ -z "$YDOTOOLD_BIN" ]; then
        for p in /usr/bin/ydotoold /usr/local/bin/ydotoold /bin/ydotoold; do
            if [ -x "$p" ]; then
                YDOTOOLD_BIN="$p"
                break
            fi
        done
    fi

    if [ -n "$YDOTOOLD_BIN" ]; then
        info "ydotoold encontrado em $YDOTOOLD_BIN. Configurando serviço systemd..."
        sudo tee /etc/systemd/system/ydotool.service > /dev/null << EOF
[Unit]
Description=ydotool daemon
After=multi-user.target

[Service]
Type=simple
ExecStart=${YDOTOOLD_BIN} --socket-path=/tmp/.ydotool_socket --socket-perm=0660
Group=input
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

        sudo systemctl daemon-reload
        sudo systemctl enable --now ydotool
        success "Serviço ydotool ativo e iniciado no boot!"
    else
        warn "Binário ydotoold não encontrado. O suporte a Wayland com ydotool pode ficar limitado."
    fi
fi

# ------------------------------------------------------------------------------
# 4. Geração Dinâmica do Serviço Systemd e Atalhos Desktop (.desktop)
# ------------------------------------------------------------------------------
info "[4/5] Configurando serviço em segundo plano e arquivos de configuração..."

# 4.0 Gerar Configuração e Token Seguro (fora do repositório)
USER_CONFIG_DIR="$HOME/.config/ignocontrol"
USER_CONFIG_FILE="$USER_CONFIG_DIR/config.json"
mkdir -p "$USER_CONFIG_DIR"
if [ ! -f "$USER_CONFIG_FILE" ]; then
    info "Gerando configuração e token seguro aleatório em $USER_CONFIG_FILE..."
    GEN_TOKEN=$("$VENV_DIR/bin/python" -c "import secrets; print(secrets.token_urlsafe(32))")
    if [ -f "$SCRIPT_DIR/config.example.json" ]; then
        sed "s/COLOQUE_UM_TOKEN_SEGURO_AQUI/$GEN_TOKEN/" "$SCRIPT_DIR/config.example.json" > "$USER_CONFIG_FILE"
    else
        echo "{\"token\": \"$GEN_TOKEN\", \"porta\": 7000, \"titulo\": \"IgnoControl\", \"botoes\": []}" > "$USER_CONFIG_FILE"
    fi
    chmod 600 "$USER_CONFIG_FILE"
    success "Token de segurança gerado e salvo em $USER_CONFIG_FILE (permissão 600)!"
fi

# 4.1 Criar Serviço do Usuário no Systemd (~/.config/systemd/user/ignocontrol.service)
mkdir -p "$HOME/.config/systemd/user"
cat << EOF > "$HOME/.config/systemd/user/ignocontrol.service"
[Unit]
Description=IgnoControl Remote Server
After=network.target sound.target

[Service]
Type=simple
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${VENV_DIR}/bin/python ${SCRIPT_DIR}/remote.py --no-browser
Restart=always
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ignocontrol.service 2>/dev/null || true
success "Serviço de segundo plano ativado (inicia automaticamente com o seu usuário)!"

# 4.2 Gerar Atalho Desktop (.desktop)
DESKTOP_FILE="$SCRIPT_DIR/ignocontrol.desktop"
cat << EOF > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Name=IgnoControl
Comment=Controle Remoto Web para Streaming e Mídia
Exec=${VENV_DIR}/bin/python ${SCRIPT_DIR}/remote.py --browser
Icon=${SCRIPT_DIR}/icon.png
Path=${SCRIPT_DIR}
Terminal=false
Categories=Utility;AudioVideo;
StartupNotify=false
X-KDE-autostart-after=panel
X-GNOME-Autostart-enabled=true
EOF

chmod +x "$DESKTOP_FILE"
success "Arquivo $DESKTOP_FILE gerado!"

# Instalar no Menu de Aplicativos (~/.local/share/applications)
mkdir -p "$HOME/.local/share/applications"
cp "$DESKTOP_FILE" "$HOME/.local/share/applications/ignocontrol.desktop"
chmod +x "$HOME/.local/share/applications/ignocontrol.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi
success "Adicionado ao Menu de Aplicativos do Sistema!"

# Instalar no Autostart (~/.config/autostart) com --no-browser (silencioso no boot)
mkdir -p "$HOME/.config/autostart"
sed 's|remote.py --browser|remote.py --no-browser|' "$DESKTOP_FILE" > "$HOME/.config/autostart/ignocontrol.desktop"
chmod +x "$HOME/.config/autostart/ignocontrol.desktop"
success "Adicionado à inicialização automática da sessão (Autostart)!"

# Instalar no Desktop se existir (~/Desktop ou ~/Área de Trabalho)
DESKTOP_DIR=""
if [ -d "$HOME/Desktop" ]; then
    DESKTOP_DIR="$HOME/Desktop"
elif [ -d "$HOME/Área de trabalho" ]; then
    DESKTOP_DIR="$HOME/Área de trabalho"
fi

if [ -n "$DESKTOP_DIR" ]; then
    cp "$DESKTOP_FILE" "$DESKTOP_DIR/ignocontrol.desktop"
    chmod +x "$DESKTOP_DIR/ignocontrol.desktop"
    success "Atalho criado na Área de Trabalho ($DESKTOP_DIR)!"
fi

# ------------------------------------------------------------------------------
# 5. Verificação de Firewall (UFW / Firewalld)
# ------------------------------------------------------------------------------
info "[5/5] Verificando regras de firewall da rede local..."

if command -v ufw >/dev/null 2>&1; then
    if sudo -n ufw status 2>/dev/null | grep -q "Status: active"; then
        info "Firewall UFW ativo detectado. Configurando acesso exclusivo para rede local..."
        sudo ufw delete allow 7000/tcp 2>/dev/null || true
        for subnet in "192.168.0.0/16" "10.0.0.0/8" "172.16.0.0/12"; do
            sudo ufw allow from "$subnet" to any port 7000 proto tcp comment 'IgnoControl LAN' 2>/dev/null || true
        done
        success "Porta 7000/tcp liberada com segurança apenas para redes locais (UFW)!"
    fi
elif command -v firewall-cmd >/dev/null 2>&1; then
    if sudo -n firewall-cmd --state 2>/dev/null | grep -q "running"; then
        info "Firewalld ativo detectado. Liberando porta 7000/tcp para zona interna..."
        sudo firewall-cmd --zone=internal --add-port=7000/tcp --permanent >/dev/null 2>&1 || true
        sudo firewall-cmd --reload >/dev/null 2>&1 || true
        success "Porta 7000/tcp liberada no firewalld (zona interna)!"
    fi
fi

# ------------------------------------------------------------------------------
# 6. Conclusão e Teste de Execução
# ------------------------------------------------------------------------------
info "Finalizando configuração..."
echo ""
echo -e "${GREEN}${BOLD}🎉 Tudo pronto! O IgnoControl está 100% instalado e configurado!${NC}"
echo ""
echo -e "Como usar:"
echo -e "  1. ${BOLD}Pelo Sistema:${NC} Ele já iniciará automaticamente ao fazer login, ou procure por '${CYAN}IgnoControl${NC}' no seu menu de aplicativos."
echo -e "  2. ${BOLD}Pelo Terminal agora:${NC} Execute:"
echo -e "     ${YELLOW}$VENV_DIR/bin/python $SCRIPT_DIR/remote.py${NC}"
echo ""
echo -e "Para desinstalar a qualquer momento: ${YELLOW}./install.sh --uninstall${NC}"
echo ""
