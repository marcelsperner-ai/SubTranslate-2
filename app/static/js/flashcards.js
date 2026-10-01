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
    const backLabelEl = document.getElementById('fcBackLabel');
    const backTextEl = document.getElementById('fcBackText');
    const backContextEl = document.getElementById('fcBackContext');
    const btnPrev = document.getElementById('btnFcPrev');
    const btnNext = document.getElementById('btnFcNext');
    const btnFlip = document.getElementById('btnFcFlip');
    const btnShuffle = document.getElementById('btnFcShuffle');
    const btnDirDeFa = document.getElementById('btnDirDeFa');
    const btnDirFaDe = document.getElementById('btnDirFaDe');

    let cards = [];
    let order = [];
    let currentIndex = 0;
    let direction = 'de-fa';

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
        return quote.replace(pattern, (match) => `<mark>${match}</mark>`);
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
        const contextHtml = highlightWord(card.quoteDe, card.wordDe);

        if (direction === 'de-fa') {
            frontLabelEl.textContent = 'Deutsch';
            frontTextEl.textContent = card.wordDe;
            backLabelEl.textContent = 'Farsi';
            backTextEl.textContent = card.keywordFa;
        } else {
            frontLabelEl.textContent = 'Farsi';
            frontTextEl.textContent = card.keywordFa;
            backLabelEl.textContent = 'Deutsch';
            backTextEl.textContent = card.wordDe;
        }
        backContextEl.innerHTML = [card.explanationFa, contextHtml].filter(Boolean).join('<br><br>');

        progressCurrentEl.textContent = String(currentIndex + 1);
        progressTotalEl.textContent = String(cards.length);
        btnPrev.disabled = currentIndex === 0;
        btnNext.disabled = currentIndex === cards.length - 1;
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
        goTo(0);
    });
    btnDirDeFa.addEventListener('click', () => setDirection('de-fa'));
    btnDirFaDe.addEventListener('click', () => setDirection('fa-de'));
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
            order = shuffle(cards.map((_, index) => index));
            statusEl.classList.add('d-none');
            deckEl.classList.remove('d-none');
            goTo(0);
        } catch (error) {
            showStatus(error.message || 'Lernkarten konnten nicht geladen werden.', true);
        }
    }

    init();
}());
