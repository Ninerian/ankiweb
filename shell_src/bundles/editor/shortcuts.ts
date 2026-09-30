/**
 * Keyboard shortcuts for the editor toolbar
 */
import { executeCommand } from "./commands";

export function setupKeyboardShortcuts(root: HTMLElement = document.body): () => void {
    const handler = (e: KeyboardEvent) => {
        const isCtrl = e.ctrlKey || e.metaKey;
        if (!isCtrl) return;

        const key = e.key.toLowerCase();

        // Check if inside a rich-text-input or editor field
        const active = document.activeElement;
        const isRich = !!active?.closest("[data-ankiweb-rich]");

        if (key === "b" && !e.shiftKey && !e.altKey) {
            e.preventDefault();
            executeCommand("bold");
        } else if (key === "i" && !e.shiftKey && !e.altKey) {
            e.preventDefault();
            executeCommand("italic");
        } else if (key === "u" && !e.shiftKey && !e.altKey) {
            e.preventDefault();
            executeCommand("underline");
        } else if (key === "s" && e.shiftKey && !e.altKey) {
            e.preventDefault();
            executeCommand("strikethrough");
        } else if (key === "d" && e.shiftKey && !e.altKey) {
            e.preventDefault();
            executeCommand("strikethrough");
        } else if (key === "r" && !e.shiftKey && !e.altKey) {
            e.preventDefault();
            executeCommand("removeFormat");
        } else if (key === "=" && !e.shiftKey && !e.altKey) {
            e.preventDefault();
            executeCommand("superscript");
        } else if ((key === "=" || key === "+") && e.shiftKey && !e.altKey) {
            e.preventDefault();
            executeCommand("subscript");
        } else if (key === "," && !e.shiftKey && !e.altKey) {
            e.preventDefault();
            executeCommand("insertUnorderedList");
        } else if (key === "." && !e.shiftKey && !e.altKey) {
            e.preventDefault();
            executeCommand("insertOrderedList");
        } else if (key === "c" && e.shiftKey && !e.altKey) {
            // Ctrl+Shift+C -> Cloze increment
            e.preventDefault();
            executeCommand("cloze");
        } else if (key === "c" && e.shiftKey && e.altKey) {
            // Ctrl+Alt+Shift+C -> Cloze same number
            e.preventDefault();
            executeCommand("cloze-same-number");
        }
    };

    const funcKeyHandler = (e: KeyboardEvent) => {
        if (e.key === "F3") {
            e.preventDefault();
            const attachBtn = document.querySelector<HTMLElement>("[data-editor-command='attach']");
            if (attachBtn) attachBtn.click();
        } else if (e.key === "F5") {
            e.preventDefault();
            const recordBtn = document.querySelector<HTMLElement>("[data-editor-command='record']");
            if (recordBtn) recordBtn.click();
        }
    };

    root.addEventListener("keydown", handler);
    root.addEventListener("keydown", funcKeyHandler);
    return () => {
        root.removeEventListener("keydown", handler);
        root.removeEventListener("keydown", funcKeyHandler);
    };
}
