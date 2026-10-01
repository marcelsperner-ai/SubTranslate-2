let currentProjectId = null;
let pollInterval = null;
let projectListPollInterval = null;
let projectListRequestActive = false;
let projectLoadSequence = 0;
let generateAssAfterValidation = false;
let currentAvailableDownloads = { srt: false, ass: false, csv: false };
const openAssPreviewWindows = new Set();
const csvPreviewControls = new Map();
const previewRequestIds = new WeakMap();

// DOM Elemente
const form = document.getElementById('newProjectForm');
const formSection = document.getElementById('uploadFormSection');
const startBtn = document.getElementById('startBtn');
const seriesSelect = document.getElementById('seriesSelect');
const episodeSelect = document.getElementById('episodeSelect');
const transSettingsForm = document.getElementById('transSettingsForm');
const translationModelSelect = document.getElementById('translationModelSelect');
const translationSettingsSaveStatus = document.getElementById('translationSettingsSaveStatus');
const syncOffsetFrozenNotice = document.getElementById('syncOffsetFrozenNotice');
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
const settingsModal = new bootstrap.Modal(document.getElementById('settingsModal'));
const defaultSrtSettingsForm = document.getElementById('defaultSrtSettingsForm');
const defaultEdtechSettingsForm = document.getElementById('defaultEdtechSettingsForm');
const defaultTranslationModelSelect = document.getElementById('defaultTranslationModelSelect');
const defaultEdtechModelSelect = document.getElementById('defaultEdtechModelSelect');
const btnSaveDefaultSettings = document.getElementById('btnSaveDefaultSettings');
const settingsSaveStatus = document.getElementById('settingsSaveStatus');
const exportPathSeriesSelect = document.getElementById('exportPathSeriesSelect');
const exportDefaultSubtitlesPath = document.getElementById('exportDefaultSubtitlesPath');
const exportDefaultVocabPath = document.getElementById('exportDefaultVocabPath');
const exportSeasonRows = document.getElementById('exportSeasonRows');
const translationSyncOffsetInput = transSettingsForm.elements['sync_offset'];
const translationZone = document.getElementById('translationZone');
const btnToggleEdtechPane = document.getElementById('btnToggleEdtechPane');

// PANE-ZUSTAND: nur eines der beiden Module ist maximiert, solange EdTech gesperrt ist bleibt SRT maximiert
let edtechPaneLocked = true;
let activePane = 'srt';

function applyPaneState() {
    const edtechActive = activePane === 'edtech' && !edtechPaneLocked;
    translationZone.classList.toggle('pane-maximized', !edtechActive);
    translationZone.classList.toggle('pane-minimized', edtechActive);
    edtechZone.classList.toggle('pane-maximized', edtechActive);
    edtechZone.classList.toggle('pane-minimized', !edtechActive);
    btnToggleEdtechPane.textContent = edtechActive ? '▼' : '▲';
}

function setActivePane(pane) {
    if (pane === 'edtech' && edtechPaneLocked) return;
    activePane = pane;
    applyPaneState();
}

function lockEdtechPane() {
    edtechPaneLocked = true;
    setActivePane('srt');
}

btnToggleEdtechPane.addEventListener('click', () => {
    setActivePane(activePane === 'edtech' ? 'srt' : 'edtech');
});

translationZone.addEventListener('click', (event) => {
    if (event.target.closest('.nav-link') || event.target.closest('button')) {
        setActivePane('srt');
    }
});

edtechZone.addEventListener('click', (event) => {
    if (event.target.closest('#btnToggleEdtechPane')) return;
    if (event.target.closest('.nav-link') || event.target.closest('button')) {
        setActivePane('edtech');
    }
});

applyPaneState();
const syncOffsetWarningModal = new bootstrap.Modal(document.getElementById('syncOffsetWarningModal'));
const btnUseEdtechSyncOffset = document.getElementById('btnUseEdtechSyncOffset');
const btnKeepTranslationSyncOffset = document.getElementById('btnKeepTranslationSyncOffset');
let yamlMetadata = {};
let appDefaultSettings = null;
let exportPathsData = {};
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
let translationSettingsSaveTimer = null;
let translationSettingsSaveSequence = 0;
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

function setTranslationStarted(started) {
    translationSyncOffsetInput.disabled = started;
    syncOffsetFrozenNotice.classList.toggle('d-none', !started);
}

async function saveTranslationRuntimeSettings() {
    if (!currentProjectId) return;
    const projectId = currentProjectId;
    const saveSequence = ++translationSettingsSaveSequence;
    translationSettingsSaveStatus.textContent = 'Einstellungen werden gespeichert ...';
    try {
        const response = await fetch(`/api/project/${projectId}/translation-settings`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                batch_size: transSettingsForm.elements['batch_size'].value,
                translation_model: translationModelSelect.value
            })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Einstellungen konnten nicht gespeichert werden.');
        if (projectId === currentProjectId && saveSequence === translationSettingsSaveSequence) {
            translationSettingsSaveStatus.textContent = result.message;
        }
    } catch (error) {
        if (projectId === currentProjectId && saveSequence === translationSettingsSaveSequence) {
            translationSettingsSaveStatus.textContent = error.message;
        }
    }
}

function scheduleTranslationSettingsSave() {
    if (!currentProjectId) return;
    window.clearTimeout(translationSettingsSaveTimer);
    translationSettingsSaveTimer = window.setTimeout(saveTranslationRuntimeSettings, 300);
}

transSettingsForm.elements['batch_size'].addEventListener('change', scheduleTranslationSettingsSave);
translationModelSelect.addEventListener('change', scheduleTranslationSettingsSave);

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
    loadDefaultSettings();
    loadExportPathSettings();
});

function populateDefaultSettingsForm(settings) {
    defaultSrtSettingsForm.elements['sync_offset'].value = settings.srt.sync_offset;
    defaultSrtSettingsForm.elements['batch_size'].value = settings.srt.batch_size;
    setModelSelectValue(defaultTranslationModelSelect, settings.srt.translation_model);
    defaultEdtechSettingsForm.elements['infobox_duration'].value = settings.edtech.infobox_duration;
    defaultEdtechSettingsForm.elements['ass_sync_offset'].value = settings.edtech.ass_sync_offset;
    defaultEdtechSettingsForm.elements['infobox_content'].value = settings.edtech.infobox_content;
    defaultEdtechSettingsForm.elements['hl_bold'].checked = Boolean(settings.edtech.hl_bold);
    defaultEdtechSettingsForm.elements['hl_underline'].checked = Boolean(settings.edtech.hl_underline);
    defaultEdtechSettingsForm.elements['hl_color'].checked = Boolean(settings.edtech.hl_color);
    setModelSelectValue(defaultEdtechModelSelect, settings.edtech.edtech_model);
}

// Überträgt die globalen Defaults auf das Upload-Formular, aber nur solange kein Projekt geladen ist.
function applyDefaultsToNewProjectForms() {
    if (!appDefaultSettings || currentProjectId) return;
    translationSyncOffsetInput.value = appDefaultSettings.srt.sync_offset;
    loadedTranslationSyncOffset = translationSyncOffsetInput.value;
    transSettingsForm.elements['batch_size'].value = appDefaultSettings.srt.batch_size;
    setModelSelectValue(translationModelSelect, appDefaultSettings.srt.translation_model);
    edtechSettingsForm.elements['infobox_duration'].value = appDefaultSettings.edtech.infobox_duration;
    edtechSettingsForm.elements['ass_sync_offset'].value = appDefaultSettings.edtech.ass_sync_offset;
    edtechSettingsForm.elements['infobox_content'].value = appDefaultSettings.edtech.infobox_content;
    edtechSettingsForm.elements['hl_bold'].checked = Boolean(appDefaultSettings.edtech.hl_bold);
    edtechSettingsForm.elements['hl_underline'].checked = Boolean(appDefaultSettings.edtech.hl_underline);
    edtechSettingsForm.elements['hl_color'].checked = Boolean(appDefaultSettings.edtech.hl_color);
    setModelSelectValue(edtechModelSelect, appDefaultSettings.edtech.edtech_model);
}

async function loadDefaultSettings() {
    try {
        const response = await fetch('/api/settings/defaults');
        if (!response.ok) return;
        appDefaultSettings = await response.json();
        populateDefaultSettingsForm(appDefaultSettings);
        applyDefaultsToNewProjectForms();
    } catch (error) {
        console.error('Standard-Einstellungen konnten nicht geladen werden.', error);
    }
}

function getSeasonsForProfile(profileKey) {
    const episodes = yamlMetadata[profileKey]?.episodes || [];
    const seasons = [...new Set(episodes.filter(e => e.includes('x')).map(e => e.split('x')[0]))];
    seasons.sort((a, b) => Number(a) - Number(b));
    return seasons;
}

function populateExportPathSeriesSelect() {
    if (!exportPathSeriesSelect) return;
    const previousValue = exportPathSeriesSelect.value;
    exportPathSeriesSelect.replaceChildren();
    Object.entries(yamlMetadata).forEach(([key, profile]) => {
        // 'default' dient als Sammelbecken für Uploads ohne eigenes Serienprofil.
        const label = key === 'default' ? 'Andere (kein dediziertes Serienprofil)' : (profile.name || key);
        exportPathSeriesSelect.appendChild(new Option(label, key));
    });
    if (previousValue && yamlMetadata[previousValue]) exportPathSeriesSelect.value = previousValue;
    renderExportPathsForProfile(exportPathSeriesSelect.value);
}

function renderExportPathsForProfile(profileKey) {
    const profileData = exportPathsData[profileKey] || {};
    const defaults = profileData.default || { subtitles_path: '', vocab_path: '' };
    exportDefaultSubtitlesPath.value = defaults.subtitles_path || '';
    exportDefaultVocabPath.value = defaults.vocab_path || '';

    exportSeasonRows.replaceChildren();
    const seasons = getSeasonsForProfile(profileKey);
    if (!seasons.length) return;

    const heading = document.createElement('p');
    heading.className = 'form-label small mb-2 mt-3';
    heading.textContent = 'Staffel-Überschreibungen (optional)';
    exportSeasonRows.appendChild(heading);

    seasons.forEach(season => {
        const seasonData = profileData[season] || { subtitles_path: '', vocab_path: '' };
        const row = document.createElement('div');
        row.className = 'row g-3 mb-2 align-items-end';

        const seasonLabelCol = document.createElement('div');
        seasonLabelCol.className = 'col-md-2';
        seasonLabelCol.innerHTML = `<label class="form-label small mb-0">Staffel ${escapeHtml(season)}</label>`;

        const subtitlesCol = document.createElement('div');
        subtitlesCol.className = 'col-md-5';
        const subtitlesInput = document.createElement('input');
        subtitlesInput.type = 'text';
        subtitlesInput.className = 'form-control form-control-sm';
        subtitlesInput.dataset.season = season;
        subtitlesInput.dataset.field = 'subtitles_path';
        subtitlesInput.placeholder = 'wie Serien-Standard';
        subtitlesInput.value = seasonData.subtitles_path || '';
        subtitlesCol.appendChild(subtitlesInput);

        const vocabCol = document.createElement('div');
        vocabCol.className = 'col-md-5';
        const vocabInput = document.createElement('input');
        vocabInput.type = 'text';
        vocabInput.className = 'form-control form-control-sm';
        vocabInput.dataset.season = season;
        vocabInput.dataset.field = 'vocab_path';
        vocabInput.placeholder = 'wie Serien-Standard';
        vocabInput.value = seasonData.vocab_path || '';
        vocabCol.appendChild(vocabInput);

        row.appendChild(seasonLabelCol);
        row.appendChild(subtitlesCol);
        row.appendChild(vocabCol);
        exportSeasonRows.appendChild(row);
    });
}

if (exportPathSeriesSelect) {
    exportPathSeriesSelect.addEventListener('change', () => {
        renderExportPathsForProfile(exportPathSeriesSelect.value);
    });
}

async function loadExportPathSettings() {
    try {
        const response = await fetch('/api/settings/export-paths');
        if (!response.ok) return;
        exportPathsData = await response.json();
        if (Object.keys(yamlMetadata).length) populateExportPathSeriesSelect();
    } catch (error) {
        console.error('Export-Pfade konnten nicht geladen werden.', error);
    }
}

async function saveExportPathSettings() {
    const profileKey = exportPathSeriesSelect.value;
    if (!profileKey) return;
    const entries = [{
        season: '',
        subtitles_path: exportDefaultSubtitlesPath.value.trim(),
        vocab_path: exportDefaultVocabPath.value.trim(),
    }];
    exportSeasonRows.querySelectorAll('[data-season]').forEach(input => {
        const season = input.dataset.season;
        let entry = entries.find(e => e.season === season);
        if (!entry) {
            entry = { season, subtitles_path: '', vocab_path: '' };
            entries.push(entry);
        }
        entry[input.dataset.field] = input.value.trim();
    });
    const response = await fetch('/api/settings/export-paths', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_key: profileKey, entries }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Export-Pfade konnten nicht gespeichert werden.');
    exportPathsData[profileKey] = { default: entries[0], ...Object.fromEntries(entries.filter(e => e.season).map(e => [e.season, e])) };
}

document.getElementById('settingsModal').addEventListener('show.bs.modal', () => {
    if (appDefaultSettings) populateDefaultSettingsForm(appDefaultSettings);
    settingsSaveStatus.textContent = '';
});

btnSaveDefaultSettings.addEventListener('click', async () => {
    settingsSaveStatus.textContent = 'Wird gespeichert ...';
    const payload = {
        srt: {
            sync_offset: defaultSrtSettingsForm.elements['sync_offset'].value,
            batch_size: defaultSrtSettingsForm.elements['batch_size'].value,
            translation_model: defaultTranslationModelSelect.value,
        },
        edtech: {
            infobox_duration: defaultEdtechSettingsForm.elements['infobox_duration'].value,
            ass_sync_offset: defaultEdtechSettingsForm.elements['ass_sync_offset'].value,
            infobox_content: defaultEdtechSettingsForm.elements['infobox_content'].value,
            hl_bold: defaultEdtechSettingsForm.elements['hl_bold'].checked,
            hl_underline: defaultEdtechSettingsForm.elements['hl_underline'].checked,
            hl_color: defaultEdtechSettingsForm.elements['hl_color'].checked,
            edtech_model: defaultEdtechModelSelect.value,
        },
    };
    try {
        const response = await fetch('/api/settings/defaults', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Standard-Einstellungen konnten nicht gespeichert werden.');
        appDefaultSettings = result;
        applyDefaultsToNewProjectForms();
        await saveExportPathSettings();
        settingsModal.hide();
    } catch (error) {
        settingsSaveStatus.textContent = error.message;
    }
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
                sync_offset: translationSyncOffsetInput.value,
                translation_model: translationModelSelect.value,
                batch_size: transSettingsForm.elements['batch_size'].value
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
        populateExportPathSeriesSelect();
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
    setTranslationStarted(false);
    currentProjectId = id;
    btnNewProject.classList.remove('active');
    projectTitle.textContent = title; // XSS-Schutz
    progressSection.style.display = 'block';
    document.getElementById('previewLinks').classList.add('d-none');
    lockEdtechPane();
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
            setTranslationStarted(Boolean(pData.translation_started));
            if (transSettingsForm.elements['batch_size']) transSettingsForm.elements['batch_size'].value = pData.batch_size || 40;
            setModelSelectValue(translationModelSelect, pData.translation_model || pData.gemini_model);
            setModelSelectValue(edtechModelSelect, pData.edtech_model || pData.gemini_model);
            translationSettingsSaveStatus.textContent = pData.translation_started
                ? 'Änderungen an Batch-Größe und Modell gelten beim nächsten Start oder Fortsetzen.'
                : '';
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
        lockEdtechPane();
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
                lockEdtechPane();
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
    setTranslationStarted(false);
    currentProjectId = null;
    btnNewProject.classList.add('active');
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
    lockEdtechPane();
    btnPauseResume.style.display = 'none';
    applyDefaultsToNewProjectForms();
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
const previewLinks = document.getElementById('previewLinks');

function setPreviewAvailability(availableDownloads) {
    previewLinks.querySelectorAll('[data-preview-type]').forEach((button) => {
        button.style.display = availableDownloads[button.dataset.previewType] ? 'inline-block' : 'none';
    });
    previewLinks.classList.toggle('d-none', !Object.values(availableDownloads).some(Boolean));
}

function createPreviewWindow(type) {
    const popup = window.open('', '_blank', 'popup=yes,width=1440,height=960,resizable=yes,scrollbars=yes');
    if (!popup) {
        alert('Das Vorschaufenster wurde vom Browser blockiert. Bitte Pop-ups für diese Seite erlauben.');
        return null;
    }
    popup.document.open();
    popup.document.write(`<!doctype html>
        <html lang="de">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Vorschau</title>
            <style>
                :root { color-scheme: light; font: 15px/1.5 system-ui, sans-serif; color: #20262b; background: #f5f6f7; }
                * { box-sizing: border-box; }
                body { margin: 0; }
                main { max-width: 1500px; margin: 0 auto; padding: 28px 32px 48px; }
                h1 { margin: 0 0 16px; font-size: 1.5rem; font-weight: 650; }
                #preview-status { margin: 12px 0; color: #59636c; }
                .table-wrap { overflow: auto; max-height: calc(100vh - 120px); background: white; border: 1px solid #d9dee2; }
                table { width: 100%; border-collapse: collapse; }
                table.ass-table { width: max-content; min-width: 0; }
                th, td { padding: 10px 12px; border-bottom: 1px solid #e5e8ea; text-align: left; vertical-align: top; }
                th { position: sticky; top: 0; z-index: 1; background: #edf0f2; font-size: .84rem; white-space: nowrap; }
                td { white-space: pre-wrap; overflow-wrap: anywhere; }
                .timestamp { min-width: 210px; color: #4d5962; font: 13px/1.5 ui-monospace, monospace; white-space: nowrap; }
                .subtitle { min-width: 380px; }
                .cue-number { min-width: 72px; text-align: right; color: #59636c; font: 13px/1.5 ui-monospace, monospace; }
                .srt-text { min-width: 320px; padding: 12px; white-space: pre-wrap; unicode-bidi: plaintext; background: #000; color: #fff; }
                .srt-original { min-width: 320px; }
                .ass-timestamp { min-width: 0; white-space: nowrap; }
                .ass-subtitle { width: max-content; min-width: 0; max-width: min(70vw, 900px); padding: 8px 12px; background: #000; color: #fff; white-space: pre-wrap; overflow-wrap: anywhere; unicode-bidi: plaintext; }
                .ass-original { background: #000; }
                .ass-original.is-empty { background: transparent; }
                .ass-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
                .ass-filter { display: inline-flex; align-items: center; gap: 6px; font-weight: 400; cursor: pointer; }
                .ass-filter input { margin: 0; }
                .csv-preview-actions { display: flex; flex-wrap: wrap; gap: 6px; min-width: 0; margin-bottom: 8px; }
                .csv-preview-actions button { border: 1px solid #84919a; border-radius: 4px; background: #fff; color: #20262b; padding: 4px 8px; font: inherit; font-size: .8rem; cursor: pointer; }
                .csv-preview-actions button.primary { border-color: #176b58; background: #176b58; color: #fff; }
                .csv-preview-actions button:disabled { opacity: .6; cursor: wait; }
                .csv-row-actions { width: 1%; padding-right: 5px; padding-left: 5px; text-align: center; white-space: nowrap; }
                .csv-cell-editor { display: block; width: 100%; min-width: 150px; min-height: 2rem; padding: 4px 6px; border: 1px solid transparent; background: transparent; color: inherit; font: inherit; overflow: hidden; resize: none; }
                .csv-cell-editor:focus { border-color: #6b9b8e; outline: 2px solid #d3e7e1; background: #fff; }
                .csv-delete-row { width: 28px; height: 28px; padding: 0 !important; font-size: 1.2rem !important; line-height: 1; }
                .csv-subtitle-preview { min-width: 220px; max-width: 420px; padding: 8px 10px; background: #000; color: #fff; white-space: pre-wrap; overflow-wrap: anywhere; unicode-bidi: plaintext; }
                .empty { padding: 20px; color: #59636c; }
                @media (max-width: 700px) { main { padding: 18px 12px 32px; } .timestamp { min-width: 170px; } .subtitle { min-width: 260px; } }
            </style>
        </head>
        <body><main><h1 id="preview-title"></h1><div id="preview-status">Vorschau wird geladen ...</div><div id="preview-content"></div></main></body>
        </html>`);
    popup.document.close();
    popup.document.title = `${type.toUpperCase()}-Vorschau`;
    popup.document.getElementById('preview-title').textContent = `${type.toUpperCase()}-Vorschau`;
    return popup;
}

function appendPreviewTable(popup, headings, rows, tableClass = '') {
    const document = popup.document;
    const wrap = document.createElement('div');
    wrap.className = 'table-wrap';
    const table = document.createElement('table');
    if (tableClass) table.className = tableClass;
    const head = document.createElement('thead');
    const headRow = document.createElement('tr');
    headings.forEach((heading) => {
        const cell = document.createElement('th');
        cell.scope = 'col';
        if (heading instanceof document.defaultView.Node) cell.append(heading);
        else cell.textContent = heading;
        headRow.append(cell);
    });
    head.append(headRow);
    const body = document.createElement('tbody');
    rows.forEach((row) => body.append(row));
    table.append(head, body);
    wrap.append(table);
    document.getElementById('preview-content').replaceChildren(wrap);
    document.getElementById('preview-status').textContent = `${rows.length} Einträge`;
}

function showPreviewMessage(popup, message) {
    if (popup.closed) return;
    const status = popup.document.getElementById('preview-status');
    status.textContent = message;
}

function resizeCsvEditor(editor) {
    editor.style.height = 'auto';
    editor.style.height = `${editor.scrollHeight}px`;
}

function createSrtCueIndex(text, offsetMs = 0) {
    const byCueId = new Map();
    const byStartTime = new Map();
    parseSrtPreview(text).forEach((cue) => {
        if (cue.cueId && !byCueId.has(cue.cueId)) byCueId.set(cue.cueId, cue);
        const timestampKey = srtStartTimeKey(cue.start, offsetMs);
        if (timestampKey !== null && !byStartTime.has(timestampKey)) byStartTime.set(timestampKey, cue);
    });
    return {byCueId, byStartTime};
}

function findCsvSubtitleCue(index, record) {
    const cueId = String(record.Cue_ID || record.cue_id || '').trim();
    if (cueId && index.byCueId.has(cueId)) return index.byCueId.get(cueId);
    const timestamp = String(record.Zeitstempel || record.timestamp || '').trim();
    const timestampKey = srtStartTimeKey(timestamp);
    return timestampKey === null ? null : index.byStartTime.get(timestampKey) || null;
}

function createCsvSubtitleCell(popup, cue) {
    const cell = popup.document.createElement('td');
    const content = popup.document.createElement('div');
    content.className = 'csv-subtitle-preview';
    content.dir = 'auto';
    if (cue) appendSrtMarkup(popup.document, content, cue.text);
    else content.textContent = '—';
    cell.append(content);
    return cell;
}

function renderCsvPreview(popup, rows, fieldnames, projectId, farsiSrt = '', germanSrt = '', translationSyncOffsetMs = 0) {
    if (!fieldnames.length) {
        showPreviewMessage(popup, 'Keine CSV-Daten vorhanden.');
        return;
    }
    const farsiCueIndex = createSrtCueIndex(farsiSrt);
    const germanCueIndex = createSrtCueIndex(germanSrt, Number(translationSyncOffsetMs || 0));
    const actions = popup.document.createElement('div');
    actions.className = 'csv-preview-actions';
    const saveButton = popup.document.createElement('button');
    saveButton.type = 'button';
    saveButton.textContent = 'Speichern';
    saveButton.hidden = true;
    const discardButton = popup.document.createElement('button');
    discardButton.type = 'button';
    discardButton.textContent = 'Änderungen verwerfen';
    discardButton.hidden = true;
    const rebuildButton = popup.document.createElement('button');
    rebuildButton.type = 'button';
    rebuildButton.className = 'primary';
    rebuildButton.textContent = 'ASS neu generieren';
    rebuildButton.hidden = true;
    actions.append(saveButton, discardButton, rebuildButton);
    const headings = ['', ...fieldnames, 'Deutscher Untertitel (SRT)', 'Farsi-Untertitel (SRT)'];
    const tableRows = rows.map((record) => {
        const row = popup.document.createElement('tr');
        const controls = popup.document.createElement('td');
        controls.className = 'csv-row-actions';
        const deleteButton = popup.document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'csv-delete-row';
        deleteButton.textContent = '×';
        deleteButton.title = 'Zeile löschen';
        deleteButton.setAttribute('aria-label', 'CSV-Zeile löschen');
        controls.append(deleteButton);
        row.append(controls);
        fieldnames.forEach((fieldname) => {
            const cell = popup.document.createElement('td');
            const editor = popup.document.createElement('textarea');
            editor.className = 'csv-cell-editor';
            editor.rows = 1;
            editor.value = record[fieldname] ?? '';
            editor.setAttribute('aria-label', fieldname);
            cell.append(editor);
            row.append(cell);
        });
        row.append(
            createCsvSubtitleCell(popup, findCsvSubtitleCue(germanCueIndex, record)),
            createCsvSubtitleCell(popup, findCsvSubtitleCue(farsiCueIndex, record))
        );
        return row;
    });
    appendPreviewTable(popup, headings, tableRows, 'csv-preview-table');
    popup.document.getElementById('preview-content').prepend(actions);
    const table = popup.document.querySelector('.csv-preview-table');
    table.querySelector('thead th:first-child').className = 'csv-row-actions';
    table.querySelectorAll('.csv-cell-editor').forEach(resizeCsvEditor);
    const body = table.tBodies[0];
    let dirty = false;
    const markDirty = () => {
        dirty = true;
        saveButton.hidden = false;
        discardButton.hidden = false;
        rebuildButton.hidden = true;
        popup.document.getElementById('preview-status').textContent = 'Änderungen noch nicht gespeichert.';
    };
    body.addEventListener('input', (event) => {
        if (!event.target.matches('.csv-cell-editor')) return;
        resizeCsvEditor(event.target);
        markDirty();
    });
    body.addEventListener('click', (event) => {
        if (!event.target.closest('.csv-delete-row')) return;
        event.target.closest('tr').remove();
        markDirty();
    });
    saveButton.addEventListener('click', async () => {
        if (!dirty) return;
        const editors = Array.from(body.querySelectorAll('.csv-cell-editor, .csv-delete-row'));
        editors.forEach((editor) => { editor.disabled = true; });
        const editedRows = Array.from(body.rows, (row) => {
            const editors = Array.from(row.querySelectorAll('.csv-cell-editor'));
            return Object.fromEntries(fieldnames.map((fieldname, index) => [fieldname, editors[index].value]));
        });
        saveButton.disabled = true;
        saveButton.textContent = 'Speichert...';
        try {
            const response = await fetch(`/api/edtech/csv/${projectId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({rows: editedRows})
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'CSV konnte nicht gespeichert werden.');
            dirty = false;
            saveButton.hidden = true;
            discardButton.hidden = true;
            rebuildButton.hidden = false;
            popup.document.getElementById('preview-status').textContent = `${result.row_count} CSV-Zeilen gespeichert.`;
        } catch (error) {
            showPreviewMessage(popup, error.message || 'CSV konnte nicht gespeichert werden.');
        } finally {
            editors.forEach((editor) => { editor.disabled = false; });
            saveButton.disabled = false;
            saveButton.textContent = 'Speichern';
        }
    });
    discardButton.addEventListener('click', async () => {
        if (!popup.confirm('Ungespeicherte Änderungen verwerfen und die zuletzt gespeicherte CSV neu laden?')) return;
        discardButton.disabled = true;
        popup.document.getElementById('preview-status').textContent = 'Gespeicherte CSV wird neu geladen...';
        try {
            const response = await fetch(`/api/edtech/preview/${projectId}`);
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'CSV konnte nicht neu geladen werden.');
            renderCsvPreview(
                popup,
                result.csv || [],
                result.csv_fieldnames || [],
                projectId,
                result.srt || '',
                result.original_srt || '',
                result.translation_sync_offset_ms || 0
            );
        } catch (error) {
            showPreviewMessage(popup, error.message || 'CSV konnte nicht neu geladen werden.');
        } finally {
            discardButton.disabled = false;
        }
    });
    rebuildButton.addEventListener('click', async () => {
        if (projectId !== currentProjectId) {
            showPreviewMessage(popup, 'Bitte zuerst dieses Projekt im Hauptfenster auswählen.');
            return;
        }
        rebuildButton.disabled = true;
        generateAssAfterValidation = true;
        popup.document.getElementById('preview-status').textContent = 'CSV wird geprüft und die ASS neu generiert...';
        const generated = await validateEdtech();
        if (generated) {
            showPreviewMessage(popup, 'ASS neu generiert.');
        } else if (generateAssAfterValidation) {
            showPreviewMessage(popup, 'CSV-Prüfung benötigt Aufmerksamkeit. Hinweise und Optionen sind im Hauptfenster geöffnet.');
        } else {
            showPreviewMessage(popup, 'ASS-Neugenerierung fehlgeschlagen. Details stehen im Hauptfenster.');
        }
        rebuildButton.disabled = false;
    });
    const projectControls = csvPreviewControls.get(projectId) || new Set();
    projectControls.forEach((control) => {
        if (control.popup === popup) projectControls.delete(control);
    });
    projectControls.add({popup, saveButton, rebuildButton});
    csvPreviewControls.set(projectId, projectControls);
    popup.addEventListener('pagehide', () => {
        projectControls.forEach((control) => {
            if (control.popup === popup) projectControls.delete(control);
        });
    }, {once: true});
}

function parseSrtPreview(text) {
    return text.trim().split(/\r?\n\s*\r?\n/).flatMap((block) => {
        const lines = block.split(/\r?\n/);
        const timeIndex = lines.findIndex((line) => line.includes('-->'));
        if (timeIndex < 0) return [];
        const [start, end] = lines[timeIndex].split('-->').map((stamp) => stamp.trim());
        const cueId = [...lines.slice(0, timeIndex)].reverse().find((line) => /^\d+$/.test(line.trim()))?.trim() || '';
        return [{cueId, start, end, text: lines.slice(timeIndex + 1).join('\n')}];
    });
}

function appendSrtMarkup(document, parent, text) {
    const source = new document.defaultView.DOMParser().parseFromString(text, 'text/html');
    const allowedTags = new Set(['b', 'strong', 'i', 'em', 'u', 's', 'strike', 'del', 'br', 'font', 'span']);
    const copyNode = (sourceNode, target) => {
        if (sourceNode.nodeType === document.defaultView.Node.TEXT_NODE) {
            target.append(document.createTextNode(sourceNode.nodeValue));
            return;
        }
        if (sourceNode.nodeType !== document.defaultView.Node.ELEMENT_NODE) return;
        const tag = sourceNode.tagName.toLowerCase();
        if (!allowedTags.has(tag)) {
            sourceNode.childNodes.forEach((child) => copyNode(child, target));
            return;
        }
        if (tag === 'br') {
            target.append(document.createElement('br'));
            return;
        }
        const renderedTag = tag === 'font' ? 'span' : tag;
        const element = document.createElement(renderedTag);
        const color = tag === 'font' ? sourceNode.getAttribute('color') : sourceNode.style.color;
        if (color) {
            element.style.color = color;
        }
        sourceNode.childNodes.forEach((child) => copyNode(child, element));
        target.append(element);
    };
    source.body.childNodes.forEach((node) => copyNode(node, parent));
}

function renderSrtPreview(popup, text, originalText) {
    const cues = parseSrtPreview(text);
    const originalCues = new Map(parseSrtPreview(originalText).map((cue) => [cue.cueId, cue]));
    const tableRows = cues.map((cue) => {
        const row = popup.document.createElement('tr');
        const cueNumber = popup.document.createElement('td');
        cueNumber.className = 'cue-number';
        cueNumber.textContent = cue.cueId;
        const timestamp = popup.document.createElement('td');
        timestamp.className = 'timestamp';
        timestamp.textContent = `${cue.start} – ${cue.end}`;
        const subtitle = popup.document.createElement('td');
        subtitle.className = 'subtitle srt-text';
        subtitle.dir = 'auto';
        appendSrtMarkup(popup.document, subtitle, cue.text);
        const original = popup.document.createElement('td');
        original.className = 'subtitle srt-text srt-original';
        original.dir = 'auto';
        const originalCue = originalCues.get(cue.cueId);
        if (originalCue) appendSrtMarkup(popup.document, original, originalCue.text);
        else original.textContent = '—';
        row.append(cueNumber, timestamp, subtitle, original);
        return row;
    });
    if (!tableRows.length) {
        showPreviewMessage(popup, 'Keine SRT-Untertitel vorhanden.');
        return;
    }
    appendPreviewTable(popup, ['Cue-Nr.', 'Zeitstempel', 'Gerenderter Untertitel', 'Deutsches Original'], tableRows);
}

function assColorToCss(value, fallback) {
    const match = String(value || '').match(/&H([0-9A-F]{6,8})&?/i);
    if (!match) return fallback;
    const hex = match[1].padStart(8, '0');
    const alpha = hex.length === 8 ? 255 - parseInt(hex.slice(0, 2), 16) : 255;
    const blue = parseInt(hex.slice(-6, -4), 16);
    const green = parseInt(hex.slice(-4, -2), 16);
    const red = parseInt(hex.slice(-2), 16);
    return `rgba(${red}, ${green}, ${blue}, ${alpha / 255})`;
}

function srtStartTimeKey(timestamp, offsetMs = 0) {
    const match = String(timestamp || '').match(/^(\d+):(\d{2}):(\d{2}),(\d{1,3})$/);
    if (!match) return null;
    const milliseconds = Number(match[4].padEnd(3, '0'));
    const totalMilliseconds = ((Number(match[1]) * 60 + Number(match[2])) * 60 + Number(match[3])) * 1000
        + milliseconds + Number(offsetMs || 0);
    const dayCentiseconds = 24 * 60 * 60 * 100;
    return ((Math.floor(totalMilliseconds / 10) % dayCentiseconds) + dayCentiseconds) % dayCentiseconds;
}

function assStartTimeKey(timestamp) {
    const match = String(timestamp || '').match(/^(\d+):(\d{2}):(\d{2})\.(\d{1,2})$/);
    if (!match) return null;
    return ((Number(match[1]) * 60 + Number(match[2])) * 60 + Number(match[3])) * 100
        + Number(match[4].padEnd(2, '0'));
}

function parseAssFile(text) {
    const styles = {};
    const events = [];
    let section = '';
    let styleFields = [];
    let eventFields = [];
    let playResX = 1920;
    let playResY = 1080;
    text.split(/\r?\n/).forEach((line) => {
        const trimmed = line.trim();
        if (/^\[.*\]$/.test(trimmed)) {
            section = trimmed.toLowerCase();
        } else if (section === '[script info]') {
            const [key, ...value] = trimmed.split(':');
            if (key?.toLowerCase() === 'playresx') playResX = Number(value.join(':').trim()) || playResX;
            if (key?.toLowerCase() === 'playresy') playResY = Number(value.join(':').trim()) || playResY;
        } else if (section === '[v4+ styles]') {
            if (trimmed.toLowerCase().startsWith('format:')) {
                styleFields = trimmed.slice(trimmed.indexOf(':') + 1).split(',').map((field) => field.trim().toLowerCase());
            } else if (trimmed.toLowerCase().startsWith('style:')) {
                const values = trimmed.slice(trimmed.indexOf(':') + 1).split(',');
                const style = Object.fromEntries(styleFields.map((field, index) => [field, (values[index] || '').trim()]));
                if (style.name) styles[style.name] = style;
            }
        } else if (section === '[events]') {
            if (trimmed.toLowerCase().startsWith('format:')) {
                eventFields = trimmed.slice(trimmed.indexOf(':') + 1).split(',').map((field) => field.trim().toLowerCase());
            } else if (trimmed.toLowerCase().startsWith('dialogue:')) {
                const values = trimmed.slice(trimmed.indexOf(':') + 1).split(',');
                if (eventFields.length) {
                    const textIndex = eventFields.indexOf('text');
                    const fields = values.slice(0, textIndex).concat([values.slice(textIndex).join(',')]);
                    events.push(Object.fromEntries(eventFields.map((field, index) => [field, (fields[index] || '').trim()])));
                }
            }
        }
    });
    return {styles, events, playResX, playResY};
}

function assStyleState(style, playResY) {
    return {
        fontname: style?.fontname || 'Arial',
        fontsize: Number(style?.fontsize) || 50,
        color: style?.primarycolour || '&H00FFFFFF&',
        bold: Number(style?.bold || 0) !== 0,
        italic: Number(style?.italic || 0) !== 0,
        underline: Number(style?.underline || 0) !== 0,
        strikeout: Number(style?.strikeout || 0) !== 0,
        backcolour: style?.backcolour || '&H80000000&',
        borderstyle: Number(style?.borderstyle) || 1,
        outline: Number(style?.outline) || 0,
        shadow: Number(style?.shadow) || 0,
        alignment: Number(style?.alignment) || 2,
        marginl: Number(style?.marginl) || 0,
        marginr: Number(style?.marginr) || 0,
        marginv: Number(style?.marginv) || 0,
        playresy: playResY
    };
}

function renderAssText(document, rawText, initialState, styles) {
    const content = document.createDocumentFragment();
    const renderScale = 440 / (initialState.playresy || 1080);
    let state = {...initialState};
    const appendText = (value) => {
        const clean = value.replace(/[\u202A-\u202E\u2066-\u2069]/g, '')
            .replace(/\\N|\\n/g, '\n').replace(/\\h/g, '\u00a0').replace(/\\\\/g, '\\');
        clean.split('\n').forEach((part, index) => {
            if (index) content.append(document.createElement('br'));
            if (!part) return;
            const span = document.createElement('span');
            span.textContent = part;
            span.dir = 'auto';
            span.style.color = assColorToCss(state.color, '#fff');
            span.style.fontFamily = `${state.fontname}, sans-serif`;
            span.style.fontSize = `${state.fontsize * renderScale}px`;
            span.style.fontWeight = state.bold ? 'bold' : 'normal';
            span.style.fontStyle = state.italic ? 'italic' : 'normal';
            span.style.textDecoration = [state.underline ? 'underline' : '', state.strikeout ? 'line-through' : ''].filter(Boolean).join(' ');
            const outline = Math.max(0, Math.min(state.outline * renderScale, 8));
            const shadow = Math.max(0, Math.min(state.shadow * renderScale, 8));
            if (outline || shadow) {
                const radius = outline + shadow;
                span.style.textShadow = `-${radius}px 0 #000, ${radius}px 0 #000, 0 -${radius}px #000, 0 ${radius}px #000`;
            }
            if (state.borderstyle === 3) {
                span.style.backgroundColor = assColorToCss(state.backcolour, 'transparent');
                span.style.padding = `${Math.max(2, outline)}px`;
            }
            content.append(span);
        });
    };
    const tokens = rawText.match(/\{[^}]*\}|[^{}]+/g) || [];
    tokens.forEach((token) => {
        if (!token.startsWith('{')) {
            appendText(token);
            return;
        }
        const tags = token.slice(1, -1).match(/\\(?:1?c|b|i|u|s|fs|fn|r|an|a)(?:[^\\]*)?/gi) || [];
        tags.forEach((tag) => {
            const match = tag.match(/^\\(1?c|b|i|u|s|fs|fn|r|an|a)(.*)$/i);
            if (!match) return;
            const name = match[1].toLowerCase();
            const value = match[2].trim();
            if (name === 'r') state = assStyleState(styles[value] || styles[initialState.stylename] || {}, initialState.playresy);
            else if (name === 'c' || name === '1c') state.color = value ? value.replace(/&?$/, '&') : initialState.color;
            else if (name === 'b') state.bold = Number(value) !== 0;
            else if (name === 'i') state.italic = Number(value) !== 0;
            else if (name === 'u') state.underline = Number(value) !== 0;
            else if (name === 's') state.strikeout = Number(value) !== 0;
            else if (name === 'fs') state.fontsize = Number(value) || state.fontsize;
            else if (name === 'fn') state.fontname = value || state.fontname;
            else if (name === 'an' || name === 'a') state.alignment = Number(value) || state.alignment;
        });
    });
    return content;
}

function renderAssPreview(popup, text, originalText, assSyncOffsetMs = 0, translationSyncOffsetMs = 0) {
    const parsed = parseAssFile(text);
    if (!parsed.events.length) {
        showPreviewMessage(popup, 'Keine ASS-Events vorhanden.');
        return;
    }
    const originalByStartTime = new Map();
    parseSrtPreview(originalText).forEach((cue) => {
        const totalOffsetMs = Number(assSyncOffsetMs || 0) + Number(translationSyncOffsetMs || 0);
        const key = srtStartTimeKey(cue.start, totalOffsetMs);
        if (key === null) return;
        if (!originalByStartTime.has(key)) originalByStartTime.set(key, []);
        originalByStartTime.get(key).push(cue);
    });
    const tableRows = parsed.events.map((event) => {
        const row = popup.document.createElement('tr');
        row.dataset.style = String(event.style || '').toLowerCase();
        const timestamp = popup.document.createElement('td');
        timestamp.className = 'timestamp ass-timestamp';
        timestamp.textContent = `${event.start} – ${event.end}`;
        const subtitle = popup.document.createElement('td');
        subtitle.className = 'ass-subtitle';
        subtitle.dir = 'auto';
        const style = parsed.styles[event.style] || parsed.styles.Standard || {};
        const state = assStyleState(style, parsed.playResY);
        state.stylename = event.style;
        state.color = style.primarycolour || '&H00FFFFFF&';
        subtitle.append(renderAssText(popup.document, event.text, state, parsed.styles));
        const original = popup.document.createElement('td');
        original.className = 'ass-subtitle ass-original';
        original.dir = 'auto';
        if (row.dataset.style === 'infobox') {
            original.classList.add('is-empty');
        } else {
            const matches = originalByStartTime.get(assStartTimeKey(event.start));
            const originalCue = matches?.shift();
            if (originalCue) appendSrtMarkup(popup.document, original, originalCue.text);
            else original.classList.add('is-empty');
        }
        row.append(timestamp, subtitle, original);
        return row;
    });
    const header = popup.document.createElement('div');
    header.className = 'ass-header';
    const title = popup.document.createElement('span');
    title.textContent = 'Gerenderter Untertitel';
    const filterLabel = popup.document.createElement('label');
    filterLabel.className = 'ass-filter';
    const filter = popup.document.createElement('input');
    filter.type = 'checkbox';
    const filterText = popup.document.createElement('span');
    filterText.textContent = 'Nur InfoBoxen';
    filterLabel.append(filter, filterText);
    header.append(title, filterLabel);
    appendPreviewTable(popup, ['Zeitstempel', header, 'Deutsches Original'], tableRows, 'ass-table');
    filter.addEventListener('change', () => {
        let visibleRows = 0;
        tableRows.forEach((row) => {
            row.hidden = filter.checked && row.dataset.style !== 'infobox';
            if (!row.hidden) visibleRows += 1;
        });
        popup.document.getElementById('preview-status').textContent = filter.checked
            ? `${visibleRows} von ${tableRows.length} InfoBoxen`
            : `${tableRows.length} Einträge`;
    });
}

function updateCsvPreviewControls(projectId) {
    const controls = csvPreviewControls.get(projectId);
    if (!controls) return;
    controls.forEach((control) => {
        if (control.popup.closed) {
            controls.delete(control);
            return;
        }
        if (!control.saveButton.hidden) return;
        control.rebuildButton.hidden = true;
        control.popup.document.getElementById('preview-status').textContent = 'ASS neu generiert.';
    });
}

async function loadPreviewIntoPopup(popup, type, projectId) {
    const requestId = (previewRequestIds.get(popup) || 0) + 1;
    previewRequestIds.set(popup, requestId);
    try {
        const response = await fetch(`/api/edtech/preview/${projectId}`);
        const files = await response.json();
        if (!response.ok) throw new Error(files.error || 'Vorschau konnte nicht geladen werden.');
        if (popup.closed || previewRequestIds.get(popup) !== requestId) return;
        if (type === 'csv') renderCsvPreview(
            popup,
            files.csv || [],
            files.csv_fieldnames || [],
            projectId,
            files.srt || '',
            files.original_srt || '',
            files.translation_sync_offset_ms || 0
        );
        else if (type === 'srt') renderSrtPreview(popup, files.srt || '', files.original_srt || '');
        else renderAssPreview(
            popup,
            files.ass || '',
            files.original_srt || '',
            files.ass_sync_offset_ms || 0,
            files.translation_sync_offset_ms || 0
        );
    } catch (error) {
        if (!popup.closed && previewRequestIds.get(popup) === requestId) {
            showPreviewMessage(popup, error.message || 'Vorschau konnte nicht geladen werden.');
        }
    }
}

async function refreshOpenAssPreviews(projectId) {
    const refreshes = [];
    openAssPreviewWindows.forEach((popup) => {
        if (popup.closed) openAssPreviewWindows.delete(popup);
        else refreshes.push(loadPreviewIntoPopup(popup, 'ass', projectId));
    });
    await Promise.all(refreshes);
}

previewLinks.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-preview-type]');
    if (!button || !currentProjectId) return;
    const type = button.dataset.previewType;
    const projectId = currentProjectId;
    const popup = createPreviewWindow(type);
    if (!popup) return;
    if (type === 'ass') {
        openAssPreviewWindows.add(popup);
        popup.addEventListener('pagehide', () => openAssPreviewWindows.delete(popup), {once: true});
    }
    await loadPreviewIntoPopup(popup, type, projectId);
});

function unlockEdtech(availableDownloads = currentAvailableDownloads) {
    const wasLocked = edtechPaneLocked;
    currentAvailableDownloads = availableDownloads;
    edtechZone.classList.remove('disabled-overlay');
    edtechStatusBox.style.display = 'none';
    edtechActiveBox.style.display = 'block';
    btnGenerateEdtech.disabled = false;
    btnGenerateEdtech.textContent = 'CSV generieren';
    
    setPreviewAvailability(availableDownloads);
    updateEdtechPromptActions();

    edtechPaneLocked = false;
    if (wasLocked) {
        setActivePane('edtech');
    } else {
        applyPaneState();
    }
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
            return false;
        }
        if (!response.ok) throw new Error(result.error || 'ASS-Generierung fehlgeschlagen.');

        currentAvailableDownloads = { srt: true, ass: true, csv: true };
        setPreviewAvailability(currentAvailableDownloads);
        validationResult.className = 'alert alert-success';
        validationResult.textContent = 'CSV geprüft; ASS erfolgreich erstellt.';
        validationResult.classList.remove('d-none');
        hasGeneratedAss = true;
        savedEdtechSettings = getEdtechSettingsSnapshot();
        updateAssRebuildButton();
        loadProjects();
        updateCsvPreviewControls(currentProjectId);
        await refreshOpenAssPreviews(currentProjectId);
        return true;
    } catch (error) {
        validationResult.className = 'alert alert-danger';
        validationResult.textContent = error.message || 'ASS-Generierung fehlgeschlagen.';
        validationResult.classList.remove('d-none');
        return false;
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
            return false;
        } else if (data.ts_mismatches.length === 0 && data.kw_mismatches.length === 0 && (data.data_issues || []).length === 0) {
            validationResult.className = 'alert alert-success';
            validationResult.textContent = 'CSV geprüft: keine Abweichungen gefunden.';
            if (generateAssAfterValidation) {
                generateAssAfterValidation = false;
                return await generateAss();
            }
            return true;
        } else {
            validationResult.className = 'alert alert-warning';
            validationResult.textContent = 'CSV enthält Abweichungen oder unsichere Cue-Zuordnungen. Bitte korrigieren oder ausdrücklich ignorieren.';
            showValidationMismatches(data);
            return false;
        }
    } catch (error) {
        generateAssAfterValidation = false;
        validationResult.className = 'alert alert-danger';
        validationResult.textContent = error.message || 'Fehler bei der Validierung.';
        return false;
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
    setPreviewAvailability({...currentAvailableDownloads, ass: false});
    
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
            setPreviewAvailability(currentAvailableDownloads);
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