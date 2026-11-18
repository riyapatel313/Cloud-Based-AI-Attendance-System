// Shared helpers used by every page.
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function logout() { localStorage.clear(); location.href = '/login'; }

async function api(path, { method = 'GET', body, raw = false } = {}) {
  const headers = {};
  const token = localStorage.getItem('token');
  if (token) headers.Authorization = 'Bearer ' + token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch('/api' + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw new Error('Cannot reach the server. Is it still running?');
  }
  if (res.status === 401 && !path.startsWith('/auth/login')) { logout(); throw new Error('Signed out'); }
  if (!res.ok) {
    let msg = 'Something went wrong (' + res.status + ').';
    try {
      const j = await res.json();
      msg = Array.isArray(j.detail) ? j.detail.map((d) => d.msg.replace('Value error, ', '')).join('. ') : (j.detail || msg);
    } catch { /* keep default */ }
    throw new Error(msg);
  }
  return raw ? res : res.json();
}

function toast(msg, kind = '') {
  let box = $('#toasts');
  if (!box) { box = document.createElement('div'); box.id = 'toasts'; document.body.appendChild(box); }
  const t = document.createElement('div');
  t.className = 'toast ' + kind; t.textContent = msg; box.appendChild(t);
  setTimeout(() => t.remove(), kind === 'bad' ? 6000 : 3500);
}

function requireRole(role) {
  if (!localStorage.getItem('token')) { location.href = '/login'; return false; }
  if (localStorage.getItem('role') !== role) { location.href = '/' + localStorage.getItem('role'); return false; }
  return true;
}

function fmtDate(iso) { return new Date(iso + (iso.length === 10 ? 'T00:00:00' : '')).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
function fmtTime(iso) { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
function chip(status) {
  const label = { present: 'Present', late: 'Late', absent: 'Absent', not_marked: 'Not marked' }[status] || status;
  return `<span class="chip ${status}">${label}</span>`;
}
function pctCell(p) {
  const cls = p < 60 ? 'low' : p < 75 ? 'mid' : '';
  return `<div class="pcell"><b>${p}%</b><div class="bar ${cls}"><i style="width:${p}%"></i></div></div>`;
}

class Camera {
  constructor(video) { this.video = video; this.stream = null; }
  async start() {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('This browser has no camera access. Open the app at http://127.0.0.1:8000 or http://localhost:8000.');
    this.stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 960 }, height: { ideal: 720 }, facingMode: 'user' }, audio: false });
    this.video.srcObject = this.stream;
    await this.video.play();
  }
  stop() { this.stream?.getTracks().forEach((t) => t.stop()); this.stream = null; this.video.srcObject = null; }
  get active() { return !!this.stream && this.video.videoWidth > 0; }
  capture(maxW = 640) {
    const v = this.video, s = Math.min(1, maxW / v.videoWidth);
    const c = document.createElement('canvas');
    c.width = Math.round(v.videoWidth * s); c.height = Math.round(v.videoHeight * s);
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.85);
  }
}

function fileToDataURL(file, maxW = 640) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(1, maxW / img.width), c = document.createElement('canvas');
      c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      resolve(c.toDataURL('image/jpeg', 0.88));
    };
    img.onerror = () => reject(new Error('Could not open ' + file.name));
    img.src = URL.createObjectURL(file);
  });
}
