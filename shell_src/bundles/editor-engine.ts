/**
 * Ankiweb Editor Rich-Text Engine
 * Exposes window.AnkiwebEditor and dispatches custom events:
 * - ankiweb:field-input (detail: { index, html })
 * - ankiweb:field-focus (detail: { index, html })
 * - ankiweb:field-blur (detail: { index, html })
 */

import { executeCommand, updateToolbarState } from "./editor/commands";
import { setupKeyboardShortcuts } from "./editor/shortcuts";
import { saveSelection, restoreSelection, SavedSelection } from "./editor/selection";
import { getEditingHost } from "./editor/host";
import { wrapSelection, insertCloze, getNextClozeIndex } from "./editor/cloze";

export interface AttachOptions {
    onInput?: (html: string) => void;
    onFocus?: () => void;
    onBlur?: () => void;
}

export interface AnkiwebEditorApi {
    attachRichText: (el: HTMLElement, options?: AttachOptions) => () => void;
    exec: (command: string, arg?: string) => void;
    getHTML: (el: HTMLElement) => string;
    setHTML: (el: HTMLElement, html: string) => void;
    focus: (el: HTMLElement) => void;
    saveSelection: (el: HTMLElement) => SavedSelection | null;
    restoreSelection: (el: HTMLElement, saved: SavedSelection) => void;
    wrapSelection: (el: HTMLElement, prefix: string, suffix: string, plainText?: boolean) => void;
    insertCloze: (increment: boolean, host?: HTMLElement) => void;
    getNextClozeIndex: (increment?: boolean) => number;
    attachMedia: () => void;
    recordAudio: () => void;
}

function getFieldIndex(el: HTMLElement): number {
    const attr = el.getAttribute("data-field-index");
    if (attr !== null) {
        return parseInt(attr, 10);
    }
    const parentField = el.closest<HTMLElement>("[data-field-index]");
    if (parentField) {
        const pAttr = parentField.getAttribute("data-field-index");
        if (pAttr !== null) return parseInt(pAttr, 10);
    }
    return 0;
}

export function attachRichText(el: HTMLElement, options?: AttachOptions): () => void {
    const idx = getFieldIndex(el);

    const onInput = () => {
        const html = el.innerHTML;
        options?.onInput?.(html);
        el.dispatchEvent(new CustomEvent("ankiweb:field-input", {
            bubbles: true,
            composed: true,
            detail: { index: idx, html }
        }));
        updateToolbarState();
    };

    const onFocus = () => {
        options?.onFocus?.();
        el.dispatchEvent(new CustomEvent("ankiweb:field-focus", {
            bubbles: true,
            composed: true,
            detail: { index: idx, html: el.innerHTML }
        }));
        updateToolbarState();
    };

    const onBlur = () => {
        options?.onBlur?.();
        el.dispatchEvent(new CustomEvent("ankiweb:field-blur", {
            bubbles: true,
            composed: true,
            detail: { index: idx, html: el.innerHTML }
        }));
        updateToolbarState();
    };

    const onSelectionChange = () => {
        if (document.activeElement === el || el.contains(document.activeElement)) {
            updateToolbarState();
        }
    };

    const onKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Tab") {
            const allRich = Array.from(document.querySelectorAll<HTMLElement>("[data-ankiweb-rich]:not([style*='display: none'])"));
            const currentPos = allRich.indexOf(el);
            if (currentPos !== -1) {
                if (e.shiftKey) {
                    if (currentPos > 0) {
                        e.preventDefault();
                        allRich[currentPos - 1].focus();
                    }
                } else {
                    if (currentPos < allRich.length - 1) {
                        e.preventDefault();
                        allRich[currentPos + 1].focus();
                    }
                }
            }
        }
    };

    el.addEventListener("input", onInput);
    el.addEventListener("focus", onFocus);
    el.addEventListener("blur", onBlur);
    el.addEventListener("keydown", onKeyDown);
    document.addEventListener("selectionchange", onSelectionChange);

    return () => {
        el.removeEventListener("input", onInput);
        el.removeEventListener("focus", onFocus);
        el.removeEventListener("blur", onBlur);
        el.removeEventListener("keydown", onKeyDown);
        document.removeEventListener("selectionchange", onSelectionChange);
    };
}

export function getHTML(el: HTMLElement): string {
    return el.innerHTML;
}

export function setHTML(el: HTMLElement, html: string): void {
    el.innerHTML = html;
    el.dispatchEvent(new Event("input", { bubbles: true }));
}

export function focusField(el: HTMLElement): void {
    el.focus();
    updateToolbarState();
}

export function promptAttachMedia(): void {
    const richHost = getEditingHost();
    if (!richHost) return;

    const inp = document.createElement("input");
    inp.type = "file";
    inp.multiple = true;
    inp.accept = "image/*,audio/*,video/*";
    inp.onchange = async () => {
        const files = Array.from(inp.files || []);
        for (const file of files) {
            const fd = new FormData();
            fd.append("file", file, file.name);
            try {
                const resp = await fetch("/upload_media", {
                    method: "POST",
                    body: fd,
                });
                const data = await resp.json();
                if (data.filename) {
                    const fn = data.filename;
                    let tag = "";
                    if (/\.(png|jpg|jpeg|gif|webp|bmp|svg|avif)$/i.test(fn)) {
                        tag = `<img src="${fn}" alt="">`;
                    } else {
                        tag = `[sound:${fn}]`;
                    }
                    richHost.focus();
                    document.execCommand("insertHTML", false, tag);
                    richHost.dispatchEvent(new Event("input", { bubbles: true }));
                }
            } catch (err) {
                console.error("Upload failed", err);
            }
        }
    };
    inp.click();
}

let activeMediaRecorder: MediaRecorder | null = null;
let recordedChunks: Blob[] = [];

export function promptRecordAudio(): void {
    const richHost = getEditingHost();
    if (!richHost) return;

    let modal = document.getElementById("ankiweb-recorder-modal") as HTMLDialogElement | null;
    if (!modal) {
        modal = document.createElement("dialog") as HTMLDialogElement;
        modal.id = "ankiweb-recorder-modal";
        modal.className = "modal";
        modal.innerHTML = `
            <div class="modal-box max-w-xs">
                <div class="flex justify-between items-center pb-2">
                    <h3 class="font-bold text-base">Record Audio</h3>
                    <button type="button" class="btn btn-sm btn-circle btn-ghost" id="rec-close-btn" aria-label="Close">✕</button>
                </div>
                <div class="text-center py-3">
                    <div class="mb-2 text-2xl font-bold text-error" id="rec-timer">00:00</div>
                    <div class="flex justify-center gap-2">
                        <button type="button" class="btn btn-error btn-sm" id="rec-toggle-btn">Start</button>
                        <button type="button" class="btn btn-primary btn-sm" id="rec-save-btn" disabled>Insert</button>
                    </div>
                </div>
            </div>
            <form method="dialog" class="modal-backdrop">
                <button>close</button>
            </form>
        `;
        document.body.appendChild(modal);
    }
    modal.showModal();

    const timerEl = modal.querySelector<HTMLElement>("#rec-timer")!;
    const toggleBtn = modal.querySelector<HTMLButtonElement>("#rec-toggle-btn")!;
    const saveBtn = modal.querySelector<HTMLButtonElement>("#rec-save-btn")!;
    const closeBtn = modal.querySelector<HTMLButtonElement>("#rec-close-btn")!;

    timerEl.textContent = "00:00";
    toggleBtn.textContent = "Start";
    toggleBtn.className = "btn btn-error btn-sm";
    saveBtn.disabled = true;

    let seconds = 0;
    let timerId: number | null = null;
    recordedChunks = [];

    modal.onclose = () => {
        if (activeMediaRecorder && activeMediaRecorder.state !== "inactive") {
            activeMediaRecorder.stop();
        }
        if (timerId !== null) {
            clearInterval(timerId);
            timerId = null;
        }
    };

    const closeModal = () => {
        modal!.close();
    };

    closeBtn.onclick = closeModal;

    toggleBtn.onclick = async () => {
        if (!activeMediaRecorder || activeMediaRecorder.state === "inactive") {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                activeMediaRecorder = new MediaRecorder(stream);
                recordedChunks = [];
                activeMediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) recordedChunks.push(e.data);
                };
                activeMediaRecorder.onstop = () => {
                    stream.getTracks().forEach((track) => track.stop());
                    saveBtn.disabled = recordedChunks.length === 0;
                };
                activeMediaRecorder.start();
                toggleBtn.textContent = "Stop";
                toggleBtn.className = "btn btn-neutral btn-sm";
                seconds = 0;
                if (timerId !== null) clearInterval(timerId);
                timerId = window.setInterval(() => {
                    seconds++;
                    const m = String(Math.floor(seconds / 60)).padStart(2, "0");
                    const s = String(seconds % 60).padStart(2, "0");
                    timerEl.textContent = `${m}:${s}`;
                }, 1000);
            } catch (err) {
                console.warn("Could not access microphone:", err);
                timerEl.textContent = "No mic";
            }
        } else {
            activeMediaRecorder.stop();
            if (timerId !== null) clearInterval(timerId);
            toggleBtn.textContent = "Start";
            toggleBtn.className = "btn btn-error btn-sm";
        }
    };

    saveBtn.onclick = async () => {
        if (recordedChunks.length === 0) return;
        const blob = new Blob(recordedChunks, { type: "audio/webm" });
        const fd = new FormData();
        const filename = `recording-${Date.now()}.webm`;
        fd.append("file", blob, filename);

        try {
            const resp = await fetch("/upload_media", { method: "POST", body: fd });
            const data = await resp.json();
            if (data.filename) {
                richHost.focus();
                document.execCommand("insertHTML", false, `[sound:${data.filename}]`);
                richHost.dispatchEvent(new Event("input", { bubbles: true }));
            }
        } catch (err) {
            console.error("Failed to save audio", err);
        }
        closeModal();
    };
}

export const api: AnkiwebEditorApi = {
    attachRichText,
    exec: executeCommand,
    getHTML,
    setHTML,
    focus: focusField,
    saveSelection,
    restoreSelection,
    wrapSelection,
    insertCloze,
    getNextClozeIndex,
    attachMedia: promptAttachMedia,
    recordAudio: promptRecordAudio,
};
// Export to window
(window as unknown as Record<string, unknown>).AnkiwebEditor = api;

// Setup global toolbar event delegation
function initToolbarDelegation(): void {
    // Toolbar buttons must not take focus: that would blur the field and lose the selection.
    document.addEventListener("mousedown", (e) => {
        const target = (e.target as HTMLElement)?.closest<HTMLElement>("[data-editor-command], .editor-toolbar button");
        if (target) {
            e.preventDefault();
        }
    });

    document.addEventListener("click", (e) => {
        const target = (e.target as HTMLElement)?.closest<HTMLElement>("[data-editor-command]");
        if (!target) return;
        // If button has inline onclick, skip duplicate execution
        if (target.hasAttribute("onclick")) return;

        const cmd = target.getAttribute("data-editor-command");
        const arg = target.getAttribute("data-editor-arg") || undefined;
        if (cmd) {
            e.preventDefault();
            executeCommand(cmd, arg);
        }
    });

    // Auto-attach rich text elements on page load
    const attachAll = () => {
        document.querySelectorAll<HTMLElement>("[data-ankiweb-rich]").forEach((el) => {
            if (!el.hasAttribute("data-ankiweb-attached")) {
                el.setAttribute("data-ankiweb-attached", "true");
                attachRichText(el);
            }
        });
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", attachAll);
    } else {
        attachAll();
    }

    // Observe dynamic field additions
    const observer = new MutationObserver(() => {
        attachAll();
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Global keyboard shortcuts
    setupKeyboardShortcuts(document.body);

    // Initial toolbar state and focus tracking
    updateToolbarState();
    document.addEventListener("focusin", () => updateToolbarState());
    document.addEventListener("focusout", () => {
        setTimeout(() => updateToolbarState(), 0);
    });
}

if (typeof document !== "undefined") {
    initToolbarDelegation();
}
