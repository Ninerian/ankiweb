/**
 * CodeMirror 6 plain text editor setup for Anki HTML fields.
 */
import { EditorView, basicSetup } from "codemirror";
import { html } from "@codemirror/lang-html";
import { EditorState } from "@codemirror/state";
import { toStoredMathjax, toUndecoratedMathjax } from "./editor-overlays/mathjax";

export interface PlainTextInstance {
    view: EditorView;
    destroy: () => void;
    getValue: () => string;
    setValue: (val: string) => void;
}

export function createPlainTextEditor(
    parent: HTMLElement,
    initialValue: string,
    onChange?: (val: string) => void
): PlainTextInstance {
    const isDark = document.body.classList.contains("nightMode") || document.documentElement.getAttribute("data-theme") === "dark";

    const updateListener = EditorView.updateListener.of((update) => {
        if (update.docChanged && onChange) {
            onChange(update.state.doc.toString());
        }
    });

    const startState = EditorState.create({
        doc: initialValue,
        extensions: [
            basicSetup,
            html(),
            updateListener,
            EditorView.lineWrapping,
            EditorView.theme({
                "&": {
                    height: "100%",
                    fontSize: "14px",
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                },
                ".cm-scroller": {
                    overflow: "auto",
                    minHeight: "100px",
                },
                ".cm-content": {
                    padding: "8px",
                }
            }, { dark: isDark })
        ]
    });

    const view = new EditorView({
        state: startState,
        parent
    });

    return {
        view,
        destroy: () => view.destroy(),
        getValue: () => view.state.doc.toString(),
        setValue: (val: string) => {
            view.dispatch({
                changes: { from: 0, to: view.state.doc.length, insert: val }
            });
        }
    };
}

// Global registry of plain text editors by field container
const plainEditors = new Map<HTMLElement, PlainTextInstance>();

export function toggleFieldPlainText(fieldEl: HTMLElement) {
    const richEl = fieldEl.querySelector<HTMLElement>("[data-ankiweb-rich]");
    const plainHost = fieldEl.querySelector<HTMLElement>("[data-ankiweb-plain]");
    if (!richEl || !plainHost) return;

    const isPlain = fieldEl.classList.contains("has-plain-text");

    if (isPlain) {
        // Switch back to rich text
        const inst = plainEditors.get(fieldEl);
        if (inst) {
            const rawHtml = inst.getValue();
            // Convert to undecorated Mathjax tags for rich text
            const richHtml = toUndecoratedMathjax(rawHtml);
            richEl.innerHTML = richHtml;
            inst.destroy();
            plainEditors.delete(fieldEl);
        }
        fieldEl.classList.remove("has-plain-text");
        plainHost.style.display = "none";
        richEl.style.display = "";
        richEl.focus();

        // Dispatch input event so subscribers update
        fieldEl.dispatchEvent(new CustomEvent("ankiweb:field-input", {
            bubbles: true,
            detail: {
                index: Number(fieldEl.dataset.fieldIndex || 0),
                html: toStoredMathjax(richEl.innerHTML)
            }
        }));
    } else {
        // Switch to plain text CodeMirror
        // Get stored HTML representation from rich text
        const storedHtml = toStoredMathjax(richEl.innerHTML);
        richEl.style.display = "none";
        plainHost.style.display = "block";
        plainHost.innerHTML = "";

        const inst = createPlainTextEditor(plainHost, storedHtml, (newVal) => {
            fieldEl.dispatchEvent(new CustomEvent("ankiweb:field-input", {
                bubbles: true,
                detail: {
                    index: Number(fieldEl.dataset.fieldIndex || 0),
                    html: newVal
                }
            }));
        });
        plainEditors.set(fieldEl, inst);
        fieldEl.classList.add("has-plain-text");
        inst.view.focus();
    }
}

// Attach listeners for HTML toggle buttons and shortcuts
export function initPlainTextToggle(root: Document | HTMLElement = document) {
    // Click on toggle-html-btn or Plain/HTML badge
    root.addEventListener("click", (e) => {
        const target = e.target as HTMLElement;
        const btn = target.closest<HTMLElement>(".toggle-html-btn, .plain-text-badge");
        if (btn) {
            e.preventDefault();
            let fieldEl = btn.closest<HTMLElement>(".editor-field");
            if (!fieldEl && btn.dataset.fieldIndex !== undefined) {
                fieldEl = document.querySelector<HTMLElement>(`.editor-field[data-field-index="${btn.dataset.fieldIndex}"]`);
            }
            if (!fieldEl) {
                const card = btn.closest(".card, .field-container, .field-wrapper");
                if (card) {
                    fieldEl = card.querySelector<HTMLElement>(".editor-field");
                }
            }
            if (fieldEl) {
                toggleFieldPlainText(fieldEl);
            }
        }
    });

    // Keyboard shortcut: Ctrl+Shift+X or Cmd+Shift+X
    root.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toUpperCase() === "X") {
            const active = document.activeElement;
            if (active) {
                const fieldEl = active.closest<HTMLElement>(".editor-field");
                if (fieldEl) {
                    e.preventDefault();
                    toggleFieldPlainText(fieldEl);
                }
            }
        }
    });
}

// Auto-initialize when loaded
if (typeof window !== "undefined") {
    (window as unknown as Record<string, unknown>).AnkiwebPlain = {
        createPlainTextEditor,
        toggleFieldPlainText,
        initPlainTextToggle,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => initPlainTextToggle());
    } else {
        initPlainTextToggle();
    }
}
