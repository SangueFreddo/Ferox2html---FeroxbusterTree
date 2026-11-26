#!/usr/bin/env bash
# Ferox2html - installer per Linux (Kali, Parrot, Debian, Ubuntu...)
#
#   ./install.sh               installa (o ripara) icona nel menu, icona sul Desktop e comando "ferox2html"
#   ./install.sh --uninstall   rimuove tutto
#
# Non serve sudo: tutto viene installato solo per il tuo utente.
# Il programma viene COPIATO in ~/.local/share/ferox2html: dopo l'installazione
# puoi spostare o cancellare la cartella scaricata, l'icona continua a funzionare.

set -euo pipefail

APP_ID="ferox2html"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$DATA_HOME/$APP_ID"
APPS_DIR="$DATA_HOME/applications"
BIN_DIR="$HOME/.local/bin"
MENU_FILE="$APPS_DIR/$APP_ID.desktop"

# Cartella Desktop (anche se in italiano, es. "Scrivania")
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
{ [ -n "$DESK" ] && [ "$DESK" != "$HOME" ]; } || DESK="$HOME/Desktop"
DESK_FILE="$DESK/$APP_ID.desktop"

green(){ printf '\033[32m[+]\033[0m %s\n' "$*"; }
yellow(){ printf '\033[33m[!]\033[0m %s\n' "$*"; }

# Toglie Ferox2html dalle associazioni dei file (ripara le vecchie versioni dell'installer,
# che potevano renderlo l'editor di testo predefinito).
clean_associations(){
    local f fixed=0
    for f in "${XDG_CONFIG_HOME:-$HOME/.config}/mimeapps.list" \
             "$APPS_DIR/mimeapps.list" "$APPS_DIR/defaults.list"; do
        [ -f "$f" ] || continue
        grep -q "$APP_ID.desktop" "$f" || continue
        python3 - "$f" "$APP_ID.desktop" <<'PY'
import sys
path, app = sys.argv[1], sys.argv[2]
out = []
for line in open(path, encoding="utf-8", errors="replace").read().splitlines():
    if "=" in line and not line.lstrip().startswith(("[", "#")) and app in line:
        key, val = line.split("=", 1)
        items = [x for x in val.split(";") if x.strip() and x.strip() != app]
        if items:
            out.append(key + "=" + ";".join(items) + ";")
        continue
    out.append(line)
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY
        fixed=1
    done
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
    if [ "$fixed" = 1 ]; then
        green "Associazioni ripulite: Ferox2html non e' piu' l'app predefinita per i file di testo"
    fi
}

# Segna un lanciatore come fidato (doppio clic senza avvisi) su GNOME/Nautilus e XFCE
trust_launcher(){
    local f="$1"
    chmod +x "$f"
    command -v gio >/dev/null || return 0
    gio set "$f" metadata::trusted true 2>/dev/null || true
    if command -v sha256sum >/dev/null; then   # XFCE 4.18+ (Kali) usa un checksum del file
        gio set -t string "$f" metadata::xfce-exe-checksum "$(sha256sum "$f" | cut -d' ' -f1)" 2>/dev/null || true
    fi
}

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$MENU_FILE" "$DESK_FILE" "$BIN_DIR/$APP_ID"
    rm -rf "$INSTALL_DIR"
    clean_associations
    green "Ferox2html rimosso (le tue scansioni e i report non sono stati toccati)."
    exit 0
fi

[ -f "$SRC/ferox2html.py" ] || { echo "ferox2html.py non trovato in $SRC"; exit 1; }
[ -f "$SRC/assets/icon.png" ] || { echo "assets/icon.png non trovato in $SRC"; exit 1; }
command -v python3 >/dev/null || { echo "python3 non trovato: sudo apt install python3"; exit 1; }

# 0) Ripara eventuali installazioni vecchie
clean_associations

# 1) Copia il programma in una posizione fissa
mkdir -p "$INSTALL_DIR"
cp -f "$SRC/ferox2html.py" "$INSTALL_DIR/ferox2html.py"
cp -f "$SRC/assets/icon.png" "$INSTALL_DIR/icon.png"
chmod +x "$INSTALL_DIR/ferox2html.py"
green "Programma installato in $INSTALL_DIR"

# 2) Icona nel menu applicazioni
#    Nessun "MimeType": cosi' Ferox2html non diventa MAI l'app predefinita per i file di testo.
mkdir -p "$APPS_DIR"
cat > "$MENU_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Ferox2html
GenericName=Feroxbuster Tree
Comment=Converte l'output di feroxbuster in un sito ad albero (stile DirBuster)
Exec=python3 "$INSTALL_DIR/ferox2html.py" --gui %F
Icon=$INSTALL_DIR/icon.png
Terminal=false
Categories=Development;Network;Utility;
Keywords=feroxbuster;dirbuster;pentest;html;report;
StartupNotify=false
EOF
chmod +x "$MENU_FILE"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
green "Icona aggiunta al menu applicazioni"

# 3) Icona sul Desktop
if [ -d "$DESK" ]; then
    cp -f "$MENU_FILE" "$DESK_FILE"
    trust_launcher "$DESK_FILE"
    green "Icona aggiunta al Desktop ($DESK)"
fi

# 4) Comando "ferox2html" nel terminale
mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/ferox2html.py" "$BIN_DIR/$APP_ID"
green "Comando 'ferox2html' creato in $BIN_DIR"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) yellow "$BIN_DIR non e' nel PATH: aggiungi questa riga a ~/.zshrc (o ~/.bashrc):"
       echo "     export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

# 5) Controllo tkinter (serve per la finestra di scelta file)
if ! python3 -c "import tkinter" 2>/dev/null; then
    if command -v zenity >/dev/null; then
        yellow "tkinter non installato: uso zenity per la finestra (va bene uguale)."
    else
        yellow "Per la finestra di scelta file installa tkinter:  sudo apt install python3-tk"
    fi
fi

echo
green "Fatto! Doppio clic sull'icona Ferox2html sul Desktop (o cercala nel menu)."
echo "    Da terminale:  ferox2html scan.txt"
echo "    Ora puoi anche cancellare questa cartella: il programma e' installato in $INSTALL_DIR"
