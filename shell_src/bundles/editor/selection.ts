/**
 * Selection & Location utilities ported from Anki's ts/lib/domlib
 */

export function getRootSelection(node: Node): Selection | null {
    const root = node.getRootNode() as Document | ShadowRoot;
    return root.getSelection ? root.getSelection() : document.getSelection();
}

export function currentRange(sel: Selection): Range | null {
    const count = sel.rangeCount;
    return count === 0 ? null : sel.getRangeAt(count - 1);
}

export function isSelectionCollapsed(sel: Selection): boolean {
    const r = currentRange(sel);
    return r ? r.collapsed : true;
}

export function getNodePath(node: Node, base: Node, acc: number[] = []): number[] {
    if (!node.parentNode || node === base) return acc;
    const parent = node.parentNode;
    const idx = Array.prototype.indexOf.call(parent.childNodes, node);
    return getNodePath(parent, base, [idx, ...acc]);
}

export function getNodeFromPath(base: Node, path: number[]): Node | null {
    if (path.length === 0) return base;
    if (base.childNodes[path[0]]) {
        const [head, ...tail] = path;
        return getNodeFromPath(base.childNodes[head], tail);
    }
    return null;
}

export interface NodeLocation {
    coordinates: number[];
    offset: number;
}

export interface SavedSelection {
    anchor: NodeLocation;
    focus?: NodeLocation;
    collapsed: boolean;
    direction?: "forward" | "backward";
}

export function compareLocations(a: NodeLocation, b: NodeLocation): number {
    const minLen = Math.min(a.coordinates.length, b.coordinates.length);
    for (let i = 0; i <= minLen; i++) {
        if (a.coordinates.length === i) {
            return b.coordinates.length === i
                ? a.offset < b.offset
                    ? -1
                    : a.offset > b.offset
                    ? 1
                    : 0
                : -1;
        }
        if (b.coordinates.length === i) return 1;
        if (a.coordinates[i] < b.coordinates[i]) return -1;
        if (a.coordinates[i] > b.coordinates[i]) return 1;
    }
    return 0;
}

export function saveSelection(base: Node): SavedSelection | null {
    const sel = getRootSelection(base);
    if (!sel || !sel.anchorNode) return null;
    const range = currentRange(sel);
    if (!range) return null;

    const collapsed = range.collapsed;
    const anchor: NodeLocation = {
        coordinates: getNodePath(sel.anchorNode, base),
        offset: sel.anchorOffset,
    };
    if (collapsed) {
        return { anchor, collapsed };
    }
    const focus: NodeLocation = {
        coordinates: getNodePath(sel.focusNode!, base),
        offset: sel.focusOffset,
    };
    const direction = compareLocations(anchor, focus) === 1 ? "backward" : "forward";
    return { anchor, focus, collapsed, direction };
}

export function restoreSelection(base: Node, saved: SavedSelection): void {
    const sel = getRootSelection(base);
    if (!sel) return;
    sel.empty();

    const range = new Range();
    const anchorNode = getNodeFromPath(base, saved.anchor.coordinates);
    if (!anchorNode) return;

    range.setStart(anchorNode, saved.anchor.offset);
    if (saved.collapsed || !saved.focus) {
        range.collapse(true);
        sel.addRange(range);
    } else {
        const focusNode = getNodeFromPath(base, saved.focus.coordinates);
        if (!focusNode) {
            range.collapse(true);
            sel.addRange(range);
            return;
        }
        if (saved.direction === "forward") {
            range.setEnd(focusNode, saved.focus.offset);
            sel.addRange(range);
        } else {
            sel.addRange(range);
            sel.extend(focusNode, saved.focus.offset);
        }
    }
}
