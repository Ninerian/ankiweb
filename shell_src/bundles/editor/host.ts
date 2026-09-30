/**
 * Which rich-text field a toolbar action applies to.
 *
 * Toolbar buttons must stay usable when no field has focus (as in Anki), so actions fall back
 * to the field that was focused last. The marker lives on the DOM so the separately bundled
 * editor engine and editor overlays agree without sharing module state.
 */

const RICH = "[data-ankiweb-rich]";
const LAST_FOCUSED = "data-ankiweb-last-focused";

function isUsable(el: HTMLElement): boolean {
    // offsetParent is null for display:none (plain-text mode); collapsed fields are not editable.
    return el.offsetParent !== null && !el.closest(".is-collapsed");
}

/** Call whenever focus may have moved: remembers the focused rich field, if any. */
export function rememberFocusedHost(): void {
    const host = document.activeElement?.closest<HTMLElement>(RICH);
    if (!host) return;
    document.querySelectorAll(`[${LAST_FOCUSED}]`).forEach((el) => el.removeAttribute(LAST_FOCUSED));
    host.setAttribute(LAST_FOCUSED, "");
}

/** Focused field, else the field holding the selection, else the last focused, else the first usable. */
export function getEditingHost(): HTMLElement | null {
    const focused = document.activeElement?.closest<HTMLElement>(RICH);
    if (focused) return focused;

    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0) {
        const node = sel.getRangeAt(0).commonAncestorContainer;
        const el = node.nodeType === Node.ELEMENT_NODE ? (node as HTMLElement) : node.parentElement;
        const selected = el?.closest<HTMLElement>(RICH);
        if (selected && isUsable(selected)) return selected;
    }

    const remembered = document.querySelector<HTMLElement>(`${RICH}[${LAST_FOCUSED}]`);
    if (remembered && isUsable(remembered)) return remembered;

    return Array.from(document.querySelectorAll<HTMLElement>(RICH)).find(isUsable) ?? null;
}
