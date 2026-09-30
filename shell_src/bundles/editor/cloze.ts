/**
 * HTML / Cloze / MathJax insertion and wrapping utilities ported from Anki
 */
import { getRootSelection, currentRange } from "./selection";

export function trimAndWrapSpaces(text: string, prefix: string, suffix: string): string {
    const match = text
        .replace(/&nbsp;/g, " ")
        .replace(/&#160;/g, " ")
        .replace(/\u00A0/g, " ")
        .match(/^(\s*)([^]*?)(\s*)$/);
    if (!match) return prefix + text + suffix;
    return match[1] + prefix + match[2] + suffix + match[3];
}

export function collapseSelectionBeforeSuffix(sel: Selection, suffix: string): void {
    const range = currentRange(sel);
    if (!range) return;
    range.setEnd(range.endContainer, range.endOffset - suffix.length);
    range.collapse(false);
    sel.removeAllRanges();
    sel.addRange(range);
}

export function wrapSelection(
    host: HTMLElement,
    prefix: string,
    suffix: string,
    plainText: boolean = false
): void {
    const sel = getRootSelection(host);
    if (!sel) return;
    const range = currentRange(sel);
    if (!range) return;

    const isCollapsed = range.collapsed;
    const contents = range.cloneContents();
    const span = document.createElement("span");
    span.appendChild(contents);

    if (plainText) {
        const text = trimAndWrapSpaces(span.innerText, prefix, suffix);
        document.execCommand("inserttext", false, text);
    } else {
        const html = trimAndWrapSpaces(span.innerHTML, prefix, suffix);
        document.execCommand("inserthtml", false, html);
    }

    if (isCollapsed && !prefix.includes("<anki-mathjax")) {
        collapseSelectionBeforeSuffix(sel, suffix);
    }
}

/**
 * Counts highest cloze index used across all fields and returns next index.
 */
export function getNextClozeIndex(increment: boolean = true): number {
    const richFields = document.querySelectorAll<HTMLElement>("[data-ankiweb-rich]");
    let maxIndex = 0;
    const clozeRegex = /\{\{c(\d+)::/gu;

    richFields.forEach((field) => {
        const text = field.innerHTML;
        let match: RegExpExecArray | null;
        while ((match = clozeRegex.exec(text)) !== null) {
            const idx = Number(match[1]);
            if (!isNaN(idx) && idx > maxIndex) {
                maxIndex = idx;
            }
        }
    });

    if (increment) {
        maxIndex++;
    }
    return Math.max(1, maxIndex);
}

export function insertCloze(increment: boolean, host?: HTMLElement): void {
    const targetHost = host || (document.activeElement?.closest<HTMLElement>("[data-ankiweb-rich]")) || document.querySelector<HTMLElement>("[data-ankiweb-rich]");
    if (!targetHost) return;

    targetHost.focus();
    const nextIdx = getNextClozeIndex(increment);
    const prefix = `{{c${nextIdx}::`;
    const suffix = "}}";

    wrapSelection(targetHost, prefix, suffix, false);
}
