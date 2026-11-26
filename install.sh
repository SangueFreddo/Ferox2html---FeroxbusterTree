#!/usr/bin/env bash
# Ferox2html - installer per Linux (Kali, Parrot, Debian, Ubuntu...)
#
#   ./install.sh               installa l'icona nel menu e sul Desktop + comando "ferox2html"
#   ./install.sh --uninstall   rimuove tutto
#
# Non serve sudo: tutto viene installato solo per il tuo utente.

set -euo pipefail

APP_ID="ferox2html"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/ferox2html.py"
ICON="$DIR/assets/icon.png"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
BIN_DIR="$HOME/.local/bin"
DESKTOP_FILE="$APPS_DIR/$APP_ID.desktop"

# Cartella Desktop (anche se in italiano, es. "Scrivania")
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[ -n "$DESK" ] && [ "$DESK" != "$HOME" ] || DESK="$HOME/Desktop"

green(){ printf '\033[32m[+]\033[0m %s\n' "$*"; }
yellow(){ printf '\033[33m[!]\033[0m %s\n' "$*"; }

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$DESKTOP_FILE" "$DESK/$APP_ID.desktop" "$BIN_DIR/$APP_ID"
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
    green "Ferox2html rimosso (i file del progetto restano in $DIR)."
    exit 0
fi

[ -f "$SCRIPT" ] || { echo "ferox2html.py non trovato in $DIR"; exit 1; }
command -v python3 >/dev/null || { echo "python3 non trovato: sudo apt install python3"; exit 1; }

chmod +x "$SCRIPT"

# 1) Icona nel menu applicazioni (+ "Apri con" per i file .txt/.json)
mkdir -p "$APPS_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Ferox2html
GenericName=Feroxbuster Tree
Comment=Converte l'output di feroxbuster in un sito ad albero (stile DirBuster)
Exec=python3 "$SCRIPT" --gui %F
Icon=$ICON
Terminal=false
Categories=Development;Security;Network;Utility;
MimeType=text/plain;application/json;
Keywords=feroxbuster;dirbuster;pentest;html;report;
StartupNotify=false
EOF
chmod +x "$DESKTOP_FILE"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
green "Icona aggiunta al menu applicazioni"

# 2) Icona sul Desktop
if [ -d "$DESK" ]; then
    cp "$DESKTOP_FILE" "$DESK/$APP_ID.desktop"
    chmod +x "$DESK/$APP_ID.desktop"
    # segna l'icona come "fidata", cosi' si apre con doppio clic senza avvisi
    command -v gio >/dev/null && gio set "$DESK/$APP_ID.desktop" metadata::trusted true 2>/dev/null || true
    green "Icona aggiunta al Desktop ($DESK)"
fi

# 3) Comando "ferox2html" nel terminale
mkdir -p "$BIN_DIR"
ln -sf "$SCRIPT" "$BIN_DIR/$APP_ID"
green "Comando 'ferox2html' creato in $BIN_DIR"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) yellow "$BIN_DIR non e' nel PATH: aggiungi questa riga a ~/.zshrc (o ~/.bashrc):"
       echo "     export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

# 4) Controllo tkinter (serve per la finestra di scelta file)
if ! python3 -c "import tkinter" 2>/dev/null; then
    if command -v zenity >/dev/null; then
        yellow "tkinter non installato: uso zenity per la finestra (va bene uguale)."
    else
        yellow "Per la finestra di scelta file installa tkinter:  sudo apt install python3-tk"
    fi
fi

echo
green "Fatto! Doppio clic sull'icona Ferox2html, oppure tasto destro su un file di feroxbuster > Apri con > Ferox2html"
echo "    Da terminale:  ferox2html scan.txt"
