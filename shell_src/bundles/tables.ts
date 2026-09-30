/**
 * tables.ts: Implementation of VirtualTable and ScrollArea components.
 * Ported from Svelte:
 * - ts/lib/components/VirtualTable.svelte
 * - ts/lib/components/ScrollArea.svelte
 * - ts/lib/components/resizable.ts
 */

export interface VirtualTableOptions {
    itemsCount: number;
    itemHeight: number;
    bottomOffset?: number;
    renderRow?: (index: number) => HTMLElement | string;
    onSliceChange?: (startIndex: number, endIndex: number) => void;
}

export class VirtualTable {
    container: HTMLElement;
    table: HTMLTableElement;
    tbody: HTMLTableSectionElement;
    thead: HTMLTableSectionElement | null;
    itemsCount: number;
    itemHeight: number;
    bottomOffset: number;
    renderRow?: (index: number) => HTMLElement | string;
    onSliceChange?: (startIndex: number, endIndex: number) => void;

    private topSpacer: HTMLTableRowElement;
    private bottomSpacer: HTMLTableRowElement;
    private topSpacerCell: HTMLTableCellElement;
    private bottomSpacerCell: HTMLTableCellElement;
    private scrollTop: number = 0;
    private containerHeight: number = 0;
    private startIndex: number = 0;
    private endIndex: number = 0;
    private destroyed: boolean = false;

    private onScrollHandler: () => void;
    private onResizeHandler: () => void;

    constructor(container: HTMLElement, options: VirtualTableOptions) {
        this.container = container;
        this.itemsCount = options.itemsCount || 0;
        this.itemHeight = options.itemHeight || 30;
        this.bottomOffset = options.bottomOffset || 0;
        this.renderRow = options.renderRow;
        this.onSliceChange = options.onSliceChange;

        const table = container.querySelector<HTMLTableElement>("table.table");
        if (!table) {
            throw new Error("VirtualTable requires a table element inside container");
        }
        this.table = table;

        let tbody = table.querySelector<HTMLTableSectionElement>("tbody");
        if (!tbody) {
            tbody = document.createElement("tbody");
            table.appendChild(tbody);
        }
        this.tbody = tbody;
        this.thead = table.querySelector<HTMLTableSectionElement>("thead");

        // Create top and bottom spacer rows
        this.topSpacer = document.createElement("tr");
        this.topSpacerCell = document.createElement("td");
        this.topSpacer.className = "vt-top-spacer";
        this.topSpacer.appendChild(this.topSpacerCell);

        this.bottomSpacer = document.createElement("tr");
        this.bottomSpacerCell = document.createElement("td");
        this.bottomSpacer.className = "vt-bottom-spacer";
        this.bottomSpacer.appendChild(this.bottomSpacerCell);

        this.onScrollHandler = () => {
            this.scrollTop = this.container.scrollTop;
            this.update();
        };

        this.onResizeHandler = () => {
            this.computeContainerHeight();
            this.update();
        };

        this.container.addEventListener("scroll", this.onScrollHandler, { passive: true });
        window.addEventListener("resize", this.onResizeHandler, { passive: true });

        // Initial layout
        this.computeContainerHeight();
        this.update();
    }

    setItemsCount(count: number) {
        this.itemsCount = count;
        this.update();
    }

    setItemHeight(height: number) {
        this.itemHeight = height;
        this.computeContainerHeight();
        this.update();
    }

    setBottomOffset(offset: number) {
        this.bottomOffset = offset;
        this.computeContainerHeight();
        this.update();
    }

    computeContainerHeight() {
        if (!this.container) return;
        const clientHeight = document.documentElement.clientHeight;
        const offsetTop = this.container.offsetTop;
        const availableHeight = clientHeight - offsetTop - this.bottomOffset;
        this.containerHeight = Math.max(0, Math.floor(availableHeight / this.itemHeight) * this.itemHeight);
        if (this.containerHeight > 0) {
            this.container.style.setProperty("--container-height", `${this.containerHeight}px`);
        }
    }

    getContainerHeight(): number {
        return this.containerHeight;
    }

    getSlice(): { startIndex: number; endIndex: number; length: number } {
        return {
            startIndex: this.startIndex,
            endIndex: this.endIndex,
            length: this.endIndex - this.startIndex,
        };
    }

    scrollToIndex(index: number) {
        const clamped = Math.max(0, Math.min(index, this.itemsCount - 1));
        this.container.scrollTop = clamped * this.itemHeight;
    }

    update() {
        if (this.destroyed) return;

        // Container height fallback if clientHeight/offsetTop yielded 0 (e.g. initial hidden or small viewport)
        let effHeight = this.containerHeight;
        if (effHeight <= 0) {
            effHeight = this.container.clientHeight || 400;
        }

        const sliceLength = Math.ceil(effHeight / this.itemHeight);
        const startIndex = Math.floor(this.scrollTop / this.itemHeight);
        const endIndex = Math.min(startIndex + sliceLength, this.itemsCount);

        this.startIndex = startIndex;
        this.endIndex = endIndex;

        // Number of columns in header or default 1 for spacer colspan
        let colCount = 1;
        if (this.thead) {
            const firstHeaderRow = this.thead.querySelector("tr");
            if (firstHeaderRow) {
                colCount = firstHeaderRow.children.length || 1;
            }
        }
        this.topSpacerCell.colSpan = colCount;
        this.bottomSpacerCell.colSpan = colCount;

        const topHeight = this.itemHeight * startIndex;
        const bottomHeight = this.itemHeight * this.itemsCount - this.itemHeight * endIndex;

        // Clear existing rows
        this.tbody.innerHTML = "";

        if (topHeight > 0) {
            this.topSpacerCell.style.height = `${topHeight}px`;
            this.topSpacerCell.style.padding = "0";
            this.topSpacerCell.style.border = "none";
            this.tbody.appendChild(this.topSpacer);
        }

        if (this.renderRow) {
            for (let i = startIndex; i < endIndex; i++) {
                const rowContent = this.renderRow(i);
                if (typeof rowContent === "string") {
                    const temp = document.createElement("template");
                    temp.innerHTML = rowContent.trim();
                    const el = temp.content.firstElementChild;
                    if (el) this.tbody.appendChild(el);
                } else if (rowContent instanceof HTMLElement) {
                    this.tbody.appendChild(rowContent);
                }
            }
        } else {
            // Default row rendering if none provided
            for (let i = startIndex; i < endIndex; i++) {
                const tr = document.createElement("tr");
                tr.setAttribute("data-row-index", i.toString());
                const td = document.createElement("td");
                td.textContent = `Row ${i}`;
                tr.appendChild(td);
                this.tbody.appendChild(tr);
            }
        }

        if (bottomHeight > 0) {
            this.bottomSpacerCell.style.height = `${bottomHeight}px`;
            this.bottomSpacerCell.style.padding = "0";
            this.bottomSpacerCell.style.border = "none";
            this.tbody.appendChild(this.bottomSpacer);
        }

        if (this.onSliceChange) {
            this.onSliceChange(startIndex, endIndex);
        }
    }

    destroy() {
        this.destroyed = true;
        this.container.removeEventListener("scroll", this.onScrollHandler);
        window.removeEventListener("resize", this.onResizeHandler);
    }
}


/**
 * ScrollArea implementation:
 * - Upstream IntersectionObserver edge detection for top/bottom/left/right scroll-shadows
 * - Upstream measuring scrollbar height
 * - Custom scrollbars: thumb ratio, dragging, track clicking, wheel forwarding, keyboard navigation,
 *   RTL support, hide when content fits, overscroll control, scrollTo API.
 */
export interface ScrollAreaOptions {
    scrollX?: boolean;
    scrollY?: boolean;
    customScrollbars?: boolean;
    scrollHideDelay?: number;
    dir?: "ltr" | "rtl";
}

export class ScrollArea {
    wrapper: HTMLElement;
    viewport: HTMLElement;
    scrollContent: HTMLElement | null;
    scrollX: boolean;
    scrollY: boolean;
    customScrollbars: boolean;
    scrollHideDelay: number;
    dir: "ltr" | "rtl";

    private observer: IntersectionObserver | null = null;
    private scrollStates: Record<string, boolean> = {
        top: false,
        right: false,
        bottom: false,
        left: false,
    };

    private shadowTop: HTMLElement | null = null;
    private shadowBottom: HTMLElement | null = null;
    private shadowLeft: HTMLElement | null = null;
    private shadowRight: HTMLElement | null = null;

    private scrollbarY: HTMLElement | null = null;
    private thumbY: HTMLElement | null = null;
    private scrollbarX: HTMLElement | null = null;
    private thumbX: HTMLElement | null = null;

    private pointerOffsetY: number = 0;
    private pointerOffsetX: number = 0;
    private isDraggingY: boolean = false;
    private isDraggingX: boolean = false;
    private hideTimeout: number | null = null;

    private onScrollHandler: () => void;
    private onResizeHandler: () => void;

    constructor(wrapper: HTMLElement, options: ScrollAreaOptions = {}) {
        this.wrapper = wrapper;
        this.scrollX = options.scrollX || false;
        this.scrollY = options.scrollY !== false; // default true if not specified
        this.customScrollbars = options.customScrollbars !== false;
        this.scrollHideDelay = options.scrollHideDelay || 600;
        this.dir = options.dir || (this.wrapper.getAttribute("dir") === "rtl" ? "rtl" : "ltr");

        const viewport = wrapper.querySelector<HTMLElement>(".scroll-area");
        if (!viewport) {
            throw new Error("ScrollArea requires an inner .scroll-area element");
        }
        this.viewport = viewport;
        this.scrollContent = wrapper.querySelector<HTMLElement>(".scroll-content");

        // Measure native scrollbar height (as upstream measureScrollbar)
        const scrollBarHeight = this.viewport.offsetHeight - this.viewport.clientHeight;
        const relativeParent = wrapper.closest<HTMLElement>(".scroll-area-relative");
        if (relativeParent) {
            relativeParent.style.setProperty("--scrollbar-height", `${scrollBarHeight}px`);
        }
        this.viewport.classList.remove("measuring");

        // Setup shadows
        this.shadowTop = wrapper.querySelector<HTMLElement>(".scroll-shadow.top-0");
        this.shadowBottom = wrapper.querySelector<HTMLElement>(".scroll-shadow.bottom-0");
        this.shadowLeft = wrapper.querySelector<HTMLElement>(".scroll-shadow.start-0");
        this.shadowRight = wrapper.querySelector<HTMLElement>(".scroll-shadow.end-0");

        // Init IntersectionObserver (as upstream initObserver)
        this.initEdgeObserver();

        if (this.customScrollbars) {
            this.viewport.classList.add("custom-scrollbars");
            this.buildCustomScrollbars();
        }

        this.onScrollHandler = () => {
            this.updateShadowsFallback();
            if (this.customScrollbars) {
                this.updateThumbPositions();
                this.showScrollbars();
                this.scheduleHideScrollbars();
            }
        };

        this.onResizeHandler = () => {
            if (this.customScrollbars) {
                this.updateScrollbarGeometry();
            }
        };

        this.viewport.addEventListener("scroll", this.onScrollHandler, { passive: true });
        window.addEventListener("resize", this.onResizeHandler, { passive: true });

        // Hover handling to show/hide scrollbars
        this.wrapper.addEventListener("pointerenter", () => {
            if (this.customScrollbars) {
                this.showScrollbars();
            }
        });

        this.wrapper.addEventListener("pointerleave", () => {
            if (this.customScrollbars && !this.isDraggingY && !this.isDraggingX) {
                this.scheduleHideScrollbars();
            }
        });

        // Initial geometry update
        setTimeout(() => {
            this.updateScrollbarGeometry();
            this.updateShadowsFallback();
        }, 0);
    }

    private initEdgeObserver() {
        if (typeof IntersectionObserver !== "undefined") {
            try {
                this.observer = new IntersectionObserver((entries) => {
                    entries.forEach((entry) => {
                        const edge = entry.target.getAttribute("data-edge");
                        if (edge && edge in this.scrollStates) {
                            this.scrollStates[edge] = !entry.isIntersecting;
                        }
                    });
                    this.renderShadows();
                }, { root: this.viewport });

                const edges = this.viewport.getElementsByClassName("scroll-edge");
                for (let i = 0; i < edges.length; i++) {
                    this.observer.observe(edges[i]);
                }
            } catch (e) {
                // Fallback to scroll position based shadows
            }
        }
    }

    private renderShadows() {
        if (this.shadowTop) this.shadowTop.style.display = this.scrollStates.top ? "block" : "none";
        if (this.shadowBottom) this.shadowBottom.style.display = this.scrollStates.bottom ? "block" : "none";
        if (this.shadowLeft) this.shadowLeft.style.display = this.scrollStates.left ? "block" : "none";
        if (this.shadowRight) this.shadowRight.style.display = this.scrollStates.right ? "block" : "none";
    }

    private updateShadowsFallback() {
        const canScrollY = this.viewport.scrollHeight > this.viewport.clientHeight;
        const canScrollX = this.viewport.scrollWidth > this.viewport.clientWidth;

        if (canScrollY) {
            this.scrollStates.top = this.viewport.scrollTop > 1;
            this.scrollStates.bottom = (this.viewport.scrollTop + this.viewport.clientHeight) < (this.viewport.scrollHeight - 1);
        } else {
            this.scrollStates.top = false;
            this.scrollStates.bottom = false;
        }

        if (canScrollX) {
            this.scrollStates.left = this.viewport.scrollLeft > 1;
            this.scrollStates.right = (this.viewport.scrollLeft + this.viewport.clientWidth) < (this.viewport.scrollWidth - 1);
        } else {
            this.scrollStates.left = false;
            this.scrollStates.right = false;
        }

        this.renderShadows();
    }

    private buildCustomScrollbars() {
        // Vertical scrollbar
        if (this.scrollY) {
            this.scrollbarY = document.createElement("div");
            this.scrollbarY.className = "scroll-area-scrollbar";
            this.scrollbarY.setAttribute("data-orientation", "vertical");
            this.scrollbarY.setAttribute("data-state", "hidden");

            this.thumbY = document.createElement("div");
            this.thumbY.className = "scroll-area-thumb";
            this.thumbY.tabIndex = 0;
            this.thumbY.setAttribute("role", "scrollbar");
            this.thumbY.setAttribute("aria-orientation", "vertical");
            this.scrollbarY.appendChild(this.thumbY);

            this.wrapper.appendChild(this.scrollbarY);
            this.bindVerticalScrollbarEvents();
        }

        // Horizontal scrollbar
        if (this.scrollX) {
            this.scrollbarX = document.createElement("div");
            this.scrollbarX.className = "scroll-area-scrollbar";
            this.scrollbarX.setAttribute("data-orientation", "horizontal");
            this.scrollbarX.setAttribute("data-state", "hidden");

            this.thumbX = document.createElement("div");
            this.thumbX.className = "scroll-area-thumb";
            this.thumbX.tabIndex = 0;
            this.thumbX.setAttribute("role", "scrollbar");
            this.thumbX.setAttribute("aria-orientation", "horizontal");
            this.scrollbarX.appendChild(this.thumbX);

            this.wrapper.appendChild(this.scrollbarX);
            this.bindHorizontalScrollbarEvents();
        }
    }

    /**
     * Upstream ratio formulas:
     * ratio = viewportSize / contentSize
     * thumbSize = max(scrollbarSize * ratio, 18)
     */
    static getThumbRatio(viewportSize: number, contentSize: number): number {
        const ratio = viewportSize / contentSize;
        return isNaN(ratio) || !isFinite(ratio) ? 0 : ratio;
    }

    static getThumbSize(viewportSize: number, contentSize: number, scrollbarSize: number): number {
        const ratio = ScrollArea.getThumbRatio(viewportSize, contentSize);
        const thumbSize = scrollbarSize * ratio;
        return Math.max(thumbSize, 18);
    }

    static getThumbOffsetFromScroll(scrollPos: number, maxScroll: number, maxThumbPos: number): number {
        if (maxScroll <= 0) return 0;
        const clampedScroll = Math.max(0, Math.min(scrollPos, maxScroll));
        return (clampedScroll / maxScroll) * maxThumbPos;
    }

    static getScrollPositionFromThumbOffset(thumbOffset: number, maxThumbPos: number, maxScroll: number): number {
        if (maxThumbPos <= 0) return 0;
        const clampedOffset = Math.max(0, Math.min(thumbOffset, maxThumbPos));
        return (clampedOffset / maxThumbPos) * maxScroll;
    }

    updateScrollbarGeometry() {
        if (!this.customScrollbars) return;

        // Vertical geometry
        if (this.scrollbarY && this.thumbY) {
            const viewportH = this.viewport.clientHeight;
            const contentH = this.viewport.scrollHeight;
            const trackH = this.scrollbarY.clientHeight || viewportH;

            const hasThumb = contentH > viewportH && trackH > 0;
            if (!hasThumb) {
                this.scrollbarY.setAttribute("data-state", "hidden");
                this.thumbY.style.display = "none";
            } else {
                this.thumbY.style.display = "block";
                const thumbH = ScrollArea.getThumbSize(viewportH, contentH, trackH);
                this.thumbY.style.height = `${thumbH}px`;
                this.thumbY.setAttribute("aria-valuemin", "0");
                this.thumbY.setAttribute("aria-valuemax", (contentH - viewportH).toString());
                this.thumbY.setAttribute("aria-valuenow", this.viewport.scrollTop.toString());
            }
        }

        // Horizontal geometry
        if (this.scrollbarX && this.thumbX) {
            const viewportW = this.viewport.clientWidth;
            const contentW = this.viewport.scrollWidth;
            const trackW = this.scrollbarX.clientWidth || viewportW;

            const hasThumb = contentW > viewportW && trackW > 0;
            if (!hasThumb) {
                this.scrollbarX.setAttribute("data-state", "hidden");
                this.thumbX.style.display = "none";
            } else {
                this.thumbX.style.display = "block";
                const thumbW = ScrollArea.getThumbSize(viewportW, contentW, trackW);
                this.thumbX.style.width = `${thumbW}px`;
                this.thumbX.setAttribute("aria-valuemin", "0");
                this.thumbX.setAttribute("aria-valuemax", (contentH_or_W => contentH_or_W - viewportW)(contentW).toString());
                this.thumbX.setAttribute("aria-valuenow", this.viewport.scrollLeft.toString());
            }
        }

        this.updateThumbPositions();
    }

    private updateThumbPositions() {
        if (this.scrollbarY && this.thumbY) {
            const viewportH = this.viewport.clientHeight;
            const contentH = this.viewport.scrollHeight;
            const trackH = this.scrollbarY.clientHeight || viewportH;
            const thumbH = parseFloat(this.thumbY.style.height) || ScrollArea.getThumbSize(viewportH, contentH, trackH);

            const maxScroll = contentH - viewportH;
            const maxThumb = trackH - thumbH;
            const offset = ScrollArea.getThumbOffsetFromScroll(this.viewport.scrollTop, maxScroll, maxThumb);
            this.thumbY.style.transform = `translate3d(0, ${offset}px, 0)`;
            this.thumbY.setAttribute("aria-valuenow", Math.round(this.viewport.scrollTop).toString());
        }

        if (this.scrollbarX && this.thumbX) {
            const viewportW = this.viewport.clientWidth;
            const contentW = this.viewport.scrollWidth;
            const trackW = this.scrollbarX.clientWidth || viewportW;
            const thumbW = parseFloat(this.thumbX.style.width) || ScrollArea.getThumbSize(viewportW, contentW, trackW);

            const maxScroll = contentW - viewportW;
            const maxThumb = trackW - thumbW;
            const offset = ScrollArea.getThumbOffsetFromScroll(this.viewport.scrollLeft, maxScroll, maxThumb);
            this.thumbX.style.transform = `translate3d(${offset}px, 0, 0)`;
            this.thumbX.setAttribute("aria-valuenow", Math.round(this.viewport.scrollLeft).toString());
        }
    }

    private showScrollbars() {
        if (this.scrollbarY && this.viewport.scrollHeight > this.viewport.clientHeight) {
            this.scrollbarY.setAttribute("data-state", "visible");
        }
        if (this.scrollbarX && this.viewport.scrollWidth > this.viewport.clientWidth) {
            this.scrollbarX.setAttribute("data-state", "visible");
        }
    }

    private scheduleHideScrollbars() {
        clearTimeout(this.hideTimeout ?? undefined);
        this.hideTimeout = window.setTimeout(() => {
            if (!this.isDraggingY && !this.isDraggingX) {
                if (this.scrollbarY) this.scrollbarY.setAttribute("data-state", "hidden");
                if (this.scrollbarX) this.scrollbarX.setAttribute("data-state", "hidden");
            }
            this.hideTimeout = null;
        }, this.scrollHideDelay);
    }

    private bindVerticalScrollbarEvents() {
        if (!this.scrollbarY || !this.thumbY) return;

        // Thumb dragging
        this.thumbY.addEventListener("pointerdown", (e) => {
            if (e.button !== 0) return;
            e.stopPropagation();
            this.isDraggingY = true;
            this.showScrollbars();
            const thumbRect = this.thumbY!.getBoundingClientRect();
            this.pointerOffsetY = e.clientY - thumbRect.top;
            (e.target as HTMLElement).setPointerCapture(e.pointerId);
            document.body.style.userSelect = "none";
        });

        this.thumbY.addEventListener("pointermove", (e) => {
            if (!this.isDraggingY || !this.scrollbarY || !this.thumbY) return;
            const trackRect = this.scrollbarY.getBoundingClientRect();
            const thumbH = this.thumbY.offsetHeight;
            const trackH = trackRect.height;
            const pointerPos = e.clientY - trackRect.top;
            const thumbTop = pointerPos - this.pointerOffsetY;
            const maxThumb = trackH - thumbH;
            const maxScroll = this.viewport.scrollHeight - this.viewport.clientHeight;

            const scrollPos = ScrollArea.getScrollPositionFromThumbOffset(thumbTop, maxThumb, maxScroll);
            this.viewport.scrollTop = scrollPos;
        });

        const stopDraggingY = (e: PointerEvent) => {
            if (!this.isDraggingY) return;
            this.isDraggingY = false;
            try {
                if (this.thumbY && this.thumbY.hasPointerCapture(e.pointerId)) {
                    this.thumbY.releasePointerCapture(e.pointerId);
                }
            } catch (err) {}
            document.body.style.userSelect = "";
            this.scheduleHideScrollbars();
        };

        this.thumbY.addEventListener("pointerup", stopDraggingY);
        this.thumbY.addEventListener("pointercancel", stopDraggingY);

        // Track click (jump scroll)
        this.scrollbarY.addEventListener("pointerdown", (e) => {
            if (e.button !== 0 || e.target === this.thumbY) return;
            const trackRect = this.scrollbarY!.getBoundingClientRect();
            const thumbH = this.thumbY!.offsetHeight;
            const clickY = e.clientY - trackRect.top;
            const maxThumb = trackRect.height - thumbH;
            const maxScroll = this.viewport.scrollHeight - this.viewport.clientHeight;

            // Center thumb at click
            const targetThumbTop = clickY - thumbH / 2;
            const scrollPos = ScrollArea.getScrollPositionFromThumbOffset(targetThumbTop, maxThumb, maxScroll);
            this.viewport.scrollTo({ top: scrollPos, behavior: "smooth" });
        });

        // Wheel forwarding from scrollbar to viewport
        this.scrollbarY.addEventListener("wheel", (e) => {
            e.preventDefault();
            this.viewport.scrollTop += e.deltaY;
        }, { passive: false });

        // Keyboard navigation when thumb is focused
        this.thumbY.addEventListener("keydown", (e) => {
            const step = 40;
            const pageStep = this.viewport.clientHeight;
            if (e.key === "ArrowUp") {
                e.preventDefault();
                this.viewport.scrollTop -= step;
            } else if (e.key === "ArrowDown") {
                e.preventDefault();
                this.viewport.scrollTop += step;
            } else if (e.key === "PageUp") {
                e.preventDefault();
                this.viewport.scrollTop -= pageStep;
            } else if (e.key === "PageDown") {
                e.preventDefault();
                this.viewport.scrollTop += pageStep;
            } else if (e.key === "Home") {
                e.preventDefault();
                this.viewport.scrollTop = 0;
            } else if (e.key === "End") {
                e.preventDefault();
                this.viewport.scrollTop = this.viewport.scrollHeight;
            }
        });
    }

    private bindHorizontalScrollbarEvents() {
        if (!this.scrollbarX || !this.thumbX) return;

        this.thumbX.addEventListener("pointerdown", (e) => {
            if (e.button !== 0) return;
            e.stopPropagation();
            this.isDraggingX = true;
            this.showScrollbars();
            const thumbRect = this.thumbX!.getBoundingClientRect();
            this.pointerOffsetX = e.clientX - thumbRect.left;
            (e.target as HTMLElement).setPointerCapture(e.pointerId);
            document.body.style.userSelect = "none";
        });

        this.thumbX.addEventListener("pointermove", (e) => {
            if (!this.isDraggingX || !this.scrollbarX || !this.thumbX) return;
            const trackRect = this.scrollbarX.getBoundingClientRect();
            const thumbW = this.thumbX.offsetWidth;
            const trackW = trackRect.width;
            const pointerPos = e.clientX - trackRect.left;
            const thumbLeft = pointerPos - this.pointerOffsetX;
            const maxThumb = trackW - thumbW;
            const maxScroll = this.viewport.scrollWidth - this.viewport.clientWidth;

            const scrollPos = ScrollArea.getScrollPositionFromThumbOffset(thumbLeft, maxThumb, maxScroll);
            this.viewport.scrollLeft = scrollPos;
        });

        const stopDraggingX = (e: PointerEvent) => {
            if (!this.isDraggingX) return;
            this.isDraggingX = false;
            try {
                if (this.thumbX && this.thumbX.hasPointerCapture(e.pointerId)) {
                    this.thumbX.releasePointerCapture(e.pointerId);
                }
            } catch (err) {}
            document.body.style.userSelect = "";
            this.scheduleHideScrollbars();
        };

        this.thumbX.addEventListener("pointerup", stopDraggingX);
        this.thumbX.addEventListener("pointercancel", stopDraggingX);

        this.scrollbarX.addEventListener("pointerdown", (e) => {
            if (e.button !== 0 || e.target === this.thumbX) return;
            const trackRect = this.scrollbarX!.getBoundingClientRect();
            const thumbW = this.thumbX!.offsetWidth;
            const clickX = e.clientX - trackRect.left;
            const maxThumb = trackRect.width - thumbW;
            const maxScroll = this.viewport.scrollWidth - this.viewport.clientWidth;

            const targetThumbLeft = clickX - thumbW / 2;
            const scrollPos = ScrollArea.getScrollPositionFromThumbOffset(targetThumbLeft, maxThumb, maxScroll);
            this.viewport.scrollTo({ left: scrollPos, behavior: "smooth" });
        });

        this.scrollbarX.addEventListener("wheel", (e) => {
            e.preventDefault();
            this.viewport.scrollLeft += e.deltaX || e.deltaY;
        }, { passive: false });

        this.thumbX.addEventListener("keydown", (e) => {
            const step = 40;
            if (e.key === "ArrowLeft") {
                e.preventDefault();
                this.viewport.scrollLeft -= step;
            } else if (e.key === "ArrowRight") {
                e.preventDefault();
                this.viewport.scrollLeft += step;
            }
        });
    }

    scrollTo(options: ScrollToOptions | number, y?: number) {
        if (typeof options === "number") {
            this.viewport.scrollTo(options, y || 0);
        } else {
            this.viewport.scrollTo(options);
        }
    }

    destroy() {
        if (this.observer) {
            this.observer.disconnect();
        }
        this.viewport.removeEventListener("scroll", this.onScrollHandler);
        window.removeEventListener("resize", this.onResizeHandler);
        if (this.scrollbarY && this.scrollbarY.parentElement) {
            this.scrollbarY.parentElement.removeChild(this.scrollbarY);
        }
        if (this.scrollbarX && this.scrollbarX.parentElement) {
            this.scrollbarX.parentElement.removeChild(this.scrollbarX);
        }
    }
}

/**
 * Resizable helper ported from ts/lib/components/resizable.ts
 */
export function createResizable(baseSize: number, onResize?: (dimension: number) => void) {
    let dimension = baseSize;
    let isResizing = false;

    return {
        start(initialDimension: number) {
            isResizing = true;
            dimension = initialDimension;
        },
        resize(increment: number): number {
            if (!isResizing) return 0;
            if (dimension + increment < 0) {
                const applied = -dimension;
                dimension = 0;
                if (onResize) onResize(dimension);
                return applied;
            }
            dimension += increment;
            if (onResize) onResize(dimension);
            return increment;
        },
        setSize(size: number) {
            dimension = size;
            if (onResize) onResize(dimension);
        },
        stop() {
            isResizing = false;
        },
        getDimension() {
            return dimension;
        }
    };
}

// Global exposure on window for direct access or testing
declare global {
    interface Window {
        AnkiwebTables?: {
            VirtualTable: typeof VirtualTable;
            ScrollArea: typeof ScrollArea;
            createResizable: typeof createResizable;
            initVirtualTables: (root?: HTMLElement | Document) => void;
            initScrollAreas: (root?: HTMLElement | Document) => void;
        };
    }
}

interface ComponentElement extends HTMLElement {
    _virtualTableInstance?: VirtualTable;
    _scrollAreaInstance?: ScrollArea;
}

function initVirtualTables(root: HTMLElement | Document = document) {
    const elements = root.querySelectorAll<ComponentElement>("[data-virtual-table]");
    elements.forEach((el) => {
        if (el._virtualTableInstance) return;
        const itemsCount = parseInt(el.getAttribute("data-items-count") || "0", 10);
        const itemHeight = parseInt(el.getAttribute("data-item-height") || "30", 10);
        const bottomOffset = parseInt(el.getAttribute("data-bottom-offset") || "0", 10);

        const vt = new VirtualTable(el, { itemsCount, itemHeight, bottomOffset });
        el._virtualTableInstance = vt;
    });
}

function initScrollAreas(root: HTMLElement | Document = document) {
    const elements = root.querySelectorAll<ComponentElement>("[data-scroll-area-wrapper]");
    elements.forEach((el) => {
        if (el._scrollAreaInstance) return;
        const scrollX = el.getAttribute("data-scroll-x") === "true";
        const scrollY = el.getAttribute("data-scroll-y") !== "false";
        const dir = el.getAttribute("dir") === "rtl" ? "rtl" : "ltr";

        const sa = new ScrollArea(el, { scrollX, scrollY, dir });
        el._scrollAreaInstance = sa;
    });
}

if (typeof window !== "undefined") {
    window.AnkiwebTables = {
        VirtualTable,
        ScrollArea,
        createResizable,
        initVirtualTables,
        initScrollAreas,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            initVirtualTables();
            initScrollAreas();
        });
    } else {
        initVirtualTables();
        initScrollAreas();
    }
}
