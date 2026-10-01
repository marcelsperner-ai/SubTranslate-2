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

    function highlightWord(quote, word) {
        if (!quote) return '';
        if (!word) return quote;
        const pattern = new RegExp(escapeRegExp(word), 'i');
        if (!pattern.test(quote)) return quote;
        return quote.replace(pattern, (match) => `<u>${match}</u>`);
    }

    function blankWord(quote, word) {
        if (!quote || !word) return null;
        const pattern = new RegExp(escapeRegExp(word), 'i');
        if (!pattern.test(quote)) return null;
        return quote.replace(pattern, () => '<span class="fc-blank">_____</span>');
    }

    function isClozeEligible(card) {
        return card.quoteDe.trim().toLowerCase() !== card.wordDe.trim().toLowerCase();
    }

    function normalizeCards(rows) {
        return rows
            .map((row) => ({
                id: row.Cue_ID || '',
                timestamp: row.Zeitstempel || '',
                wordDe: (row.Deutsches_Wort || '').trim(),
                quoteDe: (row.German_Quote || '').trim(),
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
        const quoteHtml = highlightWord(card.quoteDe, card.wordDe) || card.wordDe;

        if (mode === 'cloze') {
            const blankedHtml = blankWord(card.quoteDe, card.wordDe) || '<span class="fc-blank">_____</span>';
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
