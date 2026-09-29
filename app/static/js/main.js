let currentProjectId = null;
let pollInterval = null;
let projectListPollInterval = null;
let projectListRequestActive = false;
let projectLoadSequence = 0;
let generateAssAfterValidation = false;
let currentAvailableDownloads = { srt: false, ass: false, csv: false };

// DOM Elemente
const form = document.getElementById('newProjectForm');
const formSection = document.getElementById('uploadFormSection');
const startBtn = document.getElementById('startBtn');
const seriesSelect = document.getElementById('seriesSelect');
const episodeSelect = document.getElementById('episodeSelect');
const transSettingsForm = document.getElementById('transSettingsForm');
const translationModelSelect = document.getElementById('translationModelSelect');
const transPromptsTab = document.getElementById('transPromptsTab');
const translationPromptInput = document.getElementById('translationPromptInput');
const translationPromptSaveButton = document.getElementById('btnSaveTranslationPrompt');
const regenerateTranslationButton = document.getElementById('btnRegenerateTranslation');
const translationPromptSaveStatus = document.getElementById('translationPromptSaveStatus');
const episodeSummarySection = document.getElementById('episodeSummarySection');
const episodeSummaryInput = document.getElementById('episodeSummaryInput');
const episodeSummarySaveButton = document.getElementById('btnSaveEpisodeSummary');
const episodeSummarySaveStatus = document.getElementById('episodeSummarySaveStatus');
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
const logbookCollapse = document.getElementById('logbookCollapse');
const logbookToggleIcon = document.getElementById('logbookToggleIcon');
const projectLoadingOverlay = document.getElementById('projectLoadingOverlay');

// EdTech & Archiv Elemente
const edtechStatusBox = document.getElementById('edtechStatusBox');
const edtechActiveBox = document.getElementById('edtechActiveBox');
const validationResult = document.getElementById('validationResult');
const btnGenerateEdtech = document.getElementById('btnGenerateEdtech');
const btnRebuildAss = document.getElementById('btnRebuildAss');
const generateEdtechForm = document.getElementById('generateEdtechForm');
const edtechSettingsForm = document.getElementById('edtechSettingsForm');
const edtechModelSelect = document.getElementById('edtechModelSelect');
const edtechPromptInput = document.getElementById('edtechPromptInput');
const edtechPromptSaveButton = document.getElementById('btnSaveEdtechPrompt');
const regenerateEdtechPromptButton = document.getElementById('btnRegenerateEdtechPrompt');
const edtechPromptSaveStatus = document.getElementById('edtechPromptSaveStatus');
const fixModal = new bootstrap.Modal(document.getElementById('fixModal'));
const timestampMismatchList = document.getElementById('timestampMismatchList');
const keywordMismatchList = document.getElementById('keywordMismatchList');
const btnFixKeywordsGemini = document.getElementById('btnFixKeywordsGemini');
const btnFixTimestampsPython = document.getElementById('btnFixTimestampsPython');
const btnIgnoreMismatches = document.getElementById('btnIgnoreMismatches');
const archiveTableBody = document.querySelector('#archiveModal tbody');
const archiveConfirmModalElement = document.getElementById('archiveConfirmModal');
const archiveConfirmModal = new bootstrap.Modal(archiveConfirmModalElement);
const archiveConfirmProjectName = document.getElementById('archiveConfirmProjectName');
const btnConfirmArchiveProject = document.getElementById('btnConfirmArchiveProject');
const translationSyncOffsetInput = transSettingsForm.elements['sync_offset'];
const syncOffsetWarningModal = new bootstrap.Modal(document.getElementById('syncOffsetWarningModal'));
const btnUseEdtechSyncOffset = document.getElementById('btnUseEdtechSyncOffset');
const btnKeepTranslationSyncOffset = document.getElementById('btnKeepTranslationSyncOffset');
let yamlMetadata = {};
let promptPreviewRequest = 0;
let promptPreviewLoaded = false;
let translationPromptChanged = false;
let translationPromptConfirmed = false;
let episodeSummarySaved = true;
let hasGeneratedAss = false;
let savedEdtechSettings = null;
let pendingArchiveProjectId = null;
let loadedTranslationSyncOffset = translationSyncOffsetInput.value;
let pendingTranslationSyncOffset = null;
let edtechPromptLoaded = false;
let edtechPromptChanged = false;
let edtechPromptConfirmed = false;

function setProjectLoading(isLoading) {
    if (!projectLoadingOverlay) return;
    projectLoadingOverlay.classList.toggle('visible', isLoading);
    projectLoadingOverlay.setAttribute('aria-hidden', String(!isLoading));
}

function updateTranslationPromptActions() {
    const hasPromptChange = promptPreviewLoaded && translationPromptChanged && translationPromptInput.value.trim();
    translationPromptSaveButton.disabled = !hasPromptChange || translationPromptConfirmed;
    regenerateTranslationButton.disabled = !hasPromptChange || !translationPromptConfirmed || !currentProjectId || !currentAvailableDownloads.srt;
}

function setModelSelectValue(select, model) {
    const hasOption = Array.from(select.options).some(option => option.value === model);
    select.value = hasOption ? model : 'gemini-3.1-flash-lite';
}

function updateEdtechPromptActions() {
    const hasPromptChange = edtechPromptLoaded && edtechPromptChanged && edtechPromptInput.value.trim();
    edtechPromptSaveButton.disabled = !hasPromptChange || edtechPromptConfirmed;
    regenerateEdtechPromptButton.disabled = !hasPromptChange || !edtechPromptConfirmed || !currentProjectId || !currentAvailableDownloads.srt;
}

translationSyncOffsetInput.addEventListener('change', () => {
    const changedOffset = translationSyncOffsetInput.value;
    if (!currentProjectId || !currentAvailableDownloads.ass || changedOffset === loadedTranslationSyncOffset) return;
    pendingTranslationSyncOffset = changedOffset;
    syncOffsetWarningModal.show();
});

btnUseEdtechSyncOffset.addEventListener('click', () => {
    translationSyncOffsetInput.value = loadedTranslationSyncOffset;
    pendingTranslationSyncOffset = null;
    syncOffsetWarningModal.hide();
    document.querySelector('#edtechZone .nav-link[href="#ed-settings"]').click();
});

btnKeepTranslationSyncOffset.addEventListener('click', () => {
    loadedTranslationSyncOffset = pendingTranslationSyncOffset;
    pendingTranslationSyncOffset = null;
    syncOffsetWarningModal.hide();
});

document.getElementById('syncOffsetWarningModal').addEventListener('hidden.bs.modal', () => {
    if (pendingTranslationSyncOffset !== null) {
        translationSyncOffsetInput.value = loadedTranslationSyncOffset;
        pendingTranslationSyncOffset = null;
    }
});

function setLogbookExpanded(expanded) {
    if (!logbookCollapse) return;
    logbookCollapse.classList.toggle('show', expanded);
    logbookCollapse.setAttribute('aria-expanded', String(expanded));
    if (logbookToggleIcon) logbookToggleIcon.textContent = expanded ? '▼' : '▶';
}

if (logbookCollapse) {
    logbookCollapse.addEventListener('shown.bs.collapse', () => setLogbookExpanded(true));
    logbookCollapse.addEventListener('hidden.bs.collapse', () => setLogbookExpanded(false));
}

// 1. INITIALISIERUNG
document.addEventListener("DOMContentLoaded", () => {
    loadMetadata();
    loadProjects();
    startProjectListPolling();
    updateSelectionAvailability();
});

function setPromptTabEnabled(enabled) {
    transPromptsTab.classList.toggle('disabled', !enabled);
    transPromptsTab.setAttribute('aria-disabled', String(!enabled));
    if (enabled) {
        transPromptsTab.removeAttribute('tabindex');
    } else {
        transPromptsTab.setAttribute('tabindex', '-1');
    }
}

function renderPromptTabs(promptData, editable = false) {
    translationPromptInput.value = promptData.translation_prompt || '';
    translationPromptInput.disabled = !editable;
    updateTranslationPromptActions();
    translationPromptSaveStatus.textContent = editable
        ? (translationPromptChanged
            ? (translationPromptConfirmed ? 'Prompt geändert – gilt nur für dieses Projekt.' : 'Prompt geändert – noch nicht bestätigt.')
            : 'Prompt aus YAML geladen.')
        : 'Prompt-Vorschau';

    const edTab = document.getElementById('ed-prompts');
    if (edTab) {
        edtechPromptInput.value = promptData.edtech_prompt || '';
        edtechPromptInput.disabled = !editable || !currentAvailableDownloads.srt;
        updateEdtechPromptActions();
        edtechPromptSaveStatus.textContent = editable && currentAvailableDownloads.srt
            ? (edtechPromptChanged
                ? (edtechPromptConfirmed ? 'Prompt geändert – gilt nur für dieses Projekt.' : 'Prompt geändert – noch nicht bestätigt.')
                : 'Prompt aus YAML geladen.')
            : 'Prompt-Vorschau';
    }
}

function hasValidNewProjectSelection() {
    const profileKey = seriesSelect.value;
    if (!yamlMetadata[profileKey]) return false;
    const validEpisode = profileKey === 'default' || Boolean(episodeSelect.value);
    const validSummary = !isCustomEpisodeSelected() || episodeSummarySaved;
    return validEpisode && validSummary;
}

function isCustomEpisodeSelected() {
    return seriesSelect.value !== 'default' && episodeSelect.value === '__custom__';
}

function updateSelectionAvailability() {
    const ready = hasValidNewProjectSelection();
    startBtn.disabled = !ready || !promptPreviewLoaded || !translationPromptInput.value.trim();
    setPromptTabEnabled(ready);
    return ready;
}

async function loadPromptPreview() {
    const requestId = ++promptPreviewRequest;
    promptPreviewLoaded = false;
    translationPromptChanged = false;
    translationPromptConfirmed = false;
    edtechPromptLoaded = false;
    edtechPromptChanged = false;
    edtechPromptConfirmed = false;
    const profileKey = seriesSelect.value;
    const episodeKey = episodeSelect.value;

    if (!hasValidNewProjectSelection()) {
        const message = isCustomEpisodeSelected()
            ? 'Zusammenfassung eingeben und speichern, um den Prompt zu laden.'
            : profileKey
                ? 'Episode auswählen, um den Prompt anzuzeigen.'
                : 'Serie auswählen, um den Prompt anzuzeigen.';
        renderPromptTabs({ translation_prompt: message, edtech_prompt: message });
        updateSelectionAvailability();
        return;
    }

    startBtn.disabled = true;
    renderPromptTabs({
        translation_prompt: 'Prompt wird geladen...',
        edtech_prompt: 'Prompt wird geladen...'
    });

    try {
        const response = await fetch('/api/prompts/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profile_key: profileKey,
                episode: episodeKey,
                episode_summary: isCustomEpisodeSelected() ? episodeSummaryInput.value : ''
            })
        });
        if (!response.ok) throw new Error('Prompt-Vorschau konnte nicht geladen werden.');
        const promptData = await response.json();

        if (requestId === promptPreviewRequest && profileKey === seriesSelect.value && episodeKey === episodeSelect.value) {
            promptPreviewLoaded = true;
            translationPromptChanged = false;
            translationPromptConfirmed = false;
            renderPromptTabs(promptData, true);
            updateSelectionAvailability();
        }
    } catch (error) {
        if (requestId === promptPreviewRequest) {
            renderPromptTabs({
                translation_prompt: 'Prompt konnte nicht geladen werden.',
                edtech_prompt: 'Prompt konnte nicht geladen werden.'
            });
            promptPreviewLoaded = false;
            translationPromptChanged = false;
            translationPromptConfirmed = false;
            updateSelectionAvailability();
            console.error(error);
        }
    }
}

translationPromptInput.addEventListener('input', () => {
    translationPromptChanged = true;
    translationPromptConfirmed = false;
    translationPromptSaveStatus.textContent = 'Änderungen noch nicht gespeichert.';
    updateTranslationPromptActions();
    updateSelectionAvailability();
});

translationPromptSaveButton.addEventListener('click', () => {
    translationPromptConfirmed = true;
    translationPromptSaveStatus.textContent = 'Prompt geändert – gilt nur für dieses Projekt.';
    updateTranslationPromptActions();
    updateSelectionAvailability();
});

edtechPromptInput.addEventListener('input', () => {
    edtechPromptChanged = true;
    edtechPromptConfirmed = false;
    edtechPromptSaveStatus.textContent = 'Änderungen noch nicht gespeichert.';
    updateEdtechPromptActions();
});

edtechPromptSaveButton.addEventListener('click', () => {
    edtechPromptConfirmed = true;
    edtechPromptSaveStatus.textContent = 'Prompt geändert – gilt nur für dieses Projekt.';
    updateEdtechPromptActions();
});

regenerateEdtechPromptButton.addEventListener('click', () => {
    if (regenerateEdtechPromptButton.disabled) return;
    const confirmed = window.confirm(
        'Die bestehende CSV-Datei wird überschrieben. Die ASS-Datei muss anschließend neu erstellt werden. Fortfahren?'
    );
    if (!confirmed) return;
    generateEdtechForm.requestSubmit();
});

regenerateTranslationButton.addEventListener('click', async () => {
    if (regenerateTranslationButton.disabled || !currentProjectId) return;
    const confirmed = window.confirm(
        'Die bestehende SRT-Datei wird überschrieben. Die zugehörige CSV- und ASS-Datei werden ebenfalls entfernt und müssen neu erstellt werden. Fortfahren?'
    );
    if (!confirmed) return;

    regenerateTranslationButton.disabled = true;
    translationPromptSaveButton.disabled = true;
    translationPromptSaveStatus.textContent = 'SRT-Neugenerierung wird gestartet...';
    try {
        const response = await fetch(`/api/regenerate/${currentProjectId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                translation_prompt: translationPromptInput.value,
                sync_offset: translationSyncOffsetInput.value
            })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'SRT-Neugenerierung fehlgeschlagen.');

        currentAvailableDownloads = { srt: false, ass: false, csv: false };
        hasGeneratedAss = false;
        translationPromptChanged = false;
        translationPromptConfirmed = false;
        progressSection.style.display = 'block';
        formSection.classList.add('locked');
        translationPromptSaveStatus.textContent = 'SRT-Neugenerierung gestartet.';
        startPolling();
    } catch (error) {
        translationPromptSaveStatus.textContent = error.message;
        updateTranslationPromptActions();
    }
});

episodeSummaryInput.addEventListener('input', () => {
    episodeSummarySaved = false;
    episodeSummarySaveStatus.textContent = 'Zusammenfassung noch nicht gespeichert.';
    updateSelectionAvailability();
});

episodeSummarySaveButton.addEventListener('click', () => {
    episodeSummarySaved = true;
    episodeSummarySaveStatus.textContent = 'Zusammenfassung gespeichert.';
    updateSelectionAvailability();
    loadPromptPreview();
});

function escapeHtml(unsafe) {
    return (unsafe || '').toString()
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

function getEdtechSettingsSnapshot() {
    const settings = {};
    for (const field of edtechSettingsForm.elements) {
        if (!field.name) continue;
        if (field.name === 'edtech_model') continue;
        settings[field.name] = field.type === 'checkbox' ? field.checked : field.value;
    }
    return JSON.stringify(settings);
}

function updateAssRebuildButton() {
    const hasChanges = hasGeneratedAss && savedEdtechSettings !== null
        && getEdtechSettingsSnapshot() !== savedEdtechSettings;
    btnRebuildAss.classList.toggle('d-none', !hasChanges);
}

edtechSettingsForm.addEventListener('input', updateAssRebuildButton);
edtechSettingsForm.addEventListener('change', updateAssRebuildButton);

async function loadMetadata() {
    try {
        const response = await fetch('/api/metadata');
        if (!response.ok) throw new Error('Metadaten konnten nicht geladen werden.');

        const data = await response.json();
        yamlMetadata = data.profiles || {};
        Object.entries(yamlMetadata).forEach(([key, profile]) => {
            const option = document.createElement('option');
            option.value = key;
            option.textContent = profile.name || key;
            seriesSelect.appendChild(option);
        });
        updateSelectionAvailability();
    } catch (error) {
        console.error('Fehler beim Laden der Serien-Metadaten', error);
    }
}

seriesSelect.addEventListener('change', () => {
    episodeSelect.replaceChildren(new Option('Episode...', ''));
    const profile = yamlMetadata[seriesSelect.value];

    const needsEpisode = Boolean(profile) && seriesSelect.value !== 'default';
    episodeSelect.required = needsEpisode;
    episodeSelect.disabled = !needsEpisode;
    episodeSummarySection.classList.add('d-none');
    episodeSummaryInput.value = '';
    episodeSummarySaved = true;
    episodeSummarySaveStatus.textContent = '';

    if (needsEpisode) {
        profile.episodes.forEach((episodeKey) => {
            const option = document.createElement('option');
            option.value = episodeKey;
            option.textContent = episodeKey;
            episodeSelect.appendChild(option);
        });
        episodeSelect.add(new Option('Eigene Episode', '__custom__'));
        episodeSelect.disabled = false;
    }

    updateSelectionAvailability();
    loadPromptPreview();
});

episodeSelect.addEventListener('change', () => {
    const useCustomSummary = isCustomEpisodeSelected();
    episodeSummarySection.classList.toggle('d-none', !useCustomSummary);
    episodeSummaryInput.value = '';
    episodeSummarySaved = !useCustomSummary;
    episodeSummarySaveStatus.textContent = useCustomSummary
        ? 'Zusammenfassung eingeben; sie darf leer bleiben.'
        : '';
    updateSelectionAvailability();
    loadPromptPreview();
});

async function openProjectFromElement(projectElement) {
    const projectId = Number(projectElement.dataset.projectId);
    if (!Number.isInteger(projectId)) return;

    if (projectElement.dataset.projectArchived === 'true') {
        projectElement.disabled = true;
        try {
            const response = await fetch(`/api/unarchive/${projectId}`, { method: 'POST' });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Projekt konnte nicht wiederhergestellt werden.');
            await loadProjects();
            bootstrap.Modal.getInstance(document.getElementById('archiveModal'))?.hide();
        } catch (error) {
            projectElement.disabled = false;
            alert(error.message);
            return;
        }
    }

    loadProjectToMain(
        projectId,
        projectElement.dataset.projectTitle,
        projectElement.dataset.projectStatus
    );
}

sidebarList.addEventListener('click', (event) => {
    const archiveButton = event.target.closest('.archive-project-button[data-project-id]');
    if (archiveButton && sidebarList.contains(archiveButton)) {
        event.stopPropagation();
        pendingArchiveProjectId = Number(archiveButton.dataset.projectId);
        archiveConfirmProjectName.textContent = archiveButton.dataset.projectTitle;
        archiveConfirmModal.show();
        return;
    }

    const projectElement = event.target.closest('.mini-project-open[data-project-id]');
    if (projectElement && sidebarList.contains(projectElement)) {
        openProjectFromElement(projectElement);
    }
});

sidebarList.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;

    const projectElement = event.target.closest('.mini-project-open[data-project-id]');
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

btnConfirmArchiveProject.addEventListener('click', async () => {
    if (!pendingArchiveProjectId) return;
    btnConfirmArchiveProject.disabled = true;
    btnConfirmArchiveProject.textContent = 'Wird archiviert ...';
    try {
        const response = await fetch(`/api/archive/${pendingArchiveProjectId}`, { method: 'POST' });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Projekt konnte nicht archiviert werden.');
        archiveConfirmModal.hide();
        pendingArchiveProjectId = null;
        await loadProjects();
    } catch (error) {
        alert(error.message);
    } finally {
        btnConfirmArchiveProject.disabled = false;
        btnConfirmArchiveProject.textContent = 'Archivieren';
    }
});

archiveConfirmModalElement.addEventListener('hidden.bs.modal', () => {
    pendingArchiveProjectId = null;
});

// 2. PROJEKTE & ARCHIV LADEN
async function loadProjects() {
    if (projectListRequestActive) return;
    projectListRequestActive = true;
    try {
        const res = await fetch('/api/projects');
        if (!res.ok) throw new Error('Projektliste konnte nicht geladen werden.');
        const projects = await res.json();
        
        sidebarList.innerHTML = '';
        archiveTableBody.innerHTML = '';
        
        const activeProjects = projects.filter(project => !project.archived);
        const archivedProjects = projects.filter(project => project.archived);

        activeProjects.forEach(p => {
            let percent = p.total_lines > 0 ? Math.round((p.translated_lines / p.total_lines) * 100) : 0;
            let isActive = p.id === currentProjectId ? 'active' : '';
            let edtechDone = p.available_downloads?.ass ? 'done' : '';
            let transDone = p.available_downloads?.srt ? 'done' : '';
            let progressColor = p.status === 'abgeschlossen' ? 'bg-success' : 'var(--purple-accent)';
            let name = p.original_filename.replace('.srt', '');
            let safeName = escapeHtml(name);
            let safeStatus = escapeHtml(p.status);
            let canArchive = p.status === 'abgeschlossen'
                && p.available_downloads?.srt && p.available_downloads?.ass;

            let archiveButton = canArchive
                ? `<button type="button" class="archive-project-button" data-project-id="${Number(p.id)}" data-project-title="${safeName}" aria-label="${safeName} archivieren" title="Projekt archivieren">×</button>`
                : '';
            let sidebarHtml = `
            <div class="mini-project ${isActive}">
                <button type="button" class="mini-project-open" data-project-id="${Number(p.id)}" data-project-title="${safeName}" data-project-status="${safeStatus}">
                    <div class="d-flex justify-content-between align-items-start">
                        <div class="text-truncate" style="max-width: 68%;">
                            <div class="fw-bold fs-6 text-truncate">${safeName}</div>
                            <div class="text-muted" style="font-size: 0.8em;">Status: ${safeStatus}</div>
                        </div>
                        <div class="d-flex gap-1 me-1">
                            <span class="file-badge ${transDone}">SRT</span>
                            <span class="file-badge ${edtechDone}">ASS</span>
                        </div>
                    </div>
                    <div class="progress mt-2" style="height: 4px;">
                        <div class="progress-bar" style="background-color: ${progressColor}; width: ${percent}%;"></div>
                    </div>
                </button>
                ${archiveButton}
            </div>`;
            sidebarList.insertAdjacentHTML('beforeend', sidebarHtml);
        });

        archivedProjects.forEach(p => {
            const safeName = escapeHtml(p.original_filename.replace('.srt', ''));
            const safeStatus = escapeHtml(p.status);
            let badgeClass = p.status === 'abgeschlossen' ? 'bg-success' : (p.status === 'laufend' ? 'bg-primary' : 'bg-secondary');
            let archiveHtml = `
            <tr>
                <td>${safeName}</td>
                <td><span class="badge ${badgeClass}">${safeStatus}</span></td>
                <td class="text-muted small">${new Date(p.last_updated).toLocaleString()}</td>
                <td><button class="btn btn-sm btn-outline-secondary" data-project-id="${Number(p.id)}" data-project-title="${safeName}" data-project-status="${safeStatus}" data-project-archived="true">Öffnen</button></td>
            </tr>`;
            archiveTableBody.insertAdjacentHTML('beforeend', archiveHtml);
        });
        if (archivedProjects.length === 0) {
            archiveTableBody.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-4">Noch keine archivierten Projekte.</td></tr>';
        }
    } catch (e) {
        console.error("Fehler beim Laden der Projekte", e);
    } finally {
        projectListRequestActive = false;
    }
}

function startProjectListPolling() {
    if (projectListPollInterval) clearInterval(projectListPollInterval);
    projectListPollInterval = setInterval(loadProjects, 1000);
}

// 3. PROJEKT-DATEN, SETTINGS & PROMPTS LADEN
async function loadProjectToMain(id, title, status) {
    const loadSequence = ++projectLoadSequence;
    setProjectLoading(true);
    currentProjectId = id;
    projectTitle.textContent = title; // XSS-Schutz
    progressSection.style.display = 'block';
    document.getElementById('downloadLinks').classList.add('d-none');
    let availableDownloads = { srt: status === 'abgeschlossen', ass: false, csv: false };
    currentAvailableDownloads = availableDownloads;
    
    formSection.classList.add('locked');
    startBtn.textContent = 'Gesperrt';
    startBtn.disabled = true;
    updatePauseResumeButton(status);
    
    // Projektdaten für Settings abrufen
    try {
        let pRes = await fetch(`/api/project/${id}`);
        if (loadSequence !== projectLoadSequence) return;
        if(pRes.ok) {
            let pData = await pRes.json();
            translationSyncOffsetInput.value = pData.sync_offset ?? 0;
            loadedTranslationSyncOffset = translationSyncOffsetInput.value;
            setModelSelectValue(translationModelSelect, pData.translation_model || pData.gemini_model);
            setModelSelectValue(edtechModelSelect, pData.edtech_model || pData.gemini_model);
            availableDownloads = pData.available_downloads || availableDownloads;
            currentAvailableDownloads = availableDownloads;
            hasGeneratedAss = Boolean(availableDownloads.ass);
            updateTranslationPromptActions();
            updateEdtechPromptActions();
            // Formularfelder befüllen
            if (edtechSettingsForm.elements['infobox_duration']) edtechSettingsForm.elements['infobox_duration'].value = pData.infobox_duration || 9;
            if (edtechSettingsForm.elements['ass_sync_offset']) edtechSettingsForm.elements['ass_sync_offset'].value = pData.ass_sync_offset || 0;
            if (edtechSettingsForm.elements['infobox_content']) edtechSettingsForm.elements['infobox_content'].value = pData.infobox_content || 'german_only';
            if (edtechSettingsForm.elements['hl_bold']) edtechSettingsForm.elements['hl_bold'].checked = pData.hl_bold === 1 || pData.hl_bold === true;
            if (edtechSettingsForm.elements['hl_underline']) edtechSettingsForm.elements['hl_underline'].checked = pData.hl_underline === 1 || pData.hl_underline === true;
            if (edtechSettingsForm.elements['hl_color']) edtechSettingsForm.elements['hl_color'].checked = pData.hl_color === 1 || pData.hl_color === true;
            savedEdtechSettings = getEdtechSettingsSnapshot();
            updateAssRebuildButton();
        }
        
        // Prompts abrufen und in die Tabs schreiben
        let promptRes = await fetch(`/api/prompts/${id}`);
        if (loadSequence !== projectLoadSequence) return;
        if(promptRes.ok) {
            let promptData = await promptRes.json();
            promptPreviewLoaded = true;
            translationPromptChanged = false;
            translationPromptConfirmed = false;
            edtechPromptLoaded = true;
            edtechPromptChanged = false;
            edtechPromptConfirmed = false;
            renderPromptTabs(promptData, true);
            setPromptTabEnabled(true);
        }
    } catch(e) {
        if (loadSequence !== projectLoadSequence) return;
        console.error("Fehler beim Laden der Projektdetails", e);
        setProjectLoading(false);
    }

    if (loadSequence !== projectLoadSequence) return;
    
    if (status === 'abgeschlossen') {
        unlockEdtech(availableDownloads);
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
    const settingsData = new FormData(transSettingsForm);
    for (const [key, value] of settingsData.entries()) {
        formData.append(key, value);
    }

    const profileKey = formData.get('profile_key');
    const episodeKey = formData.get('episode');
    const profile = yamlMetadata[profileKey];
    const profileName = profile?.name || profileKey;
    const projectTitleText = episodeKey ? `${profileName} - ${episodeKey}` : profileName;
    formData.set('custom_translation_prompt', translationPromptInput.value);
    if (isCustomEpisodeSelected()) {
        formData.set('episode_summary_override', episodeSummaryInput.value);
    }
    formData.set('edtech_model', edtechModelSelect.value);
    projectTitle.textContent = projectTitleText;

    try {
        let uploadRes = await fetch('/api/upload', { method: 'POST', body: formData });
        let uploadData = await uploadRes.json();

        if (uploadRes.ok) {
            currentProjectId = uploadData.id;
            const startRes = await fetch(`/api/start/${currentProjectId}`, { method: 'POST' });
            if (!startRes.ok) {
                const startData = await startRes.json();
                loadProjectToMain(currentProjectId, projectTitleText, 'pausiert');
                alert("Projekt wurde angelegt, konnte aber nicht gestartet werden: " + startData.error);
                return;
            }
            loadProjectToMain(currentProjectId, projectTitleText, 'laufend');
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
    
    const pollStatus = async () => {
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

            // Nur die aufgeklappte Logbuchfläche folgt dem neuesten Eintrag.
            if (logbookCollapse) logbookCollapse.scrollTop = logbookCollapse.scrollHeight;

            // Erst ausblenden, wenn Status, Fortschritt und Logbuch im aktuellen Projekt angekommen sind.
            setProjectLoading(false);
            
            if (statusBadge) {
                statusBadge.textContent = data.status.toUpperCase();
                statusBadge.className = "badge " + (data.status === 'laufend' ? "bg-primary" : (data.status === 'abgeschlossen' ? "bg-success" : "bg-warning"));
            }
            updatePauseResumeButton(data.status);
            
            if (data.status === 'abgeschlossen') {
                currentAvailableDownloads.srt = true;
                unlockEdtech(currentAvailableDownloads);
                clearInterval(pollInterval);
                loadProjects(); 
            } else {
                edtechZone.classList.add('disabled-overlay');
                edtechStatusBox.style.display = 'block';
                edtechActiveBox.style.display = 'none';
            }
            
            if (data.status === 'Fehler' || data.status === 'pausiert') {
                if (data.status === 'Fehler') {
                    const collapse = bootstrap.Collapse.getOrCreateInstance(logbookCollapse, { toggle: false });
                    collapse.show();
                    logbookCollapse.scrollTop = logbookCollapse.scrollHeight;
                }
                clearInterval(pollInterval);
            }
        } catch (e) {
            console.error("Polling Fehler", e);
        }
    };

    pollStatus();
    pollInterval = setInterval(pollStatus, 2000);
}

// 6. NEU BUTTON & PAUSE BUTTON
btnNewProject.addEventListener('click', () => {
    setProjectLoading(false);
    currentProjectId = null;
    if (pollInterval) clearInterval(pollInterval);
    
    projectTitle.textContent = "Neues Projekt";
    formSection.classList.remove('locked');
    form.reset();
    episodeSelect.replaceChildren(new Option('Episode...', ''));
    episodeSelect.disabled = true;
    episodeSelect.required = false;
    translationPromptInput.value = '';
    translationPromptInput.disabled = true;
    promptPreviewLoaded = false;
    translationPromptChanged = false;
    translationPromptConfirmed = false;
    edtechPromptLoaded = false;
    edtechPromptChanged = false;
    edtechPromptConfirmed = false;
    updateTranslationPromptActions();
    updateEdtechPromptActions();
    setPromptTabEnabled(false);
    loadPromptPreview();
    startBtn.textContent = "Start";
    startBtn.disabled = true;
    statusBadge.textContent = 'WARTET';
    progressBar.style.width = '0%';
    progressText.textContent = '0 / 0 Zeilen';
    logContainer.innerHTML = '';
    setLogbookExpanded(false);
    
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
function unlockEdtech(availableDownloads = currentAvailableDownloads) {
    currentAvailableDownloads = availableDownloads;
    edtechZone.classList.remove('disabled-overlay');
    edtechStatusBox.style.display = 'none';
    edtechActiveBox.style.display = 'block';
    btnGenerateEdtech.disabled = false;
    btnGenerateEdtech.textContent = 'CSV generieren';
    
    document.getElementById('linkSrt').href = `/api/download/${currentProjectId}?type=srt`;
    document.getElementById('linkAss').href = `/api/download/${currentProjectId}?type=ass`;
    document.getElementById('linkCsv').href = `/api/download/${currentProjectId}?type=csv`;

    document.getElementById('linkSrt').style.display = availableDownloads.srt ? 'inline-block' : 'none';
    document.getElementById('linkAss').style.display = availableDownloads.ass ? 'inline-block' : 'none';
    document.getElementById('linkCsv').style.display = availableDownloads.csv ? 'inline-block' : 'none';
    document.getElementById('downloadLinks').classList.toggle(
        'd-none',
        !Object.values(availableDownloads).some(Boolean)
    );
    updateEdtechPromptActions();
}

function showValidationMismatches(data) {
    const dataIssues = data.data_issues || [];
    const msg = `Gefunden: ${data.ts_mismatches.length} Zeitstempel-Fehler, ${data.kw_mismatches.length} Keyword-Fehler und ${dataIssues.length} Datenhinweise.`;
    document.getElementById('fixMessage').textContent = msg;
    renderMismatchList(timestampMismatchList, data.ts_mismatches, 'Zeitstempel');
    renderMismatchList(keywordMismatchList, data.kw_mismatches, 'Keyword', dataIssues);
    btnFixKeywordsGemini.disabled = data.kw_mismatches.length === 0 && dataIssues.length === 0;
    btnFixTimestampsPython.disabled = data.ts_mismatches.length === 0;
    btnIgnoreMismatches.disabled = data.ts_mismatches.length === 0 && data.kw_mismatches.length === 0 && dataIssues.length === 0;
    fixModal.show();
}

function renderMismatchList(container, mismatches, label, dataIssues = []) {
    container.replaceChildren();
    mismatches.forEach((mismatch) => {
        const item = document.createElement('div');
        item.className = 'border-bottom pb-2 mb-2';
        const cueLabel = mismatch.cue_id ? `Cue ${mismatch.cue_id}` : `CSV-Zeile ${Number(mismatch.index) + 1}`;
        const neighborLabel = mismatch.other_cue_ids?.length ? ` | Treffer in Nachbar-Cue(s): ${mismatch.other_cue_ids.join(', ')}` : '';
        item.textContent = `${label} | ${cueLabel}: ${mismatch.keyword || 'Unbekannt'} | CSV: ${mismatch.csv_time || '-'} | SRT: ${mismatch.srt_time || '-'}${neighborLabel}`;
        container.appendChild(item);
    });
    dataIssues.forEach((issue) => {
        const item = document.createElement('div');
        item.className = 'border-bottom pb-2 mb-2 text-warning-emphasis';
        item.textContent = `Datenhinweis${issue.cue_id ? ` | Cue ${issue.cue_id}` : ''}: ${issue.message}`;
        container.appendChild(item);
    });
}

function setMismatchActionsBusy(isBusy) {
    btnFixKeywordsGemini.disabled = isBusy;
    btnFixTimestampsPython.disabled = isBusy;
    btnIgnoreMismatches.disabled = isBusy;
}

function showMismatchProgress(message) {
    validationResult.className = 'alert alert-info';
    validationResult.innerHTML = `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>${message}`;
    validationResult.classList.remove('d-none');
}

async function generateAss(ignoreValidationErrors = false) {
    btnGenerateEdtech.disabled = true;
    btnGenerateEdtech.textContent = 'Erstelle ASS...';
    const settingsData = new FormData(edtechSettingsForm);
    const payload = Object.fromEntries(settingsData.entries());
    payload.generate_csv_only = false;
    payload.ignore_validation_errors = ignoreValidationErrors;

    try {
        const response = await fetch(`/api/edtech/generate/${currentProjectId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const result = await response.json();

        if (response.status === 409 && result.status === 'validation_required') {
            showValidationMismatches(result);
            return;
        }
        if (!response.ok) throw new Error(result.error || 'ASS-Generierung fehlgeschlagen.');

        document.getElementById('downloadLinks').classList.remove('d-none');
        document.getElementById('linkAss').style.display = 'inline-block';
        currentAvailableDownloads = { srt: true, ass: true, csv: true };
        validationResult.className = 'alert alert-success';
        validationResult.textContent = 'CSV geprüft; ASS erfolgreich erstellt.';
        validationResult.classList.remove('d-none');
        hasGeneratedAss = true;
        savedEdtechSettings = getEdtechSettingsSnapshot();
        updateAssRebuildButton();
        loadProjects();
    } catch (error) {
        validationResult.className = 'alert alert-danger';
        validationResult.textContent = error.message || 'ASS-Generierung fehlgeschlagen.';
        validationResult.classList.remove('d-none');
    } finally {
        btnGenerateEdtech.disabled = false;
        btnGenerateEdtech.textContent = 'CSV generieren';
    }
}

async function validateEdtech() {
    validationResult.classList.add('d-none');
    
    try {
        const res = await fetch(`/api/edtech/validate/${currentProjectId}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Validierung fehlgeschlagen.');
        
        if (data.status === 'no_csv_yet') {
            validationResult.className = 'alert alert-info';
            validationResult.textContent = 'Keine CSV vorhanden. Bitte zuerst generieren.';
            generateAssAfterValidation = false;
        } else if (data.ts_mismatches.length === 0 && data.kw_mismatches.length === 0 && (data.data_issues || []).length === 0) {
            validationResult.className = 'alert alert-success';
            validationResult.textContent = 'CSV geprüft: keine Abweichungen gefunden.';
            if (generateAssAfterValidation) {
                generateAssAfterValidation = false;
                await generateAss();
            }
        } else {
            validationResult.className = 'alert alert-warning';
            validationResult.textContent = 'CSV enthält Abweichungen oder unsichere Cue-Zuordnungen. Bitte korrigieren oder ausdrücklich ignorieren.';
            showValidationMismatches(data);
        }
    } catch (error) {
        generateAssAfterValidation = false;
        validationResult.className = 'alert alert-danger';
        validationResult.textContent = error.message || 'Fehler bei der Validierung.';
    } finally {
        validationResult.classList.remove('d-none');
    }
}

async function applyMismatchFix(method) {
    setMismatchActionsBusy(true);
    fixModal.hide();
    const edtechMainTab = document.querySelector('[href="#ed-main"]');
    if (edtechMainTab) bootstrap.Tab.getOrCreateInstance(edtechMainTab).show();
    showMismatchProgress(
        method === 'gemini'
            ? 'Gemini prozessiert Korrekturanfrage ...'
            : method === 'python'
                ? 'Python korrigiert die Zeitstempel ...'
                : 'Abweichungen werden ignoriert ...'
    );
    
    try {
        let res = await fetch(`/api/edtech/fix/${currentProjectId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ method: method })
        });
        
        if (res.ok) {
            if (method === 'ignore') {
                validationResult.className = 'alert alert-warning';
                validationResult.textContent = 'Abweichungen ausdrücklich ignoriert.';
                validationResult.classList.remove('d-none');
                if (generateAssAfterValidation) {
                    generateAssAfterValidation = false;
                    await generateAss(true);
                }
            } else {
                await validateEdtech();
            }
        } else {
            const result = await res.json().catch(() => ({}));
            throw new Error(result.error || 'Fehler bei der Reparatur.');
        }
    } catch (e) {
        validationResult.className = 'alert alert-danger';
        validationResult.textContent = e.message || 'Netzwerkfehler bei der Reparatur.';
        validationResult.classList.remove('d-none');
    } finally {
        setMismatchActionsBusy(false);
    }
}

btnFixKeywordsGemini.addEventListener('click', () => applyMismatchFix('gemini'));
btnFixTimestampsPython.addEventListener('click', () => applyMismatchFix('python'));
btnIgnoreMismatches.addEventListener('click', () => applyMismatchFix('ignore'));

generateEdtechForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    btnGenerateEdtech.disabled = true;
    btnGenerateEdtech.textContent = 'Generiere CSV...';
    generateAssAfterValidation = true;
    document.getElementById('linkAss').style.display = 'none';
    
    const settingsData = new FormData(edtechSettingsForm);
    const payload = Object.fromEntries(settingsData.entries());
    payload.generate_csv_only = true;
    payload.force_csv_regeneration = true;
    if (edtechPromptConfirmed && edtechPromptInput.value.trim()) {
        payload.custom_edtech_prompt = edtechPromptInput.value;
    }
    
    try {
        let res = await fetch(`/api/edtech/generate/${currentProjectId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        let result = await res.json();
        
        if (res.ok) {
            currentAvailableDownloads.csv = true;
            currentAvailableDownloads.ass = false;
            hasGeneratedAss = false;
            updateAssRebuildButton();
            document.getElementById('downloadLinks').classList.remove('d-none');
            validationResult.className = 'alert alert-info';
            validationResult.textContent = 'CSV erstellt. Prüfung läuft...';
            validationResult.classList.remove('d-none');
            edtechPromptSaveStatus.textContent = edtechPromptConfirmed
                ? 'CSV mit dem geänderten Prompt erstellt.'
                : 'CSV erstellt.';
            await validateEdtech();
        } else {
            throw new Error(result.error || 'CSV-Generierung fehlgeschlagen.');
        }
    } catch (error) {
        validationResult.className = 'alert alert-danger';
        validationResult.textContent = error.message || 'Netzwerkfehler bei der CSV-Generierung.';
        validationResult.classList.remove('d-none');
    } finally {
        btnGenerateEdtech.disabled = false;
        btnGenerateEdtech.textContent = 'CSV generieren';
    }
});

btnRebuildAss.addEventListener('click', async () => {
    if (!currentProjectId || !hasGeneratedAss) return;

    generateAssAfterValidation = true;
    btnRebuildAss.disabled = true;
    btnRebuildAss.textContent = 'Prüfe CSV...';
    await validateEdtech();
    btnRebuildAss.disabled = false;
    btnRebuildAss.textContent = 'ASS erneut berechnen';
});