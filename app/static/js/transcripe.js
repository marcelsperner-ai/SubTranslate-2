const transcripeForm = document.getElementById('transcripeSettingsForm');
const transcripeStatus = document.getElementById('transcripeStatus');
const transcripeEvents = document.getElementById('transcripeEvents');
const transcripeButton = document.getElementById('btnTranscripe');
let transcripeSettingsLoaded = false;
let transcripeStatusBusy = false;
let transcripeInfoSequence = 0;

async function loadTranscripeProjectInfo(id) {
    const sequence = ++transcripeInfoSequence;
    const info = document.getElementById('transcripeProjectInfo');
    if (id !== Number(info.dataset.projectId)) info.classList.add('d-none');
    try {
        const project = await transcripeRequest(`project/${id}`);
        if (sequence !== transcripeInfoSequence || id !== currentProjectId || !project) return;
        const fields = Object.keys(project.assets).join(', ');
        info.textContent = `Transcripe: ${project.source_filename} · Importierte Dateien: ${fields}`;
        info.dataset.projectId = String(id);
        info.classList.remove('d-none');
    } catch (error) {
        if (sequence !== transcripeInfoSequence || id !== currentProjectId) return;
        info.textContent = error.message;
        info.classList.remove('d-none');
    }
}

async function transcripeRequest(path, options = {}) {
    const response = await fetch(`/api/transcripe/${path}`, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Transcripe-Anfrage fehlgeschlagen.');
    return result;
}

async function loadTranscripeSettings() {
    try {
        const settings = await transcripeRequest('settings');
        transcripeForm.elements.enabled.checked = settings.enabled;
        for (const field of ['inbox_dir', 'app_dir', 'python_path']) {
            transcripeForm.elements[field].value = settings[field];
        }
        transcripeSettingsLoaded = true;
    } catch (error) {
        transcripeStatus.textContent = error.message;
    }
}

async function saveTranscripeSettings() {
    if (!transcripeSettingsLoaded) throw new Error('Transcripe-Einstellungen noch nicht geladen.');
    const settings = {enabled: transcripeForm.elements.enabled.checked};
    for (const field of ['inbox_dir', 'app_dir', 'python_path']) {
        settings[field] = transcripeForm.elements[field].value;
    }
    await transcripeRequest('settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(settings),
    });
    await refreshTranscripeStatus();
}

function renderTranscripeStatus(status) {
    transcripeStatus.textContent = status.enabled
        ? `Import aktiv · ${status.import_count} Projekte · ${status.error_count} Fehler`
        : 'Automatischer Import deaktiviert';
    transcripeStatus.classList.toggle('text-danger', status.error_count > 0);
    transcripeEvents.replaceChildren();
    for (const event of status.events) {
        const entry = document.createElement('div');
        entry.className = event.level === 'error' ? 'text-danger mb-2' : 'mb-2';
        entry.textContent = `${event.message} (${event.marker})`;
        transcripeEvents.appendChild(entry);
    }
}

async function refreshTranscripeStatus() {
    if (transcripeStatusBusy) return;
    transcripeStatusBusy = true;
    try {
        renderTranscripeStatus(await transcripeRequest('status'));
        if (currentProjectId) loadTranscripeProjectInfo(currentProjectId);
    } catch (error) {
        transcripeStatus.textContent = error.message;
        transcripeStatus.classList.add('text-danger');
    } finally {
        transcripeStatusBusy = false;
    }
}

document.getElementById('btnTranscripeScan').addEventListener('click', async () => {
    try {
        await saveTranscripeSettings();
        renderTranscripeStatus(await transcripeRequest('scan', {method: 'POST'}));
        await loadProjects();
    } catch (error) {
        transcripeEvents.textContent = error.message;
        transcripeEvents.classList.add('text-danger');
    }
});

transcripeButton.addEventListener('click', async () => {
    const tab = window.open('about:blank', '_blank');
    if (tab) tab.opener = null;
    transcripeButton.disabled = true;
    transcripeStatus.textContent = 'Transcripe wird geöffnet …';
    try {
        const result = await transcripeRequest('launch', {method: 'POST'});
        if (tab && !tab.closed) {
            tab.location.replace(result.url);
        } else {
            const link = document.createElement('a');
            link.href = result.url;
            link.target = '_blank';
            link.rel = 'noopener';
            link.textContent = 'Transcripe öffnen';
            transcripeStatus.replaceChildren(link);
            return;
        }
        transcripeStatus.textContent = 'Transcripe geöffnet. Transkription dort starten.';
    } catch (error) {
        if (tab) tab.close();
        transcripeStatus.textContent = error.message;
        transcripeStatus.classList.add('text-danger');
    } finally {
        transcripeButton.disabled = false;
    }
});

document.addEventListener('DOMContentLoaded', () => {
    loadTranscripeSettings();
    refreshTranscripeStatus();
    window.setInterval(refreshTranscripeStatus, 5000);
});
