if (requireRole('teacher')) init();

function init() {
  const state = { courses: [], students: [], session: null, cam: null, scanning: false, busy: false, timer: null, view: 'overview' };
  $('#who').textContent = localStorage.getItem('name') || '';
  $('#btn-out').onclick = logout;

  // ---------- navigation ----------
  const loaders = { overview: loadOverview, classes: loadClasses, students: loadStudents, attendance: loadAttendanceSetup, reports: loadReportsSetup };
  function go(view) {
    if (state.view === 'attendance' && view !== 'attendance') stopCamera(); // camera only runs on its own page
    state.view = view;
    $$('.nav button').forEach((b) => b.classList.toggle('on', b.dataset.view === view));
    $$('.view').forEach((v) => v.classList.toggle('hidden', v.id !== 'view-' + view));
    loaders[view]().catch((e) => toast(e.message, 'bad'));
  }
  $$('.nav button').forEach((b) => (b.onclick = () => go(b.dataset.view)));

  async function fetchCourses() { state.courses = await api('/courses'); }
  async function fetchStudents() { state.students = await api('/students'); }
  const courseOptions = () => state.courses.map((c) => `<option value="${c.id}">${esc(c.code)} - ${esc(c.name)}</option>`).join('');

  // ---------- overview ----------
  async function loadOverview() {
    const [s, sessions] = await Promise.all([api('/reports/summary'), api('/sessions?limit=8')]);
    const eng = s.engine;
    $('#engine-banner').innerHTML = eng.error
      ? `<div class="banner bad"><b>Face recognition is not ready.</b> ${esc(eng.error)}</div>`
      : !eng.ready ? '<div class="banner">Face recognition is loading (first run downloads about 40 MB). Reload in a minute.</div>'
      : /dev/.test(eng.name) ? '<div class="banner">Running the test face engine. It is not accurate. Set FACE_ENGINE=opencv in .env for real use.</div>' : '';
    $('#stats').innerHTML = `
      <div class="stat"><b>${s.courses}</b><span class="muted">Classes</span></div>
      <div class="stat"><b>${s.students}</b><span class="muted">Students</span></div>
      <div class="stat"><b>${s.face_registered}</b><span class="muted">Faces registered</span></div>
      <div class="stat"><b>${s.present_today}</b><span class="muted">Present today (${s.sessions_today} session${s.sessions_today === 1 ? '' : 's'})</span></div>`;
    $('#recent-sessions').innerHTML = sessions.length
      ? `<table><thead><tr><th>Date</th><th>Class</th><th>Present</th><th>Status</th></tr></thead><tbody>${sessions.map((x) =>
        `<tr><td>${fmtDate(x.date)}</td><td><b>${esc(x.course_code)}</b> ${esc(x.course_name)}</td><td>${x.present_count} of ${x.enrolled_count}</td><td>${x.ended_at ? 'Finished' : 'Open'}</td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">No sessions yet. Create a class, add students, register their faces, then take attendance.</div>';
  }

  // ---------- classes ----------
  async function loadClasses() {
    await fetchCourses();
    $('#course-list').innerHTML = state.courses.length
      ? `<table><thead><tr><th>Code</th><th>Name</th><th>Room</th><th>Students</th><th></th></tr></thead><tbody>${state.courses.map((c) =>
        `<tr><td><b>${esc(c.code)}</b></td><td>${esc(c.name)}</td><td>${esc(c.room)}</td><td>${c.student_count}</td>
         <td class="actions"><button class="ghost sm" data-enrol="${c.id}">Choose students</button><button class="danger sm" data-del="${c.id}">Delete</button></td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">No classes yet. Add your first class above.</div>';
  }
  $('#course-form').onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api('/courses', { method: 'POST', body: { code: $('#c-code').value, name: $('#c-name').value, room: $('#c-room').value } });
      e.target.reset(); toast('Class added', 'ok'); loadClasses();
    } catch (err) { toast(err.message, 'bad'); }
  };
  $('#course-list').onclick = async (e) => {
    const enrol = e.target.dataset.enrol, del = e.target.dataset.del;
    if (del && confirm('Delete this class and all its attendance records?')) {
      try { await api('/courses/' + del, { method: 'DELETE' }); toast('Class deleted', 'ok'); loadClasses(); } catch (err) { toast(err.message, 'bad'); }
    }
    if (enrol) openEnrol(Number(enrol));
  };

  const enrolDlg = $('#enrol-dialog'); let enrolCourse = null;
  async function openEnrol(courseId) {
    enrolCourse = state.courses.find((c) => c.id === courseId);
    try {
      await fetchStudents();
      const { student_ids } = await api(`/courses/${courseId}/students`);
      $('#enrol-title').textContent = `Students in ${enrolCourse.code}`;
      $('#enrol-list').innerHTML = state.students.length
        ? state.students.map((s) => `<label><input type="checkbox" value="${s.id}" ${student_ids.includes(s.id) ? 'checked' : ''}> ${esc(s.full_name)} <span class="muted small">${esc(s.student_code)}</span></label>`).join('')
        : '<div class="empty">Add students first (Students page).</div>';
      enrolDlg.showModal();
    } catch (err) { toast(err.message, 'bad'); }
  }
  $('#enrol-cancel').onclick = () => enrolDlg.close();
  $('#enrol-save').onclick = async () => {
    const ids = $$('#enrol-list input:checked').map((i) => Number(i.value));
    try { await api(`/courses/${enrolCourse.id}/students`, { method: 'PUT', body: { student_ids: ids } }); toast(`${ids.length} students saved`, 'ok'); enrolDlg.close(); loadClasses(); }
    catch (err) { toast(err.message, 'bad'); }
  };

  // ---------- students ----------
  function renderStudents() {
    const q = $('#s-search').value.trim().toLowerCase();
    const rows = state.students.filter((s) => !q || (s.full_name + ' ' + s.student_code).toLowerCase().includes(q));
    $('#student-list').innerHTML = rows.length
      ? `<table><thead><tr><th>ID</th><th>Name</th><th>Department</th><th>Face data</th><th></th></tr></thead><tbody>${rows.map((s) =>
        `<tr><td><b>${esc(s.student_code)}</b></td><td>${esc(s.full_name)}<div class="muted small">${esc(s.email)}</div></td><td>${esc(s.department)}</td>
         <td>${s.face_count ? `<span class="chip present">${s.face_count} photo${s.face_count === 1 ? '' : 's'}</span>` : '<span class="chip absent">Not registered</span>'}</td>
         <td class="actions"><button class="sm" data-face="${s.id}">${s.face_count ? 'Add photos' : 'Register face'}</button>
         ${s.face_count ? `<button class="ghost sm" data-clear="${s.id}">Clear faces</button>` : ''}<button class="danger sm" data-del="${s.id}">Delete</button></td></tr>`).join('')}</tbody></table>`
      : `<div class="empty">${state.students.length ? 'No match.' : 'No students yet. Add one above.'}</div>`;
  }
  async function loadStudents() { await fetchStudents(); renderStudents(); }
  $('#s-search').oninput = renderStudents;
  $('#student-form').onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api('/students', { method: 'POST', body: { student_code: $('#s-code').value, full_name: $('#s-name').value, email: $('#s-email').value, department: $('#s-dept').value, password: $('#s-pass').value } });
      e.target.reset(); toast('Student added. Now register their face.', 'ok'); loadStudents();
    } catch (err) { toast(err.message, 'bad'); }
  };
  $('#student-list').onclick = async (e) => {
    const { face, clear, del } = e.target.dataset;
    try {
      if (face) openFace(state.students.find((s) => s.id === Number(face)));
      if (clear && confirm('Remove all face photos for this student?')) { await api(`/students/${clear}/faces`, { method: 'DELETE' }); toast('Face data removed', 'ok'); loadStudents(); }
      if (del && confirm('Delete this student and all their attendance records?')) { await api('/students/' + del, { method: 'DELETE' }); toast('Student deleted', 'ok'); loadStudents(); }
    } catch (err) { toast(err.message, 'bad'); }
  };

  // face registration dialog
  const faceDlg = $('#face-dialog'); let faceCam = null, faceShots = [], faceStudent = null;
  function renderShots() {
    $('#face-shots').innerHTML = faceShots.map((s) => `<img src="${s}" alt="Captured photo">`).join('') || '<span class="muted small">No photos yet</span>';
    $('#face-save').disabled = faceShots.length === 0;
  }
  async function openFace(student) {
    faceStudent = student; faceShots = []; renderShots();
    $('#face-title').textContent = 'Register face: ' + student.full_name;
    faceDlg.showModal();
    faceCam = new Camera($('#face-video'));
    try { await faceCam.start(); } catch (err) { toast('Camera unavailable: ' + err.message + ' You can upload photos instead.', 'bad'); }
  }
  function closeFace() { faceCam?.stop(); faceCam = null; if (faceDlg.open) faceDlg.close(); }
  faceDlg.addEventListener('close', () => { faceCam?.stop(); faceCam = null; });
  $('#face-cancel').onclick = closeFace;
  $('#face-capture').onclick = () => {
    if (!faceCam?.active) return toast('Camera is not running. Upload photos instead.', 'bad');
    if (faceShots.length >= 5) return toast('5 photos is enough', '');
    faceShots.push(faceCam.capture(640)); renderShots();
  };
  $('#face-upload-btn').onclick = () => $('#face-files').click();
  $('#face-files').onchange = async (e) => {
    try { for (const f of [...e.target.files].slice(0, 5 - faceShots.length)) faceShots.push(await fileToDataURL(f)); renderShots(); }
    catch (err) { toast(err.message, 'bad'); }
    e.target.value = '';
  };
  $('#face-save').onclick = async () => {
    const btn = $('#face-save'); btn.disabled = true; btn.textContent = 'Saving...';
    try {
      const r = await api(`/students/${faceStudent.id}/faces`, { method: 'POST', body: { images: faceShots } });
      r.problems.forEach((p) => toast(p, 'bad'));
      if (r.saved) { toast(`${r.saved} photo${r.saved === 1 ? '' : 's'} saved for ${faceStudent.full_name}`, 'ok'); closeFace(); loadStudents(); }
      else btn.disabled = false;
    } catch (err) { toast(err.message, 'bad'); btn.disabled = false; }
    btn.textContent = 'Save face data';
  };

  // ---------- live attendance ----------
  const video = $('#a-video'), overlay = $('#a-overlay');
  async function loadAttendanceSetup() {
    await fetchCourses();
    $('#a-course').innerHTML = state.courses.length ? courseOptions() : '<option value="">No classes yet</option>';
    $('#a-start').disabled = !state.courses.length;
  }
  function renderRoster(data) {
    state.session = data.session;
    const s = data.session, ended = !!s.ended_at;
    $('#a-title').textContent = `${s.course_code} · ${fmtDate(s.date)}`;
    $('#a-counter').textContent = `${s.present_count}/${s.enrolled_count}`;
    $('#a-roster').innerHTML = `<table><thead><tr><th>Student</th><th>Status</th><th></th></tr></thead><tbody>${data.roster.map((r) =>
      `<tr><td>${esc(r.full_name)}<div class="muted small">${esc(r.student_code)}${r.marked_by === 'face' ? ` · camera ${Math.round(r.confidence * 100)}%` : r.marked_by === 'manual' ? ' · manual' : ''}</div></td>
       <td>${chip(r.status)}</td>
       <td><select data-mark="${r.student_id}" aria-label="Set status for ${esc(r.full_name)}"><option value="">Set...</option><option value="present">Present</option><option value="late">Late</option><option value="absent">Absent</option></select></td></tr>`).join('')}</tbody></table>`;
    $('#a-end').classList.toggle('hidden', ended);
    $('#a-scan').classList.toggle('hidden', ended);
  }
  $('#a-roster').onchange = async (e) => {
    const sid = e.target.dataset.mark; if (!sid || !e.target.value) return;
    try { renderRoster(await api(`/sessions/${state.session.id}/mark`, { method: 'POST', body: { student_id: Number(sid), status: e.target.value } })); }
    catch (err) { toast(err.message, 'bad'); }
  };

  $('#a-start').onclick = async () => {
    const id = Number($('#a-course').value); if (!id) return;
    try {
      renderRoster(await api('/sessions/start', { method: 'POST', body: { course_id: id } }));
      $('#live').classList.remove('hidden'); $('#a-hint').classList.add('hidden'); setScanning(false);
      $('#cam-note').classList.remove('hidden'); $('#cam-note').textContent = 'Starting camera...';
      state.cam = new Camera(video);
      try { await state.cam.start(); $('#cam-note').classList.add('hidden'); }
      catch (err) { $('#cam-note').textContent = 'Camera unavailable: ' + err.message; }
    } catch (err) { toast(err.message, 'bad'); }
  };
  function stopCamera() { setScanning(false); state.cam?.stop(); state.cam = null; clearOverlay(); }
  function clearOverlay() { overlay.getContext('2d').clearRect(0, 0, overlay.width, overlay.height); }

  function setScanning(on) {
    state.scanning = on; clearTimeout(state.timer);
    $('#cam').classList.toggle('scanning', on);
    $('#a-scan').textContent = on ? 'Pause scanning' : 'Start scanning';
    $('#scan-note').textContent = on ? 'Scanning... students are marked present automatically.' : 'Press "Start scanning" and let students look at the camera.';
    if (on) scanLoop(); else clearOverlay();
  }
  $('#a-scan').onclick = () => { if (!state.cam?.active) return toast('Camera is not running.', 'bad'); setScanning(!state.scanning); };

  async function scanLoop() {
    if (!state.scanning || state.busy || !state.cam?.active) return;
    state.busy = true;
    try {
      const r = await api(`/sessions/${state.session.id}/recognize`, { method: 'POST', body: { image: state.cam.capture(640) } });
      drawFaces(r.faces);
      if (r.newly_marked) {
        r.faces.filter((f) => f.status === 'marked').forEach((f) => toast(`${f.name} marked present`, 'ok'));
        renderRoster(await api('/sessions/' + state.session.id));
      }
    } catch (err) { toast(err.message, 'bad'); setScanning(false); }
    state.busy = false;
    if (state.scanning) state.timer = setTimeout(scanLoop, 900);
  }

  const COLORS = { marked: '#2FB36D', already: '#2FB36D', unknown: '#D8453B', not_in_class: '#E0A21B' };
  const LABELS = { marked: 'Present', already: 'Already marked', unknown: 'Unknown', not_in_class: 'Not in this class' };
  function drawFaces(faces) {
    const box = overlay.getBoundingClientRect(); overlay.width = box.width; overlay.height = box.height;
    const ctx = overlay.getContext('2d'); ctx.clearRect(0, 0, overlay.width, overlay.height);
    // the video uses object-fit: cover, so map frame coordinates to what is actually shown
    const vw = video.videoWidth, vh = video.videoHeight, scale = Math.max(box.width / vw, box.height / vh);
    const offX = (box.width - vw * scale) / 2, offY = (box.height - vh * scale) / 2;
    ctx.lineWidth = 3; ctx.font = '600 14px "Segoe UI",system-ui,sans-serif';
    for (const f of faces) {
      const x = f.x * vw * scale + offX, y = f.y * vh * scale + offY, w = f.w * vw * scale, h = f.h * vh * scale;
      const color = COLORS[f.status];
      ctx.strokeStyle = color; ctx.strokeRect(x, y, w, h);
      const text = `${f.name} · ${LABELS[f.status]}`, tw = ctx.measureText(text).width + 14, ty = Math.max(y - 26, 0);
      ctx.fillStyle = color; ctx.fillRect(x - 1, ty, tw, 26);
      ctx.fillStyle = '#fff'; ctx.fillText(text, x + 6, ty + 18);
    }
  }

  $('#a-end').onclick = async () => {
    if (!confirm('End this session? Students not marked present will be recorded as absent.')) return;
    setScanning(false);
    try { renderRoster(await api(`/sessions/${state.session.id}/end`, { method: 'POST' })); stopCamera(); toast('Session finished', 'ok'); }
    catch (err) { toast(err.message, 'bad'); }
  };
  window.addEventListener('beforeunload', () => state.cam?.stop());

  // ---------- reports ----------
  async function loadReportsSetup() {
    await fetchCourses();
    $('#r-course').innerHTML = state.courses.length ? courseOptions() : '<option value="">No classes yet</option>';
    if (state.courses.length) await loadReport(); else { $('#r-students').innerHTML = '<div class="empty">Create a class first.</div>'; $('#r-sessions').innerHTML = ''; }
  }
  async function loadReport() {
    const id = $('#r-course').value; if (!id) return;
    const r = await api('/reports/course/' + id);
    $('#r-students').innerHTML = r.students.length
      ? `<table><thead><tr><th>Student</th><th>Present</th><th>Late</th><th>Absent</th><th>Attendance</th></tr></thead><tbody>${r.students.map((s) =>
        `<tr><td>${esc(s.full_name)}<div class="muted small">${esc(s.student_code)}</div></td><td>${s.present}</td><td>${s.late}</td><td>${s.absent}</td><td>${r.total_sessions ? pctCell(s.percentage) : '<span class="muted">No classes yet</span>'}</td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">No students in this class yet.</div>';
    $('#r-sessions').innerHTML = r.sessions.length
      ? `<table><thead><tr><th>Date</th><th>Present</th><th></th></tr></thead><tbody>${r.sessions.map((s) =>
        `<tr><td>${fmtDate(s.date)}</td><td>${s.present} of ${s.enrolled}</td><td class="actions"><button class="danger sm" data-delsession="${s.id}">Delete</button></td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">No sessions have been held yet.</div>';
  }
  $('#r-course').onchange = () => loadReport().catch((e) => toast(e.message, 'bad'));
  $('#r-sessions').onclick = async (e) => {
    const id = e.target.dataset.delsession;
    if (id && confirm('Delete this session and its records?')) {
      try { await api('/sessions/' + id, { method: 'DELETE' }); loadReport(); } catch (err) { toast(err.message, 'bad'); }
    }
  };
  async function download(detail) {
    const id = $('#r-course').value; if (!id) return;
    try {
      const res = await api(`/reports/course/${id}/export.csv?detail=${detail}`, { raw: true });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(await res.blob());
      a.download = (res.headers.get('Content-Disposition') || '').match(/filename="(.+)"/)?.[1] || 'attendance.csv';
      a.click(); URL.revokeObjectURL(a.href);
    } catch (err) { toast(err.message, 'bad'); }
  }
  $('#r-csv').onclick = () => download(false);
  $('#r-csv-detail').onclick = () => download(true);

  go('overview');
}
