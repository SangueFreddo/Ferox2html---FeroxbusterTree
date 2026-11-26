#!/usr/bin/env python3
"""
ferox2html - Converte l'output di feroxbuster in un sito HTML navigabile
(albero di cartelle e file, stile DirBuster).

USO:
    python ferox2html.py scan.txt          -> crea scan.html e lo apre nel browser
    python ferox2html.py scan.txt -o x.html
    python ferox2html.py scan1.txt scan2.json   -> unisce piu' scansioni in un solo report
    python ferox2html.py nuova.txt --compare vecchia.txt  -> evidenzia cosa e' nuovo/sparito
    python ferox2html.py                   -> si apre una finestra per scegliere il file
    ./install.sh                           -> (Linux) icona nel menu e sul Desktop
    windows\\install_windows.bat           -> (Windows) icona sul Desktop

Funziona con:
    feroxbuster -u http://sito -o scan.txt            (output testo)
    feroxbuster -u http://sito --json -o scan.json    (output JSON)

Nessuna libreria esterna richiesta.
"""

import argparse
import html
import json
import os
import re
import sys
import webbrowser
from datetime import datetime
from urllib.parse import urlsplit

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# es: 200      GET       12l       34w      567c http://sito/admin => http://sito/admin/
LINE_RE = re.compile(
    r"^\s*(\d{3})\s+([A-Z]+)\s+(\d+|-)l\s+(\d+|-)w\s+(\d+|-)c\s+(\S+)(?:\s+=>\s+(\S+))?"
)


def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_file(path):
    """Legge il file di feroxbuster e restituisce una lista di risultati."""
    results = []
    seen = set()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = ANSI_RE.sub("", raw).strip()
            if not line:
                continue
            item = None

            # Formato JSON (--json)
            if line.startswith("{"):
                try:
                    d = json.loads(line)
                except ValueError:
                    d = None
                if isinstance(d, dict) and d.get("type") == "response" and d.get("url"):
                    headers = d.get("headers") or {}
                    loc = headers.get("location") or headers.get("Location")
                    item = {
                        "url": d["url"],
                        "status": to_int(d.get("status")),
                        "method": d.get("method", "GET"),
                        "lines": to_int(d.get("line_count")),
                        "words": to_int(d.get("word_count")),
                        "size": to_int(d.get("content_length")),
                        "redirect": loc,
                    }
            else:
                # Formato testo
                m = LINE_RE.match(line)
                if m:
                    item = {
                        "url": m.group(6),
                        "status": int(m.group(1)),
                        "method": m.group(2),
                        "lines": to_int(m.group(3)),
                        "words": to_int(m.group(4)),
                        "size": to_int(m.group(5)),
                        "redirect": m.group(7),
                    }

            if item and item["url"].lower().startswith(("http://", "https://")):
                key = (item["method"], item["url"])
                if key not in seen:
                    seen.add(key)
                    results.append(item)
    return results


def read_all(sources, label="risultati"):
    """Legge uno o piu' file e unisce i risultati senza doppioni."""
    results, seen = [], set()
    for src in sources:
        found = parse_file(src)
        print(f"[*] {os.path.basename(src)}: {len(found)} {label}")
        for r in found:
            key = (r["method"], r["url"])
            if key not in seen:
                seen.add(key)
                results.append(r)
    return results


def host_of(url):
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def compare(results, old):
    """Segna i risultati nuovi e aggiunge quelli spariti rispetto alla scansione vecchia.
    Se entrambe le scansioni hanno un solo host, si confronta solo il percorso
    (cosi' funziona anche se il target ha cambiato IP)."""
    new_hosts = {host_of(r["url"]) for r in results}
    old_hosts = {host_of(r["url"]) for r in old}
    ignore_host = len(new_hosts) == 1 and len(old_hosts) == 1
    target = next(iter(new_hosts)) if ignore_host else None

    def key(url):
        u = urlsplit(url)
        path = (u.path.rstrip("/") or "/") + ("?" + u.query if u.query else "")
        return path if ignore_host else host_of(url) + path

    old_keys = {key(r["url"]) for r in old}
    new_keys = {key(r["url"]) for r in results}
    for r in results:
        r["diff"] = "new" if key(r["url"]) not in old_keys else None

    removed, done = [], set()
    for r in old:
        k = key(r["url"])
        if k in new_keys or k in done:
            continue
        done.add(k)
        g = dict(r, diff="removed")
        if ignore_host:  # porta il percorso sull'host della scansione nuova
            oh = host_of(r["url"])
            g["url"] = target + r["url"][len(oh):]
            if g.get("redirect") and g["redirect"].startswith(oh):
                g["redirect"] = target + g["redirect"][len(oh):]
        removed.append(g)
    return results + removed


def build_tree(results):
    """Costruisce l'albero: host -> cartelle -> file."""
    hosts = {}
    for r in results:
        u = urlsplit(r["url"])
        host_key = f"{u.scheme}://{u.netloc}"
        root = hosts.setdefault(
            host_key, {"name": host_key, "dir": True, "children": {}, "entry": None, "path": "/"}
        )
        path = u.path or "/"
        segments = [s for s in path.split("/") if s]
        if u.query:
            if segments:
                segments[-1] += "?" + u.query
            else:
                segments = ["?" + u.query]

        node = root
        cur = ""
        for i, seg in enumerate(segments):
            cur += "/" + seg
            node = node["children"].setdefault(
                seg, {"name": seg, "dir": False, "children": {}, "entry": None, "path": cur}
            )
            if i < len(segments) - 1:
                node["dir"] = True

        if not segments:
            root["entry"] = r
            continue

        # Se esiste gia' una voce (es. /admin e /admin/), tieni la piu' utile
        if node["entry"] is None or (path.endswith("/") and not node["entry"]["url"].endswith("/")):
            node["entry"] = r
        if path.endswith("/"):
            node["dir"] = True
        red = r.get("redirect")
        if red and red.rstrip("/").endswith(path.rstrip("/")) and red.endswith("/"):
            node["dir"] = True

    def finalize(n):
        kids = [finalize(c) for c in n["children"].values()]
        if kids:
            n["dir"] = True
        kids.sort(key=lambda k: (not k["dir"], k["name"].lower()))
        return {
            "name": n["name"],
            "dir": n["dir"],
            "path": n["path"],
            "entry": n["entry"],
            "children": kids,
        }

    return [finalize(h) for h in sorted(hosts.values(), key=lambda h: h["name"])]


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{--bg:#0f1117;--panel:#171a23;--line:#262b38;--txt:#d7dbe6;--mut:#8a91a5;--hov:#1c2130;--btn:#1f2430;
        --acc:#4f9dff;--g:#3fb950;--b:#58a6ff;--o:#d29922;--r:#f85149;--vis:#b388ff;--hl:rgba(248,81,73,.09)}
  body.light{--bg:#f6f7fb;--panel:#ffffff;--line:#d9dde7;--txt:#1d2230;--mut:#5f6678;--hov:#eef1f8;--btn:#f0f2f7;
        --acc:#1f6feb;--g:#1a7f37;--b:#0969da;--o:#9a6700;--r:#cf222e;--vis:#8250df;--hl:rgba(207,34,46,.08)}
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--txt)}
  header{padding:16px 22px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:5}
  h1{margin:0 0 4px;font-size:18px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  .author{font-size:12px;font-weight:500;color:var(--mut);text-decoration:none;border:1px solid var(--line);padding:3px 10px;border-radius:999px}
  .author:hover{color:var(--acc);border-color:var(--acc)}
  .author b{color:var(--txt)}
  .sub{color:var(--mut);font-size:12px}
  .bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}
  input[type=search]{flex:1 1 100%;min-width:220px;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--txt)}
  button{padding:7px 12px;border-radius:8px;border:1px solid var(--line);background:var(--btn);color:var(--txt);cursor:pointer;font:inherit}
  button:hover{border-color:var(--acc)}
  button.on{background:var(--acc);border-color:var(--acc);color:#fff}
  .panel{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:10px;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--bg)}
  .panel input,.panel select{padding:7px 10px;border-radius:8px;border:1px solid var(--line);background:var(--panel);color:var(--txt);font:inherit}
  #ipTo{min-width:240px}
  .ipnote{color:var(--o)}
  .ipmsg{color:var(--r);font-size:12px}
  .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
  .chip{display:flex;gap:6px;align-items:center;padding:4px 10px;border-radius:999px;border:1px solid var(--line);cursor:pointer;user-select:none;font-size:12px}
  .chip.off{opacity:.35}
  #stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;align-items:start}
  .card{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--panel)}
  .card h3{margin:0 0 6px;font-size:12px;color:var(--mut);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
  .kv{display:flex;justify-content:space-between;gap:10px;font-size:13px;padding:1px 0}
  .kv span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .kv b{font-variant-numeric:tabular-nums}
  main{padding:14px 22px 40px}
  ul{list-style:none;margin:0;padding-left:20px}
  ul.root{padding-left:0}
  li{margin:0}
  .row{display:flex;align-items:center;gap:8px;padding:3px 6px;border-radius:6px;white-space:nowrap}
  .row:hover{background:var(--hov)}
  .row.int{background:var(--hl)}
  .tog{width:16px;text-align:center;color:var(--mut);cursor:pointer;flex:none}
  .ico{flex:none}
  .ico.click{cursor:pointer}
  .name{cursor:pointer;overflow:hidden;text-overflow:ellipsis;color:inherit;text-decoration:none}
  a.name:hover{color:var(--acc);text-decoration:underline}
  .dir>.row .name{font-weight:600}
  .host>.row .name{font-weight:700;color:var(--acc)}
  .skull{color:var(--r);flex:none;display:inline-flex;vertical-align:-2px}
  .skull svg{width:15px;height:15px}
  button .skull svg{width:14px;height:14px}
  button.on .skull{color:#fff}
  .row a.name.visited,td a.visited,.host>.row a.name.visited{color:var(--vis)}
  .meta{color:var(--mut);font-size:12px;margin-left:auto;display:flex;gap:12px;align-items:center}
  .cnt{color:var(--mut);font-size:12px}
  .st{font:600 11px/1 ui-monospace,Consolas,monospace;padding:3px 6px;border-radius:5px;color:#0b0d12}
  body.light .st{color:#fff}
  .s2{background:var(--g)}.s3{background:var(--b)}.s4{background:var(--o)}.s5{background:var(--r)}.sx{background:var(--mut)}
  .red{color:var(--b);font-size:12px;overflow:hidden;text-overflow:ellipsis;max-width:380px}
  a.open{color:var(--mut);text-decoration:none;font-size:12px}
  a.open:hover{color:var(--acc)}
  .collapsed>ul{display:none}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
  th{cursor:pointer;position:sticky;top:0;background:var(--panel);color:var(--mut);font-weight:600}
  tr.int td{background:var(--hl)}
  td a{color:var(--txt);text-decoration:none;word-break:break-all}
  td a:hover{color:var(--acc)}
  .hidden{display:none!important}
  .empty{color:var(--mut);padding:30px;text-align:center}
  .toast{position:fixed;bottom:18px;right:18px;background:var(--acc);color:#fff;padding:8px 14px;border-radius:8px;opacity:0;transition:.2s;pointer-events:none}
  .toast.show{opacity:1}
  .note{color:var(--o);font-size:12px;font-style:italic;overflow:hidden;text-overflow:ellipsis;max-width:340px;cursor:pointer}
  td .note{display:block;max-width:none;white-space:normal}
  .dbadge{font:700 10px/1 system-ui,sans-serif;padding:3px 6px;border-radius:5px;flex:none;color:#fff;letter-spacing:.03em}
  .dbadge.new{background:var(--g)}.dbadge.removed{background:var(--r)}
  .row.removed>.name{text-decoration:line-through}
  tr.removed td a:not(.open){text-decoration:line-through}
  a.curl{font:600 10px/1 ui-monospace,Consolas,monospace;border:1px solid var(--line);padding:2px 4px;border-radius:4px}
  .chip.on{border-color:var(--acc);background:var(--acc);color:#fff}
  #modal{position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:20}
  .mbox{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;width:min(560px,92vw)}
  .mbox h3{margin:0 0 4px;font-size:16px}
  .mbox textarea{width:100%;margin-top:10px;padding:10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--txt);font:inherit;resize:vertical}
  .mbox .sub{word-break:break-all}
  @media print{#modal{display:none!important}header{position:static}.bar,.panel,.toast,a.open,.tog{display:none!important}.collapsed>ul{display:block!important}}
</style>
</head>
<body>
<header>
  <h1><span>📂 Feroxbuster – <span id="hostTitle">__HOSTS__</span></span>
    <a class="author" href="https://github.com/SangueFreddo" target="_blank" rel="noopener noreferrer" title="Ferox2html by SangueFreddo">by <b>SangueFreddo</b> ↗</a></h1>
  <div class="sub">File: __SRC__ · Generato: __DATE__ · <span id="tot"></span><span id="ipInfo"></span></div>
  <div class="bar">
    <input type="search" id="q" placeholder="Cerca percorso o file… (es. admin, .php, backup)">
    <button id="vTree" class="on">🌳 Albero</button>
    <button id="vList">📋 Lista</button>
    <button id="exp">Espandi tutto</button>
    <button id="col">Chiudi tutto</button>
    <button id="seenBtn" title="Nasconde i link che hai gia' aperto (quelli viola)">👁️ Nascondi visitati</button>
    <button id="intBtn" title="Mostra solo backup, dump, config, credenziali, pannelli admin e simili"><span class="skull"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="M12 2.2C7 2.2 3.2 5.8 3.2 10.4c0 2.5 1.2 4.6 3 5.9v2.9c0 .7.5 1.2 1.2 1.2h1.4v-2.2h1.6v2.2h3.2v-2.2h1.6v2.2h1.4c.7 0 1.2-.5 1.2-1.2v-2.9c1.8-1.3 3-3.4 3-5.9 0-4.6-3.8-8.2-8.8-8.2Z M6.3 11.3a2.3 2.3 0 1 0 4.6 0a2.3 2.3 0 1 0-4.6 0Z M13.1 11.3a2.3 2.3 0 1 0 4.6 0a2.3 2.3 0 1 0-4.6 0Z M12 13.9l-1.3 2.3h2.6Z"/></svg></span> Solo critici</button>
    <button id="statBtn">📊 Statistiche</button>
    <button id="expBtn">⬇️ Esporta URL</button>
    <button id="ipBtn">🔁 Cambia indirizzo IP</button>
    <button id="themeBtn" title="Tema chiaro/scuro">☀️</button>
  </div>
  <div id="ipPanel" class="panel hidden">
    <span>Host originale:</span>
    <select id="ipFrom"></select>
    <span>→ nuovo IP/host:</span>
    <input id="ipTo" placeholder="es. 192.168.1.8 oppure 192.168.1.8:8080">
    <button id="ipApply" class="on">Applica</button>
    <button id="ipReset">Ripristina originale</button>
    <span id="ipMsg" class="ipmsg"></span>
  </div>
  <div id="expPanel" class="panel hidden">
    <span title="Solo quelli visibili con ricerca e filtri attuali">URL visibili (<b id="expN">0</b>):</span>
    <button id="expCopy" class="on">📋 Copia tutti</button>
    <button id="expTxt">⬇️ Scarica .txt</button>
    <button id="expCsv">⬇️ Scarica .csv</button>
    <button id="expCurl">🐚 Copia tutti come curl</button>
    <span class="sub">·</span>
    <button id="seenReset" title="Rimette tutti i link come non visitati">🧹 Azzera visitati</button>
    <button id="workSave" title="Salva link visitati, note e IP cambiato in un file">💾 Salva progressi</button>
    <button id="workLoad" title="Ricarica un file di progressi salvato">📂 Carica progressi</button>
    <input type="file" id="workFile" accept=".json,application/json" class="hidden">
  </div>
  <div class="chips" id="chips"></div>
</header>
<main>
  <div id="statsBox" class="hidden"><div id="stats"></div><br></div>
  <div id="tree"></div>
  <div id="list" class="hidden"></div>
  <div id="empty" class="empty hidden">Nessun risultato con questi filtri.</div>
</main>
<div class="toast" id="toast">URL copiato</div>
<div id="modal" class="hidden">
  <div class="mbox">
    <h3>📝 Nota</h3>
    <div class="sub" id="mUrl"></div>
    <textarea id="mText" rows="5" placeholder="es. credenziali in chiaro, da testare SQLi, versione vulnerabile…"></textarea>
    <div class="bar">
      <button id="mSave" class="on">Salva</button>
      <button id="mDel">Elimina nota</button>
      <button id="mCancel">Annulla</button>
      <span class="sub">Ctrl+Invio = salva · Esc = chiudi</span>
    </div>
  </div>
</div>
<script>
const META = __META__;
const DATA = __DATA__;

const $ = s => document.querySelector(s);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const fmtSize = n => n == null ? "" : n < 1024 ? n + " B" : n < 1048576 ? (n/1024).toFixed(1) + " KB" : (n/1048576).toFixed(1) + " MB";
const stCls = s => s ? "s" + String(s)[0] : "sx";
const STATUS_INFO = {200:"OK",204:"No Content",301:"Moved",302:"Found",307:"Redirect",308:"Redirect",
  400:"Bad Request",401:"Unauthorized",403:"Forbidden",404:"Not Found",405:"Not Allowed",500:"Server Error",502:"Bad Gateway",503:"Unavailable"};
const store = {
  get(k){ try { return localStorage.getItem(k); } catch(_) { return null; } },
  set(k, v){ try { localStorage.setItem(k, v); } catch(_) {} }
};

// ---- File "critici" (teschio rosso): backup, config, credenziali, pannelli... ----
const SKULL_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" fill-rule="evenodd" d="M12 2.2C7 2.2 3.2 5.8 3.2 10.4c0 2.5 1.2 4.6 3 5.9v2.9c0 .7.5 1.2 1.2 1.2h1.4v-2.2h1.6v2.2h3.2v-2.2h1.6v2.2h1.4c.7 0 1.2-.5 1.2-1.2v-2.9c1.8-1.3 3-3.4 3-5.9 0-4.6-3.8-8.2-8.8-8.2Z M6.3 11.3a2.3 2.3 0 1 0 4.6 0a2.3 2.3 0 1 0-4.6 0Z M13.1 11.3a2.3 2.3 0 1 0 4.6 0a2.3 2.3 0 1 0-4.6 0Z M12 13.9l-1.3 2.3h2.6Z"/></svg>';
function skull(){ const s = el("span", "skull"); s.innerHTML = SKULL_SVG; s.title = "Critico: possibile file sensibile (backup, config, credenziali...)"; return s; }
const INT_EXT = /\.(bak|old|orig|save|swp|tmp|sql|sqlite3?|db|mdb|dump|env|ini|conf|cfg|config|key|pem|p12|pfx|crt|log|zip|tar|gz|tgz|rar|7z|backup|inc)$/i;
const INT_WORD = /(^|[\/._-])(\.git|\.svn|\.env|\.htpasswd|\.htaccess|\.ds_store|backups?|bak|dump|config|configuration|passwd|passwords?|credentials?|secrets?|private|phpinfo|phpmyadmin|adminer|admin|administrator|wp-config|web\.config|id_rsa|shell|uploads?|debug|install|setup|server-status)([\/._-]|$)/i;
function isInteresting(path){
  // si guarda solo il nome dell'ultimo elemento (non le cartelle che lo contengono)
  const p = (path || "").split("?")[0].replace(/\/+$/, "").split("/").pop();
  return INT_EXT.test(p) || INT_WORD.test(p);
}

// Lista piatta di tutte le voci (con percorso e host)
const flat = [];
(function walk(nodes, host){
  for (const n of nodes){
    const h = host || n.name;
    if (n.entry) flat.push({...n.entry, dir:n.dir, path:n.path, host:h, int: !!host && isInteresting(n.path)});
    walk(n.children, h);
  }
})(DATA, null);

// ---- Cambio indirizzo IP / host ----
const HOSTS = DATA.map(h => h.name);
const KEY = "ferox2html:" + HOSTS.join("|");
let hostMap = {};
try { hostMap = JSON.parse(store.get(KEY + ":ip") || "{}") || {}; } catch(_) { hostMap = {}; }
function fix(u){
  if (!u) return u;
  for (const o in hostMap){
    if (u === o || u.startsWith(o + "/") || u.startsWith(o + "?")) return hostMap[o] + u.slice(o.length);
  }
  return u;
}
function updateIpInfo(){
  const ch = Object.keys(hostMap);
  $("#hostTitle").textContent = HOSTS.length === 1 ? fix(HOSTS[0]) : HOSTS.length + " host";
  $("#ipInfo").textContent = "";
  if (ch.length) $("#ipInfo").append(el("span", "ipnote", " · IP cambiato: " +
    ch.map(o => o.replace(/^https?:\/\//, "") + " → " + hostMap[o].replace(/^https?:\/\//, "")).join(", ")));
  document.title = "Feroxbuster – " + $("#hostTitle").textContent;
}
HOSTS.forEach(h => { const o = el("option", null, h); o.value = h; $("#ipFrom").append(o); });
const fillIp = () => { $("#ipTo").value = (hostMap[$("#ipFrom").value] || "").replace(/^https?:\/\//, ""); };
function applyIp(){
  const from = $("#ipFrom").value;
  let v = $("#ipTo").value.trim();
  if (!v){ $("#ipMsg").textContent = "Scrivi il nuovo IP"; return; }
  let scheme = from.split("://")[0];
  const m = v.match(/^(https?):\/\//i);
  if (m){ scheme = m[1].toLowerCase(); v = v.slice(m[0].length); }
  v = v.split(/[\/?#]/)[0];
  if (!/^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:.]+\](:\d{1,5})?$/.test(v)){ $("#ipMsg").textContent = "Indirizzo non valido"; return; }
  const to = scheme + "://" + v;
  if (to === from) delete hostMap[from]; else hostMap[from] = to;
  store.set(KEY + ":ip", JSON.stringify(hostMap));
  $("#ipMsg").textContent = ""; $("#ipPanel").classList.add("hidden"); $("#ipBtn").classList.remove("on");
  updateIpInfo(); render(); toast("Indirizzo aggiornato");
}

// ---- Lavoro: spunte "visto" e note (salvate nel browser) ----
let work = { seen: {}, notes: {} };
try { const w = JSON.parse(store.get(KEY + ":work") || "null"); if (w && typeof w === "object") work = { seen: w.seen || {}, notes: w.notes || {} }; } catch(_) {}
const saveWork = () => store.set(KEY + ":work", JSON.stringify(work));
let hideSeen = false, diffMode = null;
// Quando apri un link (clic, clic centrale, ↗) diventa viola, come su Google
function markOpened(orig){
  if (!orig || work.seen[orig]) return;
  work.seen[orig] = 1; saveWork(); updateTot();
  document.querySelectorAll("a[data-u]").forEach(a => { if (a.dataset.u === orig && !a.classList.contains("open")) a.classList.add("visited"); });
  if (hideSeen) setTimeout(render, 300);
}
function openLink(a, orig){ a.dataset.u = orig; a.dataset.open = "1"; if (work.seen[orig] && !a.classList.contains("open")) a.classList.add("visited"); return a; }
const onOpen = ev => { const a = ev.target.closest && ev.target.closest("a[data-open]"); if (a && (ev.type === "click" || ev.button === 1)) markOpened(a.dataset.u); };
document.addEventListener("click", onOpen, true);
document.addEventListener("auxclick", onOpen, true);
function curlCmd(u, method){ return "curl -i -s -k -X " + (method || "GET") + " '" + String(u).replace(/'/g, "'\\''") + "'"; }

// Finestra per le note
let noteTarget = null;
function openNote(orig, shown){
  noteTarget = orig;
  $("#mUrl").textContent = shown;
  $("#mText").value = work.notes[orig] || "";
  $("#modal").classList.remove("hidden");
  $("#mText").focus();
}
function closeNote(){ $("#modal").classList.add("hidden"); noteTarget = null; }
function saveNote(){
  if (noteTarget == null) return;
  const t = $("#mText").value.trim();
  if (t) work.notes[noteTarget] = t; else delete work.notes[noteTarget];
  saveWork(); closeNote(); render(); updateTot(); toast(t ? "Nota salvata" : "Nota eliminata");
}

// Pulsanti azione comuni (nota, curl, copia, apri)
function actions(orig, url, method){
  const out = [];
  const nt = el("a", "open", "📝"); nt.href = "#"; nt.title = work.notes[orig] ? "Modifica nota" : "Aggiungi nota";
  nt.onclick = ev => { ev.preventDefault(); ev.stopPropagation(); openNote(orig, url); };
  const cu = el("a", "open curl", "curl"); cu.href = "#"; cu.title = "Copia come comando curl";
  cu.onclick = ev => { ev.preventDefault(); ev.stopPropagation(); copy(curlCmd(url, method), "Comando curl copiato"); };
  const cp = el("a", "open", "📋"); cp.href = "#"; cp.title = "Copia " + url;
  cp.onclick = ev => { ev.preventDefault(); ev.stopPropagation(); copy(url); };
  const a = el("a", "open", "↗"); a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.title = "Apri " + url;
  openLink(a, orig);
  out.push(nt, cu, cp, a);
  return out;
}
function noteSpan(orig, url){
  const t = work.notes[orig]; if (!t) return null;
  const n = el("span", "note", "📝 " + t); n.title = t + "\n(clic per modificare)";
  n.onclick = ev => { ev.preventDefault(); ev.stopPropagation(); openNote(orig, url); };
  return n;
}
function diffBadge(d){
  if (!d) return null;
  const b = el("span", "dbadge " + d, d === "new" ? "NUOVO" : "SPARITO");
  b.title = d === "new" ? "Non c'era nella scansione precedente" : "C'era nella scansione precedente, ora non piu'";
  return b;
}

// ---- Utilità ----
function toast(msg){ const t = $("#toast"); t.textContent = msg || "URL copiato"; t.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 1300); }
function copy(u, msg){
  // navigator.clipboard puo' non funzionare su file:// in alcuni browser: fallback con textarea
  const fallback = () => { const t = document.createElement("textarea"); t.value = u; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.append(t); t.select(); try { document.execCommand("copy"); toast(msg); } catch(_) {} t.remove(); };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(u).then(() => toast(msg), fallback); else fallback();
}
function download(name, text, type){
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type: type + ";charset=utf-8"}));
  a.download = name; document.body.append(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
function fileIcon(n){
  const x = n.toLowerCase();
  if (/\.(php|asp|aspx|jsp|cgi|py|pl|rb)(\?|$)/.test(x)) return "⚙️";
  if (/\.(zip|tar|gz|tgz|rar|7z|bak|old|sql|db|backup|dump)(\?|$)/.test(x)) return "📦";
  if (/\.(txt|log|md|xml|json|yml|yaml|conf|config|ini|env|cfg)(\?|$)/.test(x)) return "📝";
  if (/\.(png|jpe?g|gif|svg|ico|webp)(\?|$)/.test(x)) return "🖼️";
  if (/\.(js|css|map)(\?|$)/.test(x)) return "🧩";
  if (/\.(html?)(\?|$)/.test(x)) return "🌐";
  return "📄";
}
function extOf(path){
  const last = (path || "").split("?")[0].replace(/\/+$/, "").split("/").pop() || "";
  const i = last.lastIndexOf(".");
  return i > 0 ? last.slice(i).toLowerCase() : "(senza estensione)";
}

// ---- Filtri per status ----
const statuses = [...new Set(flat.map(e => e.status))].sort((a,b) => a - b);
const active = new Set(statuses);
let onlyInt = false;
function updateTot(){
  const real = flat.filter(e => e.diff !== "removed");
  let t = real.length + " risultati · " + DATA.length + " host · " + real.filter(e => e.int).length + " critici · " +
    flat.filter(e => work.seen[e.url]).length + "/" + flat.length + " visitati";
  const nn = Object.keys(work.notes).length; if (nn) t += " · 📝 " + nn + " note";
  if (META.compare) t += " · confronto con: " + META.compare;
  $("#tot").textContent = t;
}
updateTot();
for (const s of statuses){
  const c = el("span", "chip");
  c.append(el("span", "st " + stCls(s), s), document.createTextNode((STATUS_INFO[s] || "") + " (" + flat.filter(e => e.status === s).length + ")"));
  c.title = "Clicca per mostrare/nascondere";
  c.onclick = () => { active.has(s) ? active.delete(s) : active.add(s); c.classList.toggle("off"); render(); };
  $("#chips").append(c);
}

if (META.compare){
  for (const [d, label] of [["new", "🆕 Nuovi"], ["removed", "❌ Spariti"]]){
    const n = flat.filter(e => e.diff === d).length;
    const c = el("span", "chip", label + " (" + n + ")");
    c.title = "Mostra solo questi (clicca di nuovo per tornare a tutti)";
    c.onclick = () => {
      diffMode = diffMode === d ? null : d;
      document.querySelectorAll(".chip.dchip").forEach(x => x.classList.remove("on"));
      if (diffMode) c.classList.add("on");
      render();
    };
    c.classList.add("dchip");
    $("#chips").append(c);
  }
}

const query = () => $("#q").value.trim().toLowerCase();
function entryOk(e, q){
  return active.has(e.status) && (!onlyInt || e.int) && (!hideSeen || !work.seen[e.url]) && (!diffMode || e.diff === diffMode) &&
    (!q || (e.path + " " + fix(e.url) + " " + (work.notes[e.url] || "")).toLowerCase().includes(q));
}
// Voci visibili adesso (stessi filtri dell'albero e della lista)
function visibleEntries(){ const q = query(); return flat.filter(e => entryOk(e, q)); }

// ---- Vista ad albero ----
function buildNode(n, q, depth, isHost, base){
  if (isHost) base = n.name;
  const kids = n.children.map(c => buildNode(c, q, depth + 1, false, base)).filter(Boolean);
  const int = !isHost && isInteresting(n.path);
  const self = n.entry ? entryOk({...n.entry, path: n.path, int}, q) : false;
  if (!self && !kids.length) return null;

  const li = el("li", isHost ? "host dir" : n.dir ? "dir" : "file");
  const d = n.entry ? n.entry.diff : null;
  const row = el("div", "row" + (int && n.entry ? " int" : "") + (d === "removed" ? " removed" : ""));
  const orig = n.entry ? n.entry.url : base + n.path + (n.dir && !n.path.endsWith("/") ? "/" : "");
  const url = fix(orig);
  const tog = el("span", "tog", n.dir ? (kids.length ? "▾" : "") : "");
  const ico = el("span", "ico", isHost ? "🌐" : n.dir ? "📁" : fileIcon(n.name));
  // Il nome e' un link: clic = apre la pagina in una nuova scheda
  const name = el("a", "name", isHost ? fix(n.name) : n.name + (n.dir ? "/" : ""));
  name.href = url; name.target = "_blank"; name.rel = "noopener noreferrer"; name.title = "Apri " + url;
  openLink(name, orig);
  row.append(tog, ico, name);
  const db = diffBadge(d); if (db) row.append(db);
  if (int && n.entry) row.append(skull());
  if (n.dir && kids.length) row.append(el("span", "cnt", "(" + kids.length + ")"));
  const ns = noteSpan(orig, url); if (ns) row.append(ns);

  const meta = el("span", "meta");
  if (n.entry){
    const e = n.entry;
    if (e.redirect){ const rd = fix(e.redirect); const r = el("span", "red", "→ " + rd); r.title = rd; meta.append(r); }
    if (e.size != null) meta.append(el("span", null, fmtSize(e.size)));
    const st = el("span", "st " + stCls(e.status), e.status ?? "?");
    st.title = STATUS_INFO[e.status] || "";
    meta.append(st);
  } else {
    meta.append(el("span", "cnt", "non trovato direttamente"));
  }
  meta.append(...actions(orig, url, n.entry ? n.entry.method : "GET"));
  row.append(meta);
  li.append(row);

  if (kids.length){
    const ul = el("ul"); kids.forEach(k => ul.append(k)); li.append(ul);
    // Apri/chiudi la cartella con la freccia o con l'icona
    const toggle = () => { li.classList.toggle("collapsed"); tog.textContent = li.classList.contains("collapsed") ? "▸" : "▾"; };
    tog.onclick = toggle; ico.onclick = toggle; ico.classList.add("click"); ico.title = "Apri/chiudi cartella";
    if (!q && !onlyInt && depth >= 2) { li.classList.add("collapsed"); tog.textContent = "▸"; }
  }
  return li;
}

// ---- Vista lista ----
let sortKey = "url", sortDir = 1;
function renderList(){
  const rows = visibleEntries().sort((a,b) => {
    const x = sortKey === "url" ? fix(a.url) : a[sortKey], y = sortKey === "url" ? fix(b.url) : b[sortKey];
    return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
  });
  const t = el("table");
  const hr = el("tr");
  [["status","Status"],["method","Metodo"],["size","Dimensione"],["lines","Righe"],["words","Parole"],["url","URL"]].forEach(([k,l]) => {
    const th = el("th", null, l + (sortKey === k ? (sortDir > 0 ? " ▲" : " ▼") : ""));
    th.onclick = () => { sortDir = sortKey === k ? -sortDir : 1; sortKey = k; render(); };
    hr.append(th);
  });
  t.append(hr);
  for (const e of rows){
    const tr = el("tr", [e.int ? "int" : "", e.diff === "removed" ? "removed" : ""].join(" ").trim() || null);
    const u = fix(e.url);
    const st = el("td"); st.append(el("span", "st " + stCls(e.status), e.status)); tr.append(st);
    tr.append(el("td", null, e.method), el("td", null, fmtSize(e.size)), el("td", null, e.lines ?? ""), el("td", null, e.words ?? ""));
    const td = el("td");
    const [nt, cu, cp] = actions(e.url, u, e.method);
    td.append(nt, document.createTextNode(" "), cu, document.createTextNode(" "), cp, document.createTextNode(" "));
    const db = diffBadge(e.diff); if (db){ td.append(db, document.createTextNode(" ")); }
    if (e.int){ td.append(skull(), document.createTextNode(" ")); }
    const a = el("a", null, u + (e.redirect ? "  →  " + fix(e.redirect) : ""));
    a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer"; openLink(a, e.url); td.append(a);
    const ns = noteSpan(e.url, u); if (ns) td.append(ns);
    tr.append(td);
    t.append(tr);
  }
  $("#list").replaceChildren(t);
  return rows.length;
}

// ---- Statistiche (su tutta la scansione) ----
function card(title, pairs){
  const c = el("div", "card"); c.append(el("h3", null, title));
  for (const [k, v] of pairs){ const r = el("div", "kv"); const ks = el("span", null, k); ks.title = k; r.append(ks, el("b", null, v)); c.append(r); }
  return c;
}
function renderStats(){
  const files = flat.filter(e => !e.dir), dirs = flat.filter(e => e.dir);
  const tot = flat.reduce((s, e) => s + (e.size || 0), 0);
  const ext = {};
  files.forEach(e => { const x = extOf(e.path); ext[x] = (ext[x] || 0) + 1; });
  const topExt = Object.entries(ext).sort((a,b) => b[1] - a[1]).slice(0, 8);
  const big = files.filter(e => e.size).sort((a,b) => b.size - a.size).slice(0, 6).map(e => [e.path, fmtSize(e.size)]);
  const byStatus = statuses.map(s => [s + " " + (STATUS_INFO[s] || ""), flat.filter(e => e.status === s).length]);
  const ints = flat.filter(e => e.int).slice(0, 8).map(e => [e.path, e.status]);
  $("#stats").replaceChildren(
    card("Totali", [["Risultati", flat.length], ["Cartelle", dirs.length], ["File", files.length], ["Host", DATA.length], ["Critici", flat.filter(e => e.int).length], ["Dimensione totale", fmtSize(tot)]]),
    card("Per status", byStatus),
    card("Estensioni più trovate", topExt.length ? topExt : [["—", ""]]),
    card("File più grandi", big.length ? big : [["—", ""]]),
    card("Critici (primi 8)", ints.length ? ints : [["Nessuno", ""]]),
    card("Avanzamento", [["🔗 Link visitati", flat.filter(e => work.seen[e.url]).length + " / " + flat.length], ["📝 Con nota", Object.keys(work.notes).length]]
      .concat(META.compare ? [["🆕 Nuovi", flat.filter(e => e.diff === "new").length], ["❌ Spariti", flat.filter(e => e.diff === "removed").length]] : []))
  );
}

// ---- Render ----
let view = "tree";
function render(){
  const q = query();
  let n;
  if (view === "tree"){
    const ul = el("ul", "root");
    DATA.forEach(h => { const li = buildNode(h, q, 0, true); if (li) ul.append(li); });
    $("#tree").replaceChildren(ul);
    n = ul.children.length;
  } else n = renderList();
  $("#empty").classList.toggle("hidden", n > 0);
  $("#expN").textContent = visibleEntries().length;
}

// ---- Tema (scuro di default) ----
function setTheme(t){
  document.body.classList.toggle("light", t === "light");
  $("#themeBtn").textContent = t === "light" ? "🌙" : "☀️";
  $("#themeBtn").title = t === "light" ? "Passa al tema scuro" : "Passa al tema chiaro";
  store.set("ferox2html:theme", t);
}
setTheme(store.get("ferox2html:theme") === "light" ? "light" : "dark");

// ---- Eventi ----
const togglePanel = (panel, btn) => { const h = $(panel).classList.toggle("hidden"); $(btn).classList.toggle("on", !h); return !h; };
$("#q").oninput = render;
$("#vTree").onclick = () => { view = "tree"; $("#vTree").classList.add("on"); $("#vList").classList.remove("on"); $("#tree").classList.remove("hidden"); $("#list").classList.add("hidden"); render(); };
$("#vList").onclick = () => { view = "list"; $("#vList").classList.add("on"); $("#vTree").classList.remove("on"); $("#list").classList.remove("hidden"); $("#tree").classList.add("hidden"); render(); };
$("#exp").onclick = () => document.querySelectorAll("#tree li.collapsed").forEach(li => { li.classList.remove("collapsed"); li.querySelector(".tog").textContent = "▾"; });
$("#col").onclick = () => document.querySelectorAll("#tree li.dir:not(.host)").forEach(li => { if (li.querySelector("ul")){ li.classList.add("collapsed"); li.querySelector(".tog").textContent = "▸"; } });
$("#intBtn").onclick = () => { onlyInt = !onlyInt; $("#intBtn").classList.toggle("on", onlyInt); render(); };
$("#statBtn").onclick = () => { if (togglePanel("#statsBox", "#statBtn")) renderStats(); };
$("#expBtn").onclick = () => { togglePanel("#expPanel", "#expBtn"); render(); };
$("#expCopy").onclick = () => { const v = visibleEntries(); if (v.length) copy(v.map(e => fix(e.url)).join("\n"), v.length + " URL copiati"); };
$("#expTxt").onclick = () => download("ferox_urls.txt", visibleEntries().map(e => fix(e.url)).join("\n") + "\n", "text/plain");
$("#expCsv").onclick = () => {
  const esc = v => '"' + String(v ?? "").replace(/"/g, '""') + '"';
  const lines = [["status","method","size","lines","words","critical","visited","diff","url","redirect","note"].join(",")]
    .concat(visibleEntries().map(e => [e.status, e.method, e.size, e.lines, e.words, e.int ? "yes" : "", work.seen[e.url] ? "yes" : "",
      e.diff || "", fix(e.url), fix(e.redirect), work.notes[e.url] || ""].map(esc).join(",")));
  download("ferox_urls.csv", "﻿" + lines.join("\r\n") + "\r\n", "text/csv");
};
$("#expCurl").onclick = () => { const v = visibleEntries(); if (v.length) copy(v.map(e => curlCmd(fix(e.url), e.method)).join("\n"), v.length + " comandi curl copiati"); };
$("#workSave").onclick = () => {
  const data = { app: "ferox2html", version: 1, hosts: HOSTS, saved: new Date().toISOString(), seen: work.seen, notes: work.notes, ip: hostMap };
  download("ferox2html_progressi.json", JSON.stringify(data, null, 2), "application/json");
};
$("#workLoad").onclick = () => $("#workFile").click();
$("#workFile").onchange = ev => {
  const f = ev.target.files[0]; if (!f) return;
  const r = new FileReader();
  r.onload = () => {
    try {
      const d = JSON.parse(r.result);
      if (!d || d.app !== "ferox2html") throw new Error("formato");
      Object.assign(work.seen, d.seen || {}); Object.assign(work.notes, d.notes || {});
      if (d.ip && typeof d.ip === "object") for (const k in d.ip) if (HOSTS.includes(k)) hostMap[k] = d.ip[k];
      saveWork(); store.set(KEY + ":ip", JSON.stringify(hostMap));
      updateIpInfo(); updateTot(); render(); toast("Progressi caricati");
    } catch(_) { toast("File di progressi non valido"); }
    ev.target.value = "";
  };
  r.readAsText(f);
};
$("#seenReset").onclick = () => {
  if (!Object.keys(work.seen).length){ toast("Nessun link visitato"); return; }
  if (!confirm("Rimettere tutti i link come non visitati?")) return;
  work.seen = {}; saveWork(); updateTot(); render(); toast("Link visitati azzerati");
};
$("#seenBtn").onclick = () => { hideSeen = !hideSeen; $("#seenBtn").classList.toggle("on", hideSeen); render(); };
$("#mSave").onclick = saveNote;
$("#mCancel").onclick = closeNote;
$("#mDel").onclick = () => { $("#mText").value = ""; saveNote(); };
$("#modal").onclick = ev => { if (ev.target.id === "modal") closeNote(); };
$("#mText").onkeydown = ev => { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) saveNote(); };
document.addEventListener("keydown", ev => { if (ev.key === "Escape" && !$("#modal").classList.contains("hidden")) closeNote(); });
$("#ipBtn").onclick = () => { if (togglePanel("#ipPanel", "#ipBtn")){ fillIp(); $("#ipMsg").textContent = ""; $("#ipTo").focus(); } };
$("#ipFrom").onchange = fillIp;
$("#ipApply").onclick = applyIp;
$("#ipTo").onkeydown = ev => { if (ev.key === "Enter") applyIp(); };
$("#ipReset").onclick = () => { delete hostMap[$("#ipFrom").value]; store.set(KEY + ":ip", JSON.stringify(hostMap)); $("#ipTo").value = ""; updateIpInfo(); render(); toast("Indirizzo originale ripristinato"); };
$("#themeBtn").onclick = () => setTheme(document.body.classList.contains("light") ? "dark" : "light");

updateIpInfo();
render();
</script>
</body>
</html>
"""


def make_html(tree, src_name, meta=None):
    data = json.dumps(tree, ensure_ascii=False).replace("</", "<\\/")
    meta_js = json.dumps(meta or {}, ensure_ascii=False).replace("</", "<\\/")
    hosts = tree[0]["name"] if len(tree) == 1 else f"{len(tree)} host"
    title = "Feroxbuster – " + hosts
    # i segnaposto si sostituiscono prima dei dati, cosi' un nome di file del target non puo' interferire
    page = (
        HTML_TEMPLATE.replace("__HOSTS__", html.escape(hosts))
        .replace("__TITLE__", html.escape(title))
        .replace("__SRC__", html.escape(src_name))
        .replace("__DATE__", datetime.now().strftime("%d/%m/%Y %H:%M"))
    )
    return page.replace("__META__", meta_js).replace("__DATA__", data)


def notify(msg, error=False, gui=False):
    """Mostra un messaggio: nel terminale e, se avviato dall'icona (--gui), in una finestrella."""
    print(msg)
    if not gui:
        return
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        (messagebox.showerror if error else messagebox.showinfo)("Ferox2html", msg, parent=root)
        root.destroy()
    except Exception:
        try:
            import subprocess
            subprocess.run(["zenity", "--error" if error else "--info", "--title=Ferox2html", "--text=" + msg],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass


def pick_file(gui=False):
    """Finestra per scegliere i file se non vengono passati da riga di comando."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)  # la finestra compare davanti a tutto
        paths = filedialog.askopenfilenames(
            parent=root,
            title="Scegli l'output di feroxbuster (anche piu' file)",
            filetypes=[("Output feroxbuster", "*.txt *.json *.log *.out"), ("Tutti i file", "*.*")],
        )
        root.destroy()
        return list(paths)
    except Exception:
        pass
    # Linux senza tkinter: prova con zenity
    try:
        import subprocess
        r = subprocess.run(["zenity", "--file-selection", "--multiple", "--separator=\n",
                            "--title=Scegli l'output di feroxbuster"],
                           capture_output=True, text=True, check=False)
        if r.returncode in (0, 1):  # 1 = annullato
            return [x for x in r.stdout.splitlines() if x.strip()]
    except Exception:
        pass
    if gui or not sys.stdin or not sys.stdin.isatty():
        notify("Impossibile aprire la finestra di scelta file.\n"
               "Su Kali/Debian installa tkinter:  sudo apt install python3-tk", error=True, gui=gui)
        return []
    p = input("Percorso del file di feroxbuster: ").strip().strip('"')
    return [p] if p else []


def main():
    ap = argparse.ArgumentParser(description="Converte l'output di feroxbuster in un sito HTML navigabile.")
    ap.add_argument("input", nargs="*", help="uno o piu' file di output di feroxbuster (.txt o --json)")
    ap.add_argument("-o", "--output", help="file HTML da creare (default: stesso nome .html)")
    ap.add_argument("--no-open", action="store_true", help="non aprire il browser alla fine")
    ap.add_argument("-c", "--compare", nargs="+", metavar="VECCHIA",
                    help="confronta con una scansione precedente: evidenzia cosa e' nuovo e cosa e' sparito")
    ap.add_argument("--gui", action="store_true", help="usato dalle icone: mostra gli errori in una finestra")
    args = ap.parse_args()

    gui = args.gui
    sources = args.input or pick_file(gui)
    if not sources:
        print("Nessun file scelto.")
        return 0
    missing = [s for s in sources if not os.path.isfile(s)]
    if missing:
        notify("File non trovato: " + ", ".join(missing), error=True, gui=gui)
        return 1

    results = read_all(sources)
    if not results:
        notify("Nessun risultato riconosciuto in: " + ", ".join(os.path.basename(s) for s in sources) +
               "\n\nÈ un file creato da feroxbuster con -o (o --json -o)?", error=True, gui=gui)
        return 1

    base = os.path.splitext(sources[0])[0]
    out = args.output or (base + ".html" if len(sources) == 1 else base + "_merged.html")
    names = ", ".join(os.path.basename(s) for s in sources)
    meta = {}
    if args.compare:
        missing = [s for s in args.compare if not os.path.isfile(s)]
        if missing:
            notify("File da confrontare non trovato: " + ", ".join(missing), error=True, gui=gui)
            return 1
        old = read_all(args.compare, "risultati (vecchia)")
        results = compare(results, old)
        meta["compare"] = ", ".join(os.path.basename(s) for s in args.compare)
        n_new = sum(1 for r in results if r.get("diff") == "new")
        n_rem = sum(1 for r in results if r.get("diff") == "removed")
        print(f"[*] Confronto: {n_new} nuovi, {n_rem} spariti")
        if not args.output:
            out = os.path.splitext(sources[0])[0] + "_diff.html"
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(make_html(build_tree(results), names, meta))
    except OSError as e:
        notify(f"Impossibile salvare il report:\n{out}\n\n{e}", error=True, gui=gui)
        return 1

    print(f"[+] {len(results)} voci -> {os.path.abspath(out)}")
    if not args.no_open:
        webbrowser.open("file://" + os.path.abspath(out).replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
