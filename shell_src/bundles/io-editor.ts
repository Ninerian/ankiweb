import { Shape, ToolType, Point, RectShape, EllipseShape, PolygonShape, TextShape } from "./io/types";
import {
    SHAPE_MASK_COLOR,
    BORDER_COLOR,
    TEXT_BACKGROUND_COLOR,
    TEXT_FONT_FAMILY,
    TEXT_FONT_SIZE,
    TEXT_COLOR,
    floatToDisplay,
    shapesToCloze,
    clozeToShapes,
} from "./io/cloze";
import { getShapePixelBounds, getCombinedBounds } from "./io/geometry";

export class IoEditor {
    private container: HTMLElement | null = null;
    private stage: HTMLDivElement | null = null;
    private imgEl: HTMLImageElement | null = null;
    private svgEl: SVGSVGElement | null = null;
    private toolbarEl: HTMLDivElement | null = null;

    private shapes: Shape[] = [];
    private selectedIds: Set<string> = new Set();
    private activeTool: ToolType = "cursor";
    private activeColor: string = SHAPE_MASK_COLOR;

    // Viewport transform (zoom & pan)
    private scale: number = 1;
    private panX: number = 0;
    private panY: number = 0;

    // Natural image dimensions
    private imgWidth: number = 0;
    private imgHeight: number = 0;

    // Undo / Redo history
    private undoStack: string[] = [];
    private redoStack: string[] = [];

    // Interaction state
    private isDrawing: boolean = false;
    private drawStart: Point = { x: 0, y: 0 };
    private currentPolygonPoints: Point[] = [];
    private activeDrag: {
        mode: "move" | "resize" | "rotate" | "marquee" | "pan";
        handle?: string;
        startX: number;
        startY: number;
        startClientX?: number;
        startClientY?: number;
        initialShapes: Map<string, Shape>;
        initialPan?: { x: number; y: number };
        center?: { x: number; y: number };
        initialAngle?: number;
        startAngleRad?: number;
    } | null = null;

    private isTranslucent: boolean = false;
    private eventListeners: Map<string, Set<Function>> = new Map();

    constructor() {
        this.setupKeyboardShortcuts();
    }

    public init(containerIdOrEl: string | HTMLElement) {
        if (typeof containerIdOrEl === "string") {
            this.container = document.getElementById(containerIdOrEl);
        } else {
            this.container = containerIdOrEl;
        }

        if (!this.container) {
            console.warn("[IoEditor] Container not found!");
            return;
        }

        this.container.innerHTML = "";
        this.container.classList.add("io-editor-container");

        // Build Toolbar
        this.buildToolbar();

        // Build Viewport & Stage
        const viewport = document.createElement("div");
        viewport.className = "io-canvas-viewport";

        this.stage = document.createElement("div");
        this.stage.className = "io-canvas-stage";

        this.imgEl = document.createElement("img");
        this.imgEl.className = "io-img-bg";

        this.svgEl = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        this.svgEl.setAttribute("class", "io-svg-layer");

        this.stage.appendChild(this.imgEl);
        this.stage.appendChild(this.svgEl);
        viewport.appendChild(this.stage);
        this.container.appendChild(viewport);

        this.bindViewportEvents(viewport);
        this.pushUndo();
    }

    private buildToolbar() {
        this.toolbarEl = document.createElement("div");
        this.toolbarEl.className = "io-toolbar";

        // Tool group (Cursor, Rect, Ellipse, Polygon, Text, Color)
        const toolGroup = document.createElement("div");
        toolGroup.className = "io-toolbar-group";

        const tools: { id: ToolType; label: string; shortcut: string }[] = [
            { id: "cursor", label: "Select (S)", shortcut: "S" },
            { id: "rect", label: "Rectangle (R)", shortcut: "R" },
            { id: "ellipse", label: "Ellipse (E)", shortcut: "E" },
            { id: "polygon", label: "Polygon (P)", shortcut: "P" },
            { id: "text", label: "Text (T)", shortcut: "T" },
            { id: "fill", label: "Color (C)", shortcut: "C" },
        ];

        for (const t of tools) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = `io-btn ${this.activeTool === t.id ? "active" : ""}`;
            btn.dataset.tool = t.id;
            btn.title = t.label;
            btn.textContent = t.id.charAt(0).toUpperCase() + t.id.slice(1);
            btn.onclick = () => this.setTool(t.id);
            toolGroup.appendChild(btn);
        }
        this.toolbarEl.appendChild(toolGroup);

        // Color picker
        const colorInput = document.createElement("input");
        colorInput.type = "color";
        colorInput.className = "io-color-picker";
        colorInput.value = this.activeColor;
        colorInput.title = "Occlusion Color";
        colorInput.oninput = () => {
            this.activeColor = colorInput.value;
            if (this.selectedIds.size > 0) {
                this.recordUndo();
                for (const s of this.shapes) {
                    if (this.selectedIds.has(s.id)) {
                        s.fill = this.activeColor;
                    }
                }
                this.render();
                this.emitChange();
            }
        };
        this.toolbarEl.appendChild(colorInput);

        // Mode toggle button (Image Occlusion Mode) matching legacy
        const modeBtn = document.createElement("button");
        modeBtn.type = "button";
        modeBtn.className = "io-btn io-btn-mode";
        modeBtn.title = "Image Occlusion Mode";
        modeBtn.textContent = "Mode";
        modeBtn.onclick = () => {
            // Toggle hide-all mode in page signals
            const hideAllBtn = document.getElementById("mode-btn-hide-all");
            const hideOneBtn = document.getElementById("mode-btn-hide-one");
            if (hideAllBtn && hideOneBtn) {
                if (hideAllBtn.classList.contains("active")) {
                    hideOneBtn.click();
                } else {
                    hideAllBtn.click();
                }
            }
        };
        this.toolbarEl.appendChild(modeBtn);

        // Actions group (Undo/Redo, Group, Ungroup, Delete, Duplicate)
        const actGroup = document.createElement("div");
        actGroup.className = "io-toolbar-group";

        const addBtn = (parent: HTMLElement, text: string, title: string, fn: () => void) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "io-btn";
            btn.textContent = text;
            btn.title = title;
            btn.onclick = fn;
            parent.appendChild(btn);
            return btn;
        };

        addBtn(actGroup, "Undo", "Undo (Ctrl+Z)", () => this.undo());
        addBtn(actGroup, "Redo", "Redo (Ctrl+Y)", () => this.redo());
        addBtn(actGroup, "Dup", "Duplicate (D)", () => this.duplicateSelected());
        addBtn(actGroup, "Group", "Group (G)", () => this.groupSelected());
        addBtn(actGroup, "Ungroup", "Ungroup (U)", () => this.ungroupSelected());
        addBtn(actGroup, "Del", "Delete (Del)", () => this.deleteSelected());
        addBtn(actGroup, "All", "Select All (A)", () => this.selectAll());
        this.toolbarEl.appendChild(actGroup);
        // Z-Order Group (Bring to Front, Send to Back)
        const zGroup = document.createElement("div");
        zGroup.className = "io-toolbar-group";
        addBtn(zGroup, "Front", "Bring to Front", () => this.bringToFront());
        addBtn(zGroup, "Back", "Send to Back", () => this.sendToBack());
        this.toolbarEl.appendChild(zGroup);

        // Alignment Group (Left, H-Center, Right, Top, V-Center, Bottom)
        const alignGroup = document.createElement("div");
        alignGroup.className = "io-toolbar-group";
        addBtn(alignGroup, "⇥L", "Align Left (Shift+L)", () => this.alignLeft());
        addBtn(alignGroup, "↔C", "Align Horizontal Center (Shift+H)", () => this.alignHorizontalCenter());
        addBtn(alignGroup, "R⇤", "Align Right (Shift+R)", () => this.alignRight());
        addBtn(alignGroup, "⤒T", "Align Top (Shift+T)", () => this.alignTop());
        addBtn(alignGroup, "↕C", "Align Vertical Center (Shift+V)", () => this.alignVerticalCenter());
        addBtn(alignGroup, "⤓B", "Align Bottom (Shift+B)", () => this.alignBottom());
        this.toolbarEl.appendChild(alignGroup);

        // Zoom & View Group
        const viewGroup = document.createElement("div");
        viewGroup.className = "io-toolbar-group";
        addBtn(viewGroup, "+", "Zoom In (])", () => this.zoom(1.2));
        addBtn(viewGroup, "-", "Zoom Out ([)", () => this.zoom(1 / 1.2));
        addBtn(viewGroup, "Fit", "Reset Zoom (F)", () => this.resetZoom());
        addBtn(viewGroup, "Eye", "Toggle Translucent (L)", () => this.toggleTranslucent());
        this.toolbarEl.appendChild(viewGroup);

        this.container.appendChild(this.toolbarEl);
    }

    public setTool(tool: ToolType) {
        this.activeTool = tool;
        if (tool !== "polygon" && this.currentPolygonPoints.length > 0) {
            this.currentPolygonPoints = [];
        }
        if (this.toolbarEl) {
            const btns = this.toolbarEl.querySelectorAll(".io-btn[data-tool]");
            btns.forEach(b => {
                if ((b as HTMLElement).dataset.tool === tool) {
                    b.classList.add("active");
                } else {
                    b.classList.remove("active");
                }
            });
        }
        this.render();
    }

    public async loadImage(url: string): Promise<void> {
        return new Promise((resolve, reject) => {
            if (!this.container) {
                const def = document.getElementById("ankiweb-io-editor") || document.querySelector("[data-ankiweb-io-editor]");
                if (def) this.init(def as HTMLElement);
            }
            if (!this.imgEl) {
                reject(new Error("Editor not initialized"));
                return;
            }

            this.imgEl.onload = () => {
                this.imgWidth = this.imgEl!.naturalWidth || this.imgEl!.width || 800;
                this.imgHeight = this.imgEl!.naturalHeight || this.imgEl!.height || 600;
                this.imgEl!.style.width = `${this.imgWidth}px`;
                this.imgEl!.style.height = `${this.imgHeight}px`;

                if (this.svgEl) {
                    this.svgEl.setAttribute("viewBox", `0 0 ${this.imgWidth} ${this.imgHeight}`);
                    this.svgEl.style.width = `${this.imgWidth}px`;
                    this.svgEl.style.height = `${this.imgHeight}px`;
                }
                this.resetZoom();
                this.render();
                resolve();
            };
            this.imgEl.onerror = (e) => reject(e);
            this.imgEl.src = url;
        });
    }

    public getShapes(): Shape[] {
        return JSON.parse(JSON.stringify(this.shapes));
    }

    public setShapes(shapesOrJson: Shape[] | string): void {
        if (typeof shapesOrJson === "string") {
            try {
                this.shapes = JSON.parse(shapesOrJson);
            } catch {
                this.shapes = clozeToShapes(shapesOrJson);
            }
        } else {
            this.shapes = JSON.parse(JSON.stringify(shapesOrJson));
        }
        this.selectedIds.clear();
        this.pushUndo();
        this.render();
        this.emitChange();
    }

    public toCloze(options?: { hideAll?: boolean }): string {
        const hideAll = options?.hideAll !== undefined ? options.hideAll : true;
        return shapesToCloze(this.shapes, hideAll);
    }

    public fromCloze(clozeText: string): void {
        this.shapes = clozeToShapes(clozeText);
        this.selectedIds.clear();
        this.pushUndo();
        this.render();
        this.emitChange();
    }

    public on(event: string, callback: Function) {
        if (!this.eventListeners.has(event)) {
            this.eventListeners.set(event, new Set());
        }
        this.eventListeners.get(event)!.add(callback);
    }

    public off(event: string, callback: Function) {
        this.eventListeners.get(event)?.delete(callback);
    }

    private emit(event: string, detail: unknown) {
        const cbs = this.eventListeners.get(event);
        if (cbs) {
            cbs.forEach(fn => {
                try { fn(detail); } catch (e) { console.error(e); }
            });
        }
        window.dispatchEvent(new CustomEvent(event, { detail }));
    }

    private emitChange() {
        const cloze = this.toCloze();
        const payload = {
            shapes: this.getShapes(),
            count: this.shapes.filter(s => s.type !== "text").length,
            cloze,
        };
        this.emit("shapes-changed", payload);
        this.emit("ankiweb:io-shapes-changed", payload);
    }

    private emitSelection() {
        const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
        const payload = {
            selectedShapes: selected,
            count: selected.length,
        };
        this.emit("selection-changed", payload);
        this.emit("ankiweb:io-selection-changed", payload);
    }

    // Zoom & Pan
    private updateTransform() {
        if (this.stage) {
            this.stage.style.transform = `translate(${this.panX}px, ${this.panY}px) scale(${this.scale})`;
        }
    }

    public zoom(factor: number) {
        const oldScale = this.scale;
        this.scale = Math.max(0.1, Math.min(5, this.scale * factor));
        // Zoom around viewport center
        if (this.container) {
            const vp = this.container.querySelector(".io-canvas-viewport") as HTMLElement;
            if (vp) {
                const cx = vp.clientWidth / 2;
                const cy = vp.clientHeight / 2;
                this.panX = cx - (cx - this.panX) * (this.scale / oldScale);
                this.panY = cy - (cy - this.panY) * (this.scale / oldScale);
            }
        }
        this.updateTransform();
    }

    public resetZoom() {
        if (!this.container || !this.imgWidth) return;
        const vp = this.container.querySelector(".io-canvas-viewport") as HTMLElement;
        if (!vp) return;
        const w = vp.clientWidth || 800;
        const h = vp.clientHeight || 600;

        const scaleX = (w - 40) / this.imgWidth;
        const scaleY = (h - 40) / this.imgHeight;
        this.scale = Math.min(1, Math.min(scaleX, scaleY));
        if (this.scale <= 0) this.scale = 1;

        this.panX = (w - this.imgWidth * this.scale) / 2;
        this.panY = (h - this.imgHeight * this.scale) / 2;
        this.updateTransform();
    }

    // Undo / Redo
    private pushUndo() {
        this.undoStack.push(JSON.stringify(this.shapes));
        this.redoStack = [];
    }

    private recordUndo() {
        this.undoStack.push(JSON.stringify(this.shapes));
        this.redoStack = [];
    }

    public undo() {
        if (this.undoStack.length > 1) {
            const current = this.undoStack.pop()!;
            this.redoStack.push(current);
            const prev = this.undoStack[this.undoStack.length - 1];
            this.shapes = JSON.parse(prev);
            this.selectedIds.clear();
            this.render();
            this.emitChange();
        }
    }

    public redo() {
        if (this.redoStack.length > 0) {
            const next = this.redoStack.pop()!;
            this.undoStack.push(next);
            this.shapes = JSON.parse(next);
            this.selectedIds.clear();
            this.render();
            this.emitChange();
        }
    }

    public deleteSelected() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        this.shapes = this.shapes.filter(s => !this.selectedIds.has(s.id));
        this.selectedIds.clear();
        this.render();
        this.emitChange();
        this.emitSelection();
    }

    public duplicateSelected() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        const toDup = this.shapes.filter(s => this.selectedIds.has(s.id));
        const newSelected: Set<string> = new Set();
        for (const s of toDup) {
            const copy: Shape = JSON.parse(JSON.stringify(s));
            copy.id = `${copy.type}-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`;
            // 10px offset in normalized coordinates
            const dx = 10 / this.imgWidth;
            const dy = 10 / this.imgHeight;
            copy.left = Math.min(0.95, copy.left + dx);
            copy.top = Math.min(0.95, copy.top + dy);
            if (copy.type === "polygon") {
                copy.points = copy.points.map(pt => ({
                    x: Math.min(0.95, pt.x + dx),
                    y: Math.min(0.95, pt.y + dy),
                }));
            }
            copy.ordinal = undefined;
            this.shapes.push(copy);
            newSelected.add(copy.id);
        }
        // Match legacy: deselect original, select ONLY the cloned copy
        this.selectedIds = newSelected;
        this.render();
        this.emitChange();
        this.emitSelection();
    }

    public groupSelected() {
        if (this.selectedIds.size < 2) return;
        this.recordUndo();
        const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
        const ordinals = selected.map(s => s.ordinal).filter((o): o is number => typeof o === "number" && o > 0);
        const minOrd = ordinals.length > 0 ? Math.min(...ordinals) : undefined;
        const groupId = `group-${Date.now()}`;

        for (const s of selected) {
            s.groupId = groupId;
            if (minOrd) s.ordinal = minOrd;
        }
        this.render();
        this.emitChange();
    }

    public ungroupSelected() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        for (const s of this.shapes) {
            if (this.selectedIds.has(s.id)) {
                s.groupId = undefined;
            }
        }
        this.render();
        this.emitChange();
    }

    public selectAll() {
        this.selectedIds = new Set(this.shapes.map(s => s.id));
        this.render();
        this.emitSelection();
    }

    public bringToFront() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
        const unselected = this.shapes.filter(s => !this.selectedIds.has(s.id));
        this.shapes = [...unselected, ...selected];
        this.render();
        this.emitChange();
    }

    public sendToBack() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
        const unselected = this.shapes.filter(s => !this.selectedIds.has(s.id));
        this.shapes = [...selected, ...unselected];
        this.render();
        this.emitChange();
    }

    // Alignments (left, horizontal center, right, top, vertical center, bottom)
    public alignLeft() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
        if (selected.length === 1) {
            this.setShapeLeft(selected[0], 0);
        } else {
            const minX = Math.min(...selected.map(s => this.getShapeLeft(s)));
            for (const s of selected) this.setShapeLeft(s, minX);
        }
        this.render();
        this.emitChange();
    }

    public alignHorizontalCenter() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
        if (selected.length === 1) {
            const w = this.getShapeWidth(selected[0]);
            this.setShapeLeft(selected[0], (1 - w) / 2);
        } else {
            const minX = Math.min(...selected.map(s => this.getShapeLeft(s)));
            const maxX = Math.max(...selected.map(s => this.getShapeLeft(s) + this.getShapeWidth(s)));
            const groupCenter = (minX + maxX) / 2;
            for (const s of selected) {
                const w = this.getShapeWidth(s);
                this.setShapeLeft(s, groupCenter - w / 2);
            }
        }
        this.render();
        this.emitChange();
    }

    public alignRight() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
        if (selected.length === 1) {
            const w = this.getShapeWidth(selected[0]);
            this.setShapeLeft(selected[0], 1 - w);
        } else {
            const maxX = Math.max(...selected.map(s => this.getShapeLeft(s) + this.getShapeWidth(s)));
            for (const s of selected) {
                const w = this.getShapeWidth(s);
                this.setShapeLeft(s, maxX - w);
            }
        }
        this.render();
        this.emitChange();
    }

    public alignTop() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
        if (selected.length === 1) {
            this.setShapeTop(selected[0], 0);
        } else {
            const minY = Math.min(...selected.map(s => this.getShapeTop(s)));
            for (const s of selected) this.setShapeTop(s, minY);
        }
        this.render();
        this.emitChange();
    }

    public alignVerticalCenter() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
        if (selected.length === 1) {
            const h = this.getShapeHeight(selected[0]);
            this.setShapeTop(selected[0], (1 - h) / 2);
        } else {
            const minY = Math.min(...selected.map(s => this.getShapeTop(s)));
            const maxY = Math.max(...selected.map(s => this.getShapeTop(s) + this.getShapeHeight(s)));
            const groupCenter = (minY + maxY) / 2;
            for (const s of selected) {
                const h = this.getShapeHeight(s);
                this.setShapeTop(s, groupCenter - h / 2);
            }
        }
        this.render();
        this.emitChange();
    }

    public alignBottom() {
        if (this.selectedIds.size === 0) return;
        this.recordUndo();
        const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
        if (selected.length === 1) {
            const h = this.getShapeHeight(selected[0]);
            this.setShapeTop(selected[0], 1 - h);
        } else {
            const maxY = Math.max(...selected.map(s => this.getShapeTop(s) + this.getShapeHeight(s)));
            for (const s of selected) {
                const h = this.getShapeHeight(s);
                this.setShapeTop(s, maxY - h);
            }
        }
        this.render();
        this.emitChange();
    }

    private getShapeLeft(s: Shape): number {
        if (s.type === "polygon") return Math.min(...s.points.map(p => p.x));
        if (s.type === "ellipse") return s.left - s.rx;
        return s.left;
    }

    private getShapeTop(s: Shape): number {
        if (s.type === "polygon") return Math.min(...s.points.map(p => p.y));
        if (s.type === "ellipse") return s.top - s.ry;
        return s.top;
    }

    private getShapeWidth(s: Shape): number {
        if (s.type === "rect") return s.width;
        if (s.type === "ellipse") return s.rx * 2;
        if (s.type === "polygon") {
            const xs = s.points.map(p => p.x);
            return Math.max(...xs) - Math.min(...xs);
        }
        return (100 * (s.scale || 1)) / this.imgWidth;
    }

    private getShapeHeight(s: Shape): number {
        if (s.type === "rect") return s.height;
        if (s.type === "ellipse") return s.ry * 2;
        if (s.type === "polygon") {
            const ys = s.points.map(p => p.y);
            return Math.max(...ys) - Math.min(...ys);
        }
        return (30 * (s.scale || 1)) / this.imgHeight;
    }

    private setShapeLeft(s: Shape, newLeft: number) {
        const curLeft = this.getShapeLeft(s);
        const dx = newLeft - curLeft;
        s.left += dx;
        if (s.type === "polygon") {
            s.points = s.points.map(p => ({ x: p.x + dx, y: p.y }));
        }
    }

    private setShapeTop(s: Shape, newTop: number) {
        const curTop = this.getShapeTop(s);
        const dy = newTop - curTop;
        s.top += dy;
        if (s.type === "polygon") {
            s.points = s.points.map(p => ({ x: p.x, y: p.y + dy }));
        }
    }

    public toggleTranslucent() {
        this.isTranslucent = !this.isTranslucent;
        this.render();
    }

    // Precise Viewport & Pointer Events Mapping directly via rendered image bounds
    public clientToNormal(clientX: number, clientY: number): Point {
        if (!this.imgEl) return { x: 0, y: 0 };
        const r = this.imgEl.getBoundingClientRect();
        if (!r.width || !r.height) return { x: 0, y: 0 };
        const normX = (clientX - r.left) / r.width;
        const normY = (clientY - r.top) / r.height;
        return {
            x: Math.max(0, Math.min(1, normX)),
            y: Math.max(0, Math.min(1, normY)),
        };
    }

    private bindViewportEvents(viewport: HTMLElement) {
        viewport.onwheel = (e: WheelEvent) => {
            e.preventDefault();
            if (e.ctrlKey) {
                const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
                this.zoom(zoomFactor);
            } else {
                this.panX -= e.deltaX;
                this.panY -= e.deltaY;
                this.updateTransform();
            }
        };

        viewport.onpointerdown = (e: PointerEvent) => {
            if (e.button === 1 || e.spaceKey || (e.button === 0 && e.altKey)) {
                // Pan
                this.activeDrag = {
                    mode: "pan",
                    startX: e.clientX,
                    startY: e.clientY,
                    initialShapes: new Map(),
                    initialPan: { x: this.panX, y: this.panY },
                };
                viewport.setPointerCapture(e.pointerId);
                return;
            }

            if (e.button !== 0) return;

            const pt = this.clientToNormal(e.clientX, e.clientY);

            if (this.activeTool === "rect" || this.activeTool === "ellipse") {
                this.isDrawing = true;
                this.drawStart = pt;
                this.recordUndo();
                const newShape: Shape = this.activeTool === "rect" ? {
                    id: `rect-${Date.now()}`,
                    type: "rect",
                    left: pt.x,
                    top: pt.y,
                    width: 0.001,
                    height: 0.001,
                    angle: 0,
                    fill: this.activeColor,
                } : {
                    id: `ellipse-${Date.now()}`,
                    type: "ellipse",
                    left: pt.x,
                    top: pt.y,
                    rx: 0.001,
                    ry: 0.001,
                    angle: 0,
                    fill: this.activeColor,
                };
                this.shapes.push(newShape);
                this.selectedIds = new Set([newShape.id]);
                this.render();
                viewport.setPointerCapture(e.pointerId);
            } else if (this.activeTool === "polygon") {
                if (this.currentPolygonPoints.length === 0) {
                    this.recordUndo();
                }
                // Check if closing polygon near start point (within 15px in image space)
                if (this.currentPolygonPoints.length >= 3) {
                    const first = this.currentPolygonPoints[0];
                    const distSq = Math.hypot((pt.x - first.x) * this.imgWidth, (pt.y - first.y) * this.imgHeight);
                    if (distSq < 20) {
                        // Close polygon
                        const xs = this.currentPolygonPoints.map(p => p.x);
                        const ys = this.currentPolygonPoints.map(p => p.y);
                        const minX = Math.min(...xs);
                        const minY = Math.min(...ys);
                        const polyShape: PolygonShape = {
                            id: `polygon-${Date.now()}`,
                            type: "polygon",
                            left: minX,
                            top: minY,
                            angle: 0,
                            fill: this.activeColor,
                            points: [...this.currentPolygonPoints],
                        };
                        this.shapes.push(polyShape);
                        this.currentPolygonPoints = [];
                        this.selectedIds = new Set([polyShape.id]);
                        this.setTool("cursor");
                        this.render();
                        this.emitChange();
                        this.emitSelection();
                        return;
                    }
                }
                this.currentPolygonPoints.push(pt);
                this.render();
            } else if (this.activeTool === "text") {
                this.recordUndo();
                const textShape: TextShape = {
                    id: `text-${Date.now()}`,
                    type: "text",
                    left: pt.x,
                    top: pt.y,
                    angle: 0,
                    fill: TEXT_COLOR,
                    text: "Text",
                    scale: 1,
                    fontSize: 40 / 600,
                };
                this.shapes.push(textShape);
                this.selectedIds = new Set([textShape.id]);
                this.setTool("cursor");
                this.emitChange();
                this.emitSelection();
                this.editText(textShape);
            } else if (this.activeTool === "cursor") {
                // Background click: start marquee selection
                const target = e.target as SVGElement;
                if (!target.closest(".io-shape") && !target.closest(".io-handle")) {
                    if (!e.shiftKey) {
                        this.selectedIds.clear();
                    }
                    this.activeDrag = {
                        mode: "marquee",
                        startX: pt.x,
                        startY: pt.y,
                        initialShapes: new Map(),
                    };
                    viewport.setPointerCapture(e.pointerId);
                    this.render();
                    this.emitSelection();
                }
            }
        };

        viewport.onpointermove = (e: PointerEvent) => {
            if (this.activeDrag?.mode === "pan") {
                const dx = e.clientX - this.activeDrag.startX;
                const dy = e.clientY - this.activeDrag.startY;
                this.panX = (this.activeDrag.initialPan?.x || 0) + dx;
                this.panY = (this.activeDrag.initialPan?.y || 0) + dy;
                this.updateTransform();
                return;
            }

            const pt = this.clientToNormal(e.clientX, e.clientY);

            if (this.isDrawing) {
                const active = this.shapes[this.shapes.length - 1];
                if (!active) return;

                if (active.type === "rect") {
                    const l = Math.min(this.drawStart.x, pt.x);
                    const t = Math.min(this.drawStart.y, pt.y);
                    const w = Math.abs(pt.x - this.drawStart.x);
                    const h = Math.abs(pt.y - this.drawStart.y);
                    active.left = l;
                    active.top = t;
                    active.width = Math.max(0.005, w);
                    active.height = Math.max(0.005, h);
                } else if (active.type === "ellipse") {
                    const rx = Math.abs(pt.x - this.drawStart.x) / 2;
                    const ry = Math.abs(pt.y - this.drawStart.y) / 2;
                    const l = Math.min(this.drawStart.x, pt.x) + rx;
                    const t = Math.min(this.drawStart.y, pt.y) + ry;
                    active.left = l;
                    active.top = t;
                    active.rx = Math.max(0.005, rx);
                    active.ry = Math.max(0.005, ry);
                }
                this.render();
            } else if (this.activeDrag?.mode === "move") {
                const dx = pt.x - this.activeDrag.startX;
                const dy = pt.y - this.activeDrag.startY;
                for (const [id, init] of this.activeDrag.initialShapes) {
                    const s = this.shapes.find(x => x.id === id);
                    if (!s) continue;
                    s.left = Math.max(0, Math.min(1, init.left + dx));
                    s.top = Math.max(0, Math.min(1, init.top + dy));
                    if (s.type === "polygon" && init.type === "polygon") {
                        s.points = init.points.map(p => ({
                            x: Math.max(0, Math.min(1, p.x + dx)),
                            y: Math.max(0, Math.min(1, p.y + dy)),
                        }));
                    }
                }
                this.render();
            } else if (this.activeDrag?.mode === "resize") {
                const dx = pt.x - this.activeDrag.startX;
                const dy = pt.y - this.activeDrag.startY;
                const handle = this.activeDrag.handle;
                for (const [id, init] of this.activeDrag.initialShapes) {
                    const s = this.shapes.find(x => x.id === id);
                    if (!s) continue;
                    if (s.type === "rect" && init.type === "rect") {
                        if (handle === "e" || handle?.includes("e")) s.width = Math.max(0.005, init.width + dx);
                        if (handle === "s" || handle?.includes("s")) s.height = Math.max(0.005, init.height + dy);
                        if (handle === "w" || handle?.includes("w")) {
                            const newW = Math.max(0.005, init.width - dx);
                            s.left = init.left + (init.width - newW);
                            s.width = newW;
                        }
                        if (handle === "n" || handle?.includes("n")) {
                            const newH = Math.max(0.005, init.height - dy);
                            s.top = init.top + (init.height - newH);
                            s.height = newH;
                        }
                    } else if (s.type === "ellipse" && init.type === "ellipse") {
                        if (handle === "e" || handle?.includes("e") || handle === "w" || handle?.includes("w")) {
                            s.rx = Math.max(0.005, init.rx + ((handle === "e" || handle?.includes("e")) ? dx : -dx));
                        }
                        if (handle === "s" || handle?.includes("s") || handle === "n" || handle?.includes("n")) {
                            s.ry = Math.max(0.005, init.ry + ((handle === "s" || handle?.includes("s")) ? dy : -dy));
                        }
                    } else if (s.type === "text" && init.type === "text") {
                        const dist = Math.hypot(dx, dy);
                        s.scale = Math.max(0.2, (init.scale || 1) + (dx > 0 ? dist * 2 : -dist * 2));
                    }
                }
                this.render();
            } else if (this.activeDrag?.mode === "rotate") {
                const center = this.activeDrag.center!;
                const curAngleRad = Math.atan2(
                    (pt.y - center.y) * this.imgHeight,
                    (pt.x - center.x) * this.imgWidth
                );
                const deltaAngleDeg = ((curAngleRad - this.activeDrag.startAngleRad!) * 180) / Math.PI;
                let newAngle = (this.activeDrag.initialAngle! + deltaAngleDeg) % 360;
                if (newAngle < 0) newAngle += 360;

                for (const [id] of this.activeDrag.initialShapes) {
                    const s = this.shapes.find(x => x.id === id);
                    if (s) s.angle = Math.round(newAngle);
                }
                this.render();
            } else if (this.activeDrag?.mode === "marquee") {
                // Update selection marquee
                const startX = Math.min(this.activeDrag.startX, pt.x);
                const startY = Math.min(this.activeDrag.startY, pt.y);
                const endX = Math.max(this.activeDrag.startX, pt.x);
                const endY = Math.max(this.activeDrag.startY, pt.y);

                // Select all shapes intersecting marquee
                for (const s of this.shapes) {
                    const b = getShapePixelBounds(s, this.imgWidth, this.imgHeight);
                    const bNorm = {
                        left: b.x / this.imgWidth,
                        top: b.y / this.imgHeight,
                        right: (b.x + b.width) / this.imgWidth,
                        bottom: (b.y + b.height) / this.imgHeight,
                    };
                    const intersects = !(
                        bNorm.right < startX ||
                        bNorm.left > endX ||
                        bNorm.bottom < startY ||
                        bNorm.top > endY
                    );
                    if (intersects) {
                        this.selectedIds.add(s.id);
                    }
                }
                this.renderMarquee(startX, startY, endX - startX, endY - startY);
            }
        };

        viewport.onpointerup = (e: PointerEvent) => {
            if (this.isDrawing) {
                this.isDrawing = false;
                const active = this.shapes[this.shapes.length - 1];
                if (active) {
                    const b = getShapePixelBounds(active, this.imgWidth, this.imgHeight);
                    if (b.width < 5 || b.height < 5) {
                        this.shapes.pop();
                        this.selectedIds.clear();
                    } else {
                        this.emitChange();
                        this.emitSelection();
                    }
                }
                this.setTool("cursor");
            }

            if (this.activeDrag) {
                if (
                    this.activeDrag.mode === "move" ||
                    this.activeDrag.mode === "resize" ||
                    this.activeDrag.mode === "rotate"
                ) {
                    this.emitChange();
                    this.emitSelection();
                } else if (this.activeDrag.mode === "marquee") {
                    this.removeMarquee();
                    this.emitSelection();
                }
                this.activeDrag = null;
            }
            try { viewport.releasePointerCapture(e.pointerId); } catch {}
        };
    }

    private renderMarquee(x: number, y: number, w: number, h: number) {
        if (!this.svgEl) return;
        let marquee = this.svgEl.querySelector(".io-marquee-box") as SVGRectElement;
        if (!marquee) {
            marquee = document.createElementNS("http://www.w3.org/2000/svg", "rect");
            marquee.setAttribute("class", "io-marquee-box");
            marquee.setAttribute("fill", "rgba(13, 110, 253, 0.15)");
            marquee.setAttribute("stroke", "#0d6efd");
            marquee.setAttribute("stroke-width", "1");
            marquee.setAttribute("stroke-dasharray", "4 4");
            this.svgEl.appendChild(marquee);
        }
        marquee.setAttribute("x", `${x * this.imgWidth}`);
        marquee.setAttribute("y", `${y * this.imgHeight}`);
        marquee.setAttribute("width", `${w * this.imgWidth}`);
        marquee.setAttribute("height", `${h * this.imgHeight}`);
    }

    private removeMarquee() {
        if (!this.svgEl) return;
        const marquee = this.svgEl.querySelector(".io-marquee-box");
        if (marquee) marquee.remove();
        this.render();
    }

    private editText(textShape: TextShape) {
        if (!this.stage) return;
        const input = document.createElement("input");
        input.type = "text";
        input.value = textShape.text;
        input.className = "io-text-editor-input";
        input.style.position = "absolute";
        input.style.left = `${textShape.left * this.imgWidth}px`;
        input.style.top = `${textShape.top * this.imgHeight}px`;
        input.style.fontFamily = TEXT_FONT_FAMILY;
        input.style.fontSize = `${20 * (textShape.scale || 1)}px`;
        input.style.zIndex = "1000";

        const finish = () => {
            textShape.text = input.value || "Text";
            input.remove();
            this.render();
            this.emitChange();
        };

        input.onblur = finish;
        input.onkeydown = (e) => {
            if (e.key === "Enter") finish();
        };

        this.stage.appendChild(input);
        input.focus();
        input.select();
    }

    // SVG Rendering
    private render() {
        if (!this.svgEl) return;
        this.svgEl.innerHTML = "";

        const gShapes = document.createElementNS("http://www.w3.org/2000/svg", "g");

        for (const s of this.shapes) {
            const isSelected = this.selectedIds.has(s.id);
            const fill = s.fill || SHAPE_MASK_COLOR;

            let el: SVGElement | null = null;
            const b = getShapePixelBounds(s, this.imgWidth, this.imgHeight);
            const cx = b.x + b.width / 2;
            const cy = b.y + b.height / 2;

            if (s.type === "rect") {
                const r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
                r.setAttribute("x", `${s.left * this.imgWidth}`);
                r.setAttribute("y", `${s.top * this.imgHeight}`);
                r.setAttribute("width", `${s.width * this.imgWidth}`);
                r.setAttribute("height", `${s.height * this.imgHeight}`);
                r.setAttribute("fill", fill);
                r.setAttribute("stroke", BORDER_COLOR);
                r.setAttribute("stroke-width", "1");
                el = r;
            } else if (s.type === "ellipse") {
                const elSvg = document.createElementNS("http://www.w3.org/2000/svg", "ellipse");
                elSvg.setAttribute("cx", `${s.left * this.imgWidth}`);
                elSvg.setAttribute("cy", `${s.top * this.imgHeight}`);
                elSvg.setAttribute("rx", `${s.rx * this.imgWidth}`);
                elSvg.setAttribute("ry", `${s.ry * this.imgHeight}`);
                elSvg.setAttribute("fill", fill);
                elSvg.setAttribute("stroke", BORDER_COLOR);
                elSvg.setAttribute("stroke-width", "1");
                el = elSvg;
            } else if (s.type === "polygon") {
                const poly = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
                const pts = s.points.map(p => `${p.x * this.imgWidth},${p.y * this.imgHeight}`).join(" ");
                poly.setAttribute("points", pts);
                poly.setAttribute("fill", fill);
                poly.setAttribute("stroke", BORDER_COLOR);
                poly.setAttribute("stroke-width", "1");
                el = poly;
            } else if (s.type === "text") {
                const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
                const txt = document.createElementNS("http://www.w3.org/2000/svg", "text");
                txt.setAttribute("x", `${s.left * this.imgWidth}`);
                txt.setAttribute("y", `${s.top * this.imgHeight + 20 * (s.scale || 1)}`);
                txt.setAttribute("fill", s.fill || TEXT_COLOR);
                txt.setAttribute("font-family", TEXT_FONT_FAMILY);
                txt.setAttribute("font-size", `${20 * (s.scale || 1)}px`);
                txt.textContent = s.text;
                g.appendChild(txt);
                el = g;
            }

            if (el) {
                el.classList.add("io-shape");
                if (this.isTranslucent) el.classList.add("io-shape-transparent");
                if (isSelected) el.classList.add("selected");

                if (s.angle && s.angle !== 0) {
                    el.setAttribute("transform", `rotate(${s.angle} ${cx} ${cy})`);
                }

                // Pointer interaction for selecting / moving
                el.onpointerdown = (e: PointerEvent) => {
                    if (this.activeTool === "fill") {
                        s.fill = this.activeColor;
                        this.render();
                        this.emitChange();
                        return;
                    }

                    if (this.activeTool !== "cursor") return;

                    e.stopPropagation();
                    if (!e.shiftKey && !this.selectedIds.has(s.id)) {
                        this.selectedIds.clear();
                    }
                    this.selectedIds.add(s.id);

                    if (s.groupId) {
                        for (const other of this.shapes) {
                            if (other.groupId === s.groupId) {
                                this.selectedIds.add(other.id);
                            }
                        }
                    }

                    const pt = this.clientToNormal(e.clientX, e.clientY);
                    const initialShapes = new Map<string, Shape>();
                    for (const id of this.selectedIds) {
                        const targetShape = this.shapes.find(x => x.id === id);
                        if (targetShape) {
                            initialShapes.set(id, JSON.parse(JSON.stringify(targetShape)));
                        }
                    }

                    this.activeDrag = {
                        mode: "move",
                        startX: pt.x,
                        startY: pt.y,
                        initialShapes,
                    };

                    this.recordUndo();
                    this.render();
                    this.emitSelection();
                };

                el.ondblclick = (e: MouseEvent) => {
                    if (s.type === "text") {
                        e.stopPropagation();
                        this.editText(s as TextShape);
                    }
                };

                gShapes.appendChild(el);
            }
        }
        this.svgEl.appendChild(gShapes);

        // Render In-Progress Polygon
        if (this.currentPolygonPoints.length > 0) {
            const gPoly = document.createElementNS("http://www.w3.org/2000/svg", "g");
            for (let i = 0; i < this.currentPolygonPoints.length; i++) {
                const pt = this.currentPolygonPoints[i];
                const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                circle.setAttribute("cx", `${pt.x * this.imgWidth}`);
                circle.setAttribute("cy", `${pt.y * this.imgHeight}`);
                circle.setAttribute("r", "4");
                circle.setAttribute("fill", "#0d6efd");
                gPoly.appendChild(circle);

                if (i > 0) {
                    const prev = this.currentPolygonPoints[i - 1];
                    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
                    line.setAttribute("x1", `${prev.x * this.imgWidth}`);
                    line.setAttribute("y1", `${prev.y * this.imgHeight}`);
                    line.setAttribute("x2", `${pt.x * this.imgWidth}`);
                    line.setAttribute("y2", `${pt.y * this.imgHeight}`);
                    line.setAttribute("stroke", "#333");
                    line.setAttribute("stroke-width", "1.5");
                    gPoly.appendChild(line);
                }
            }
            this.svgEl.appendChild(gPoly);
        }

        // Render Selection Bounding Box & Handles
        if (this.selectedIds.size > 0 && this.activeTool === "cursor") {
            const selected = this.shapes.filter(s => this.selectedIds.has(s.id));
            const bounds = getCombinedBounds(selected, this.imgWidth, this.imgHeight);
            if (bounds) {
                const gSel = document.createElementNS("http://www.w3.org/2000/svg", "g");
                const cx = bounds.x + bounds.width / 2;
                const cy = bounds.y + bounds.height / 2;

                const singleAngle = selected.length === 1 ? selected[0].angle || 0 : 0;
                if (singleAngle) {
                    gSel.setAttribute("transform", `rotate(${singleAngle} ${cx} ${cy})`);
                }

                const box = document.createElementNS("http://www.w3.org/2000/svg", "rect");
                box.setAttribute("x", `${bounds.x - 2}`);
                box.setAttribute("y", `${bounds.y - 2}`);
                box.setAttribute("width", `${bounds.width + 4}`);
                box.setAttribute("height", `${bounds.height + 4}`);
                box.setAttribute("class", "io-selection-box");
                gSel.appendChild(box);

                // 8 Resize Handles (4 corners + 4 edge middles)
                const midX = bounds.x + bounds.width / 2;
                const midY = bounds.y + bounds.height / 2;
                const handles: { h: string; x: number; y: number }[] = [
                    { h: "nw", x: bounds.x, y: bounds.y },
                    { h: "n",  x: midX, y: bounds.y },
                    { h: "ne", x: bounds.x + bounds.width, y: bounds.y },
                    { h: "e",  x: bounds.x + bounds.width, y: midY },
                    { h: "se", x: bounds.x + bounds.width, y: bounds.y + bounds.height },
                    { h: "s",  x: midX, y: bounds.y + bounds.height },
                    { h: "sw", x: bounds.x, y: bounds.y + bounds.height },
                    { h: "w",  x: bounds.x, y: midY },
                ];
                for (const { h, x, y } of handles) {
                    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                    circle.setAttribute("cx", `${x}`);
                    circle.setAttribute("cy", `${y}`);
                    circle.setAttribute("r", "5");
                    circle.setAttribute("class", `io-handle io-handle-${h}`);

                    circle.onpointerdown = (e: PointerEvent) => {
                        e.stopPropagation();
                        const pt = this.clientToNormal(e.clientX, e.clientY);
                        const initialShapes = new Map<string, Shape>();
                        for (const s of selected) {
                            initialShapes.set(s.id, JSON.parse(JSON.stringify(s)));
                        }
                        this.activeDrag = {
                            mode: "resize",
                            handle: h,
                            startX: pt.x,
                            startY: pt.y,
                            initialShapes,
                        };
                        this.recordUndo();
                    };
                    gSel.appendChild(circle);
                }

                // Rotation Handle (top-center with connecting stem)
                const rotX = cx;
                const rotY = bounds.y - 20;

                const rotStem = document.createElementNS("http://www.w3.org/2000/svg", "line");
                rotStem.setAttribute("x1", `${cx}`);
                rotStem.setAttribute("y1", `${bounds.y - 2}`);
                rotStem.setAttribute("x2", `${rotX}`);
                rotStem.setAttribute("y2", `${rotY}`);
                rotStem.setAttribute("stroke", "#0d6efd");
                rotStem.setAttribute("stroke-width", "1");
                gSel.appendChild(rotStem);

                const rotCircle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                rotCircle.setAttribute("cx", `${rotX}`);
                rotCircle.setAttribute("cy", `${rotY}`);
                rotCircle.setAttribute("r", "5");
                rotCircle.setAttribute("class", "io-handle io-handle-rot");
                rotCircle.style.cursor = "grab";

                rotCircle.onpointerdown = (e: PointerEvent) => {
                    e.stopPropagation();
                    const pt = this.clientToNormal(e.clientX, e.clientY);
                    const centerNorm = {
                        x: cx / this.imgWidth,
                        y: cy / this.imgHeight,
                    };
                    const startAngleRad = Math.atan2(
                        (pt.y - centerNorm.y) * this.imgHeight,
                        (pt.x - centerNorm.x) * this.imgWidth
                    );
                    const initialShapes = new Map<string, Shape>();
                    for (const s of selected) {
                        initialShapes.set(s.id, JSON.parse(JSON.stringify(s)));
                    }
                    this.activeDrag = {
                        mode: "rotate",
                        startX: pt.x,
                        startY: pt.y,
                        center: centerNorm,
                        initialAngle: singleAngle,
                        startAngleRad,
                        initialShapes,
                    };
                    this.recordUndo();
                };
                gSel.appendChild(rotCircle);

                this.svgEl.appendChild(gSel);
            }
        }
    }

    private setupKeyboardShortcuts() {
        window.addEventListener("keydown", (e: KeyboardEvent) => {
            if (e.repeat) return; // Guard key repeat
            const target = e.target as HTMLElement;
            if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
                return;
            }

            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
                e.preventDefault();
                this.undo();
            } else if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "y" || (e.shiftKey && e.key.toLowerCase() === "z"))) {
                e.preventDefault();
                this.redo();
            } else if (e.key === "Delete" || e.key === "Backspace") {
                this.deleteSelected();
            } else if (e.key.toLowerCase() === "d" && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                this.duplicateSelected();
            } else if (e.key.toLowerCase() === "g" && !e.ctrlKey && !e.metaKey) {
                this.groupSelected();
            } else if (e.key.toLowerCase() === "u" && !e.ctrlKey && !e.metaKey) {
                this.ungroupSelected();
            } else if (e.key.toLowerCase() === "a" && !e.ctrlKey && !e.metaKey) {
                this.selectAll();
            } else if (e.key.toLowerCase() === "s" && !e.ctrlKey && !e.metaKey) {
                this.setTool("cursor");
            } else if (e.key.toLowerCase() === "r" && !e.ctrlKey && !e.metaKey) {
                this.setTool("rect");
            } else if (e.key.toLowerCase() === "e" && !e.ctrlKey && !e.metaKey) {
                this.setTool("ellipse");
            } else if (e.key.toLowerCase() === "p" && !e.ctrlKey && !e.metaKey) {
                this.setTool("polygon");
            } else if (e.key.toLowerCase() === "t" && !e.ctrlKey && !e.metaKey) {
                this.setTool("text");
            } else if (e.key.toLowerCase() === "c" && !e.ctrlKey && !e.metaKey) {
                this.setTool("fill");
            } else if (e.key.toLowerCase() === "l" && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
                this.toggleTranslucent();
            } else if (e.key.toLowerCase() === "f" && !e.ctrlKey && !e.metaKey) {
                this.resetZoom();
            } else if (e.key === "[") {
                this.zoom(1 / 1.2);
            } else if (e.key === "]") {
                this.zoom(1.2);
            } else if (e.shiftKey && e.key.toUpperCase() === "L") {
                e.preventDefault();
                this.alignLeft();
            } else if (e.shiftKey && e.key.toUpperCase() === "H") {
                e.preventDefault();
                this.alignHorizontalCenter();
            } else if (e.shiftKey && e.key.toUpperCase() === "R") {
                e.preventDefault();
                this.alignRight();
            } else if (e.shiftKey && e.key.toUpperCase() === "T") {
                e.preventDefault();
                this.alignTop();
            } else if (e.shiftKey && e.key.toUpperCase() === "V") {
                e.preventDefault();
                this.alignVerticalCenter();
            } else if (e.shiftKey && e.key.toUpperCase() === "B") {
                e.preventDefault();
                this.alignBottom();
            }
        });
    }
}

// Global singleton instance
const editorInstance = new IoEditor();

(window as any).AnkiwebIoEditor = {
    init: (container: string | HTMLElement) => editorInstance.init(container),
    loadImage: (url: string) => editorInstance.loadImage(url),
    getShapes: () => editorInstance.getShapes(),
    setShapes: (shapes: Shape[] | string) => editorInstance.setShapes(shapes),
    toCloze: (options?: { hideAll?: boolean }) => editorInstance.toCloze(options),
    fromCloze: (clozeText: string) => editorInstance.fromCloze(clozeText),
    on: (event: string, callback: Function) => editorInstance.on(event, callback),
    off: (event: string, callback: Function) => editorInstance.off(event, callback),
    setTool: (tool: ToolType) => editorInstance.setTool(tool),
    deleteSelected: () => editorInstance.deleteSelected(),
    duplicateSelected: () => editorInstance.duplicateSelected(),
    groupSelected: () => editorInstance.groupSelected(),
    ungroupSelected: () => editorInstance.ungroupSelected(),
    selectAll: () => editorInstance.selectAll(),
    bringToFront: () => editorInstance.bringToFront(),
    sendToBack: () => editorInstance.sendToBack(),
    alignLeft: () => editorInstance.alignLeft(),
    alignHorizontalCenter: () => editorInstance.alignHorizontalCenter(),
    alignRight: () => editorInstance.alignRight(),
    alignTop: () => editorInstance.alignTop(),
    alignVerticalCenter: () => editorInstance.alignVerticalCenter(),
    alignBottom: () => editorInstance.alignBottom(),
    undo: () => editorInstance.undo(),
    redo: () => editorInstance.redo(),
    zoom: (f: number) => editorInstance.zoom(f),
    resetZoom: () => editorInstance.resetZoom(),
    clientToNormal: (cx: number, cy: number) => editorInstance.clientToNormal(cx, cy),
};

export default editorInstance;
