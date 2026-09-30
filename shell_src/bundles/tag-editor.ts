import {
    UNICODE_SEPARATOR,
    replaceWithUnicodeSeparator,
    replaceWithColons,
    normalizeTag,
    shortenTag,
    TagItem,
    createTagItem,
} from "./tag-editor/utils";

interface ExtendedHTMLElement extends HTMLElement {
    __ankiweb_tag_editor?: TagEditorController;
}

interface WindowWithTagEditor extends Window {
    AnkiwebTagEditor?: {
        init: () => void;
        TagEditorController: typeof TagEditorController;
    };
}

export class TagEditorController {
    private root: HTMLElement;
    private chipsContainer: HTMLElement;
    private spacer: HTMLElement;
    private addButton: HTMLElement;
    private selectedButton: HTMLElement;
    private menu: HTMLElement;

    private tags: TagItem[] = [];
    private activeIndex: number | null = null;
    private selectedIndices: Set<number> = new Set<number>();
    private anchorIndex: number | null = null;

    private currentInput: HTMLInputElement | null = null;
    private suggestions: string[] = [];
    private selectedSuggestionIndex: number | null = null;

    private isShortened = false;

    constructor(root: HTMLElement) {
        this.root = root;
        this.chipsContainer = root.querySelector(".tags-chips-container") as HTMLElement;
        this.spacer = root.querySelector(".tag-spacer") as HTMLElement;
        this.addButton = root.querySelector(".tag-add-button") as HTMLElement;
        this.selectedButton = root.querySelector(".tags-selected-button") as HTMLElement;
        this.menu = root.querySelector(".autocomplete-menu") as HTMLElement;

        let initialTags: string[] = [];
        try {
            const raw = root.getAttribute("data-initial-tags");
            if (raw) {
                const parsed = JSON.parse(raw);
                if (Array.isArray(parsed)) {
                    initialTags = parsed.filter((item): item is string => typeof item === "string");
                }
            }
        } catch (e) {
            console.error("Failed to parse data-initial-tags", e);
        }

        this.tags = initialTags.map(createTagItem);

        this.bindEvents();
        this.render();
    }

    private bindEvents(): void {
        this.addButton.addEventListener("click", () => this.appendEmptyTag());
        this.spacer.addEventListener("click", () => this.appendEmptyTag());

        this.selectedButton.addEventListener("click", () => {
            this.showSelectedActionsMenu();
        });

        this.root.addEventListener("keydown", (e: KeyboardEvent) => {
            if (e.ctrlKey && e.shiftKey && (e.key === "T" || e.key === "t")) {
                e.preventDefault();
                this.appendEmptyTag();
                return;
            }

            if (this.selectedIndices.size > 0 && this.activeIndex === null) {
                if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A")) {
                    e.preventDefault();
                    this.selectAll();
                } else if ((e.ctrlKey || e.metaKey) && (e.key === "c" || e.key === "C")) {
                    e.preventDefault();
                    this.copySelected();
                } else if (e.key === "Backspace" || e.key === "Delete") {
                    e.preventDefault();
                    this.deleteSelected();
                } else if (e.key === "Escape") {
                    this.clearSelection();
                }
            }
        });

        document.addEventListener("mousedown", (e: MouseEvent) => {
            if (!this.root.contains(e.target as Node)) {
                this.closeAutocomplete();
                if (this.activeIndex !== null) {
                    this.commitActiveInput();
                }
                this.clearSelection();
            }
        });
    }

    private emitTagsChanged(): void {
        const plainTags = this.tags.map((t) => replaceWithColons(t.name));
        const event = new CustomEvent("ankiweb:tags-changed", {
            bubbles: true,
            composed: true,
            detail: { tags: plainTags },
        });
        this.root.dispatchEvent(event);
    }

    public getTags(): string[] {
        return this.tags.map((t) => replaceWithColons(t.name)).filter((t) => t.trim() !== "");
    }

    public appendEmptyTag(): void {
        this.clearSelection();
        if (this.tags.length > 0 && this.tags[this.tags.length - 1].name.trim() === "") {
            this.activeIndex = this.tags.length - 1;
        } else {
            this.tags.push(createTagItem(""));
            this.activeIndex = this.tags.length - 1;
        }
        this.render();
        this.focusInput();
    }

    private clearSelection(): void {
        this.selectedIndices.clear();
        this.anchorIndex = null;
        this.updateSelectionUI();
    }

    private selectAll(): void {
        this.selectedIndices.clear();
        for (let i = 0; i < this.tags.length; i++) {
            this.selectedIndices.add(i);
        }
        this.updateSelectionUI();
    }

    private copySelected(): void {
        const selectedTags = Array.from(this.selectedIndices)
            .sort((a, b) => a - b)
            .map((i) => replaceWithColons(this.tags[i].name))
            .join("\n");

        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(selectedTags);
        } else {
            const ta = document.createElement("textarea");
            ta.value = selectedTags;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
        }
        this.clearSelection();
    }

    private deleteSelected(): void {
        const sorted = Array.from(this.selectedIndices).sort((a, b) => b - a);
        for (const idx of sorted) {
            this.tags.splice(idx, 1);
        }
        this.clearSelection();
        this.render();
        this.emitTagsChanged();
    }

    private showSelectedActionsMenu(): void {
        if (this.selectedIndices.size > 0) {
            this.deleteSelected();
        }
    }

    private updateSelectionUI(): void {
        const hasSelection = this.selectedIndices.size > 0;
        if (hasSelection) {
            this.selectedButton.classList.remove("hidden");
            this.addButton.classList.add("hidden");
        } else {
            this.selectedButton.classList.add("hidden");
            this.addButton.classList.remove("hidden");
        }

        const chips = this.chipsContainer.querySelectorAll(".tag-chip");
        chips.forEach((chip, i) => {
            if (this.selectedIndices.has(i)) {
                chip.classList.add("selected");
            } else {
                chip.classList.remove("selected");
            }
        });
    }

    private commitActiveInput(): void {
        if (this.activeIndex === null || !this.currentInput) return;

        const val = normalizeTag(this.currentInput.value);
        if (val.length === 0) {
            this.tags.splice(this.activeIndex, 1);
            this.activeIndex = null;
        } else {
            const formatted = replaceWithUnicodeSeparator(val);
            const existingIdx = this.tags.findIndex((t, i) => i !== this.activeIndex && t.name.toLowerCase() === formatted.toLowerCase());

            if (existingIdx >= 0) {
                this.tags.splice(this.activeIndex, 1);
                this.activeIndex = null;
                this.render();
                const existingChip = this.chipsContainer.querySelectorAll(".tag-chip")[existingIdx] as HTMLElement | null;
                if (existingChip) {
                    existingChip.classList.add("flashing");
                    setTimeout(() => existingChip.classList.remove("flashing"), 300);
                }
                this.emitTagsChanged();
                return;
            } else {
                this.tags[this.activeIndex].name = formatted;
                this.activeIndex = null;
            }
        }

        this.closeAutocomplete();
        this.render();
        this.emitTagsChanged();
    }

    private focusInput(): void {
        if (this.currentInput) {
            this.currentInput.focus();
            const len = this.currentInput.value.length;
            this.currentInput.setSelectionRange(len, len);
        }
    }

    private render(): void {
        this.chipsContainer.innerHTML = "";

        this.tags.forEach((tag, idx) => {
            const isEditing = this.activeIndex === idx;

            const relativeWrapper = document.createElement("div");
            relativeWrapper.className = "tag-relative";
            relativeWrapper.setAttribute("draggable", isEditing ? "false" : "true");

            relativeWrapper.addEventListener("dragstart", (e: DragEvent) => {
                if (isEditing) {
                    e.preventDefault();
                    return;
                }
                e.dataTransfer?.setData("text/plain", idx.toString());
                relativeWrapper.style.opacity = "0.4";
            });

            relativeWrapper.addEventListener("dragend", () => {
                relativeWrapper.style.opacity = "1";
            });

            relativeWrapper.addEventListener("dragover", (e: DragEvent) => {
                e.preventDefault();
            });

            relativeWrapper.addEventListener("drop", (e: DragEvent) => {
                e.preventDefault();
                const fromStr = e.dataTransfer?.getData("text/plain");
                if (fromStr !== undefined && fromStr !== "") {
                    const fromIdx = parseInt(fromStr, 10);
                    if (!isNaN(fromIdx) && fromIdx !== idx && fromIdx >= 0 && fromIdx < this.tags.length) {
                        const moved = this.tags.splice(fromIdx, 1)[0];
                        this.tags.splice(idx, 0, moved);
                        this.render();
                        this.emitTagsChanged();
                    }
                }
            });

            if (isEditing) {
                const inputWrapper = document.createElement("div");
                inputWrapper.className = "tag-input-wrapper";

                const input = document.createElement("input");
                input.type = "text";
                input.className = "tag-input";
                input.value = tag.name;
                this.currentInput = input;

                this.bindInputEvents(input, idx);

                inputWrapper.appendChild(input);
                relativeWrapper.appendChild(inputWrapper);
            } else {
                const chip = document.createElement("button");
                chip.type = "button";
                chip.tabIndex = -1;
                chip.className = `tag-chip ${this.selectedIndices.has(idx) ? "selected" : ""}`;
                chip.title = replaceWithColons(tag.name);

                const label = document.createElement("span");
                label.className = "tag-label";
                label.textContent = this.isShortened ? shortenTag(tag.name) : tag.name;
                chip.appendChild(label);

                const delBtn = document.createElement("span");
                delBtn.className = "tag-delete-btn";
                delBtn.innerHTML = `
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" fill="currentColor" viewBox="0 0 16 16">
                      <path d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708z"/>
                    </svg>
                `;
                delBtn.addEventListener("click", (e: MouseEvent) => {
                    e.stopPropagation();
                    this.tags.splice(idx, 1);
                    this.clearSelection();
                    this.render();
                    this.emitTagsChanged();
                });
                chip.appendChild(delBtn);

                chip.addEventListener("click", (e: MouseEvent) => {
                    if (e.shiftKey) {
                        this.handleRangeSelect(idx);
                    } else if (e.ctrlKey || e.metaKey) {
                        this.handleToggleSelect(idx);
                    } else {
                        this.clearSelection();
                        this.activeIndex = idx;
                        this.render();
                        this.focusInput();
                    }
                });

                relativeWrapper.appendChild(chip);
            }

            this.chipsContainer.appendChild(relativeWrapper);
        });

        this.updateSelectionUI();
    }

    private handleToggleSelect(index: number): void {
        if (this.selectedIndices.has(index)) {
            this.selectedIndices.delete(index);
        } else {
            this.selectedIndices.add(index);
            this.anchorIndex = index;
        }
        this.updateSelectionUI();
    }

    private handleRangeSelect(index: number): void {
        if (this.anchorIndex === null) {
            this.anchorIndex = index;
            this.selectedIndices.add(index);
        } else {
            const start = Math.min(this.anchorIndex, index);
            const end = Math.max(this.anchorIndex, index);
            for (let i = start; i <= end; i++) {
                this.selectedIndices.add(i);
            }
        }
        this.updateSelectionUI();
    }

    private bindInputEvents(input: HTMLInputElement, idx: number): void {
        input.addEventListener("input", () => {
            const curVal = input.value;
            this.tags[idx].name = curVal;
            this.fetchAutocomplete(curVal);
        });

        input.addEventListener("keydown", (e: KeyboardEvent) => {
            const start = input.selectionStart || 0;
            const end = input.selectionEnd || 0;
            const isCollapsed = start === end;
            const atStart = start === 0 && isCollapsed;
            const atEnd = start === input.value.length && isCollapsed;

            if (e.key === " " || e.key === ":") {
                const before = input.value.slice(0, start);
                const after = input.value.slice(end);

                if (e.key === " ") {
                    e.preventDefault();
                    this.splitTag(idx, start, end);
                    return;
                } else if (e.key === ":") {
                    if (before.endsWith(":")) {
                        e.preventDefault();
                        input.value = before.slice(0, -1) + UNICODE_SEPARATOR + after;
                        input.setSelectionRange(start, start);
                        this.tags[idx].name = input.value;
                        this.fetchAutocomplete(input.value);
                        return;
                    }
                }
            }

            if (e.key === "Enter") {
                e.preventDefault();
                if (this.selectedSuggestionIndex !== null && this.suggestions[this.selectedSuggestionIndex]) {
                    this.chooseSuggestion(this.suggestions[this.selectedSuggestionIndex]);
                } else {
                    this.commitActiveInput();
                }
                return;
            }

            if (e.key === "ArrowDown") {
                if (this.suggestions.length > 0) {
                    e.preventDefault();
                    this.navigateSuggestions(1);
                    return;
                }
            } else if (e.key === "ArrowUp") {
                if (this.suggestions.length > 0) {
                    e.preventDefault();
                    this.navigateSuggestions(-1);
                    return;
                }
            } else if (e.key === "Tab") {
                if (this.suggestions.length > 0 && this.selectedSuggestionIndex !== null) {
                    e.preventDefault();
                    this.chooseSuggestion(this.suggestions[this.selectedSuggestionIndex]);
                    return;
                }
            }

            if (e.key === "Backspace" && atStart) {
                e.preventDefault();
                this.joinWithPrevious(idx);
                return;
            }

            if (e.key === "Delete" && atEnd) {
                e.preventDefault();
                this.joinWithNext(idx);
                return;
            }

            if (e.key === "ArrowLeft" && atStart && idx > 0) {
                e.preventDefault();
                this.commitActiveInput();
                this.activeIndex = idx - 1;
                this.render();
                this.focusInput();
                return;
            }

            if (e.key === "ArrowRight" && atEnd && idx < this.tags.length - 1) {
                e.preventDefault();
                this.commitActiveInput();
                this.activeIndex = idx + 1;
                this.render();
                this.focusInput();
                return;
            }
            if ((e.ctrlKey || e.metaKey) && (e.key === "a" || e.key === "A") && input.value.length === 0) {
                e.preventDefault();
                this.commitActiveInput();
                this.selectAll();
                return;
            }
        });

        input.addEventListener("paste", (e: ClipboardEvent) => {
            const pasteData = e.clipboardData?.getData("text/plain");
            if (!pasteData) return;

            const tokens = pasteData.trim().split(/\s+/).filter((t) => t.length > 0);
            if (tokens.length > 1) {
                e.preventDefault();
                const first = tokens.shift();
                if (!first) return;
                const currentVal = input.value;
                const start = input.selectionStart || 0;
                const end = input.selectionEnd || 0;
                const combinedFirst = currentVal.slice(0, start) + first + currentVal.slice(end);

                this.tags[idx].name = replaceWithUnicodeSeparator(normalizeTag(combinedFirst));

                let insertIdx = idx + 1;
                for (const tok of tokens) {
                    this.tags.splice(insertIdx, 0, createTagItem(normalizeTag(tok)));
                    insertIdx++;
                }

                this.activeIndex = insertIdx - 1;
                this.render();
                this.focusInput();
                this.emitTagsChanged();
            }
        });
    }

    private splitTag(idx: number, start: number, end: number): void {
        const val = this.tags[idx].name;
        const left = val.slice(0, start);
        const right = val.slice(end);

        this.tags[idx].name = normalizeTag(left);
        const newTag = createTagItem(normalizeTag(right));
        this.tags.splice(idx + 1, 0, newTag);

        this.activeIndex = idx + 1;
        this.render();
        this.focusInput();
        this.emitTagsChanged();
    }

    private joinWithPrevious(idx: number): void {
        if (idx === 0) {
            if (this.tags[idx].name.length === 0) {
                this.tags.splice(idx, 1);
                this.activeIndex = null;
                this.render();
                this.emitTagsChanged();
            }
            return;
        }

        const prevTag = this.tags.splice(idx - 1, 1)[0];
        const newIdx = idx - 1;
        const currentName = this.tags[newIdx].name;
        const prevLen = prevTag.name.length;
        this.tags[newIdx].name = prevTag.name + currentName;
        this.activeIndex = newIdx;
        this.render();

        if (this.currentInput) {
            this.currentInput.focus();
            this.currentInput.setSelectionRange(prevLen, prevLen);
        }
        this.emitTagsChanged();
    }

    private joinWithNext(idx: number): void {
        if (idx >= this.tags.length - 1) return;

        const nextTag = this.tags.splice(idx + 1, 1)[0];
        const currentLen = this.tags[idx].name.length;
        this.tags[idx].name = this.tags[idx].name + nextTag.name;
        this.activeIndex = idx;
        this.render();

        if (this.currentInput) {
            this.currentInput.focus();
            this.currentInput.setSelectionRange(currentLen, currentLen);
        }
        this.emitTagsChanged();
    }

    private async fetchAutocomplete(query: string): Promise<void> {
        const clean = normalizeTag(replaceWithColons(query));
        if (clean.length === 0) {
            this.closeAutocomplete();
            return;
        }

        try {
            const resp = await fetch(`/api/tags/complete?input=${encodeURIComponent(clean)}&matchLimit=50`);
            if (!resp.ok) return;
            const data: unknown = await resp.json();
            if (data && typeof data === "object" && "tags" in data) {
                const rawTags = (data as Record<string, unknown>).tags;
                if (Array.isArray(rawTags)) {
                    const results = rawTags.filter((t): t is string => typeof t === "string");
                    this.suggestions = results.map(replaceWithUnicodeSeparator);
                    this.selectedSuggestionIndex = null;
                    this.renderAutocomplete();
                }
            }
        } catch (e) {
            console.error("Autocomplete fetch failed", e);
        }
    }

    private renderAutocomplete(): void {
        if (this.suggestions.length === 0 || this.activeIndex === null || !this.currentInput) {
            this.closeAutocomplete();
            return;
        }

        this.menu.innerHTML = "";
        this.suggestions.forEach((item, index) => {
            const el = document.createElement("div");
            el.className = `autocomplete-item ${index === this.selectedSuggestionIndex ? "selected" : ""}`;
            el.textContent = item;
            el.addEventListener("mousedown", (e) => {
                e.preventDefault();
                this.chooseSuggestion(item);
            });
            this.menu.appendChild(el);
        });

        const rect = this.currentInput.getBoundingClientRect();
        const rootRect = this.root.getBoundingClientRect();

        this.menu.style.top = `${rect.bottom - rootRect.top}px`;
        this.menu.style.left = `${rect.left - rootRect.left}px`;
        this.menu.classList.remove("hidden");
    }

    private navigateSuggestions(delta: number): void {
        if (this.suggestions.length === 0) return;

        if (this.selectedSuggestionIndex === null) {
            this.selectedSuggestionIndex = delta > 0 ? 0 : this.suggestions.length - 1;
        } else {
            this.selectedSuggestionIndex = (this.selectedSuggestionIndex + delta + this.suggestions.length) % this.suggestions.length;
        }

        const items = this.menu.querySelectorAll(".autocomplete-item");
        items.forEach((item, idx) => {
            if (idx === this.selectedSuggestionIndex) {
                item.classList.add("selected");
                item.scrollIntoView({ block: "nearest" });
            } else {
                item.classList.remove("selected");
            }
        });
    }

    private chooseSuggestion(chosen: string): void {
        if (this.activeIndex === null || !this.currentInput) return;
        this.currentInput.value = chosen;
        this.tags[this.activeIndex].name = chosen;
        this.commitActiveInput();
    }

    private closeAutocomplete(): void {
        this.suggestions = [];
        this.selectedSuggestionIndex = null;
        this.menu.classList.add("hidden");
        this.menu.innerHTML = "";
    }
}

function initTagEditors(): void {
    const editors = document.querySelectorAll<ExtendedHTMLElement>("[data-ankiweb-tag-editor]");
    editors.forEach((el) => {
        if (!el.__ankiweb_tag_editor) {
            el.__ankiweb_tag_editor = new TagEditorController(el);
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTagEditors);
} else {
    initTagEditors();
}

const win = window as WindowWithTagEditor;
win.AnkiwebTagEditor = {
    init: initTagEditors,
    TagEditorController,
};
