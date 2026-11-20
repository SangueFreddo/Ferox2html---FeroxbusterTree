#!/usr/bin/env python3
"""
ferox2html - Converte l'output di feroxbuster in un sito HTML navigabile
(albero di cartelle e file, stile DirBuster).

USO:
    python ferox2html.py scan.txt          -> crea scan.html e lo apre nel browser
    python ferox2html.py scan.txt -o x.html
    python ferox2html.py                   -> si apre una finestra per scegliere il file
    (su Windows puoi anche trascinare il file sopra lo script)

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
  :root{--bg:#0f1117;--panel:#171a23;--line:#262b38;--txt:#d7dbe6;--mut:#8a91a5;
        --acc:#4f9dff;--g:#3fb950;--b:#58a6ff;--o:#d29922;--r:#f85149;--p:#bc8cff}
  *{box-sizing:border-box}
  body{margin:0;font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--txt)}
  header{padding:16px 22px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:5}
  h1{margin:0 0 4px;font-size:18px}
  .sub{color:var(--mut);font-size:12px}
  .bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}
  input[type=search]{flex:1;min-width:220px;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--txt)}
  button{padding:7px 12px;border-radius:8px;border:1px solid var(--line);background:#1f2430;color:var(--txt);cursor:pointer}
  button:hover{border-color:var(--acc)}
  button.on{background:var(--acc);border-color:var(--acc);color:#fff}
  .chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
  .chip{display:flex;gap:6px;align-items:center;padding:4px 10px;border-radius:999px;border:1px solid var(--line);cursor:pointer;user-select:none;font-size:12px}
  .chip.off{opacity:.35}
  main{padding:14px 22px 40px}
  ul{list-style:none;margin:0;padding-left:20px}
  ul.root{padding-left:0}
  li{margin:0}
  .row{display:flex;align-items:center;gap:8px;padding:3px 6px;border-radius:6px;white-space:nowrap}
  .row:hover{background:#1c2130}
  .tog{width:16px;text-align:center;color:var(--mut);cursor:pointer;flex:none}
  .ico{flex:none}
  .name{cursor:pointer;overflow:hidden;text-overflow:ellipsis}
  .dir>.row .name{font-weight:600}
  .host>.row .name{font-weight:700;color:var(--acc)}
  .meta{color:var(--mut);font-size:12px;margin-left:auto;display:flex;gap:12px;align-items:center}
  .cnt{color:var(--mut);font-size:12px}
  .st{font:600 11px/1 ui-monospace,Consolas,monospace;padding:3px 6px;border-radius:5px;color:#0b0d12}
  .s2{background:var(--g)}.s3{background:var(--b)}.s4{background:var(--o)}.s5{background:var(--r)}.sx{background:var(--mut)}
  .red{color:var(--b);font-size:12px;overflow:hidden;text-overflow:ellipsis;max-width:380px}
  a.open{color:var(--mut);text-decoration:none;font-size:12px}
  a.open:hover{color:var(--acc)}
  .collapsed>ul{display:none}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
  th{cursor:pointer;position:sticky;top:0;background:var(--panel);color:var(--mut);font-weight:600}
  td a{color:var(--txt);text-decoration:none;word-break:break-all}
  td a:hover{color:var(--acc)}
  .hidden{display:none!important}
  .empty{color:var(--mut);padding:30px;text-align:center}
  .toast{position:fixed;bottom:18px;right:18px;background:var(--acc);color:#fff;padding:8px 14px;border-radius:8px;opacity:0;transition:.2s}
  .toast.show{opacity:1}
</style>
</head>
<body>
<header>
  <h1>📂 __TITLE__</h1>
  <div class="sub">File: __SRC__ · Generato: __DATE__ · <span id="tot"></span></div>
  <div class="bar">
    <input type="search" id="q" placeholder="Cerca percorso o file… (es. admin, .php, backup)">
    <button id="vTree" class="on">🌳 Albero</button>
    <button id="vList">📋 Lista</button>
    <button id="exp">Espandi tutto</button>
    <button id="col">Chiudi tutto</button>
  </div>
  <div class="chips" id="chips"></div>
</header>
<main>
  <div id="tree"></div>
  <div id="list" class="hidden"></div>
  <div id="empty" class="empty hidden">Nessun risultato con questi filtri.</div>
</main>
<div class="toast" id="toast">URL copiato</div>
<script>
const DATA = __DATA__;

const $ = s => document.querySelector(s);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const fmtSize = n => n == null ? "" : n < 1024 ? n + " B" : n < 1048576 ? (n/1024).toFixed(1) + " KB" : (n/1048576).toFixed(1) + " MB";
const stCls = s => s ? "s" + String(s)[0] : "sx";
const STATUS_INFO = {200:"OK",204:"No Content",301:"Moved",302:"Found",307:"Redirect",308:"Redirect",
  400:"Bad Request",401:"Unauthorized",403:"Forbidden",404:"Not Found",405:"Not Allowed",500:"Server Error",502:"Bad Gateway",503:"Unavailable"};

// Lista piatta di tutte le voci
const flat = [];
(function walk(nodes){ for (const n of nodes){ if (n.entry) flat.push({...n.entry, dir:n.dir}); walk(n.children); } })(DATA);

// Filtri per status
const statuses = [...new Set(flat.map(e => e.status))].sort((a,b)=>a-b);
const active = new Set(statuses);
$("#tot").textContent = flat.length + " risultati · " + DATA.length + " host";
for (const s of statuses){
  const c = el("span", "chip");
  const b = el("span", "st " + stCls(s), s);
  c.append(b, document.createTextNode((STATUS_INFO[s] || "") + " (" + flat.filter(e=>e.status===s).length + ")"));
  c.title = "Clicca per mostrare/nascondere";
  c.onclick = () => { active.has(s) ? active.delete(s) : active.add(s); c.classList.toggle("off"); render(); };
  $("#chips").append(c);
}

function toast(){ const t=$("#toast"); t.classList.add("show"); setTimeout(()=>t.classList.remove("show"),1000); }
function copy(u){
  // navigator.clipboard puo' non funzionare su file:// in alcuni browser: fallback con textarea
  const fallback = () => { const t = document.createElement("textarea"); t.value = u; t.style.position = "fixed"; t.style.opacity = "0";
    document.body.append(t); t.select(); try { document.execCommand("copy"); toast(); } catch(_) {} t.remove(); };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(u).then(toast, fallback); else fallback();
}

function matches(n, q){
  const okStatus = n.entry ? active.has(n.entry.status) : false;
  const okText = !q || (n.path + " " + (n.entry ? n.entry.url : "")).toLowerCase().includes(q);
  return okStatus && okText;
}

// Restituisce il <li> o null se il ramo non ha nulla di visibile
function buildNode(n, q, depth, isHost, base){
  if (isHost) base = n.name;
  const kids = n.children.map(c => buildNode(c, q, depth+1, false, base)).filter(Boolean);
  const self = matches(n, q);
  if (!self && !kids.length && !isHost) return null;
  if (isHost && !self && !kids.length) return null;

  const li = el("li", (isHost ? "host dir" : n.dir ? "dir" : "file"));
  const row = el("div", "row");
  const tog = el("span", "tog", n.dir ? (kids.length ? "▾" : "") : "");
  const ico = el("span", "ico", isHost ? "🌐" : n.dir ? "📁" : fileIcon(n.name));
  const name = el("span", "name", isHost ? n.name : n.name + (n.dir ? "/" : ""));
  row.append(tog, ico, name);
  if (n.dir && kids.length) row.append(el("span", "cnt", "(" + countLeaves(kids) + ")"));

  const meta = el("span", "meta");
  if (n.entry){
    const e = n.entry;
    if (e.redirect){ const r = el("span", "red", "→ " + e.redirect); r.title = e.redirect; meta.append(r); }
    if (e.size != null) meta.append(el("span", null, fmtSize(e.size)));
    const st = el("span", "st " + stCls(e.status), e.status ?? "?");
    st.title = STATUS_INFO[e.status] || "";
    meta.append(st);
    const cp = el("a", "open", "📋"); cp.href = "#"; cp.title = "Copia " + e.url;
    cp.onclick = ev => { ev.preventDefault(); ev.stopPropagation(); copy(e.url); };
    meta.append(cp);
    const a = el("a", "open", "↗"); a.href = e.url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.title = "Apri " + e.url;
    meta.append(a);
    name.title = e.url + "  (doppio clic = copia URL)";
    name.ondblclick = ev => { ev.stopPropagation(); copy(e.url); };
  } else {
    const u = base + n.path + (n.dir && !n.path.endsWith("/") ? "/" : "");
    meta.append(el("span", "cnt", "non trovato direttamente"));
    const cp = el("a", "open", "📋"); cp.href = "#"; cp.title = "Copia " + u;
    cp.onclick = ev => { ev.preventDefault(); ev.stopPropagation(); copy(u); };
    const a = el("a", "open", "↗"); a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer"; a.title = "Apri " + u;
    meta.append(cp, a);
  }
  row.append(meta);
  li.append(row);

  if (kids.length){
    const ul = el("ul"); kids.forEach(k => ul.append(k)); li.append(ul);
    const toggle = () => { li.classList.toggle("collapsed"); tog.textContent = li.classList.contains("collapsed") ? "▸" : "▾"; };
    tog.onclick = toggle; name.onclick = toggle;
    if (!q && depth >= 2) { li.classList.add("collapsed"); tog.textContent = "▸"; }
  }
  return li;
}
function countLeaves(lis){ return lis.reduce((s, li) => s + 1, 0); }
function fileIcon(n){
  const x = n.toLowerCase();
  if (/\.(php|asp|aspx|jsp|cgi|py|pl|rb)(\?|$)/.test(x)) return "⚙️";
  if (/\.(zip|tar|gz|rar|7z|bak|old|sql|db|backup)(\?|$)/.test(x)) return "📦";
  if (/\.(txt|log|md|xml|json|yml|yaml|conf|config|ini|env)(\?|$)/.test(x)) return "📝";
  if (/\.(png|jpe?g|gif|svg|ico|webp)(\?|$)/.test(x)) return "🖼️";
  if (/\.(js|css|map)(\?|$)/.test(x)) return "🧩";
  if (/\.(html?)(\?|$)/.test(x)) return "🌐";
  return "📄";
}

let sortKey = "url", sortDir = 1;
function renderList(q){
  const rows = flat.filter(e => active.has(e.status) && (!q || e.url.toLowerCase().includes(q)))
    .sort((a,b) => { const x=a[sortKey], y=b[sortKey]; return (x>y?1:x<y?-1:0) * sortDir; });
  const t = el("table");
  const hr = el("tr");
  [["status","Status"],["method","Metodo"],["size","Dimensione"],["lines","Righe"],["words","Parole"],["url","URL"]].forEach(([k,l]) => {
    const th = el("th", null, l + (sortKey===k ? (sortDir>0?" ▲":" ▼") : ""));
    th.onclick = () => { sortDir = sortKey===k ? -sortDir : 1; sortKey = k; render(); };
    hr.append(th);
  });
  t.append(hr);
  for (const e of rows){
    const tr = el("tr");
    const st = el("td"); st.append(el("span", "st " + stCls(e.status), e.status)); tr.append(st);
    tr.append(el("td", null, e.method), el("td", null, fmtSize(e.size)), el("td", null, e.lines ?? ""), el("td", null, e.words ?? ""));
    const td = el("td");
    const cp = el("a", "open", "📋 "); cp.href = "#"; cp.title = "Copia URL";
    cp.onclick = ev => { ev.preventDefault(); copy(e.url); }; td.append(cp);
    const a = el("a", null, e.url + (e.redirect ? "  →  " + e.redirect : ""));
    a.href = e.url; a.target = "_blank"; a.rel = "noopener noreferrer"; td.append(a); tr.append(td);
    t.append(tr);
  }
  $("#list").replaceChildren(t);
  return rows.length;
}

let view = "tree";
function render(){
  const q = $("#q").value.trim().toLowerCase();
  let n;
  if (view === "tree"){
    const ul = el("ul", "root");
    DATA.forEach(h => { const li = buildNode(h, q, 0, true); if (li) ul.append(li); });
    $("#tree").replaceChildren(ul);
    n = ul.children.length;
  } else n = renderList(q);
  $("#empty").classList.toggle("hidden", n > 0);
}

$("#q").oninput = render;
$("#vTree").onclick = () => { view="tree"; $("#vTree").classList.add("on"); $("#vList").classList.remove("on"); $("#tree").classList.remove("hidden"); $("#list").classList.add("hidden"); render(); };
$("#vList").onclick = () => { view="list"; $("#vList").classList.add("on"); $("#vTree").classList.remove("on"); $("#list").classList.remove("hidden"); $("#tree").classList.add("hidden"); render(); };
$("#exp").onclick = () => document.querySelectorAll("#tree li.collapsed").forEach(li => { li.classList.remove("collapsed"); li.querySelector(".tog").textContent="▾"; });
$("#col").onclick = () => document.querySelectorAll("#tree li.dir:not(.host)").forEach(li => { if (li.querySelector("ul")){ li.classList.add("collapsed"); li.querySelector(".tog").textContent="▸"; } });
render();
</script>
</body>
</html>
"""


def make_html(tree, src_name):
    data = json.dumps(tree, ensure_ascii=False).replace("</", "<\\/")
    title = "Feroxbuster – " + (tree[0]["name"] if len(tree) == 1 else f"{len(tree)} host")
    return (
        HTML_TEMPLATE.replace("__DATA__", data)
        .replace("__TITLE__", html.escape(title))
        .replace("__SRC__", html.escape(src_name))
        .replace("__DATE__", datetime.now().strftime("%d/%m/%Y %H:%M"))
    )


def pick_file():
    """Finestra per scegliere il file se non viene passato da riga di comando."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title="Scegli l'output di feroxbuster",
            filetypes=[("Output feroxbuster", "*.txt *.json *.log *.out"), ("Tutti i file", "*.*")],
        )
        root.destroy()
        return path or None
    except Exception:
        return input("Percorso del file di feroxbuster: ").strip().strip('"') or None


def main():
    ap = argparse.ArgumentParser(description="Converte l'output di feroxbuster in un sito HTML navigabile.")
    ap.add_argument("input", nargs="?", help="file di output di feroxbuster (.txt o --json)")
    ap.add_argument("-o", "--output", help="file HTML da creare (default: stesso nome .html)")
    ap.add_argument("--no-open", action="store_true", help="non aprire il browser alla fine")
    args = ap.parse_args()

    src = args.input or pick_file()
    if not src:
        print("Nessun file scelto.")
        return 1
    if not os.path.isfile(src):
        print(f"[!] File non trovato: {src}")
        return 1

    results = parse_file(src)
    if not results:
        print("[!] Nessun risultato riconosciuto. Il file è un output di feroxbuster (-o)?")
        return 1

    out = args.output or os.path.splitext(src)[0] + ".html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(make_html(build_tree(results), os.path.basename(src)))

    print(f"[+] {len(results)} risultati -> {os.path.abspath(out)}")
    if not args.no_open:
        webbrowser.open("file://" + os.path.abspath(out).replace("\\", "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
