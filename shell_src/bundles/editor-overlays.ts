/**
 * Entry point for editor-overlays.ts bundle.
 * Initializes HTML filter, MathJax overlays/editor, Image resize handles/alt, and Paste/Drop handlers.
 */
import { filterHTML, FilterMode } from "./editor-overlays/html-filter";
import { toStoredMathjax, toUndecoratedMathjax, renderMathjaxSvg } from "./editor-overlays/mathjax";
import { setupImageOverlay } from "./editor-overlays/image-overlay";
import { setupPasteAndDrop } from "./editor-overlays/paste-handler";
import { openMathjaxEditor, AnkiMathjaxElement } from "./editor-overlays/mathjax-editor";
import { getEditingHost } from "./editor/host";

export interface EditorOverlaysApi {
    filterHTML: typeof filterHTML;
    FilterMode: typeof FilterMode;
    toStoredMathjax: typeof toStoredMathjax;
    toUndecoratedMathjax: typeof toUndecoratedMathjax;
    renderMathjaxSvg: typeof renderMathjaxSvg;
    openMathjaxEditor: typeof openMathjaxEditor;
    setupImageOverlay: typeof setupImageOverlay;
    setupPasteAndDrop: typeof setupPasteAndDrop;
    initEditorOverlays: (root?: HTMLElement) => void;
}

export function initEditorOverlays(root: HTMLElement = document.body) {
    // 1. Setup image resize / alt overlays
    setupImageOverlay(root);

    // 2. Setup paste and drop on rich text inputs
    setupPasteAndDrop(root);

    // 3. Listen for MathJax insert events or shortcuts
    root.addEventListener("keydown", (e) => {
        // Ctrl+M or Cmd+M: Insert MathJax inline
        // Ctrl+Shift+M or Cmd+Shift+M: Insert MathJax block
        if ((e.ctrlKey || e.metaKey) && e.key.toUpperCase() === "M") {
            const active = document.activeElement;
            const richHost = active?.closest<HTMLElement>("[data-ankiweb-rich]");
            if (richHost) {
                e.preventDefault();
                openMathjaxEditor(undefined, { hostEl: richHost, defaultBlock: e.shiftKey });
            }
        }
    });

    // 4. Custom events dispatched by toolbar
    root.addEventListener("ankiweb:insert-mathjax", ((e: CustomEvent<{ block?: boolean }>) => {
        const richHost = getEditingHost();
        if (richHost) {
            openMathjaxEditor(undefined, { hostEl: richHost, defaultBlock: !!e.detail?.block });
        }
    }) as EventListener);
}

const api: EditorOverlaysApi = {
    filterHTML,
    FilterMode,
    toStoredMathjax,
    toUndecoratedMathjax,
    renderMathjaxSvg,
    openMathjaxEditor,
    setupImageOverlay,
    setupPasteAndDrop,
    initEditorOverlays,
};

// Global export
(window as unknown as Record<string, unknown>).AnkiwebOverlays = api;

if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => initEditorOverlays());
    } else {
        initEditorOverlays();
    }
}
