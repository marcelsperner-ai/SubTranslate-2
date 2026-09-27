let currentProjectId = null;
let pollInterval = null;

// DOM Elemente
const form = document.getElementById('newProjectForm');
const formSection = document.getElementById('uploadFormSection');
const startBtn = document.getElementById('startBtn');
const sidebarList = document.getElementById('sidebarProjectList');
const projectTitle = document.getElementById('currentProjectTitle');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const statusBadge = document.getElementById('statusBadge');
const logContainer = document.getElementById('logContainer');
const edtechZone = document.getElementById('edtechZone');
const btnNewProject = document.getElementById('btnNewProject');
const progressSection = document.getElementById('progressSection');
const btnPauseResume = document.getElementById('btnPauseResume');

// EdTech & Archiv Elemente
const edtechStatusBox = document.getElementById('edtechStatusBox');
const edtechActiveBox = document.getElementById('edtechActiveBox');
const btnValidateEdtech = document.getElementById('btnValidateEdtech');
const validationResult = document.getElementById('validationResult');
const btnGenerateEdtech = document.getElementById('btnGenerateEdtech');
const generateEdtechForm = document.getElementById('generateEdtechForm');
const edtechSettingsForm = document.getElementById('edtechSettingsForm');
const fixModal = new bootstrap.Modal(document.getElementById('fixModal'));
const btnApplyFix = document.getElementById('btnApplyFix');
const archiveTableBody = document.querySelector('#archiveModal tbody');

// 1. INITIALISIERUNG
document.addEventListener("DOMContentLoaded", () => {
    loadProjects();
});

function escapeHtml(unsafe) {
    return (unsafe || '').toString()
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

function openProjectFromElement(projectElement) {
    const projectId = Number(projectElement.dataset.projectId);
    if (!Number.isInteger(projectId)) return;

    loadProjectToMain(
        projectId,
        projectElement.dataset.projectTitle,
        projectElement.dataset.projectStatus
    );
}

sidebarList.addEventListener('click', (event) => {
    const projectElement = event.target.closest('.mini-project[data-project-id]');
    if (projectElement && sidebarList.contains(projectElement)) {
        openProjectFromElement(projectElement);
    }
});

sidebarList.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;

    const projectElement = event.target.closest('.mini-project[data-project-id]');
    if (projectElement && sidebarList.contains(projectElement)) {
        event.preventDefault();
        openProjectFromElement(projectElement);
    }
});

archiveTableBody.addEventListener('click', (event) => {
    const projectElement = event.target.closest('button[data-project-id]');
    if (projectElement && archiveTableBody.contains(projectElement)) {
        openProjectFromElement(projectElement);
    }
});

// 2. PROJEKTE & ARCHIV LADEN
async function loadProjects() {
    try {
        const res = await fetch('/api/projects');
        const projects = await res.json();
        
        sidebarList.innerHTML = '';
        archiveTableBody.innerHTML = '';
        
        projects.forEach(p => {
            let percent = p.total_lines > 0 ? Math.round((p.translated_lines / p.total_lines) * 100) : 0;
            let isActive = p.id === currentProjectId ? 'active' : '';
            let edtechDone = p.edtech_done ? 'done' : '';
            let transDone = p.status === 'abgeschlossen' ? 'done' : '';
            let progressColor = p.status === 'abgeschlossen' ? 'bg-success' : 'var(--purple-accent)';
            let name = p.original_filename.replace('.srt', '');
            let safeName = escapeHtml(name);
            let safeStatus = escapeHtml(p.status);

            // Sidebar Eintrag
            let sidebarHtml = `
            <div class="mini-project ${isActive}" data-project-id="${Number(p.id)}" data-project-title="${safeName}" data-project-status="${safeStatus}" role="button" tabindex="0">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="text-truncate" style="max-width: 70%;">
                        <div class="fw-bold fs-6 text-truncate">${safeName}</div>
                        <div class="text-muted" style="font-size: 0.8em;">Status: ${safeStatus}</div>
                    </div>
                    <div class="d-flex gap-1">
                        <span class="file-badge ${transDone}">SRT</span>
                        <span class="file-badge ${edtechDone}">ASS</span>
                    </div>
                </div>
                <div class="progress mt-2" style="height: 4px;">
                    <div class="progress-bar" style="background-color: ${progressColor}; width: ${percent}%;"></div>
                </div>
            </div>`;
            sidebarList.insertAdjacentHTML('beforeend', sidebarHtml);

            // Archiv Eintrag (nur Status-Farbe anpassen)
            let badgeClass = p.status === 'abgeschlossen' ? 'bg-success' : (p.status === 'laufend' ? 'bg-primary' : 'bg-secondary');
            let archiveHtml = `
            <tr>
                <td>${safeName}</td>
                <td><span class="badge ${badgeClass}">${safeStatus}</span></td>
                <td class="text-muted small">${new Date(p.last_updated).toLocaleString()}</td>
                <td><button class="btn btn-sm btn-outline-secondary" data-project-id="${Number(p.id)}" data-project-title="${safeName}" data-project-status="${safeStatus}" data-bs-dismiss="modal">Öffnen</button></td>
            </tr>`;
            archiveTableBody.insertAdjacentHTML('beforeend', archiveHtml);
        });
    } catch (e) {
        console.error("Fehler beim Laden der Projekte", e);
    }
}

// 3. PROJEKT-DATEN, SETTINGS & PROMPTS LADEN
async function loadProjectToMain(id, title, status) {
    currentProjectId = id;
    projectTitle.textContent = title; // XSS-Schutz
    progressSection.style.display = 'block';
    
    formSection.classList.add('locked');
    startBtn.textContent = 'Gesperrt';
    updatePauseResumeButton(status);
    
    // Projektdaten für Settings abrufen
    try {
        let pRes = await fetch(`/api/project/${id}`);
        if(pRes.ok) {
            let pData = await pRes.json();
            // Formularfelder befüllen
            if (edtechSettingsForm.elements['infobox_duration']) edtechSettingsForm.elements['infobox_duration'].value = pData.infobox_duration || 9;
            if (edtechSettingsForm.elements['ass_sync_offset']) edtechSettingsForm.elements['ass_sync_offset'].value = pData.ass_sync_offset || 0;
            if (edtechSettingsForm.elements['infobox_content']) edtechSettingsForm.elements['infobox_content'].value = pData.infobox_content || 'german_only';
            if (edtechSettingsForm.elements['hl_bold']) edtechSettingsForm.elements['hl_bold'].checked = pData.hl_bold === 1 || pData.hl_bold === true;
            if (edtechSettingsForm.elements['hl_underline']) edtechSettingsForm.elements['hl_underline'].checked = pData.hl_underline === 1 || pData.hl_underline === true;
            if (edtechSettingsForm.elements['hl_color']) edtechSettingsForm.elements['hl_color'].checked = pData.hl_color === 1 || pData.hl_color === true;
        }
        
        // Prompts abrufen und in die Tabs schreiben
        let promptRes = await fetch(`/api/prompts/${id}`);
        if(promptRes.ok) {
            let promptData = await promptRes.json();

            const createSafePre = (text) => {
                let pre = document.createElement('pre');
                pre.className = 'bg-light p-3 border rounded font-monospace';
                pre.style.cssText = 'white-space: pre-wrap; font-size: 0.85em;';
                pre.textContent = text;
                return pre;
            };

            const transTab = document.getElementById('trans-prompts');
            transTab.innerHTML = '';
            transTab.appendChild(createSafePre(promptData.translation_prompt));

            const edTab = document.getElementById('ed-prompts');
            if (edTab) {
                edTab.innerHTML = '';
                edTab.appendChild(createSafePre(promptData.edtech_prompt));
            }
        }
    } catch(e) {
        console.error("Fehler beim Laden der Projektdetails", e);
    }
    
    if (status === 'abgeschlossen') {
        unlockEdtech();
    } else {
        edtechZone.classList.add('disabled-overlay');
        edtechStatusBox.style.display = 'block';
        edtechActiveBox.style.display = 'none';
    }
    
    startPolling();
    loadProjects(); 
}

// 4. NEUES PROJEKT HOCHLADEN & STARTEN
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    formSection.classList.add('locked');
    startBtn.textContent = 'Läuft...';
    progressSection.style.display = 'block';
    
    const formData = new FormData(form);
    let serie = formData.get('series');
    let ep = formData.get('episode');
    formData.append('episode_summary', `${serie} - ${ep}`);
    projectTitle.textContent = `${serie} - ${ep}`;

    try {
        let uploadRes = await fetch('/api/upload', { method: 'POST', body: formData });
        let uploadData = await uploadRes.json();

        if (uploadRes.ok) {
            currentProjectId = uploadData.id;
            const startRes = await fetch(`/api/start/${currentProjectId}`, { method: 'POST' });
            if (!startRes.ok) {
                const startData = await startRes.json();
                loadProjectToMain(currentProjectId, `${serie} - ${ep}`, 'pausiert');
                alert("Projekt wurde angelegt, konnte aber nicht gestartet werden: " + startData.error);
                return;
            }
            startPolling();
            loadProjects();
        } else {
            alert("Upload fehlgeschlagen: " + uploadData.error);
            formSection.classList.remove('locked');
            startBtn.textContent = 'Start';
            progressSection.style.display = 'none';
        }
    } catch (err) {
        alert("Netzwerkfehler.");
        formSection.classList.remove('locked');
        startBtn.textContent = 'Start';
        progressSection.style.display = 'none';
    }
});

function updatePauseResumeButton(status) {
    const canResume = status === 'pausiert' || status === 'Fehler';
    btnPauseResume.style.display = status === 'laufend' || canResume ? 'inline-block' : 'none';
    btnPauseResume.textContent = canResume ? (status === 'Fehler' ? 'Erneut versuchen' : 'Fortsetzen') : 'Pause';
}

// 5. POLLING (Fortschritt, Logs)
function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    
    pollInterval = setInterval(async () => {
        if (!currentProjectId) return;

        try {
            let res = await fetch(`/api/status/${currentProjectId}`);
            if (!res.ok) return;
            
            let data = await res.json();
            let percent = data.total_lines > 0 ? Math.round((data.translated_lines / data.total_lines) * 100) : 0;
            
            if (progressBar) progressBar.style.width = percent + '%';
            if (progressText) progressText.textContent = `${data.translated_lines} / ${data.total_lines} Zeilen`;
            
            // LOGS XSS-sicher einfügen
            if (logContainer) {
                logContainer.innerHTML = '';
                data.logs.forEach(log => {
                    let div = document.createElement('div');
                    div.textContent = log;
                    logContainer.appendChild(div);
                });
            }
            
            if (statusBadge) {
                statusBadge.textContent = data.status.toUpperCase();
                statusBadge.className = "badge " + (data.status === 'laufend' ? "bg-primary" : (data.status === 'abgeschlossen' ? "bg-success" : "bg-warning"));
            }
            updatePauseResumeButton(data.status);
            
            if (data.status === 'abgeschlossen') {
                unlockEdtech();
                clearInterval(pollInterval);
                loadProjects(); 
            } else {
                edtechZone.classList.add('disabled-overlay');
                edtechStatusBox.style.display = 'block';
                edtechActiveBox.style.display = 'none';
            }
            
            if (data.status === 'Fehler' || data.status === 'pausiert') {
                clearInterval(pollInterval);
            }
        } catch (e) {
            console.error("Polling Fehler", e);
        }
    }, 2000);
}

// 6. NEU BUTTON & PAUSE BUTTON
btnNewProject.addEventListener('click', () => {
    currentProjectId = null;
    if (pollInterval) clearInterval(pollInterval);
    
    projectTitle.textContent = "Neues Projekt";
    formSection.classList.remove('locked');
    form.reset();
    startBtn.textContent = "Start";
    statusBadge.textContent = 'WARTET';
    progressBar.style.width = '0%';
    progressText.textContent = '0 / 0 Zeilen';
    logContainer.innerHTML = '';
    
    progressSection.style.display = 'none';
    edtechZone.classList.add('disabled-overlay');
    edtechStatusBox.style.display = 'block';
    edtechActiveBox.style.display = 'none';
    btnPauseResume.style.display = 'none';
});

btnPauseResume.addEventListener('click', async () => {
    if (!currentProjectId) return;
    btnPauseResume.disabled = true;
    
    let status = statusBadge.textContent.toLowerCase();
    let shouldResume = status === 'pausiert' || status === 'fehler';
    let endpoint = shouldResume ? `/api/start/${currentProjectId}` : `/api/pause/${currentProjectId}`;
    
    try {
        const response = await fetch(endpoint, { method: 'POST' });
        if (!response.ok) {
            const result = await response.json();
            alert(result.error || 'Statusänderung fehlgeschlagen.');
            return;
        }
        startPolling();
    } catch (err) {
        alert('Netzwerkfehler bei der Statusänderung.');
    } finally {
        btnPauseResume.disabled = false;
    }
});

// --- EDTECH LOGIK ---
function unlockEdtech() {
    edtechZone.classList.remove('disabled-overlay');
    edtechStatusBox.style.display = 'none';
    edtechActiveBox.style.display = 'block';
    
    document.getElementById('linkSrt').href = `/api/download/${currentProjectId}?type=srt`;
    document.getElementById('linkAss').href = `/api/download/${currentProjectId}?type=ass`;
    document.getElementById('linkCsv').href = `/api/download/${currentProjectId}?type=csv`;
}

btnValidateEdtech.addEventListener('click', async () => {
    btnValidateEdtech.disabled = true;
    btnValidateEdtech.textContent = "Prüfe...";
    validationResult.classList.add('d-none');
    
    try {
        let res = await fetch(`/api/edtech/validate/${currentProjectId}`);
        let data = await res.json();
        
        if (data.status === 'no_csv_yet') {
            validationResult.className = "alert alert-info";
            validationResult.textContent = "Keine CSV vorhanden. Bei 'Generieren' wird Gemini eine neue Liste erstellen.";
            btnGenerateEdtech.disabled = false;
        } else if (data.ts_mismatches.length === 0 && data.kw_mismatches.length === 0) {
            validationResult.className = "alert alert-success";
            validationResult.textContent = "100% Match! Keine Abweichungen zwischen SRT und CSV.";
            btnGenerateEdtech.disabled = false;
        } else {
            let msg = `Gefunden: ${data.ts_mismatches.length} Zeitstempel-Fehler und ${data.kw_mismatches.length} Keyword-Fehler.`;
            document.getElementById('fixMessage').textContent = msg;
            document.getElementById('fixMethodSelect').value = data.kw_mismatches.length > 0 ? 'gemini' : 'python';
            fixModal.show();
        }
    } catch (e) {
        alert("Fehler bei der Validierung.");
    } finally {
        btnValidateEdtech.disabled = false;
        btnValidateEdtech.textContent = "CSV Validieren";
        validationResult.classList.remove('d-none');
    }
});

btnApplyFix.addEventListener('click', async () => {
    const method = document.getElementById('fixMethodSelect').value;
    btnApplyFix.disabled = true;
    btnApplyFix.textContent = "Repariere...";
    
    try {
        let res = await fetch(`/api/edtech/fix/${currentProjectId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ method: method })
        });
        
        if (res.ok) {
            fixModal.hide();
            if (method === 'ignore') {
                validationResult.className = "alert alert-warning";
                validationResult.textContent = "Fehler ignoriert. Die Generierung kann fortgesetzt werden.";
                btnGenerateEdtech.disabled = false;
            } else {
                btnValidateEdtech.click(); // Nur bei echten Korrekturen neu validieren
            }
        } else {
            alert("Fehler bei der Reparatur.");
        }
    } catch (e) {
        alert("Netzwerkfehler.");
    } finally {
        btnApplyFix.disabled = false;
        btnApplyFix.textContent = "Ausführen";
    }
});

generateEdtechForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    btnGenerateEdtech.disabled = true;
    btnGenerateEdtech.textContent = "Generiere...";
    
    const settingsData = new FormData(edtechSettingsForm);
    const payload = Object.fromEntries(settingsData.entries());
    payload.generate_csv_only = document.getElementById('generateCsvOnly').checked;
    
    try {
        let res = await fetch(`/api/edtech/generate/${currentProjectId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        let result = await res.json();
        
        if (res.ok) {
            alert("Erfolgreich generiert!");
            document.getElementById('downloadLinks').classList.remove('d-none');
            const isCsvOnly = document.getElementById('generateCsvOnly').checked;
            document.getElementById('linkAss').style.display = isCsvOnly ? 'none' : 'inline-block';
            loadProjects(); 
        } else {
            alert("Fehler: " + result.error);
        }
    } catch (e) {
        alert("Netzwerkfehler.");
    } finally {
        btnGenerateEdtech.disabled = false;
        btnGenerateEdtech.textContent = "ASS & CSV Generieren";
    }
});