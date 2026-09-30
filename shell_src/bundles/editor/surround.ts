/**
 * Port of Anki's rich text surround engine (ts/lib/domlib/surround/*)
 */
import { getRootSelection, currentRange } from "./selection";
import { isElement, isTextNode, findAncestor, findDeepestAncestor, removeNode, isBlockElement } from "./dom";

export interface FormatMatcher {
    (element: Element, matchContext: MatchContext): void;
}

export class MatchContext {
    private _shouldRemove = false;
    private _callback: (() => void) | null = null;
    cache: any = null;

    remove() {
        this._shouldRemove = true;
    }

    clear(cb: () => void) {
        this._callback = cb;
    }

    get matches(): boolean {
        return !!this._callback || this._shouldRemove;
    }

    shouldRemove(): boolean {
        if (this._callback) {
            this._callback();
            this._callback = null;
        }
        return this._shouldRemove;
    }

    setCache(val: any) {
        this.cache = val;
    }

    getCache(defVal: any): any {
        return this.cache !== null ? this.cache : defVal;
    }
}

export interface FormatDefinition {
    tagName?: string;
    matcher: FormatMatcher;
    surroundElement?: HTMLElement;
    exclusiveNames?: string[];
}

export class Surrounder {
    private formats: Map<string, FormatDefinition> = new Map();

    registerFormat(name: string, def: FormatDefinition) {
        this.formats.set(name, def);
    }

    hasFormat(name: string): boolean {
        return this.formats.has(name);
    }

    isSurrounded(name: string, host: HTMLElement): boolean {
        const def = this.formats.get(name);
        if (!def) return false;
        const sel = getRootSelection(host);
        if (!sel) return false;
        const range = currentRange(sel);
        if (!range) return false;

        const checkNode = (node: Node | null): boolean => {
            if (!node) return false;
            return !!findAncestor(node, host, (el) => {
                const ctx = new MatchContext();
                def.matcher(el, ctx);
                return ctx.matches;
            });
        };

        return checkNode(range.startContainer) || checkNode(range.endContainer);
    }

    surround(name: string, host: HTMLElement, exclusiveNames: string[] = []): void {
        const def = this.formats.get(name);
        if (!def) return;
        const sel = getRootSelection(host);
        if (!sel) return;
        const range = currentRange(sel);
        if (!range) return;

        // Check if currently surrounded -> toggle off
        const currentlySurrounded = this.isSurrounded(name, host);

        if (currentlySurrounded) {
            this.removeFormat(name, host);
        } else {
            // Remove any exclusive formats first
            const exclusives = [...(def.exclusiveNames || []), ...exclusiveNames];
            for (const excl of exclusives) {
                if (this.isSurrounded(excl, host)) {
                    this.removeFormat(excl, host);
                }
            }
            this.applyFormat(name, host);
        }
    }

    applyFormat(name: string, host: HTMLElement): void {
        const def = this.formats.get(name);
        if (!def) return;
        const sel = getRootSelection(host);
        if (!sel) return;
        const range = currentRange(sel);
        if (!range) return;

        if (range.collapsed) {
            return;
        }

        const surroundEl = def.surroundElement
            ? def.surroundElement.cloneNode(false) as HTMLElement
            : document.createElement(def.tagName || "span");

        try {
            range.surroundContents(surroundEl);
            const newRange = new Range();
            newRange.selectNodeContents(surroundEl);
            sel.removeAllRanges();
            sel.addRange(newRange);
        } catch {
            // If selection crosses boundary points, extract contents and append
            const contents = range.extractContents();
            surroundEl.appendChild(contents);
            range.insertNode(surroundEl);
            const newRange = new Range();
            newRange.selectNodeContents(surroundEl);
            sel.removeAllRanges();
            sel.addRange(newRange);
        }
    }

    removeFormat(name: string, host: HTMLElement): void {
        const def = this.formats.get(name);
        if (!def) return;
        const sel = getRootSelection(host);
        if (!sel) return;
        const range = currentRange(sel);
        if (!range) return;

        // Find matching ancestor elements in range
        const nodesToClean: Element[] = [];

        const walk = (node: Node) => {
            if (isElement(node)) {
                const ctx = new MatchContext();
                def.matcher(node, ctx);
                if (ctx.matches) {
                    nodesToClean.push(node);
                }
            }
            for (let child = node.firstChild; child; child = child.nextSibling) {
                walk(child);
            }
        };

        // Also check ancestors of start & end container
        for (const container of [range.startContainer, range.endContainer]) {
            let p: Element | null = isElement(container) ? container : container.parentElement;
            while (p && p !== host) {
                const ctx = new MatchContext();
                def.matcher(p, ctx);
                if (ctx.matches && !nodesToClean.includes(p)) {
                    nodesToClean.push(p);
                }
                p = p.parentElement;
            }
        }

        if (range.commonAncestorContainer) {
            walk(range.commonAncestorContainer);
        }

        for (const el of nodesToClean) {
            const ctx = new MatchContext();
            def.matcher(el, ctx);
            if (ctx.shouldRemove()) {
                // Replace element with its children
                const parent = el.parentNode;
                if (parent) {
                    while (el.firstChild) {
                        parent.insertBefore(el.firstChild, el);
                    }
                    parent.removeChild(el);
                }
            } else if (el instanceof HTMLElement) {
                // Clean up empty style attribute or empty elements
                if (el.hasAttribute("style") && !el.getAttribute("style")?.trim()) {
                    el.removeAttribute("style");
                }
            }
        }
        cleanEmptyAttributes(host);
    }

    removeFormats(names: string[], host: HTMLElement): void {
        for (const name of names) {
            this.removeFormat(name, host);
        }
    }
}

export function cleanEmptyAttributes(host: HTMLElement): void {
    const styled = host.querySelectorAll<HTMLElement>("[style]");
    styled.forEach((el) => {
        if (!el.getAttribute("style")?.trim()) {
            el.removeAttribute("style");
        }
    });
    const spans = host.querySelectorAll<HTMLElement>("span");
    spans.forEach((span) => {
        if (!span.getAttribute("style")?.trim() && !span.className && !span.id && span.attributes.length === 0) {
            const parent = span.parentNode;
            if (parent) {
                while (span.firstChild) parent.insertBefore(span.firstChild, span);
                parent.removeChild(span);
            }
        }
    });
}

export function removeAllFormatting(host: HTMLElement): void {
    const sel = getRootSelection(host);
    if (!sel) return;
    const range = currentRange(sel);
    if (!range) return;

    if (range.collapsed) {
        // Clear format at caret or entire field if selection empty
        document.execCommand("removeFormat", false, undefined);
        return;
    }

    document.execCommand("removeFormat", false, undefined);

    // Also strip inline spans with style or empty spans
    const el = isElement(range.commonAncestorContainer)
        ? range.commonAncestorContainer
        : range.commonAncestorContainer.parentElement;

    if (el) {
        const spans = el.querySelectorAll("span, font");
        spans.forEach((s) => {
            if (!s.className && !s.getAttribute("style")) {
                const parent = s.parentNode;
                if (parent) {
                    while (s.firstChild) parent.insertBefore(s.firstChild, s);
                    parent.removeChild(s);
                }
            }
        });
    }
}
