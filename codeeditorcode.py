import json
import uuid
import time
import sys
import re
import os
from datetime import datetime, timezone
from flask import Flask, render_template_string, request, Response, jsonify
import requests as req_lib
from colorama import Fore, init


init(autoreset=True)
app = Flask(__name__)





# ============================================
# File / Memory helpers (same as before)
# ============================================
MEMORY_FILE = "mission_logs.json"
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(WORKSPACE_DIR, 'dev-projects')

if not os.path.exists(PROJECTS_DIR):
    os.makedirs(PROJECTS_DIR)

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# ============================================
# LLM / Search config
# ============================================
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-coder:free")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

ALEXZO_SEARCH_URL = os.getenv(
    "ALEXZO_SEARCH_URL",
    "https://alexzo.vercel.app/api/search"
)
ALEXZO_API_KEY = (
    os.getenv("ALEXZO_API_KEY", "")
    or os.getenv("ALEXZO_TOKEN", "")
)

WEB_SEARCH_PATTERNS = (
    r"\blatest\b", r"\bnews\b", r"\bcurrent\b", r"\brecent\b",
    r"\btrending\b", r"\bweb search\b", r"\bsearch (on|the) web\b",
    r"\bonline search\b", r"\binternet se\b", r"\bweb se\b",
    r"\baaj ki\b", r"\btaaza\b", r"\breal[ -]?time\b"
)


def should_use_web_search(prompt):
    p = (prompt or "").lower().strip()
    return any(re.search(pattern, p) for pattern in WEB_SEARCH_PATTERNS)


def fetch_web_search_context(query):
    if not ALEXZO_API_KEY:
        return ""
    try:
        res = req_lib.post(
            ALEXZO_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {ALEXZO_API_KEY}",
                "Content-Type": "application/json"
            },
            json={"query": query},
            timeout=30
        )
        if res.status_code != 200:
            return ""
        data = res.json()
        return json.dumps(data, ensure_ascii=False, indent=2)[:6000]
    except Exception:
        return ""


def call_openrouter(prompt, history_messages, files_context, web_context=""):
    system_prompt = (
        "You are Dev-X, an expert coding assistant. "
        "Always provide practical, implementation-ready responses. "
        "When editing code, include concise explanation and exact file changes."
    )

    user_content = prompt
    if files_context:
        user_content += f"\n\nProject files context:\n{files_context}"
    if web_context:
        user_content += (
            "\n\nWeb search context (use only if relevant and mention it may be fresh):\n"
            f"{web_context}"
        )

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "system", "content": system_prompt}] + history_messages + [
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.2
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://cloudflarepages.com",
        "X-Title": "Dev-X"
    }

    res = req_lib.post(
        OPENROUTER_API_URL,
        json=payload,
        headers=headers,
        timeout=120
    )
    if res.status_code >= 400:
        body = res.text[:500]
        raise RuntimeError(f"OpenRouter error {res.status_code}: {body}")
    data = res.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter returned no choices")
    return choices[0].get("message", {}).get("content", "")

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {"chats": {}, "current_chat": None, "projects": {}}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "chats" not in data: data["chats"] = {}
            if "projects" not in data: data["projects"] = {}
            return data
    except:
        return {"chats": {}, "current_chat": None, "projects": {}}

def save_memory(data):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_project_dir(chat_id):
    mem = load_memory()
    folder_name = chat_id[:12]
    for fname, cid in mem.get('projects', {}).items():
        if cid == chat_id:
            folder_name = fname
            break
    clean_name = "".join(
        [c for c in folder_name if c.isalnum() or c in ('-', '_')]
    ).strip()
    if not clean_name:
        clean_name = chat_id[:12]
    d = os.path.join(PROJECTS_DIR, clean_name)
    os.makedirs(d, exist_ok=True)
    return d

def get_project_files(chat_id):
    pdir = get_project_dir(chat_id)
    files = {}
    for root, dirs, fnames in os.walk(pdir):
        if '.git' in root:
            continue
        for fn in fnames:
            fpath = os.path.join(root, fn)
            relpath = os.path.relpath(
                fpath, pdir
            ).replace("\\", "/")
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    files[relpath] = f.read()
            except:
                files[relpath] = ""
    return files

def save_project_file(chat_id, filename, content):
    pdir = get_project_dir(chat_id)
    fpath = os.path.join(
        pdir, filename.replace("/", os.sep)
    )
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
    return {"added": 1, "removed": 0}

def delete_project_item(chat_id, path):
    pdir = get_project_dir(chat_id)
    fpath = os.path.join(pdir, path.replace("/", os.sep))
    if os.path.isfile(fpath):
        os.remove(fpath)
        return True
    elif os.path.isdir(fpath):
        import shutil
        shutil.rmtree(fpath)
        return True
    return False

def create_project_folder(chat_id, path):
    pdir = get_project_dir(chat_id)
    fpath = os.path.join(pdir, path.replace("/", os.sep))
    os.makedirs(fpath, exist_ok=True)
    return True

def get_file_tree(chat_id):
    pdir = get_project_dir(chat_id)
    tree = []
    for root, dirs, files in os.walk(pdir):
        if '.git' in root or '__pycache__' in root:
            continue
        rel = os.path.relpath(
            root, pdir
        ).replace("\\", "/")
        if rel == ".":
            rel = ""
        for d in sorted(dirs):
            if d.startswith('.'):
                continue
            p = (rel + "/" + d) if rel else d
            tree.append({"type": "folder", "name": d, "path": p})
        for f in sorted(files):
            p = (rel + "/" + f) if rel else f
            tree.append({"type": "file", "name": f, "path": p})
    return tree


# ============================================
# HTML UI (same as your original - no changes)
# ============================================
HTML_UI = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#0a0a0c" id="themeMetaColor">
<title>Dev-X</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<style>
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root{
--bg:#0a0a0c;--s1:#111114;--s2:#18181c;--s3:#222228;--s4:#2c2c34;
--b1:#2a2a33;--b2:#3a3a45;
--t1:#f0f0f2;--t2:#a0a0ac;--t3:#68687a;--t4:#48485a;
--ac:#6366f1;--ac2:#818cf8;--ab:rgba(99,102,241,.12);--abr:rgba(99,102,241,.4);
--gn:#22c55e;--rd:#ef4444;--yl:#eab308;--or:#f97316;--cy:#06b6d4;
--r:10px;--r2:14px;--r3:20px;
--sab:env(safe-area-inset-bottom,0px);--sat:env(safe-area-inset-top,0px);
}
html.light{
--bg:#ffffff;--s1:#f8f9fa;--s2:#f1f3f5;--s3:#e9ecef;--s4:#dee2e6;
--b1:#dee2e6;--b2:#ced4da;
--t1:#1a1a2e;--t2:#495057;--t3:#868e96;--t4:#adb5bd;
}
html,body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--t1);height:100%;height:100dvh;overflow:hidden;-webkit-tap-highlight-color:transparent}
body{display:flex;flex-direction:column}
::-webkit-scrollbar{width:0;height:0}
.topbar{background:var(--s1);border-bottom:1px solid var(--b1);display:flex;flex-direction:column;z-index:40;padding-top:var(--sat)}
.top-row{height:46px;display:flex;align-items:center;padding:0 8px;gap:6px}
.top-row .logo{display:flex;align-items:center;gap:5px;flex-shrink:0}
.top-row .logo-icon{width:26px;height:26px;border-radius:6px;background:linear-gradient(135deg,var(--ac),#a855f7);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:9px;color:#fff}
.top-row .logo-text{font-size:13px;font-weight:800;letter-spacing:-.3px}.top-row .logo-text span{color:var(--ac)}
.top-row .pname{flex:1;text-align:center;font-size:11px;font-weight:600;color:var(--t3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.top-row .pname.on{color:var(--ac)}
.tbtn{width:32px;height:32px;border-radius:8px;border:none;background:var(--s2);color:var(--t2);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
.tbtn:active{transform:scale(.9);background:var(--s3)}
.tab-row{display:flex;height:38px;border-top:1px solid rgba(42,42,50,.3)}
.tab-item{flex:1;display:flex;align-items:center;justify-content:center;gap:5px;font-size:11.5px;font-weight:600;color:var(--t4);cursor:pointer;position:relative;transition:color .15s}
.tab-item i{font-size:13px}
.tab-item.on{color:var(--ac)}
.tab-item.on::after{content:'';position:absolute;bottom:0;left:18%;right:18%;height:2.5px;border-radius:2px 2px 0 0;background:var(--ac)}
.tab-item:active{opacity:.6}
.main{flex:1;position:relative;overflow:hidden}
.page{position:absolute;inset:0;display:flex;flex-direction:column;background:var(--bg);opacity:0;pointer-events:none;transition:opacity .15s}
.page.on{opacity:1;pointer-events:auto}
.chat-area{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:12px;-webkit-overflow-scrolling:touch;overscroll-behavior:contain}
.msg{display:flex;gap:9px;animation:mIn .2s ease}
@keyframes mIn{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
.av{width:28px;height:28px;border-radius:8px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800}
.av.ai{background:linear-gradient(135deg,var(--ac),#a855f7);color:#fff}
.av.u{background:var(--s3);color:var(--t2)}
.mmb{flex:1;min-width:0}
.mh{font-size:10px;font-weight:600;margin-bottom:2px;display:flex;align-items:center;gap:5px}
.mh .tm{font-weight:400;color:var(--t4);font-size:9px}
.mt{font-size:13px;line-height:1.5;color:var(--t2);word-break:break-word}
.fbg{display:inline-flex;align-items:center;gap:5px;padding:5px 9px;background:var(--s2);border:1px solid var(--b1);border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:10px;margin:3px 3px 0 0;cursor:pointer}
.fbg:active{border-color:var(--abr);background:var(--ab)}
.fbg .fn{color:var(--t1);font-weight:600}.fbg .fg{color:var(--gn)}
.agent-working{display:inline-flex;align-items:center;gap:6px;color:var(--ac);font-size:12px;font-weight:600}
.agent-working .aw-dots{display:flex;gap:3px}
.agent-working .aw-dots span{width:4px;height:4px;border-radius:50%;background:var(--ac);animation:awDot 1.2s infinite ease-in-out}
.agent-working .aw-dots span:nth-child(2){animation-delay:.15s}
.agent-working .aw-dots span:nth-child(3){animation-delay:.3s}
@keyframes awDot{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-5px);opacity:1}}
.welcome{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;text-align:center;padding:20px}
.w-icon{width:54px;height:54px;border-radius:15px;background:linear-gradient(135deg,var(--ac),#a855f7);display:flex;align-items:center;justify-content:center;font-size:24px;box-shadow:0 8px 25px rgba(99,102,241,.25)}
.w-title{font-size:20px;font-weight:800}
.w-sub{font-size:12px;color:var(--t3);max-width:280px;line-height:1.5}
.dash-box{width:100%;display:flex;flex-direction:column;align-items:center;gap:14px;margin-top:6px}
.dash-form{display:flex;gap:8px;width:100%;max-width:340px}
.dash-inp{flex:1;padding:11px 14px;background:var(--s2);border:1.5px solid var(--b1);border-radius:var(--r);color:var(--t1);font-family:'Inter';font-size:14px;outline:none}
.dash-inp:focus{border-color:var(--ac);box-shadow:0 0 0 3px var(--ab)}
.dash-inp::placeholder{color:var(--t4)}
.dash-go{padding:11px 16px;background:var(--ac);color:#fff;border:none;border-radius:var(--r);font-size:15px;cursor:pointer;flex-shrink:0}
.dash-go:active{transform:scale(.9)}
.dash-div{width:100%;max-width:340px;display:flex;align-items:center;gap:12px;color:var(--t4);font-size:10px;text-transform:uppercase;letter-spacing:.8px;font-weight:600}
.dash-div::before,.dash-div::after{content:'';flex:1;height:1px;background:var(--b1)}
.dash-grid{width:100%;max-width:340px;display:grid;grid-template-columns:1fr 1fr;gap:8px}
.dcard{background:var(--s2);border:1px solid var(--b1);border-radius:var(--r);padding:14px 8px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:6px}
.dcard:active{border-color:var(--ac);background:var(--ab);transform:scale(.96)}
.dcard i{font-size:20px;color:var(--t3)}
.dcard span{font-size:11px;font-weight:600;color:var(--t2);text-align:center;word-break:break-word}
.chat-bar{padding:8px 10px;background:var(--bg);border-top:1px solid var(--b1)}
.chat-bar .row{display:flex;align-items:flex-end;gap:7px;background:var(--s2);border:1.5px solid var(--b1);border-radius:var(--r2);padding:5px 9px}
.chat-bar .row:focus-within{border-color:var(--ac);box-shadow:0 0 0 3px var(--ab)}
.chat-bar textarea{flex:1;background:none;border:none;outline:none;resize:none;font-family:'Inter';font-size:15px;color:var(--t1);max-height:90px;min-height:22px;line-height:1.4;padding:4px 0}
.chat-bar textarea::placeholder{color:var(--t4)}
.chat-bar textarea:disabled{opacity:.3}
.go-btn{width:36px;height:36px;border-radius:var(--r);border:none;background:var(--ac);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0}
.go-btn:active{transform:scale(.9)}.go-btn:disabled{opacity:.2;transform:none}
.lock{display:none;position:absolute;bottom:0;left:0;right:0;z-index:5;background:linear-gradient(transparent,var(--bg) 35%);padding:28px 20px 16px;flex-direction:column;align-items:center;gap:10px}
.lock.on{display:flex}
.lock .li{width:44px;height:44px;border-radius:50%;background:var(--s3);border:1px solid var(--b1);display:flex;align-items:center;justify-content:center;color:var(--t4);font-size:18px}
.lock p{font-size:12px;color:var(--t4)}
.lock .lb{padding:10px 24px;background:var(--ac);color:#fff;border:none;border-radius:var(--r);font-size:13px;font-weight:600;cursor:pointer}
.lock .lb:active{transform:scale(.95)}
.code-head{height:42px;background:var(--s1);border-bottom:1px solid var(--b1);display:flex;align-items:center;padding:0 6px;gap:4px}
.code-head .file-toggle{width:36px;height:36px;border-radius:var(--r);border:none;background:var(--s2);color:var(--t2);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0}
.code-head .file-toggle:active{background:var(--s3);transform:scale(.9)}
.code-head .file-toggle.on{color:var(--ac);background:var(--ab)}
.code-tabs{display:flex;flex:1;overflow-x:auto;-webkit-overflow-scrolling:touch;gap:1px}
.ctab{padding:0 12px;height:36px;display:flex;align-items:center;gap:4px;font-size:10.5px;font-weight:500;color:var(--t3);cursor:pointer;white-space:nowrap;font-family:'JetBrains Mono',monospace;flex-shrink:0;border-radius:6px}
.ctab:active{background:var(--s3)}
.ctab.on{color:var(--t1);background:var(--s3)}
.ctab .cdot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.cdot.htm{background:var(--or)}.cdot.css{background:var(--cy)}.cdot.jss{background:var(--yl)}
.code-body{flex:1;display:flex;position:relative;overflow:hidden}
.file-panel{position:absolute;top:0;bottom:0;left:0;width:70%;max-width:280px;background:var(--s1);border-right:1px solid var(--b1);z-index:10;transform:translateX(-100%);transition:transform .2s cubic-bezier(.32,.72,.2,1);display:flex;flex-direction:column;box-shadow:4px 0 15px rgba(0,0,0,.3)}
.file-panel.on{transform:translateX(0)}
.fp-head{padding:10px 12px;border-bottom:1px solid var(--b1);display:flex;align-items:center;justify-content:space-between}
.fp-title{font-size:12px;font-weight:700;display:flex;align-items:center;gap:6px}
.fp-title i{color:var(--ac)}
.fp-acts{display:flex;gap:4px}
.fp-btn{width:28px;height:28px;border-radius:6px;border:1px solid var(--b1);background:var(--s2);color:var(--t3);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:11px}
.fp-btn:active{background:var(--s3);color:var(--t1);transform:scale(.9)}
.fp-list{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:4px 0}
.proj-root{display:flex;align-items:center;gap:6px;padding:10px 10px;background:var(--s2);border-bottom:1px solid var(--b1);cursor:pointer;font-size:12px;font-weight:700;color:var(--ac)}
.proj-root:active{background:var(--s3)}
.proj-root .pr-arrow{font-size:9px;width:14px;text-align:center;transition:transform .15s;display:inline-block;color:var(--t3)}
.proj-root .pr-arrow.open{transform:rotate(90deg)}
.proj-root .pr-icon{font-size:14px}
.proj-root .pr-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tree-folder-head{display:flex;align-items:center;gap:6px;padding:9px 10px;cursor:pointer;font-size:12.5px;color:var(--t2);border-bottom:1px solid rgba(42,42,50,.2)}
.tree-folder-head:active{background:var(--s3)}
.tree-folder-head .arrow{font-size:9px;width:14px;text-align:center;color:var(--t3);transition:transform .15s;display:inline-block}
.tree-folder-head .arrow.open{transform:rotate(90deg)}
.tree-folder-head .fold-icon{color:var(--yl);font-size:14px}
.tree-folder-head .fold-name{flex:1;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tree-folder-head .fold-del{background:none;border:none;color:var(--t4);cursor:pointer;font-size:12px;padding:2px 4px}
.tree-folder-children{display:none;padding-left:12px}
.tree-folder-children.open{display:block}
.tree-file{display:flex;align-items:center;gap:7px;padding:9px 10px;cursor:pointer;font-size:12.5px;color:var(--t2);border-bottom:1px solid rgba(42,42,50,.15);position:relative}
.tree-file:active{background:var(--s3)}
.tree-file.sel{background:var(--ab);color:var(--ac);border-left:3px solid var(--ac)}
.tree-file .file-icon{font-size:13px;width:18px;text-align:center;flex-shrink:0}
.tree-file .file-icon.htm{color:var(--or)}.tree-file .file-icon.css{color:var(--cy)}.tree-file .file-icon.jss{color:var(--yl)}
.tree-file .file-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tree-file .file-del{background:none;border:none;color:var(--t4);cursor:pointer;font-size:12px;padding:2px 4px;position:absolute;right:8px}
.tree-file .file-del:active{color:var(--rd)}
.fp-empty{padding:30px;text-align:center;color:var(--t4);font-size:12px;line-height:1.6}
.fp-shade{position:absolute;top:0;bottom:0;left:0;right:0;background:rgba(0,0,0,.3);z-index:9;display:none}
.fp-shade.on{display:block}
.code-editor{flex:1;overflow:hidden;position:relative;display:flex;flex-direction:column}
.ce-scroll{flex:1;overflow:auto;-webkit-overflow-scrolling:touch;position:relative}
.ce-wrap{display:flex;min-height:100%}
.ce-ln{padding:10px 6px;text-align:right;user-select:none;font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.65;color:var(--t4);background:var(--s2);border-right:1px solid var(--b1);min-width:32px;flex-shrink:0}
.ce-code{flex:1;padding:10px 8px;font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.65;white-space:pre;color:var(--t2);tab-size:2;min-height:100%;overflow-x:auto}
.ce-code .cl{min-height:1.65em}
.ce-code .cl.df{background:rgba(34,197,94,.08);border-left:3px solid var(--gn);padding-left:5px;margin-left:-8px}
.ce-code .cl b{color:#ff7b72;font-weight:normal}
.ce-code .cl s{color:#a5d6ff;text-decoration:none}
.ce-code .cl i{color:#8b949e;font-style:italic}
.ce-code .cl u{color:#79c0ff;text-decoration:none}
.ce-code .cl em{color:#7ee787;font-style:normal}
.ce-code .cl mark{color:#d2a8ff;background:none}
.ce-code .cl strong{color:#79c0ff;font-weight:normal}
.ce-code .cl var{color:#ffa657;font-style:normal}
.ce-edit{position:absolute;top:0;left:0;right:0;bottom:0;padding:10px 8px 10px 40px;border:none;resize:none;background:transparent;font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.65;color:transparent;caret-color:var(--ac);outline:none;white-space:pre;tab-size:2;z-index:2;overflow:auto;-webkit-overflow-scrolling:touch}
.ce-edit::selection{background:rgba(99,102,241,.25)}
.ce-empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--t4);gap:8px;padding:30px}
.ce-empty i{font-size:30px;opacity:.2}.ce-empty p{font-size:12px}
.save-bar{display:none;padding:7px 12px;background:var(--s2);border-top:1px solid var(--b1);align-items:center;justify-content:space-between}
.save-bar.on{display:flex}
.save-bar span{font-size:10px;color:var(--t3)}
.save-bar button{padding:6px 14px;background:var(--ac);color:#fff;border:none;border-radius:7px;font-size:11px;font-weight:600;cursor:pointer}
.pv-bar{height:38px;background:var(--s2);border-bottom:1px solid var(--b1);display:flex;align-items:center;padding:0 10px;gap:6px}
.pv-dots{display:flex;gap:4px}.pv-dot{width:7px;height:7px;border-radius:50%}
.pv-url{flex:1;background:var(--s3);border-radius:10px;padding:3px 10px;font-size:10px;color:var(--t4);font-family:'JetBrains Mono',monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pv-cbtn{width:28px;height:28px;border-radius:7px;border:none;background:none;color:var(--t3);cursor:pointer;font-size:13px;display:flex;align-items:center;justify-content:center}
.pv-cbtn.on{color:var(--ac)}
.pv-frame{border:none;background:#fff;width:100%;flex:1}
.pv-console{background:var(--s1);border-top:1px solid var(--b1);display:none;flex-direction:column;height:170px;flex-shrink:0}
.pv-console.on{display:flex}
.pv-ch{display:flex;align-items:center;justify-content:space-between;padding:0 10px;height:26px;background:var(--s2);border-bottom:1px solid var(--b1);font-size:10px;font-weight:600;color:var(--t2)}
.pv-cb{flex:1;overflow-y:auto;padding:3px;font-family:'JetBrains Mono',monospace;font-size:10px;-webkit-overflow-scrolling:touch}
.cmsg{padding:3px 5px;border-bottom:1px solid rgba(42,42,50,.2);word-break:break-all}
.cmsg.err{color:#ef4444;background:rgba(239,68,68,.05)}
.cmsg.warn{color:#eab308;background:rgba(234,179,8,.05)}
.cmsg.log{color:var(--t1)}
.cbx{background:none;border:none;color:var(--t2);cursor:pointer;padding:2px 5px;font-size:12px}
.shade{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:60;opacity:0;pointer-events:none;transition:opacity .2s}
.shade.on{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;bottom:0;left:0;width:min(290px,82vw);background:var(--s1);z-index:61;transform:translateX(-100%);transition:transform .25s cubic-bezier(.32,.72,.2,1);display:flex;flex-direction:column;box-shadow:4px 0 20px rgba(0,0,0,.4)}
.drawer.on{transform:translateX(0)}
.dr-head{padding:16px;border-bottom:1px solid var(--b1);display:flex;align-items:center;justify-content:space-between}
.dr-logo{display:flex;align-items:center;gap:7px}
.dr-logo .ic{width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,var(--ac),#a855f7);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:10px;color:#fff}
.dr-logo .tx{font-size:15px;font-weight:800}.dr-logo .tx span{color:var(--ac)}
.dr-new{margin:12px 14px;padding:10px;background:var(--ac);color:#fff;border:none;border-radius:var(--r);font-family:'Inter';font-size:13px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px;justify-content:center}
.dr-new:active{background:var(--ac2);transform:scale(.97)}
.dr-list{flex:1;overflow-y:auto;padding:4px 10px;-webkit-overflow-scrolling:touch}
.dr-i{padding:11px 12px;border-radius:var(--r);cursor:pointer;display:flex;align-items:center;justify-content:space-between;margin-bottom:2px;font-size:13px;color:var(--t2);font-weight:500}
.dr-i:active{background:var(--s3)}
.dr-i.on{background:var(--ab);color:var(--ac);border:1px solid var(--abr)}
.dr-i .dl{background:none;border:none;color:var(--t4);cursor:pointer;font-size:13px;padding:4px}
.dr-i .dl:active{color:var(--rd)}
.dr-i .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bsheet{position:fixed;inset:0;z-index:70;display:none;flex-direction:column;justify-content:flex-end}
.bsheet.on{display:flex}
.bs-bg{position:absolute;inset:0;background:rgba(0,0,0,.5)}
.bs-body{position:relative;z-index:1;background:var(--s1);border-radius:var(--r3) var(--r3) 0 0;padding:18px 16px calc(16px + var(--sab));max-height:70dvh;overflow-y:auto;animation:bsUp .2s ease}
@keyframes bsUp{from{transform:translateY(100%)}to{transform:translateY(0)}}
.bs-body::before{content:'';display:block;width:32px;height:4px;border-radius:2px;background:var(--b2);margin:0 auto 14px}
.bs-body h3{font-size:15px;font-weight:700;margin-bottom:14px;display:flex;align-items:center;gap:7px}
.bs-inp{width:100%;padding:12px 14px;background:var(--s2);border:1.5px solid var(--b1);border-radius:var(--r);color:var(--t1);font-family:'Inter';font-size:14px;outline:none;margin-bottom:12px}
.bs-inp:focus{border-color:var(--ac)}.bs-inp::placeholder{color:var(--t4)}
.bs-btns{display:flex;gap:8px;justify-content:flex-end}
.bs-b{padding:10px 20px;border-radius:var(--r);border:none;font-size:13px;font-weight:600;cursor:pointer;font-family:'Inter'}
.bs-b.pri{background:var(--ac);color:#fff}.bs-b.pri:active{background:var(--ac2)}
.bs-b.sec{background:var(--s3);color:var(--t2)}.bs-b.sec:active{background:var(--s4)}
.bs-b.danger{background:var(--rd);color:#fff}.bs-b.danger:active{opacity:.8}
.sg{margin-bottom:12px}
.sgl{font-size:10px;font-weight:700;color:var(--t3);margin-bottom:3px;text-transform:uppercase;letter-spacing:.5px}
.sr{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--b1)}
.sr:last-child{border:none}
.sn{font-size:13px;font-weight:500}.sd{font-size:10px;color:var(--t4);margin-top:1px}
.tg{width:44px;height:26px;border-radius:13px;background:var(--s3);border:1px solid var(--b1);cursor:pointer;position:relative;transition:all .2s;flex-shrink:0}
.tg.on{background:var(--ac);border-color:var(--ac)}
.tg::after{content:'';position:absolute;width:18px;height:18px;border-radius:50%;background:#fff;top:3px;left:3px;transition:all .2s}
.tg.on::after{left:21px}
.nf-type-btns{display:flex;gap:8px;margin-bottom:12px}
.nf-type-btn{flex:1;padding:9px;border-radius:var(--r);border:1.5px solid var(--b1);background:var(--s2);color:var(--t2);font-size:12px;font-weight:600;cursor:pointer;text-align:center;font-family:'Inter'}
.nf-type-btn.on{border-color:var(--ac);color:var(--ac);background:var(--ab)}
.nf-type-btn:active{transform:scale(.96)}
.confirm-text{font-size:14px;color:var(--t2);line-height:1.5;margin-bottom:16px;text-align:center}
.confirm-highlight{color:var(--t1);font-weight:600}
.confirm-icon{width:48px;height:48px;border-radius:50%;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);display:flex;align-items:center;justify-content:center;margin:0 auto 14px;color:var(--rd);font-size:20px}
</style>
</head>
<body>
<div class="topbar">
  <div class="top-row">
    <button class="tbtn" onclick="openDrawer()"><i class="fa-solid fa-bars"></i></button>
    <div class="logo"><div class="logo-icon">DX</div><div class="logo-text"><span>Dev</span>-X</div></div>
    <div class="pname" id="pname"></div>
    <button class="tbtn" id="themeBtn" onclick="toggleTheme()"><i class="fa-solid fa-moon"></i></button>
    <button class="tbtn" onclick="openBS('settingsBS')"><i class="fa-solid fa-gear"></i></button>
  </div>
  <div class="tab-row">
    <div class="tab-item on" id="tAgent" onclick="go('agent')"><i class="fa-solid fa-robot"></i> Agent</div>
    <div class="tab-item" id="tCode" onclick="go('code')"><i class="fa-solid fa-code"></i> Code</div>
    <div class="tab-item" id="tPreview" onclick="go('preview')"><i class="fa-solid fa-play"></i> Preview</div>
  </div>
</div>
<div class="main">
  <div class="page on" id="pgAgent">
    <div class="chat-area" id="chatArea"></div>
    <div class="chat-bar" id="chatBar"><div class="row"><textarea id="inp" placeholder="Describe what to build..." rows="1" onkeydown="hKey(event)" oninput="autoH(this)"></textarea><button class="go-btn" id="goBtn" onclick="sendMsg()"><i class="fa-solid fa-arrow-up"></i></button></div></div>
    <div class="lock" id="lockOv"><div class="li"><i class="fa-solid fa-lock"></i></div><p>Create or open a project to chat</p><button class="lb" onclick="openBS('newProjBS')"><i class="fa-solid fa-folder-plus" style="margin-right:5px"></i>New Project</button></div>
  </div>
  <div class="page" id="pgCode">
    <div class="code-head"><button class="file-toggle" id="fileToggle" onclick="toggleFiles()"><i class="fa-solid fa-bars-staggered"></i></button><div class="code-tabs" id="cTabs"></div></div>
    <div class="code-body">
      <div class="fp-shade" id="fpShade" onclick="toggleFiles()"></div>
      <div class="file-panel" id="filePanel">
        <div class="fp-head"><div class="fp-title"><i class="fa-solid fa-folder-tree"></i> Explorer</div><div class="fp-acts"><button class="fp-btn" onclick="openBS('newFileBS')"><i class="fa-solid fa-plus"></i></button><button class="fp-btn" onclick="refreshTree()"><i class="fa-solid fa-rotate"></i></button><button class="fp-btn" onclick="toggleFiles()"><i class="fa-solid fa-xmark"></i></button></div></div>
        <div id="projRootDisp" class="proj-root" style="display:none" onclick="PROJ_EXP=!PROJ_EXP;refreshTree()"><i class="fa-solid fa-chevron-right pr-arrow" id="prArrow"></i><i class="fa-solid fa-folder-open pr-icon"></i><span class="pr-name" id="projRootName"></span></div>
        <div class="fp-list" id="fList"></div>
      </div>
      <div class="code-editor" id="cEditor">
        <div class="ce-empty" id="cEmpty"><i class="fa-solid fa-file-code"></i><p>Select a file to edit</p></div>
        <div class="ce-scroll" id="ceScroll" style="display:none"><div class="ce-wrap"><div class="ce-ln" id="cLn"></div><div class="ce-code" id="cCode"></div></div><textarea class="ce-edit" id="cEdit" spellcheck="false" oninput="onEdit()" onscroll="syncScr()"></textarea></div>
      </div>
    </div>
    <div class="save-bar" id="saveBar"><span>Unsaved</span><button onclick="saveFile()">Save</button></div>
  </div>
  <div class="page" id="pgPreview">
    <div class="pv-bar"><div class="pv-dots"><div class="pv-dot" style="background:#ef4444"></div><div class="pv-dot" style="background:#eab308"></div><div class="pv-dot" style="background:#22c55e"></div></div><div class="pv-url" id="pvUrl">preview</div><button class="pv-cbtn" id="conBtn" onclick="toggleCon()"><i class="fa-solid fa-terminal"></i></button></div>
    <iframe class="pv-frame" id="pvFrame" sandbox="allow-scripts allow-same-origin"></iframe>
    <div class="pv-console" id="conPanel"><div class="pv-ch"><span><i class="fa-solid fa-terminal"></i> Console</span><div><button class="cbx" onclick="clearCon()"><i class="fa-solid fa-ban"></i></button><button class="cbx" onclick="toggleCon()"><i class="fa-solid fa-xmark"></i></button></div></div><div class="pv-cb" id="conBody"></div></div>
  </div>
</div>
<div class="shade" id="shade" onclick="closeDrawer()"></div>
<div class="drawer" id="drawer">
  <div class="dr-head"><div class="dr-logo"><div class="ic">DX</div><div class="tx"><span>Dev</span>-X</div></div><button class="tbtn" onclick="closeDrawer()"><i class="fa-solid fa-xmark"></i></button></div>
  <button class="dr-new" onclick="closeDrawer();openBS('newProjBS')"><i class="fa-solid fa-plus"></i> New Project</button>
  <div class="dr-list" id="drList"></div>
</div>
<div class="bsheet" id="settingsBS"><div class="bs-bg" onclick="closeBS('settingsBS')"></div><div class="bs-body"><h3><i class="fa-solid fa-gear" style="color:var(--ac)"></i> Settings</h3><div class="sg"><div class="sgl">Auto Switch</div><div class="sr"><div><div class="sn">Auto → Code</div><div class="sd">Switch to Code when agent writes</div></div><div class="tg on" id="autoCode" onclick="this.classList.toggle('on')"></div></div><div class="sr"><div><div class="sn">Auto → Preview</div><div class="sd">Switch to Preview after done</div></div><div class="tg on" id="autoPrev" onclick="this.classList.toggle('on')"></div></div></div><div class="sg"><div class="sgl">Data</div><div class="sr"><div><div class="sn">Clear All</div><div class="sd">Delete all projects</div></div><button onclick="confirmAction('Delete all projects and data?','clearAllConfirmed')" style="padding:8px 16px;background:var(--rd);color:#fff;border:none;border-radius:var(--r);font-size:12px;font-weight:600;cursor:pointer">Clear</button></div></div><div class="bs-btns"><button class="bs-b sec" onclick="closeBS('settingsBS')">Close</button></div></div></div>
<div class="bsheet" id="newProjBS"><div class="bs-bg" onclick="closeBS('newProjBS')"></div><div class="bs-body"><h3><i class="fa-solid fa-folder-plus" style="color:var(--ac)"></i> New Project</h3><input class="bs-inp" id="npInp" placeholder="Project name..." onkeydown="if(event.key==='Enter')createProj()"><div class="bs-btns"><button class="bs-b sec" onclick="closeBS('newProjBS')">Cancel</button><button class="bs-b pri" onclick="createProj()">Create</button></div></div></div>
<div class="bsheet" id="newFileBS"><div class="bs-bg" onclick="closeBS('newFileBS')"></div><div class="bs-body"><h3><i class="fa-solid fa-file-circle-plus" style="color:var(--ac)"></i> New File</h3><div class="nf-type-btns"><button class="nf-type-btn on" id="nfBtnFile" onclick="setNFType('file')"><i class="fa-solid fa-file"></i> File</button><button class="nf-type-btn" id="nfBtnFolder" onclick="setNFType('folder')"><i class="fa-solid fa-folder"></i> Folder</button></div><input class="bs-inp" id="nfInp" placeholder="filename.html" onkeydown="if(event.key==='Enter')createFile()"><div class="bs-btns"><button class="bs-b sec" onclick="closeBS('newFileBS')">Cancel</button><button class="bs-b pri" onclick="createFile()">Create</button></div></div></div>
<div class="bsheet" id="confirmBS"><div class="bs-bg" onclick="closeBS('confirmBS')"></div><div class="bs-body"><div class="confirm-icon"><i class="fa-solid fa-triangle-exclamation"></i></div><div class="confirm-text" id="confirmText"></div><div class="bs-btns"><button class="bs-b sec" onclick="closeBS('confirmBS')">Cancel</button><button class="bs-b danger" id="confirmOkBtn">Delete</button></div></div></div>

<script>
let CID='',PF={},AF='',STR=false,PFC={},CON=false,NF_T='file',TAB='agent',FP_OPEN=false,EXP={},PROJ_NAME='',DARK=true,PROJ_EXP=true;

function confirmAction(msg,cbName,extra){document.getElementById('confirmText').innerHTML=msg;document.getElementById('confirmOkBtn').onclick=function(){closeBS('confirmBS');if(cbName==='clearAllConfirmed')clearAllConfirmed();else if(cbName==='delChatConfirmed')delChatConfirmed(extra);else if(cbName==='delItemConfirmed')delItemConfirmed(extra);};openBS('confirmBS');}
function go(t){TAB=t;['agent','code','preview'].forEach(v=>{document.getElementById('pg'+v.charAt(0).toUpperCase()+v.slice(1)).classList.toggle('on',v===t);document.getElementById('t'+v.charAt(0).toUpperCase()+v.slice(1)).classList.toggle('on',v===t);});if(t==='preview')updPreview();if(t==='code'){renderTabs();if(AF)showFile(AF);refreshTree();}}
function toggleTheme(){DARK=!DARK;document.documentElement.classList.toggle('light',!DARK);document.getElementById('themeBtn').innerHTML=DARK?'<i class="fa-solid fa-moon"></i>':'<i class="fa-solid fa-sun"></i>';document.getElementById('themeMetaColor').content=DARK?'#0a0a0c':'#f8f9fa';}
function openDrawer(){document.getElementById('shade').classList.add('on');document.getElementById('drawer').classList.add('on')}
function closeDrawer(){document.getElementById('shade').classList.remove('on');document.getElementById('drawer').classList.remove('on')}
function openBS(id){document.getElementById(id).classList.add('on');const i=document.getElementById(id).querySelector('.bs-inp');if(i){i.value='';setTimeout(()=>i.focus(),200)}}
function closeBS(id){document.getElementById(id).classList.remove('on')}
function esc(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML}
function setNFType(t){NF_T=t;document.getElementById('nfBtnFile').classList.toggle('on',t==='file');document.getElementById('nfBtnFolder').classList.toggle('on',t==='folder');document.getElementById('nfInp').placeholder=t==='file'?'filename.html':'folder-name';}
function toggleFiles(){FP_OPEN=!FP_OPEN;document.getElementById('filePanel').classList.toggle('on',FP_OPEN);document.getElementById('fpShade').classList.toggle('on',FP_OPEN);document.getElementById('fileToggle').classList.toggle('on',FP_OPEN);if(FP_OPEN)refreshTree();}

const KW=/\b(const|let|var|function|return|if|else|for|while|do|switch|case|break|continue|new|this|class|extends|import|export|from|default|try|catch|finally|throw|async|await|typeof|instanceof|void|delete|true|false|null|undefined|console|document|window|addEventListener|querySelector|getElementById|createElement|appendChild|innerHTML|textContent|style|classList|setAttribute|setTimeout|setInterval|fetch|then|JSON|parse|stringify|Math|Array|Object|String|Number|Date|Promise|Map|Set)\b/g;
const HT=/(&lt;\/?)([\w-]+)/g;const SRE=/(["'`])(?:(?!\1|\\).|\\.)*?\1/g;
const CJR=/(\/\/.*$|\/\*[\s\S]*?\*\/)/gm;const CHR=/(&lt;!--[\s\S]*?--&gt;)/g;
const NRE=/\b(\d+\.?\d*)\b/g;const ARE=/\s([\w-]+)=/g;
const CSE=/^([^{:@\/][^{]*)\{/gm;const CPE=/^\s*([\w-]+)\s*:/gm;
function hi(c,tp){let x=esc(c);if(tp==='js'){x=x.replace(SRE,'<s>$&</s>');x=x.replace(CJR,'<i>$1</i>');x=x.replace(KW,'<b>$&</b>');x=x.replace(NRE,'<u>$1</u>');}else if(tp==='css'){x=x.replace(SRE,'<s>$&</s>');x=x.replace(CJR,'<i>$1</i>');x=x.replace(CSE,'<mark>$1</mark>{');x=x.replace(CPE,(m,p)=>'  <u>'+p+'</u>:');x=x.replace(NRE,'<var>$1</var>');}else{x=x.replace(CHR,'<i>$1</i>');x=x.replace(SRE,'<s>$&</s>');x=x.replace(HT,'$1<em>$2</em>');x=x.replace(ARE,' <strong>$1</strong>=');}return x;}
function gtp(fn){if(fn.endsWith('.js'))return'js';if(fn.endsWith('.css'))return'css';return'html';}

async function loadCL(){const r=await fetch('/get_history');const d=await r.json();const l=document.getElementById('drList');l.innerHTML='';Object.keys(d.chats).reverse().forEach(id=>{const c=d.chats[id];const e=document.createElement('div');e.className='dr-i'+(id===CID?' on':'');e.innerHTML=`<span class="nm">${esc(c.title)}</span><button class="dl" onclick="event.stopPropagation();confirmAction('Delete project <span class=confirm-highlight>${esc(c.title)}</span>?','delChatConfirmed','${id}')"><i class="fa-solid fa-trash"></i></button>`;e.onclick=()=>{closeDrawer();swChat(id);};l.appendChild(e);});}
async function loadMsgs(){const r=await fetch('/get_history');const d=await r.json();if(!d.chats[CID])return;const msgs=d.chats[CID].messages;const c=document.getElementById('chatArea');c.innerHTML='';if(!msgs.length){c.innerHTML=`<div class="msg"><div class="av ai">DX</div><div class="mmb"><div class="mh" style="color:var(--ac)">Dev-X</div><div class="mt">Project ready! Tell me what to build.</div></div></div>`;return;}msgs.forEach(m=>{if(m.role==='user')addU(m.content,false);else{const p=parseR(m.content);addA(p.expl,p.diffs,false);}});scr();}
function addU(t,anim=true){const c=document.getElementById('chatArea');const w=c.querySelector('.welcome');if(w)w.remove();const d=document.createElement('div');d.className='msg';if(!anim)d.style.animation='none';const tm=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});d.innerHTML=`<div class="av u"><i class="fa-solid fa-user" style="font-size:10px"></i></div><div class="mmb"><div class="mh">You <span class="tm">${tm}</span></div><div class="mt">${esc(t)}</div></div>`;c.appendChild(d);}
function addA(expl,diffs,anim=true){const c=document.getElementById('chatArea');const d=document.createElement('div');d.className='msg';if(!anim)d.style.animation='none';const tm=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});let bd='';diffs.forEach(f=>{bd+=`<div class="fbg" onclick="openF('${f.name}')"><i class="fa-solid fa-file-code" style="color:var(--ac);font-size:10px"></i><span class="fn">${f.name}</span><span class="fg">✓</span></div>`;});d.innerHTML=`<div class="av ai">DX</div><div class="mmb"><div class="mh" style="color:var(--ac)">Dev-X <span class="tm">${tm}</span></div><div class="mt">${fmtChat(expl||'')}</div>${bd?'<div style="margin-top:5px;display:flex;flex-wrap:wrap">'+bd+'</div>':''}</div>`;c.appendChild(d);}

function fmtChat(t){
  t=t.replace(/---FILE:[\s\S]*?---ENDFILE---/g,'').replace(/---DIFF:[\s\S]*?---ENDDIFF---/g,'');
  t=t.replace(/---FILE:[\s\S]*$/g,'').replace(/---DIFF:[\s\S]*$/g,'');
  t=t.replace(/---ENDFILE---/g,'').replace(/---ENDDIFF---/g,'');
  t=t.replace(/```[\s\S]*?```/g,'').replace(/```[\s\S]*$/g,'');
  t=t.replace(/\*\*/g,'').replace(/\*/g,'');
  t=t.replace(/\s(safe|success|done|safe\n|success\n)$/gi,'');
  t=t.replace(/^.*---FILE.*$/gim,'').replace(/^.*---END.*$/gim,'');
  t=t.replace(/^.*---DIFF.*$/gim,'');
  t=t.trim();
  if(!t||t.length<3) return 'Code generated successfully';
  let lines=t.split('\n').map(l=>l.trim()).filter(l=>l.length>0);
  if(lines.length>0){
    let r=[];
    lines.forEach(l=>{
      if(l.match(/^(index\.html|style\.css|app\.js|script\.js|file|endfile|diff|success)/i))return;
      r.push(l);
    });
    if(r.length===0)return 'Code generated successfully';
    return r.join('<br>');
  }
  return t;
}

function mkWorking(){const c=document.getElementById('chatArea');const d=document.createElement('div');d.className='msg';d.id='workingMsg';d.innerHTML=`<div class="av ai">DX</div><div class="mmb"><div class="mh" style="color:var(--ac)">Dev-X</div><div class="mt"><div class="agent-working"><span>Working</span><div class="aw-dots"><span></span><span></span><span></span></div></div></div></div>`;c.appendChild(d);scr();return d;}

async function loadFiles(){if(!CID)return;const r=await fetch(`/get_files/${CID}`);PF=await r.json();renderTabs();if(Object.keys(PF).length>0&&(!AF||!PF[AF]))AF=Object.keys(PF)[0];}

async function refreshTree(){
  if(!CID){document.getElementById('fList').innerHTML='<div class="fp-empty">No project open</div>';document.getElementById('projRootDisp').style.display='none';return;}
  document.getElementById('projRootDisp').style.display='flex';
  document.getElementById('projRootName').textContent=PROJ_NAME||'Project';
  const arrowEl=document.getElementById('prArrow');
  arrowEl.classList.toggle('open',PROJ_EXP);
  const c=document.getElementById('fList');
  if(!PROJ_EXP){c.innerHTML='';return;}
  const r=await fetch(`/get_tree/${CID}`);const tree=await r.json();c.innerHTML='';
  if(!tree||!tree.length){c.innerHTML='<div class="fp-empty">Empty project.<br>Ask agent to create files.</div>';return;}
  const root={name:'root',path:'',type:'folder',children:{}};
  tree.forEach(f=>{const parts=f.path.split('/');let cur=root;parts.forEach((p,i)=>{if(!cur.children[p])cur.children[p]={name:p,path:i===parts.length-1?f.path:parts.slice(0,i+1).join('/'),type:i===parts.length-1?f.type:'folder',children:{}};cur=cur.children[p];});});
  function renderNode(node,container,depth){
    const sorted=Object.values(node.children).sort((a,b)=>{if(a.type===b.type)return a.name.localeCompare(b.name);return a.type==='folder'?-1:1;});
    sorted.forEach(it=>{
      if(it.type==='folder'){
        const isOpen=EXP[it.path]||false;const fd=document.createElement('div');
        const head=document.createElement('div');head.className='tree-folder-head';head.style.paddingLeft=(depth*14+10)+'px';
        head.innerHTML=`<i class="fa-solid fa-chevron-right arrow ${isOpen?'open':''}"></i><i class="fa-solid fa-folder${isOpen?'-open':''} fold-icon"></i><span class="fold-name">${it.name}</span><button class="fold-del" onclick="event.stopPropagation();confirmAction('Delete folder <span class=confirm-highlight>${it.name}</span>?','delItemConfirmed','${it.path}')"><i class="fa-solid fa-trash-can"></i></button>`;
        head.onclick=(e)=>{if(e.target.closest('.fold-del'))return;EXP[it.path]=!EXP[it.path];refreshTree();};
        fd.appendChild(head);const children=document.createElement('div');children.className='tree-folder-children'+(isOpen?' open':'');renderNode(it,children,depth+1);fd.appendChild(children);container.appendChild(fd);
      }else{
        const fi=document.createElement('div');fi.className='tree-file'+(it.path===AF?' sel':'');fi.style.paddingLeft=(depth*14+10)+'px';
        const ext=it.name.split('.').pop();const ic=ext==='html'?'fa-file-code htm':ext==='css'?'fa-file-code css':ext==='js'?'fa-file-code jss':'fa-file';
        fi.innerHTML=`<i class="fa-solid ${ic} file-icon"></i><span class="file-name">${it.name}</span><button class="file-del" onclick="event.stopPropagation();confirmAction('Delete <span class=confirm-highlight>${it.name}</span>?','delItemConfirmed','${it.path}')"><i class="fa-solid fa-trash-can"></i></button>`;
        fi.onclick=(e)=>{if(e.target.closest('.file-del'))return;AF=it.path;showFile(AF);toggleFiles();renderTabs();};container.appendChild(fi);
      }
    });
  }
  renderNode(root,c,0);
}
function renderTabs(){const c=document.getElementById('cTabs');c.innerHTML='';Object.keys(PF).forEach(fn=>{const t=document.createElement('div');t.className='ctab'+(fn===AF?' on':'');const ext=fn.split('.').pop();let dc=ext==='html'?'htm':ext==='css'?'css':'jss';t.innerHTML=`<span class="cdot ${dc}"></span>${fn}`;t.onclick=()=>{AF=fn;showFile(fn);renderTabs();};c.appendChild(t);});}
function showFile(fn){const content=PF[fn]||'';document.getElementById('cEmpty').style.display='none';document.getElementById('ceScroll').style.display='block';document.getElementById('cEdit').value=content;renderCode(fn,content,false);document.getElementById('saveBar').classList.remove('on');}
function renderCode(fn,content,diff){const old=PFC[fn]||'';const oL=old?old.split('\n'):[];const nL=content.split('\n');const tp=gtp(fn);let h='';nL.forEach((line,i)=>{const hd=hi(line,tp);let cls='cl';if(diff&&oL.length>0&&(i>=oL.length||oL[i]!==line))cls+=' df';h+=`<div class="${cls}">${hd||' '}</div>`;});document.getElementById('cLn').innerText=nL.map((_,i)=>i+1).join('\n');document.getElementById('cCode').innerHTML=h;PFC[fn]=content;document.getElementById('cEdit').value=content;}
function openF(fn){AF=fn;if(PF[fn]!==undefined){showFile(fn);go('code');renderTabs();}}
function onEdit(){const v=document.getElementById('cEdit').value;PF[AF]=v;renderCode(AF,v,false);document.getElementById('saveBar').classList.add('on');clearTimeout(window._st);window._st=setTimeout(()=>saveFile(),2000);}
function syncScr(){const t=document.getElementById('cEdit'),d=document.getElementById('ceScroll');d.scrollTop=t.scrollTop;}
async function saveFile(){if(!AF||!CID)return;await fetch('/save_file',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_id:CID,filename:AF,content:PF[AF]||''})});document.getElementById('saveBar').classList.remove('on');}

function updPreview(){
  const ifr=document.getElementById('pvFrame');
  let h=PF['index.html']||PF[Object.keys(PF).find(f=>f.endsWith('.html'))]||'';
  h=h.replace(/^\s*```(?:html|css|javascript|js)?\s*\n?/i,'').replace(/\n?```\s*$/i,'');
  Object.keys(PF).forEach(f=>{if(f.endsWith('.css'))h=h.replace('</head>',`<style>${PF[f]}</style></head>`);});
  Object.keys(PF).forEach(f=>{if(f.endsWith('.js')&&!f.endsWith('.html'))h=h.replace('</body>',`<script>${PF[f]}<\/script></body>`);});
  const cap=`<script>(function(){function s(l,m){try{window.parent.postMessage({type:'con',level:l,message:String(m)},'*')}catch(e){}}var _l=console.log,_e=console.error,_w=console.warn;console.log=function(){_l.apply(console,arguments);s('log',Array.prototype.slice.call(arguments).map(function(a){return typeof a==='object'?JSON.stringify(a):String(a)}).join(' '))};console.error=function(){_e.apply(console,arguments);s('err',Array.prototype.slice.call(arguments).map(function(a){return typeof a==='object'?JSON.stringify(a):String(a)}).join(' '))};console.warn=function(){_w.apply(console,arguments);s('warn',Array.prototype.slice.call(arguments).map(function(a){return typeof a==='object'?JSON.stringify(a):String(a)}).join(' '))};window.onerror=function(m,u,l){s('err',m+(l?' (line '+l+')':''));return false};window.addEventListener('unhandledrejection',function(e){s('err','Promise: '+(e.reason?e.reason.message||String(e.reason):''))});window.addEventListener('error',function(e){if(e.target&&e.target!==window)s('err',(e.target.tagName||'')+' load failed')},true)})()\x3c/script>`;
  if(h.indexOf('<head>')!==-1)h=h.replace('<head>','<head>'+cap);else h=cap+h;
  if(h.indexOf('viewport')===-1&&h.indexOf('<head>')!==-1)h=h.replace('<head>','<head><meta name="viewport" content="width=device-width,initial-scale=1.0">');
  ifr.srcdoc=h;document.getElementById('pvUrl').textContent=Object.keys(PF).find(f=>f.endsWith('.html'))||'preview';
  if(CON)document.getElementById('conPanel').classList.add('on');
}
function toggleCon(){CON=!CON;document.getElementById('conPanel').classList.toggle('on',CON);document.getElementById('conBtn').classList.toggle('on',CON)}
function clearCon(){document.getElementById('conBody').innerHTML=''}
window.addEventListener('message',e=>{if(e.data&&e.data.type==='con'){const c=document.getElementById('conBody');const d=document.createElement('div');d.className='cmsg '+e.data.level;d.textContent=e.data.message;c.appendChild(d);c.scrollTop=c.scrollHeight;}});

function cleanFileName(fn){fn=fn.trim();fn=fn.replace(/^(Safe|safe|SAFE)\s*/,'');fn=fn.replace(/^[^a-zA-Z0-9_.\-\/]+/,'');return fn;}

function parseR(text){
  let expl=text;
  const rx=/(?:Safe\s*)?---FILE:(.+?)---\s*([\s\S]*?)---ENDFILE---/g;
  let m,files={},diffs=[];
  while((m=rx.exec(text))!==null){let fn=cleanFileName(m[1]);let c=m[2].replace(/^\s*```(?:html|css|javascript|js)?\s*\n?/i,'').replace(/\n?```\s*$/i,'').replace(/^\s*(Safe|Here is|Sure|Certainly|I have).*?\n/i,'');files[fn]=c;expl=expl.replace(m[0],'');}
  const lt=text.lastIndexOf('---FILE:'),le=text.lastIndexOf('---ENDFILE---');
  if(lt>le&&lt>-1){const lend=text.indexOf('\n',lt);if(lend>-1){const fm=text.substring(lt,lend).match(/---FILE:(.+?)---/);if(fm){let fn=cleanFileName(fm[1]);let c=text.substring(lend+1).replace(/^\s*```(?:html|css|javascript|js)?\s*\n?/i,'').replace(/\n?```\s*$/i,'');files[fn]=c;expl=expl.substring(0,lt);}}}
  const dx=/(?:Safe\s*)?---(?:safe)?DIFF:(.+?)---\s*([\s\S]*?)---ENDDIFF---/g;
  while((m=dx.exec(text))!==null){const fn=cleanFileName(m[1]),body=m[2];expl=expl.replace(m[0],'');const sr=/<<<<<<< SEARCH\n([\s\S]*?)\n=======\n([\s\S]*?)>>>>>>> REPLACE/g;let sm;while((sm=sr.exec(body))!==null)diffs.push({name:fn,search:sm[1],replace:sm[2],full_match:sm[0]});}
  const dlt=expl.lastIndexOf('---DIFF:');if(dlt>-1)expl=expl.substring(0,dlt);
  const flt=expl.lastIndexOf('---FILE:');if(flt>-1)expl=expl.substring(0,flt);
  const slt=expl.lastIndexOf('Safe---');if(slt>-1)expl=expl.substring(0,slt);
  const slt2=expl.lastIndexOf('Safe\n---');if(slt2>-1)expl=expl.substring(0,slt2);
  expl=expl.replace(/```[\s\S]*?```/g,'').replace(/```[\s\S]*$/g,'').trim();
  let fD=[];
  Object.keys(files).forEach(fn=>fD.push({name:fn,content:files[fn],added:1}));
  diffs.forEach(d=>fD.push({name:d.name,diff:d,added:1}));
  return{expl,files,diffs:fD,rawDiffs:diffs};
}

function applyDiff(o,s,r){if(!o)return r;const n=t=>t.replace(/\r\n/g,'\n');const oo=n(o),ss=n(s),rr=n(r);if(oo.includes(ss))return oo.replace(ss,rr);const oL=oo.split('\n'),sL=ss.split('\n');for(let i=0;i<=oL.length-sL.length;i++){let ok=true;for(let j=0;j<sL.length;j++){if(oL[i+j].trim()!==sL[j].trim()){ok=false;break;}}if(ok)return(oL.slice(0,i).join('\n')+(i>0?'\n':''))+rr+(i+sL.length<oL.length?'\n'+oL.slice(i+sL.length).join('\n'):'');}return o;}

async function sendMsg(){
  const inp=document.getElementById('inp');const txt=inp.value.trim();
  if(!txt||STR||!CID)return;
  STR=true;inp.value='';autoH(inp);document.getElementById('goBtn').disabled=true;
  addU(txt);scr();const thk=mkWorking();let didAutoCode=false;
  try{
    const res=await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt:txt,chat_id:CID,is_file:false})});
    const reader=res.body.getReader();const dec=new TextDecoder();let full='';thk.remove();
    const uid=Date.now(),cid='s'+uid,did='d'+uid;
    const sd=document.createElement('div');sd.className='msg';
    const tm=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
    sd.innerHTML=`<div class="av ai">DX</div><div class="mmb"><div class="mh" style="color:var(--ac)">Dev-X <span class="tm">${tm}</span></div><div class="mt" id="${cid}"><div class="agent-working"><span>Working</span><div class="aw-dots"><span></span><span></span><span></span></div></div></div><div id="${did}" style="margin-top:5px;display:flex;flex-wrap:wrap"></div></div>`;
    document.getElementById('chatArea').appendChild(sd);
    let sf={},lp={};
    while(true){
      const{value,done}=await reader.read();if(done)break;full+=dec.decode(value);
      const p=parseR(full);const se=document.getElementById(cid);
      if(se){let hasFiles=Object.keys(p.files).length>0||p.rawDiffs.length>0;if(hasFiles)se.innerHTML='<div class="agent-working"><span>Writing code</span><div class="aw-dots"><span></span><span></span><span></span></div></div>';else{let x=p.expl||'';if(x.length>3)se.innerHTML=fmtChat(x);}}
      for(const[fn,ct] of Object.entries(p.files)){if(!lp[fn]||lp[fn]!==ct){lp[fn]=ct;PF[fn]=ct;AF=fn;renderTabs();document.getElementById('cEmpty').style.display='none';document.getElementById('ceScroll').style.display='block';renderCode(fn,ct,true);if(!didAutoCode&&document.getElementById('autoCode').classList.contains('on')){didAutoCode=true;go('code');}clearTimeout(window._ss);window._ss=setTimeout(()=>{fetch('/save_file',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_id:CID,filename:fn,content:ct})})},300);}}
      if(p.rawDiffs){for(const d of p.rawDiffs){const dk=d.name+'||'+d.full_match;if(!sf[dk]){sf[dk]=true;const oc=PF[d.name]||'';const nc=applyDiff(oc,d.search,d.replace);if(nc!==oc){PF[d.name]=nc;lp[d.name]=nc;AF=d.name;renderTabs();document.getElementById('cEmpty').style.display='none';document.getElementById('ceScroll').style.display='block';renderCode(d.name,nc,true);if(!didAutoCode&&document.getElementById('autoCode').classList.contains('on')){didAutoCode=true;go('code');}fetch('/save_file',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_id:CID,filename:d.name,content:nc})});}}}}
      scr();
    }
    const fp=parseR(full);let fd=[];
    for(const[fn,ct] of Object.entries(fp.files)){let cc=ct.replace(/^\s*```(?:html|css|javascript|js)?\s*\n?/i,'').replace(/\n?```\s*$/i,'');PF[fn]=cc;await fetch('/save_file',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_id:CID,filename:fn,content:cc})});fd.push({name:fn,added:1});}
    if(fp.rawDiffs)fp.rawDiffs.forEach(d=>fd.push({name:d.name,added:1}));
    const se=document.getElementById(cid),de=document.getElementById(did);
    if(se)se.innerHTML=fmtChat(fp.expl||'');
    if(de){let bd='';fd.forEach(f=>{bd+=`<div class="fbg" onclick="openF('${f.name}')"><i class="fa-solid fa-file-code" style="color:var(--ac);font-size:10px"></i><span class="fn">${f.name}</span><span class="fg">✓</span></div>`;});de.innerHTML=bd;}
    await loadFiles();if(AF&&PF[AF])renderCode(AF,PF[AF],true);
    if(document.getElementById('autoPrev').classList.contains('on')&&fd.length>0){setTimeout(()=>{go('preview');},400);}
    await loadCL();await refreshTree();
  }catch(e){thk?.remove();addA('Something went wrong.',[],true);}
  STR=false;document.getElementById('goBtn').disabled=false;scr();
}
function scr(){const e=document.getElementById('chatArea');e.scrollTop=e.scrollHeight}
function hKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg()}}
function autoH(e){e.style.height='auto';e.style.height=Math.min(e.scrollHeight,90)+'px'}
function usg(t){if(!CID)return;document.getElementById('inp').value=t;sendMsg()}

async function selectProj(name){const r=await fetch('/new_chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_name:name})});const d=await r.json();if(d.chat_id){CID=d.chat_id;PROJ_NAME=d.project_name||name;PFC={};await loadAll();}}
async function createProj(){const n=document.getElementById('npInp').value.trim();if(!n)return;closeBS('newProjBS');await selectProj(n);}
async function swChat(id){await fetch(`/switch_chat/${id}`,{method:'POST'});CID=id;PFC={};await loadAll();}
async function delChatConfirmed(id){await fetch(`/delete_chat/${id}`,{method:'POST'});if(id===CID){CID='';PF={};AF='';PFC={};}await loadCL();if(!CID)await loadAll();}
async function clearAllConfirmed(){await fetch('/clear_all',{method:'POST'});CID='';PF={};AF='';PFC={};closeBS('settingsBS');await loadAll();}
function closeProject(){if(!CID)return;CID='';PF={};AF='';PFC={};PROJ_NAME='';document.getElementById('pvFrame').srcdoc='';clearCon();loadAll();loadCL();}
async function createFile(){const v=document.getElementById('nfInp').value.trim();if(!v||!CID)return;closeBS('newFileBS');if(NF_T==='folder')await fetch('/create_folder',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_id:CID,path:v})});else{await fetch('/save_file',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_id:CID,filename:v,content:''})});PF[v]='';AF=v;showFile(AF);renderTabs();}await loadFiles();refreshTree();}
async function delItemConfirmed(path){await fetch('/delete_item',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({chat_id:CID,path})});if(PF[path])delete PF[path];if(AF===path)AF=Object.keys(PF)[0]||'';await loadFiles();refreshTree();if(AF)showFile(AF);}
function toggleChat(on){const g=document.getElementById('goBtn'),i=document.getElementById('inp'),lo=document.getElementById('lockOv'),cb=document.getElementById('chatBar');g.disabled=!on;i.disabled=!on;if(!on){i.placeholder='Open a project first...';lo.classList.add('on');cb.style.display='none';}else{i.placeholder='Describe what to build...';lo.classList.remove('on');cb.style.display='block';}}
function renderWelcome(){const cs=document.getElementById('chatArea');fetch('/list_projects').then(r=>r.json()).then(proj=>{let cards='';proj.forEach(p=>{cards+=`<div class="dcard" onclick="selectProj('${esc(p)}')"><i class="fa-solid fa-folder"></i><span>${esc(p)}</span></div>`;});cs.innerHTML=`<div class="welcome"><div class="w-icon"><i class="fa-solid fa-bolt" style="color:#fff"></i></div><div class="w-title">Dev-X</div><div class="w-sub">Create or open a project to build with AI</div><div class="dash-box"><div class="dash-form"><input type="text" class="dash-inp" id="dashInp" placeholder="New project name..." onkeydown="if(event.key==='Enter'){selectProj(this.value.trim())}"><button class="dash-go" onclick="const v=document.getElementById('dashInp').value.trim();if(v)selectProj(v)"><i class="fa-solid fa-plus"></i></button></div>${proj.length>0?`<div class="dash-div">Recent</div><div class="dash-grid">${cards}</div>`:''}</div></div>`;});}
async function loadAll(){
  if(!CID){document.getElementById('pname').textContent='';document.getElementById('pname').classList.remove('on');toggleChat(false);renderWelcome();document.getElementById('fList').innerHTML='';document.getElementById('cTabs').innerHTML='';document.getElementById('ceScroll').style.display='none';document.getElementById('cEmpty').style.display='flex';document.getElementById('projRootDisp').style.display='none';await loadCL();go('agent');return;}
  try{const h=await fetch('/get_history');const j=await h.json();if(j.chats[CID]){PROJ_NAME=j.chats[CID].title;document.getElementById('pname').textContent=PROJ_NAME;document.getElementById('pname').classList.add('on');}}catch(e){}
  toggleChat(true);await loadMsgs();await loadFiles();await loadCL();await refreshTree();go('agent');if(Object.keys(PF).length>0&&!AF)AF=Object.keys(PF)[0];
}
async function init(){const r=await fetch('/get_history');const d=await r.json();CID=(!d.current_chat||!d.chats[d.current_chat])?'':d.current_chat;await loadAll();}
init();
</script>
</body>
</html>
"""


# ============================================
# Flask Routes
# ============================================
@app.route('/')
def index():
    return render_template_string(HTML_UI)

@app.route('/get_history')
def get_history():
    return jsonify(load_memory())

@app.route('/list_projects')
def list_projects():
    if not os.path.exists(PROJECTS_DIR):
        return jsonify([])
    projects = [
        d for d in os.listdir(PROJECTS_DIR)
        if os.path.isdir(os.path.join(PROJECTS_DIR, d))
    ]
    return jsonify(projects)

@app.route('/new_chat', methods=['POST'])
def new_chat():
    mem = load_memory()
    data = request.json or {}
    project_name = data.get('project_name')
    if not project_name:
        project_name = f"Project-{str(uuid.uuid4())[:6]}"
    clean_name = "".join(
        [c for c in project_name if c.isalnum() or c in ('-', '_')]
    ).strip()
    if clean_name in mem['projects']:
        cid = mem['projects'][clean_name]
        mem['current_chat'] = cid
        save_memory(mem)
        return jsonify({
            "chat_id": cid,
            "project_name": clean_name,
            "exists": True
        })
    new_id = str(uuid.uuid4())
    mem['chats'][new_id] = {"title": clean_name, "messages": []}
    mem['current_chat'] = new_id
    mem['projects'][clean_name] = new_id
    save_memory(mem)
    get_project_dir(new_id)
    return jsonify({"chat_id": new_id, "project_name": clean_name})

@app.route('/delete_chat/<id>', methods=['POST'])
def delete_chat(id):
    mem = load_memory()
    if id in mem['chats']:
        title = mem['chats'][id].get('title')
        if title and title in mem['projects']:
            del mem['projects'][title]
        del mem['chats'][id]
        if mem['current_chat'] == id:
            mem['current_chat'] = None
        save_memory(mem)
    return jsonify({"success": True})

@app.route('/switch_chat/<id>', methods=['POST'])
def switch_chat(id):
    mem = load_memory()
    if id in mem['chats']:
        mem['current_chat'] = id
        save_memory(mem)
    return jsonify({"success": True})

@app.route('/get_files/<chat_id>')
def get_files(chat_id):
    return jsonify(get_project_files(chat_id))

@app.route('/get_tree/<chat_id>')
def get_tree(chat_id):
    return jsonify(get_file_tree(chat_id))

@app.route('/save_file', methods=['POST'])
def save_file():
    data = request.json
    diff = save_project_file(
        data['chat_id'], data['filename'], data['content']
    )
    return jsonify(diff)

@app.route('/create_folder', methods=['POST'])
def create_folder():
    data = request.json
    create_project_folder(data['chat_id'], data['path'])
    return jsonify({"success": True})

@app.route('/clear_all', methods=['POST'])
def clear_all():
    save_memory({"chats": {}, "current_chat": None, "projects": {}})
    import shutil
    if os.path.exists(PROJECTS_DIR):
        shutil.rmtree(PROJECTS_DIR)
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    return jsonify({"success": True})

@app.route('/delete_item', methods=['POST'])
def delete_item():
    data = request.json
    chat_id = data.get('chat_id')
    rel_path = data.get('path')
    if not chat_id or not rel_path:
        return jsonify({'error': 'Missing data'}), 400
    success = delete_project_item(chat_id, rel_path)
    if success:
        return jsonify({'status': 'deleted'})
    return jsonify({'error': 'Not found'}), 404


@app.route('/ask', methods=['POST'])
def ask():
    data = request.json
    prompt = (data.get('prompt') or '').strip()
    chat_id = data.get('chat_id')
    is_file = data.get('is_file')

    if not chat_id:
        return jsonify({"error": "No Project ID"}), 400
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    mem = load_memory()
    if chat_id not in mem['chats']:
        return jsonify({"error": "Project not found"}), 404

    chat = mem['chats'][chat_id]
    if chat['title'] == "New Project":
        chat['title'] = prompt[:30] + (
            "..." if len(prompt) > 30 else ""
        )
        save_memory(mem)

    # Build history + files context
    existing_files = get_project_files(chat_id)
    files_context = ""
    if existing_files:
        files_context = "\n\nCurrent project files:\n"
        for fname, content in existing_files.items():
            files_context += (
                f"---FILE:{fname}---\n{content}\n---ENDFILE---\n"
            )

    history_messages = [
        {
            "role": m.get("role", "user"),
            "content": m.get("content", "")[:2000]
        }
        for m in chat['messages'][-6:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]

    def generate():
        try:
            if not OPENROUTER_API_KEY:
                yield "Configuration error: OPENROUTER_API_KEY missing"
                return

            web_context = ""
            if should_use_web_search(prompt):
                web_payload = fetch_web_search_context(prompt)
                if web_payload:
                    stamp = datetime.now(timezone.utc).isoformat()
                    web_context = f"Fetched at {stamp}\n{web_payload}"

            full_reply = call_openrouter(
                prompt=prompt,
                history_messages=history_messages,
                files_context=files_context,
                web_context=web_context
            )
            yield full_reply

            # Save to memory
            db = load_memory()
            user_entry = {"role": "user", "content": prompt}
            if is_file:
                user_entry["type"] = "file"
            db['chats'][chat_id]['messages'].append(user_entry)
            db['chats'][chat_id]['messages'].append({
                "role": "assistant",
                "content": full_reply
            })
            save_memory(db)

        except Exception as e:
            yield f"Connection error: {str(e)}"

    return Response(generate(), mimetype='text/plain')


if __name__ == "__main__":
    print(f"\n{Fore.CYAN}{'='*40}")
    print(f"  🚀 Dev-X Mobile System Ready")
    print(f"  🔗 Local: http://127.0.0.1:5000")
    print(f"  🔗 Network: http://0.0.0.0:5000")
    print(f"{'='*40}\n")
    
    # threaded=True: Isse mobile browser hang nahi hoga multiple requests par
    # host='0.0.0.0': Isse phone ke hotspot ya wifi network par bhi access ho sakega
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
