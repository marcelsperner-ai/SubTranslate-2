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
const edtechStatusBox = document.getElementById('edtechStatusBox');
const edtechActiveBox = document.getElementById('edtechActiveBox');
const btnValidateEdtech = document.getElementById('btnValidateEdtech');
const validationResult = document.getElementById('validationResult');
const btnGenerateEdtech = document.getElementById('btnGenerateEdtech');
const generateEdtechForm = document.getElementById('generateEdtechForm');
const edtechSettingsForm = document.getElementById('edtechSettingsForm');
const fixModal = new bootstrap.Modal(document.getElementById('fixModal'));
const btnApplyFix = document.getElementById('btnApplyFix');

// 1. INITIALISIERUNG
document.addEventListener("DOMContentLoaded", () => {
    loadProjects();
});

// 2. PROJEKTE LADEN (Sidebar)
async function loadProjects() {
    try {
        const res = await fetch('/api/projects');
        const projects = await res.json();
        
        sidebarList.innerHTML = '';
        projects.forEach(p => {
            // Berechne Fortschritt
            let percent = p.total_lines > 0 ? Math.round((p.translated_lines / p.total_lines) * 100) : 0;
            let isActive = p.id === currentProjectId ? 'active' : '';
            let edtechDone = p.edtech_done ? 'done' : '';
            let transDone = p.status === 'abgeschlossen' ? 'done' : '';
            let progressColor = p.status === 'abgeschlossen' ? 'bg-success' : 'var(--purple-accent)';
            
            // Name aus Datei extrahieren, falls Serie/Episode nicht separat gespeichert sind
            let name = p.original_filename.replace('.srt', '');

            let html = `
            <div class="mini-project ${isActive}" onclick="loadProjectToMain(${p.id}, '${name}', '${p.status}')">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="text-truncate" style="max-width: 70%;">
                        <div class="fw-bold fs-6 text-truncate">${name}</div>
                        <div class="text-muted" style="font-size: 0.8em;">Status: ${p.status}</div>
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
            sidebarList.insertAdjacentHTML('beforeend', html);
        });
    } catch (e) {
        console.error("Fehler beim Laden der Projekte", e);
    }
}

// 3. PROJEKT IN DIE HAUPTANSICHT LADEN
function loadProjectToMain(id, title, status) {
    currentProjectId = id;
    projectTitle.innerText = title;
    progressSection.style.display = 'block';
    
    // UI sperren, da es kein neues Projekt ist
    formSection.classList.add('locked');
    startBtn.innerText = 'Gesperrt';
    updatePauseResumeButton(status);
    edtechZone.classList.toggle('disabled-overlay', status !== 'abgeschlossen');
    
    // Polling starten
    startPolling();
    loadProjects(); // Sidebar aktualisieren (active state)
}

// 4. NEUES PROJEKT HOCHLADEN & STARTEN
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    formSection.classList.add('locked');
    startBtn.innerText = 'Läuft...';
    progressSection.style.display = 'block';
    
    const formData = new FormData(form);
    
    // Kombiniere Serie und Episode als Zusammenfassung für den Kontext
    let serie = formData.get('series');
    let ep = formData.get('episode');
    formData.append('episode_summary', `${serie} - ${ep}`);
    
    projectTitle.innerText = `${serie} - ${ep}`;

    try {
        let uploadRes = await fetch('/api/upload', { method: 'POST', body: formData });
        let uploadData = await uploadRes.json();

        if (uploadRes.ok) {
            currentProjectId = uploadData.id;
            
            // Unmittelbar den Start-Befehl abfeuern
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
            startBtn.innerText = 'Start';
            progressSection.style.display = 'none';
        }
    } catch (err) {
        alert("Netzwerkfehler.");
        formSection.classList.remove('locked');
        startBtn.innerText = 'Start';
        progressSection.style.display = 'none';
    }
});

function updatePauseResumeButton(status) {
    const canResume = status === 'pausiert' || status === 'Fehler';
    btnPauseResume.style.display = status === 'laufend' || canResume ? 'inline-block' : 'none';
    btnPauseResume.innerText = canResume
        ? (status === 'Fehler' ? 'Erneut versuchen' : 'Fortsetzen')
        : 'Pause';
}

// 5. POLLING (Fortschritt, Logs, EdTech Freischaltung)
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
            if (progressText) progressText.innerText = `${data.translated_lines} / ${data.total_lines} Zeilen`;
            
            if (logContainer) logContainer.innerHTML = data.logs.join('<br>');
            
            if (statusBadge) {
                statusBadge.innerText = data.status.toUpperCase();
                statusBadge.className = "badge " + (data.status === 'laufend' ? "bg-primary" : (data.status === 'abgeschlossen' ? "bg-success" : "bg-warning"));
            }
            updatePauseResumeButton(data.status);
            
            // EdTech Freischaltung
            if (data.status === 'abgeschlossen') {
                edtechZone.classList.remove('disabled-overlay');
                edtechZone.querySelector('h5').innerText = "Bereit für die EdTech-Generierung";
                edtechZone.querySelector('p').innerText = "Wähle deine Einstellungen und starte den Prozess.";
                clearInterval(pollInterval);
                loadProjects(); // Finales Update für die Sidebar-Badges
            } else {
                edtechZone.classList.add('disabled-overlay');
            }
            
            if (data.status === 'Fehler' || data.status === 'pausiert') {
                clearInterval(pollInterval);
            }
        } catch (e) {
            console.error("Polling Fehler", e);
        }
    }, 2000);
}
// "Neu"-Button Handler
btnNewProject.addEventListener('click', () => {
    currentProjectId = null;
    if (pollInterval) clearInterval(pollInterval);
    
    projectTitle.innerText = "Neues Projekt";
    formSection.classList.remove('locked');
    form.reset();
    startBtn.innerText = "Start";
    statusBadge.innerText = 'WARTET';
    progressBar.style.width = '0%';
    progressText.innerText = '0 / 0 Zeilen';
    logContainer.innerHTML = '';
    
    progressSection.style.display = 'none';
    edtechZone.classList.add('disabled-overlay');
    btnPauseResume.style.display = 'none';
});

// Pause / Resume Mechanik (Basic)
btnPauseResume.addEventListener('click', async () => {
    if (!currentProjectId) return;
    btnPauseResume.disabled = true;
    
    let status = statusBadge.innerText.toLowerCase();
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
// Wird vom Poller gerufen, wenn Status auf 'abgeschlossen' wechselt
function unlockEdtech() {
    edtechZone.classList.remove('disabled-overlay');
    edtechStatusBox.style.display = 'none';
    edtechActiveBox.style.display = 'block';
    
    // Setze Download Links
    document.getElementById('linkSrt').href = `/api/download/${currentProjectId}?type=srt`;
    document.getElementById('linkAss').href = `/api/download/${currentProjectId}?type=ass`;
    document.getElementById('linkCsv').href = `/api/download/${currentProjectId}?type=csv`;
}

// In startPolling() die if-Bedingung anpassen:
// if (data.status === 'abgeschlossen') {
//     unlockEdtech();
//     clearInterval(pollInterval);
//     loadProjects();
// }

// 1. VALIDIEREN
btnValidateEdtech.addEventListener('click', async () => {
    btnValidateEdtech.disabled = true;
    btnValidateEdtech.innerText = "Prüfe...";
    validationResult.classList.add('d-none');
    
    try {
        let res = await fetch(`/api/edtech/validate/${currentProjectId}`);
        let data = await res.json();
        
        if (data.status === 'no_csv_yet') {
            validationResult.className = "alert alert-info";
            validationResult.innerText = "Keine CSV vorhanden. Bei 'Generieren' wird Gemini eine neue Liste erstellen.";
            btnGenerateEdtech.disabled = false;
        } else if (data.ts_mismatches.length === 0 && data.kw_mismatches.length === 0) {
            validationResult.className = "alert alert-success";
            validationResult.innerText = "100% Match! Keine Abweichungen zwischen SRT und CSV.";
            btnGenerateEdtech.disabled = false;
        } else {
            // Mismatches gefunden -> Modal öffnen
            let msg = `Gefunden: ${data.ts_mismatches.length} Zeitstempel-Fehler und ${data.kw_mismatches.length} Keyword-Fehler.`;
            document.getElementById('fixMessage').innerText = msg;
            
            // Logik-Empfehlung im Modal vorauswählen
            if (data.kw_mismatches.length > 0) {
                document.getElementById('fixMethodSelect').value = 'gemini';
            } else {
                document.getElementById('fixMethodSelect').value = 'python';
            }
            
            fixModal.show();
        }
    } catch (e) {
        alert("Fehler bei der Validierung.");
    } finally {
        btnValidateEdtech.disabled = false;
        btnValidateEdtech.innerText = "CSV Validieren";
        validationResult.classList.remove('d-none');
    }
});

// 2. REPARIEREN (Modal Button)
btnApplyFix.addEventListener('click', async () => {
    const method = document.getElementById('fixMethodSelect').value;
    btnApplyFix.disabled = true;
    btnApplyFix.innerText = "Repariere...";
    
    try {
        let res = await fetch(`/api/edtech/fix/${currentProjectId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ method: method })
        });
        
        if (res.ok) {
            fixModal.hide();
            // Erneut validieren um zu prüfen, ob es geklappt hat
            btnValidateEdtech.click(); 
        } else {
            alert("Fehler bei der Reparatur.");
        }
    } catch (e) {
        alert("Netzwerkfehler.");
    } finally {
        btnApplyFix.disabled = false;
        btnApplyFix.innerText = "Ausführen";
    }
});

// 3. GENERIEREN (ASS & CSV)
generateEdtechForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    btnGenerateEdtech.disabled = true;
    btnGenerateEdtech.innerText = "Generiere (Gemini denkt)...";
    
    // Einstellungen aus dem Settings-Tab auslesen
    const settingsData = new FormData(edtechSettingsForm);
    const payload = Object.fromEntries(settingsData.entries());
    
    // Checkbox State hinzufügen
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
            loadProjects(); // Sidebar Badges aktualisieren
        } else {
            alert("Fehler: " + result.error);
        }
    } catch (e) {
        alert("Netzwerkfehler.");
    } finally {
        btnGenerateEdtech.disabled = false;
        btnGenerateEdtech.innerText = "ASS & CSV Generieren";
    }
});