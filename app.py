import os, json, sqlite3, requests
from flask import Flask, request, jsonify, render_template_string, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "comodo-pro-final-v4"
DB = "comodo.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    c = get_db()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password_hash TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, user_id INTEGER)')
    c.execute('CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, name TEXT, content TEXT, UNIQUE(project_id, name))')
    c.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)')
    c.commit()
    c.close()

init_db()

@app.route("/")
def index(): return render_template_string(HTML)

@app.route("/api/auth/register", methods=["POST"])
def register():
    d = request.json
    u, p = d.get("username"), d.get("password")
    c = get_db()
    try:
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (u, generate_password_hash(p)))
        c.commit()
        return jsonify({"success": True})
    except: return jsonify({"error": "User already exists"}), 400
    finally: c.close()

@app.route("/api/auth/login", methods=["POST"])
def login():
    d = request.json
    u, p = d.get("username"), d.get("password")
    c = get_db()
    user = c.execute("SELECT * FROM users WHERE username = ?", (u,)).fetchone()
    c.close()
    if user and check_password_hash(user["password_hash"], p):
        session["user_id"] = user["id"]
        return jsonify({"success": True})
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/auth/logout", methods=["POST"])
def logout(): session.clear(); return jsonify({"success": True})

@app.route("/api/auth/me")
def me():
    if "user_id" in session: return jsonify({"id": session["user_id"]})
    return jsonify(None)

@app.route("/api/projects", methods=["GET", "POST"])
def projects():
    if "user_id" not in session: return jsonify({"error": "Unauthorized"}), 401
    c = get_db()
    if request.method == "POST":
        n = request.json.get("name")
        cur = c.cursor()
        cur.execute("INSERT INTO projects (name, user_id) VALUES (?, ?)", (n, session["user_id"]))
        pid = cur.lastrowid
        c.commit()
        c.close()
        return jsonify({"id": pid, "name": n})
    else:
        ps = c.execute("SELECT * FROM projects WHERE user_id = ?", (session["user_id"],)).fetchall()
        c.close()
        return jsonify([dict(p) for p in ps])

@app.route("/api/projects/<int:pid>/files", methods=["GET", "POST"])
def files(pid):
    if "user_id" not in session: return jsonify(None), 401
    c = get_db()
    if request.method == "POST":
        n, cont = request.json.get("name"), request.json.get("content")
        c.execute("INSERT OR REPLACE INTO files (project_id, name, content) VALUES (?, ?, ?)", (pid, n, cont))
        c.commit()
        c.close()
        return jsonify({"success": True})
    else:
        fs = c.execute("SELECT * FROM files WHERE project_id = ?", (pid,)).fetchall()
        c.close()
        return jsonify([dict(f) for f in fs])

@app.route("/api/projects/<int:pid>/messages", methods=["GET", "POST"])
def messages(pid):
    if "user_id" not in session: return jsonify(None), 401
    c = get_db()
    if request.method == "POST":
        c.execute("INSERT INTO messages (project_id, role, content) VALUES (?, ?, ?)", (pid, request.json.get("role"), request.json.get("content")))
        c.commit()
        c.close()
        return jsonify({"success": True})
    else:
        ms = c.execute("SELECT * FROM messages WHERE project_id = ? ORDER BY timestamp ASC", (pid,)).fetchall()
        c.close()
        return jsonify([dict(m) for m in ms])

@app.route("/api/ai/chat", methods=["POST"])
def ai():
    if "user_id" not in session: return jsonify(None), 401
    res = requests.post("https://aimodelapi.onrender.com/v1/chat/completions",
                        json={"model": "kimi-k2-thinking", "messages": request.json.get("messages")},
                        headers={"Authorization": "Bearer devx-m1lo3nnwb5msbkpod3w1qg76hin220ze"})
    return jsonify(res.json())

HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"><title>Comodo Pro</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
    <style>
        :root{--bg:#09090b;--s1:#121216;--s2:#1c1c21;--b1:#2e2e36;--t1:#ededed;--t2:#a1a1aa;--ac:#6366f1;}
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:sans-serif;background:var(--bg);color:var(--t1);height:100dvh;display:flex;flex-direction:column;overflow:hidden}
        .bar{background:var(--s1);border-bottom:1px solid var(--b1);height:48px;display:flex;align-items:center;padding:0 12px;gap:12px;z-index:50}
        .tabs{display:flex;background:var(--s1);border-bottom:1px solid var(--b1)}
        .tab{flex:1;height:40px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;color:var(--t2);cursor:pointer}
        .tab.on{color:var(--ac);border-bottom:2px solid var(--ac);background:rgba(99,102,241,0.1)}
        .main{flex:1;position:relative}.page{position:absolute;inset:0;display:none;flex-direction:column}.page.on{display:flex}
        .chat{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:16px}
        .chat-bar{padding:12px;border-top:1px solid var(--b1)}.row{display:flex;gap:8px;background:var(--s2);padding:8px;border-radius:10px}
        textarea{flex:1;background:none;border:none;outline:none;color:#fff;resize:none;font-family:inherit}
        .auth-page{position:fixed;inset:0;background:var(--bg);z-index:100;display:none;align-items:center;justify-content:center}
        .auth-page.on{display:flex}.auth-card{width:320px;background:var(--s1);padding:32px;border-radius:16px;border:1px solid var(--b1)}
        input,button{width:100%;padding:10px;margin-bottom:12px;border-radius:8px;border:none;outline:none}
        input{background:var(--s2);color:#fff}button{background:var(--ac);color:#fff;font-weight:700;cursor:pointer}
        .welcome{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:20px}
        .dash-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:24px;width:100%}
        .dcard{background:var(--s2);padding:16px;border-radius:12px;cursor:pointer;border:1px solid var(--b1);text-align:center}
        .file-panel{width:240px;background:var(--s1);border-right:1px solid var(--b1);display:flex;flex-direction:column}
        .tree-item{padding:8px 12px;font-size:13px;cursor:pointer}.tree-item.sel{color:var(--ac);background:rgba(99,102,241,0.1)}
        .editor-wrap{flex:1;position:relative;background:#0d1117;overflow:hidden}
        .ce-edit{position:absolute;inset:0;padding:16px;padding-left:48px;background:transparent;color:transparent;caret-color:var(--ac);font-family:monospace;font-size:13px;line-height:1.5;border:none;outline:none;white-space:pre;z-index:2;overflow:auto}
        .ce-code{position:absolute;inset:0;padding:16px;padding-left:48px;font-family:monospace;font-size:13px;line-height:1.5;color:#c9d1d9;white-space:pre;overflow:auto}
        b{color:#ff7b72;font-weight:400} em{color:#7ee787;font-style:normal}
    </style>
</head>
<body>
    <div class="auth-page" id="authPage">
        <div class="auth-card">
            <h2 style="margin-bottom:20px;text-align:center">Comodo Pro</h2>
            <div id="authErr" style="color:#ef4444;font-size:12px;margin-bottom:12px;display:none"></div>
            <input id="au" placeholder="Username">
            <input id="ap" type="password" placeholder="Password">
            <button id="authBtn" onclick="doAuth()">Login</button>
            <p style="text-align:center;font-size:12px;margin-top:12px;color:var(--t2)">Need account? <a href="#" onclick="toggleAuthMode()" id="authModeLink" style="color:var(--ac)">Register</a></p>
        </div>
    </div>
    <div class="bar">
        <div style="font-weight:800;font-size:18px"><span>Co</span>modo</div>
        <div id="pname" style="flex:1;text-align:center;font-size:12px;font-weight:600;color:var(--ac)"></div>
        <button onclick="logout()" style="width:auto;padding:6px 12px;background:var(--s2)">Logout</button>
    </div>
    <div class="tabs">
        <div class="tab on" id="tAgent" onclick="go('agent')">Agent</div>
        <div class="tab" id="tCode" onclick="go('code')">Code</div>
        <div class="tab" id="tPreview" onclick="go('preview')">Preview</div>
    </div>
    <div class="main">
        <div class="page on" id="pgAgent">
            <div class="chat" id="chatArea"></div>
            <div class="chat-bar"><div class="row"><textarea id="inp" placeholder="Vibe here..."></textarea><button onclick="send()" style="width:40px">Go</button></div></div>
            <div id="lock" style="position:absolute;inset:0;background:var(--bg);display:none;flex-direction:column;align-items:center;justify-content:center">
                <p style="color:var(--t2);margin-bottom:12px">Create a project to start</p>
                <input id="npInp" placeholder="Project name..." style="width:240px">
                <button onclick="createP()" style="width:240px">New Project</button>
            </div>
        </div>
        <div class="page" id="pgCode" style="flex-direction:row">
            <div class="file-panel">
                <div style="padding:12px;font-weight:700;border-bottom:1px solid var(--b1)">FILES <button onclick="newF()" style="float:right;width:24px;padding:0">+</button></div>
                <div id="fList"></div>
            </div>
            <div class="editor-wrap">
                <div class="ce-code" id="cCode"></div>
                <textarea class="ce-edit" id="cEdit" oninput="onEd()" onscroll="document.getElementById('cCode').scrollTop=this.scrollTop"></textarea>
            </div>
        </div>
        <div class="page" id="pgPreview"><iframe id="pv" style="flex:1;border:none;background:#fff" sandbox="allow-scripts allow-same-origin"></iframe></div>
    </div>
<script>
let CID=null, PF={}, AF='', MODE='login';
const api = {
    r: async (u,m='GET',b=null)=>{
        try {
            const r=await fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):null});
            if(r.status===401){showA();return null;} return r.json();
        } catch(e) { return {error:e.message}; }
    },
    me:()=>api.r('/api/auth/me'),
    login:(u,p)=>api.r('/api/auth/login','POST',{username:u,password:p}),
    reg:(u,p)=>api.r('/api/auth/register','POST',{username:u,password:p}),
    logout:()=>api.r('/api/auth/logout','POST'),
    listP:()=>api.r('/api/projects'),
    createP:(n)=>api.r('/api/projects','POST',{name:n}),
    getF:(id)=>api.r(`/api/projects/${id}/files`),
    saveF:(id,n,c)=>api.r(`/api/projects/${id}/files`,'POST',{name:n,content:c}),
    getM:(id)=>api.r(`/api/projects/${id}/messages`),
    addM:(id,r,c)=>api.r(`/api/projects/${id}/messages`,'POST',{role:r,content:c}),
    ai:(m)=>api.r('/api/ai/chat','POST',{messages:m})
};
function showA(){document.getElementById('authPage').classList.add('on')}
function hideA(){document.getElementById('authPage').classList.remove('on')}
function toggleAuthMode(){
    MODE=MODE==='login'?'reg':'login';
    document.getElementById('authBtn').innerText=MODE==='login'?'Login':'Register';
    document.getElementById('authModeLink').innerText=MODE==='login'?'Register':'Login';
    console.log("MODE switched to", MODE);
}
async function doAuth(){
    const u=document.getElementById('au').value, p=document.getElementById('ap').value, err=document.getElementById('authErr');
    const r=await (MODE==='login'?api.login(u,p):api.reg(u,p));
    if(r&&r.success){
        if(MODE==='login'){hideA();loadAll();}
        else{
            MODE='login';
            document.getElementById('authBtn').innerText='Login';
            document.getElementById('authModeLink').innerText='Register';
            err.innerText="Registered! Please login.";err.style.display='block';err.style.color='#22c55e';
            console.log("Registration successful, switched to login mode");
        }
    }
    else{ err.innerText=r?r.error:"Error";err.style.display='block';err.style.color='#ef4444'; }
}
async function logout(){await api.logout();CID=null;showA();}
async function loadAll(){
    const ps=await api.listP(); if(!ps)return;
    if(!CID) renderWelcome(ps); else selectP(CID, document.getElementById('pname').innerText);
}
function renderWelcome(ps){
    const c=document.getElementById('chatArea');
    let h='<div class="welcome"><h2>Welcome to Comodo Pro</h2><div class="dash-grid">';
    ps.forEach(p=>h+=`<div class="dcard" onclick="selectP(${p.id},'${p.name}')">${p.name}</div>`);
    c.innerHTML=h+'</div></div>'; document.getElementById('lock').style.display='flex';
}
async function createP(){const n=document.getElementById('npInp').value;if(n){const r=await api.createP(n);selectP(r.id,r.name);}}
async function selectP(id,name){
    CID=id;document.getElementById('pname').innerText=name;document.getElementById('lock').style.display='none';
    const ms=await api.getM(id);document.getElementById('chatArea').innerHTML='';
    ms.forEach(m=>addMsgUI(m.role,m.content));
    const fs=await api.getF(id);PF={};fs.forEach(f=>PF[f.name]=f.content);
    refTree();if(Object.keys(PF).length)showF(Object.keys(PF)[0]);
}
async function send(){
    const i=document.getElementById('inp'),t=i.value;if(!t||!CID)return;i.value='';
    addMsgUI('user',t);await api.addM(CID,'user',t);
    let m=[{role:'system',content:'Output files using ---FILE:name---content---ENDFILE---.'}];
    m.push({role:'user',content:t});
    const r=await api.ai(m);if(r&&r.choices){
        const ai=r.choices[0].message.content;const p=parseAI(ai);
        addMsgUI('assistant',p.expl);await api.addM(CID,'assistant',ai);
        for(let f in p.files){PF[f]=p.files[f];await api.saveF(CID,f,p.files[f]);}
        refTree();
    }
}
function parseAI(t){
    const rx=/---FILE:(.+?)---([\s\S]*?)---ENDFILE---/g;let m,files={},expl=t;
    while((m=rx.exec(t))!==null){files[m[1].trim()]=m[2].trim();expl=expl.replace(m[0],'');}
    return {expl:expl.trim(),files};
}
function addMsgUI(role,content){
    const c=document.getElementById('chatArea'),d=document.createElement('div');d.className='msg';
    d.innerHTML=`<div class="av ${role==='user'?'':'ai'}">${role==='user'?'U':'Co'}</div><div class="mmb"><div class="mt">${content.replace(/\n/g,'<br>')}</div></div>`;
    c.appendChild(d);c.scrollTop=c.scrollHeight;
}
function showF(n){
    AF=n;document.getElementById('cEdit').value=PF[n]||'';
    const tp=n.split('.').pop();let h=(PF[n]||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    if(tp==='js') h=h.replace(/\b(const|let|var|function|return|if|else|for|while|await|async)\b/g, '<b>$1</b>');
    else if(tp==='html') h=h.replace(/(&lt;\/?)([\w-]+)/g, '$1<em>$2</em>');
    document.getElementById('cCode').innerHTML=h.split('\n').map(l=>`<div style="min-height:1.5em">${l||' '}</div>`).join('');
    refTree();
}
function onEd(){const v=document.getElementById('cEdit').value;PF[AF]=v;showF(AF);clearTimeout(window.sv);window.sv=setTimeout(()=>api.saveF(CID,AF,v),1000);}
function refTree(){
    const l=document.getElementById('fList');l.innerHTML='';
    Object.keys(PF).forEach(f=>{
        const e=document.createElement('div');e.className='tree-item'+(f===AF?' sel':'');e.innerText=f;e.onclick=()=>showF(f);l.appendChild(e);
    });
}
async function newF(){const n=prompt('Name:');if(n){await api.saveF(CID,n,'');PF[n]='';refTree();showF(n);}}
function go(t){['agent','code','preview'].forEach(p=>{document.getElementById('pg'+p.charAt(0).toUpperCase()+p.slice(1)).classList.toggle('on',p===t);document.getElementById('t'+p.charAt(0).toUpperCase()+p.slice(1)).classList.toggle('on',p===t);});if(t==='preview')updP();}
function updP(){
    let h=PF['index.html']||'';Object.keys(PF).forEach(f=>{if(f.endsWith('.css'))h=h.replace('</head>',`<style>${PF[f]}</style></head>`);if(f.endsWith('.js')&&!f.endsWith('.html'))h=h.replace('</body>',`<script>${PF[f]}<\/script></body>`);});
    document.getElementById('pv').srcdoc=h;
}
(async()=>{const u=await api.me();if(u&&u.id){hideA();loadAll();}else{showA();}})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
