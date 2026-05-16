async function fetchAutocomplete(query, url) {
    const response = await fetch(`${url}?q=${encodeURIComponent(query)}`);
    if (!response.ok) {
        return [];
    }
    const payload = await response.json();
    return payload.suggestions || [];
}

function suggestionLabel(matchType) {
    const labels = {
        exact: "genau",
        prefix: "beginnt so",
        fehlschreibung: "fast richtig",
        "meintest-du": "meintest du?",
    };
    return labels[matchType] || "";
}

function renderSuggestions(container, suggestions) {
    container.innerHTML = "";
    suggestions.forEach((item) => {
        const li = document.createElement("li");
        li.className = `suggestion-item suggestion-${item.match_type}`;
        const link = document.createElement("a");
        link.href = `/word/${encodeURIComponent(item.lemma)}`;
        link.textContent = item.lemma;

        const meta = document.createElement("span");
        meta.className = `suggestion-badge suggestion-badge-${item.match_type}`;
        meta.textContent = suggestionLabel(item.match_type);

        li.appendChild(link);
        li.appendChild(meta);
        container.appendChild(li);
    });
}

async function setupAutocomplete() {
    const input = document.querySelector("[data-autocomplete-input]");
    const results = document.querySelector("[data-autocomplete-results]");
    if (!input || !results) {
        return;
    }

    let timerId = null;
    input.addEventListener("input", () => {
        clearTimeout(timerId);
        const query = input.value.trim();
        if (!query) {
            renderSuggestions(results, []);
            return;
        }

        timerId = window.setTimeout(async () => {
            const suggestions = await fetchAutocomplete(query, input.dataset.autocompleteUrl);
            renderSuggestions(results, suggestions);
        }, 120);
    });
}

function setupReviewKeyboardShortcuts() {
    const editorSection = document.querySelector("[data-review-editor]");
    if (!editorSection) {
        return;
    }

    const openButton = document.querySelector("[data-open-editor]");
    const closeButton = document.querySelector("[data-close-editor]");
    const approveForm = document.querySelector('form[action$="/approve"]');
    const regenerateForm = document.querySelector('form[action$="/toggle-regeneration"]');
    const saveButton = editorSection.querySelector('button[type="submit"]');
    const textarea = editorSection.querySelector("textarea");
    const nextLink = Array.from(document.querySelectorAll(".review-nav-link")).find((element) => element.textContent.includes("Nächste"));

    function openEditor() {
        editorSection.hidden = false;
        textarea?.focus();
    }

    function closeEditor() {
        editorSection.hidden = true;
    }

    openButton?.addEventListener("click", openEditor);
    closeButton?.addEventListener("click", closeEditor);

    document.addEventListener("keydown", (event) => {
        const tagName = document.activeElement?.tagName;
        const editingText = tagName === "TEXTAREA" || tagName === "INPUT";

        if (event.key.toLowerCase() === "e" && !editingText) {
            event.preventDefault();
            openEditor();
        }
        if (event.key.toLowerCase() === "b" && !editingText) {
            event.preventDefault();
            approveForm?.requestSubmit();
        }
        if (event.key.toLowerCase() === "r" && !editingText) {
            event.preventDefault();
            regenerateForm?.requestSubmit();
        }
        if (event.key.toLowerCase() === "n" && !editingText) {
            event.preventDefault();
            nextLink?.click();
        }
        if (event.key.toLowerCase() === "s" && editingText && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            saveButton?.click();
        }
        if (event.key === "Escape" && !editorSection.hidden) {
            event.preventDefault();
            closeEditor();
        }
    });
}

function setupWritingCheck() {
    const infoPanel = document.querySelector("[data-writing-info]");
    const buttons = document.querySelectorAll("[data-marker-button]");
    if (!infoPanel || !buttons.length) {
        return;
    }

    const title = infoPanel.querySelector("h3");
    const body = infoPanel.querySelector("p");

    buttons.forEach((button) => {
        let state = 0;
        button.addEventListener("click", () => {
            state = Math.min(state + 1, 2);
            buttons.forEach((item) => item.classList.toggle("is-active", item === button));

            if (state === 1) {
                title.textContent = button.dataset.category || "Hinweis";
                body.textContent = button.dataset.tip || "Schau dir dieses Wort noch einmal genau an.";
                return;
            }

            title.textContent = "Richtiges Wort";
            const correctWord = button.dataset.correctWord || "Noch offen";
            const url = button.dataset.wordUrl;
            if (url) {
                body.innerHTML = `<strong>${correctWord}</strong><br><a href="${url}">Zum Wörterbucheintrag</a>`;
                return;
            }
            body.innerHTML = `<strong>${correctWord}</strong>`;
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    setupAutocomplete();
    setupReviewKeyboardShortcuts();
    setupWritingCheck();
});
