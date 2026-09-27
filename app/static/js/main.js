let currentJobId = null;
let pollInterval = null;

const uploadForm = document.getElementById('uploadForm');
const uploadBtn = document.getElementById('uploadBtn');
const activeJobCard = document.getElementById('activeJobCard');
const emptyState = document.getElementById('emptyState');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const statusBadge = document.getElementById('statusBadge');
const logContainer = document.getElementById('logContainer');
const pauseBtn = document.getElementById('pauseBtn');
const resumeBtn = document.getElementById('resumeBtn');

// 1. UPLOAD & START
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    uploadBtn.disabled = true;
    uploadBtn.innerText = "Lade hoch...";

    const formData = new FormData(uploadForm);

    try {
        // Datei hochladen und Projekt anlegen
        let response = await fetch('/api/upload', { method: 'POST', body: formData });
        let result = await response.json();

        if (response.ok) {
            currentJobId = result.id;
            
            // Sofort den Worker starten
            await fetch(`/api/start/${currentJobId}`, { method: 'POST' });
            
            // UI umbauen
            emptyState.style.display = 'none';
            activeJobCard.style.display = 'block';
            document.getElementById('jobTitle').innerText = "Übersetzung läuft (Projekt-ID: " + currentJobId + ")";
            
            // Polling starten
            startPolling();
        } else {
            alert("Fehler beim Upload: " + result.error);
        }
    } catch (err) {
        alert("Netzwerkfehler.");
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.innerText = "Übersetzung starten";
    }
});

// 2. LIVE-POLLING (Der Streamlit-Ersatz)
function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    
    pollInterval = setInterval(async () => {
        if (!currentJobId) return;

        let res = await fetch(`/api/status/${currentJobId}`);
        if (!res.ok) return;
        
        let data = await res.json();
        
        // Fortschrittsbalken berechnen
        let percent = data.total_lines > 0 ? Math.round((data.translated_lines / data.total_lines) * 100) : 0;
        progressBar.style.width = percent + '%';
        progressText.innerText = `${data.translated_lines} / ${data.total_lines} Zeilen`;
        
        // Logs aktualisieren
        logContainer.innerHTML = data.logs.join('\n');
        
        // Status Badge & Buttons
        statusBadge.innerText = data.status.toUpperCase();
        if (data.status === 'laufend') {
            statusBadge.className = "badge bg-primary";
            pauseBtn.style.display = 'inline-block';
            resumeBtn.style.display = 'none';
            progressBar.classList.add('progress-bar-animated');
        } else if (data.status === 'pausiert') {
            statusBadge.className = "badge bg-warning text-dark";
            pauseBtn.style.display = 'none';
            resumeBtn.style.display = 'inline-block';
            progressBar.classList.remove('progress-bar-animated');
        } else if (data.status === 'abgeschlossen') {
            statusBadge.className = "badge bg-success";
            pauseBtn.style.display = 'none';
            resumeBtn.style.display = 'none';
            progressBar.classList.remove('progress-bar-animated');
            clearInterval(pollInterval); // Polling beenden
        } else if (data.status === 'Fehler') {
            statusBadge.className = "badge bg-danger";
            progressBar.classList.add('bg-danger');
            clearInterval(pollInterval);
        }
    }, 2000); // Alle 2 Sekunden abfragen
}

// 3. PAUSE & FORTSETZEN
pauseBtn.addEventListener('click', async () => {
    if (!currentJobId) return;
    pauseBtn.disabled = true;
    await fetch(`/api/pause/${currentJobId}`, { method: 'POST' });
    pauseBtn.disabled = false;
});

resumeBtn.addEventListener('click', async () => {
    if (!currentJobId) return;
    resumeBtn.disabled = true;
    await fetch(`/api/start/${currentJobId}`, { method: 'POST' });
    resumeBtn.disabled = false;
});