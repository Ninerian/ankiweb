/**
 * Image overlay handles for resizing and alt text editing.
 */

let overlayContainer: HTMLElement | null = null;
let currentImage: HTMLImageElement | null = null;

function ensureOverlayContainer(): HTMLElement {
    if (!overlayContainer) {
        overlayContainer = document.createElement("div");
        overlayContainer.className = "ankiweb-image-overlay-layer";
        overlayContainer.style.position = "absolute";
        overlayContainer.style.display = "none";
        overlayContainer.style.zIndex = "1000";
        overlayContainer.style.pointerEvents = "none";
        document.body.appendChild(overlayContainer);
    }
    return overlayContainer;
}

export function setupImageOverlay(root: HTMLElement) {
    const container = ensureOverlayContainer();

    // Box highlighting current image with 4 corner resize handles and alt-text / size badge
    container.innerHTML = `
        <div class="ankiweb-image-frame" style="position: absolute; border: 2px solid var(--color-primary); box-sizing: border-box; pointer-events: auto;">
            <div class="ankiweb-image-badge bg-neutral text-neutral-content px-1 py-0 rounded" style="position: absolute; bottom: -24px; left: 0; font-size: 11px; white-space: nowrap; opacity: 0.9;">
                <span class="ankiweb-image-dims"></span> | <span class="ankiweb-image-alt-btn text-info" style="cursor: pointer; text-decoration: underline;">Alt</span>
            </div>
            <div class="ankiweb-image-handle handle-se" data-dir="se" style="position: absolute; right: -5px; bottom: -5px; width: 10px; height: 10px; background: var(--color-primary); cursor: nwse-resize;"></div>
            <div class="ankiweb-image-handle handle-sw" data-dir="sw" style="position: absolute; left: -5px; bottom: -5px; width: 10px; height: 10px; background: var(--color-primary); cursor: nesw-resize;"></div>
            <div class="ankiweb-image-handle handle-ne" data-dir="ne" style="position: absolute; right: -5px; top: -5px; width: 10px; height: 10px; background: var(--color-primary); cursor: nesw-resize;"></div>
            <div class="ankiweb-image-handle handle-nw" data-dir="nw" style="position: absolute; left: -5px; top: -5px; width: 10px; height: 10px; background: var(--color-primary); cursor: nwse-resize;"></div>
        </div>
    `;

    const frame = container.querySelector(".ankiweb-image-frame") as HTMLElement;
    const dimsEl = container.querySelector(".ankiweb-image-dims") as HTMLElement;
    const altBtn = container.querySelector(".ankiweb-image-alt-btn") as HTMLElement;

    function updatePosition() {
        if (!currentImage || !currentImage.isConnected) {
            hideOverlay();
            return;
        }
        const rect = currentImage.getBoundingClientRect();
        const scrollX = window.scrollX;
        const scrollY = window.scrollY;

        container.style.display = "block";
        container.style.left = `${rect.left + scrollX}px`;
        container.style.top = `${rect.top + scrollY}px`;
        container.style.width = `${rect.width}px`;
        container.style.height = `${rect.height}px`;

        frame.style.width = `${rect.width}px`;
        frame.style.height = `${rect.height}px`;

        const curW = currentImage.width || Math.round(rect.width);
        const curH = currentImage.height || Math.round(rect.height);
        dimsEl.textContent = `${curW} × ${curH}`;
    }

    function hideOverlay() {
        container.style.display = "none";
        currentImage = null;
    }

    altBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!currentImage) return;
        const currentAlt = currentImage.getAttribute("alt") || "";
        const newAlt = window.prompt("Image alternate text (alt):", currentAlt);
        if (newAlt !== null) {
            currentImage.setAttribute("alt", newAlt);
            currentImage.dispatchEvent(new Event("input", { bubbles: true }));
        }
    });

    // Resize dragging
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let startWidth = 0;
    let startHeight = 0;
    let dragDir = "se";

    container.addEventListener("pointerdown", (e) => {
        const target = e.target as HTMLElement;
        if (!target.classList.contains("ankiweb-image-handle") || !currentImage) return;
        e.preventDefault();
        e.stopPropagation();

        isDragging = true;
        dragDir = target.dataset.dir || "se";
        startX = e.clientX;
        startY = e.clientY;
        startWidth = currentImage.getBoundingClientRect().width;
        startHeight = currentImage.getBoundingClientRect().height;
        target.setPointerCapture(e.pointerId);

        const onPointerMove = (ev: PointerEvent) => {
            if (!isDragging || !currentImage) return;
            const dx = ev.clientX - startX;
            const dy = ev.clientY - startY;

            let newW = startWidth;
            let newH = startHeight;

            if (dragDir === "se") {
                newW = Math.max(20, startWidth + dx);
                newH = Math.max(20, startHeight + dy);
            } else if (dragDir === "sw") {
                newW = Math.max(20, startWidth - dx);
                newH = Math.max(20, startHeight + dy);
            } else if (dragDir === "ne") {
                newW = Math.max(20, startWidth + dx);
                newH = Math.max(20, startHeight - dy);
            } else if (dragDir === "nw") {
                newW = Math.max(20, startWidth - dx);
                newH = Math.max(20, startHeight - dy);
            }

            // Maintain aspect ratio if shift is pressed
            if (ev.shiftKey && startHeight > 0) {
                const ratio = startWidth / startHeight;
                newH = Math.round(newW / ratio);
            }

            currentImage.setAttribute("width", String(Math.round(newW)));
            currentImage.setAttribute("height", String(Math.round(newH)));
            currentImage.style.width = `${Math.round(newW)}px`;
            currentImage.style.height = `${Math.round(newH)}px`;

            updatePosition();
        };

        const onPointerUp = (ev: PointerEvent) => {
            if (!isDragging) return;
            isDragging = false;
            try {
                target.releasePointerCapture(ev.pointerId);
            } catch {
                // ignore
            }
            window.removeEventListener("pointermove", onPointerMove);
            window.removeEventListener("pointerup", onPointerUp);
            if (currentImage) {
                currentImage.dispatchEvent(new Event("input", { bubbles: true }));
            }
        };

        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp);
    });

    // Listen for image clicks inside rich text inputs
    root.addEventListener("click", (e) => {
        const target = e.target;
        if (target instanceof HTMLImageElement && !target.dataset.anki) {
            currentImage = target;
            updatePosition();
        } else if (!(e.target as HTMLElement).closest(".ankiweb-image-overlay-layer")) {
            hideOverlay();
        }
    });

    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);

    return {
        updatePosition,
        hide: hideOverlay,
    };
}
