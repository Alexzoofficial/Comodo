import json
import uuid
import time
import sys
import re
import os
from flask import Flask, render_template_string, request, Response, jsonify
import requests as req_lib
from colorama import Fore, init


init(autoreset=True)
app = Flask(__name__)





# ============================================
# API Configuration (Use environment variables)
# ============================================
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL = os.environ.get("AI_MODEL", "qwen/qwen3-coder:free")
SEARCH_API_KEY = os.environ.get("SEARCH_API_KEY", "")
SEARCH_API_URL = "https://alexzo.vercel.app/api/search"

def web_search(query):
    try:
        resp = req_lib.post(
            SEARCH_API_URL,
            json={"query": query},
            headers={
                "Authorization": f"Bearer {SEARCH_API_KEY}",
                "Content-Type": "application/json"
            },
            timeout=15
        )
        if resp.status_code == 200:
            return resp.json()
        return {"error": f"Search API error: {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}

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
def get_ui_html():
    try:
        path = os.path.join(WORKSPACE_DIR, "index.html")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return "<h1>Error: index.html not found</h1>"


# ============================================
# Flask Routes
# ============================================
@app.route('/')
def index():
    return render_template_string(get_ui_html())

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
    prompt = data.get('prompt')
    chat_id = data.get('chat_id')
    is_file = data.get('is_file')

    if not chat_id:
        return jsonify({"error": "No Project ID"}), 400

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

    # Search logic
    search_keywords = ["search", "find", "latest", "current", "news", "who is", "weather", "today"]
    needs_search = any(kw in prompt.lower() for kw in search_keywords)

    search_results = ""
    if needs_search:
        res = web_search(prompt)
        if isinstance(res, dict) and "results" in res:
            search_results = "\n\nWeb Search Results:\n" + json.dumps(res["results"], indent=2)
        elif isinstance(res, list):
            search_results = "\n\nWeb Search Results:\n" + json.dumps(res, indent=2)
        else:
            search_results = f"\n\nWeb Search Results: {res}"

    messages = [
        {"role": "system", "content": f"You are Comodo, an extremely skilled software engineer. You help users build projects. Provide code in ---FILE:filename--- content ---ENDFILE--- or ---DIFF:filename--- content ---ENDDIFF--- format.{search_results}"},
    ]

    for m in chat['messages'][-10:]:
        messages.append({"role": m['role'], "content": m['content']})

    user_msg = prompt
    if files_context:
        user_msg += "\n\n" + files_context
    messages.append({"role": "user", "content": user_msg})

    def generate():
        try:
            resp = req_lib.post(
                OPENROUTER_API_URL,
                json={
                    "model": AI_MODEL,
                    "messages": messages,
                    "stream": True
                },
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://comodo.dev", # Optional
                    "X-Title": "Comodo Editor" # Optional
                },
                stream=True,
                timeout=120
            )

            if resp.status_code != 200:
                yield f"API Error: {resp.status_code} - {resp.text}"
                return

            full_reply = ""
            for line in resp.iter_lines():
                if line:
                    line_text = line.decode('utf-8')
                    if line_text.startswith("data: "):
                        data_str = line_text[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            data_json = json.loads(data_str)
                            delta = data_json['choices'][0]['delta'].get('content', '')
                            if delta:
                                full_reply += delta
                                yield delta
                        except:
                            continue

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
    print(f"  🚀 Comodo Mobile System Ready")
    print(f"  🔗 Local: http://127.0.0.1:5000")
    print(f"  🔗 Network: http://0.0.0.0:5000")
    print(f"{'='*40}\n")

    # threaded=True: Isse mobile browser hang nahi hoga multiple requests par
    # host='0.0.0.0': Isse phone ke hotspot ya wifi network par bhi access ho sakega
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)