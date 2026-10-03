(function () {
    const page = document.querySelector('.flashcards-page');
    const tId = page.dataset.tId;
    const projectMissing = page.dataset.projectMissing === 'true';

    const statusEl = document.getElementById('fcStatus');
    const deckEl = document.getElementById('fcDeck');
    const cardEl = document.getElementById('fcCard');
    const progressCurrentEl = document.getElementById('fcProgressCurrent');
    const progressTotalEl = document.getElementById('fcProgressTotal');
    const frontLabelEl = document.getElementById('fcFrontLabel');
    const frontTextEl = document.getElementById('fcFrontText');
    const frontHintEl = document.getElementById('fcFrontHint');
    const backLabelEl = document.getElementById('fcBackLabel');
    const backTextEl = document.getElementById('fcBackText');
    const backContextEl = document.getElementById('fcBackContext');
    const btnPrev = document.getElementById('btnFcPrev');
    const btnNext = document.getElementById('btnFcNext');
    const btnFlip = document.getElementById('btnFcFlip');
    const btnShuffle = document.getElementById('btnFcShuffle');
    const btnDirDeFa = document.getElementById('btnDirDeFa');
    const btnDirFaDe = document.getElementById('btnDirFaDe');
    const fcDirectionGroup = document.getElementById('fcDirectionGroup');
    const btnModeFlip = document.getElementById('btnModeFlip');
    const btnModeCloze = document.getElementById('btnModeCloze');

    let cards = [];
    let order = [];
    let flipOrder = [];
    let clozeOrder = [];
    let currentIndex = 0;
    let direction = 'de-fa';
    let mode = 'flip';

    function showStatus(message, isError = false) {
        statusEl.textContent = message;
        statusEl.classList.toggle('is-error', isError);
        statusEl.classList.remove('d-none');
        deckEl.classList.add('d-none');
    }

    function escapeRegExp(text) {
        return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    function escapeHtml(text) {
        return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function foldQuotes(text) {
        return text.replace(/[\u2018\u2019\u00b4`]/g, "'").toLowerCase();
    }

    function findParts(quote, parts) {
        const folded = foldQuotes(quote);
        const ranges = [];
        let position = 0;
        for (const part of parts) {
            const needle = foldQuotes(part.trim());
            if (!needle) continue;
            const pattern = new RegExp(`(?<![\\p{L}\\p{N}_])${escapeRegExp(needle)}(?![\\p{L}\\p{N}_])`, 'u');
            const match = pattern.exec(folded.slice(position));
            if (!match) return null;
            const start = position + match.index;
            ranges.push([start, start + needle.length]);
            position = start + needle.length;
        }
        return ranges.length ? ranges : null;
    }

    function findRanges(card) {
        const quote = card.quoteDe;
        if (!quote) return null;
        if (card.segments.length) {
            const bySegments = findParts(quote, card.segments);
            if (bySegments) return bySegments;
        }
        if (card.formDe) {
            const byForm = findParts(quote, [card.formDe]);
            if (byForm) return byForm;
        }
        const index = foldQuotes(quote).indexOf(foldQuotes(card.wordDe));
        return card.wordDe && index >= 0 ? [[index, index + card.wordDe.length]] : null;
    }

    function renderRanges(quote, ranges, wrap) {
        if (!ranges) return escapeHtml(quote);
        let html = '';
        let cursor = 0;
        ranges.forEach(([start, end]) => {
            html += escapeHtml(quote.slice(cursor, start)) + wrap(escapeHtml(quote.slice(start, end)));
            cursor = end;
        });
        return html + escapeHtml(quote.slice(cursor));
    }

    function highlightWord(card) {
        if (!card.quoteDe) return '';
        return renderRanges(card.quoteDe, findRanges(card), (text) => `<u>${text}</u>`);
    }

    function blankWord(card) {
        const ranges = findRanges(card);
        if (!ranges) return null;
        return renderRanges(card.quoteDe, ranges, () => '<span class="fc-blank">_____</span>');
    }

    function stripPunctuation(text) {
        return text.replace(/[^\p{L}\p{N}]/gu, '').toLowerCase();
    }

    function isClozeEligible(card) {
        const ranges = findRanges(card);
        if (!ranges) return false;
        const covered = ranges.map(([start, end]) => card.quoteDe.slice(start, end)).join('');
        return stripPunctuation(covered) !== stripPunctuation(card.quoteDe);
    }

    function normalizeCards(rows) {
        return rows
            .map((row) => ({
                id: row.Cue_ID || '',
                timestamp: row.Zeitstempel || '',
                wordDe: (row.Deutsches_Wort || '').trim(),
                quoteDe: (row.German_Quote || '').trim(),
                formDe: (row['Wortform_im_Zitat'] || '').trim(),
                segments: (row['Lücken_Segmente'] || '').split('|').map((part) => part.trim()).filter(Boolean),
                keywordFa: (row.Farsi_Keyword || '').trim(),
                explanationFa: (row['Erklärung auf Farsi'] || '').trim(),
                contextDe: (row['Erklärung im Kontext der Geschichte'] || '').trim(),
            }))
            .filter((card) => card.wordDe && card.keywordFa);
    }

    function shuffle(array) {
        const copy = array.slice();
        for (let i = copy.length - 1; i > 0; i -= 1) {
            const j = Math.floor(Math.random() * (i + 1));
            [copy[i], copy[j]] = [copy[j], copy[i]];
        }
        return copy;
    }

    function renderCard() {
        cardEl.classList.remove('is-flipped');
        const card = cards[order[currentIndex]];
        const quoteHtml = highlightWord(card) || escapeHtml(card.wordDe);

        if (mode === 'cloze') {
            const blankedHtml = blankWord(card) || '<span class="fc-blank">_____</span>';
            frontLabelEl.textContent = 'Lückentext';
            frontTextEl.innerHTML = blankedHtml;
            frontTextEl.classList.add('fc-card-text--quote');
            frontHintEl.textContent = `Gesucht: ${card.keywordFa}`;
            frontHintEl.classList.remove('d-none');
            backLabelEl.textContent = 'Auflösung';
            backTextEl.innerHTML = quoteHtml;
            backTextEl.classList.add('fc-card-text--quote');
            backContextEl.innerHTML = [card.keywordFa, card.explanationFa, card.contextDe].filter(Boolean).join('<br><br>');
        } else if (direction === 'de-fa') {
            frontLabelEl.textContent = 'Deutsch';
            frontTextEl.innerHTML = quoteHtml;
            frontTextEl.classList.add('fc-card-text--quote');
            frontHintEl.classList.add('d-none');
            backLabelEl.textContent = 'Farsi';
            backTextEl.textContent = card.keywordFa;
            backTextEl.classList.remove('fc-card-text--quote');
            backContextEl.innerHTML = [card.explanationFa, card.contextDe].filter(Boolean).join('<br><br>');
        } else {
            frontLabelEl.textContent = 'Farsi';
            frontTextEl.textContent = card.keywordFa;
            frontTextEl.classList.remove('fc-card-text--quote');
            frontHintEl.classList.add('d-none');
            backLabelEl.textContent = 'Deutsch';
            backTextEl.innerHTML = quoteHtml;
            backTextEl.classList.add('fc-card-text--quote');
            backContextEl.innerHTML = [card.explanationFa, card.contextDe].filter(Boolean).join('<br><br>');
        }

        progressCurrentEl.textContent = String(currentIndex + 1);
        progressTotalEl.textContent = String(order.length);
        btnPrev.disabled = currentIndex === 0;
        btnNext.disabled = currentIndex === order.length - 1;
    }

    function goTo(index) {
        if (index < 0 || index >= order.length) return;
        currentIndex = index;
        renderCard();
    }

    function setDirection(newDirection) {
        direction = newDirection;
        btnDirDeFa.classList.toggle('is-active', direction === 'de-fa');
        btnDirFaDe.classList.toggle('is-active', direction === 'fa-de');
        renderCard();
    }

    function setMode(newMode) {
        mode = newMode;
        btnModeFlip.classList.toggle('is-active', mode === 'flip');
        btnModeCloze.classList.toggle('is-active', mode === 'cloze');
        fcDirectionGroup.classList.toggle('d-none', mode === 'cloze');
        order = mode === 'cloze' ? clozeOrder : flipOrder;
        currentIndex = 0;
        renderCard();
    }

    cardEl.addEventListener('click', () => cardEl.classList.toggle('is-flipped'));
    cardEl.addEventListener('keydown', (event) => {
        if (event.key === ' ' || event.key === 'Enter') {
            event.preventDefault();
            cardEl.classList.toggle('is-flipped');
        }
    });
    btnFlip.addEventListener('click', () => cardEl.classList.toggle('is-flipped'));
    btnPrev.addEventListener('click', () => goTo(currentIndex - 1));
    btnNext.addEventListener('click', () => goTo(currentIndex + 1));
    btnShuffle.addEventListener('click', () => {
        order = shuffle(order);
        if (mode === 'cloze') clozeOrder = order; else flipOrder = order;
        goTo(0);
    });
    btnDirDeFa.addEventListener('click', () => setDirection('de-fa'));
    btnDirFaDe.addEventListener('click', () => setDirection('fa-de'));
    btnModeFlip.addEventListener('click', () => setMode('flip'));
    btnModeCloze.addEventListener('click', () => setMode('cloze'));
    document.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowLeft') goTo(currentIndex - 1);
        else if (event.key === 'ArrowRight') goTo(currentIndex + 1);
    });

    async function init() {
        if (projectMissing) {
            showStatus('Projekt nicht gefunden.', true);
            return;
        }
        try {
            const response = await fetch(`/api/edtech/preview/${tId}`);
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Lernkarten konnten nicht geladen werden.');
            cards = normalizeCards(data.csv || []);
            if (!cards.length) {
                showStatus('Für dieses Projekt sind noch keine Vokabeln vorhanden.');
                return;
            }
            flipOrder = shuffle(cards.map((_, index) => index));
            clozeOrder = shuffle(cards.map((_, index) => index).filter((index) => isClozeEligible(cards[index])));
            if (!clozeOrder.length) {
                btnModeCloze.disabled = true;
                btnModeCloze.title = 'Keine Einträge mit mehrwortigem Zitat vorhanden.';
            }
            order = flipOrder;
            statusEl.classList.add('d-none');
            deckEl.classList.remove('d-none');
            goTo(0);
        } catch (error) {
            showStatus(error.message || 'Lernkarten konnten nicht geladen werden.', true);
        }
    }

    init();
}());
