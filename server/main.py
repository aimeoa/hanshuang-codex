"""
瀵掗湝鐮寸敳宸ュ叿 - 鏈嶅姟绔?API
FastAPI + SQLite
浠呬繚鐣欙細妫€鏌ユ洿鏂?+ 鍙戝竷鏂扮増鏈?+ 绠＄悊鍚庡彴
"""
from fastapi import FastAPI, Form, HTTPException, Header
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import os

app = FastAPI(title='瀵掗湝鐮寸敳宸ュ叿 API')

app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

DB_PATH = os.path.join(os.path.dirname(__file__), 'hanshuang.db')
ADMIN_KEY = os.getenv('HANSHUANG_ADMIN_KEY', 'change-me')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version TEXT NOT NULL,
        download_url TEXT,
        changelog TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

@app.on_event('startup')
async def startup():
    init_db()

@app.get('/api/check_update')
async def check_update(version: str = '1.0.0'):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT version, download_url, changelog FROM versions ORDER BY created_at DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    if row:
        latest, url, changelog = row
        return JSONResponse({'latest_version': latest, 'download_url': url or '', 'changelog': changelog or ''})
    return JSONResponse({'latest_version': version, 'download_url': '', 'changelog': ''})

@app.post('/api/admin/push_version')
async def push_version(version: str = Form(...), download_url: str = Form(''), changelog: str = Form(''), x_admin_key: str = Header(default='')):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail='Forbidden')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO versions (version, download_url, changelog) VALUES (?,?,?)', (version, download_url, changelog))
    conn.commit()
    conn.close()
    return JSONResponse({'success': True, 'message': '鍙戝竷鎴愬姛'})

@app.get('/api/admin/versions')
async def list_versions(x_admin_key: str = Header(default='')):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail='Forbidden')
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT version, download_url, changelog, created_at FROM versions ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()
    versions = [{'version': r[0], 'download_url': r[1], 'changelog': r[2], 'created_at': r[3]} for r in rows]
    return JSONResponse({'versions': versions})

@app.get('/admin', response_class=HTMLResponse)
async def admin_panel():
    html_path = os.path.join(os.path.dirname(__file__), 'admin.html')
    if os.path.exists(html_path):
        with open(html_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(f.read())
    return HTMLResponse('<h1>admin.html not found</h1>')
