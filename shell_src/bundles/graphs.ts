// Hover tooltip support for graphs with event delegation that survives dynamic DOM updates

function ensureTooltip(): HTMLElement {
    let tooltip = document.getElementById("graphs-tooltip");
    if (!tooltip) {
        tooltip = document.createElement("div");
        tooltip.id = "graphs-tooltip";
        document.body.appendChild(tooltip);
    }
    return tooltip;
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureTooltip);
} else {
    ensureTooltip();
}

document.addEventListener("mouseover", (e) => {
    const target = (e.target as HTMLElement).closest("[data-tooltip]") as HTMLElement;
    if (target) {
        const text = target.getAttribute("data-tooltip");
        if (text) {
            const tooltip = ensureTooltip();
            tooltip.textContent = text;
            tooltip.classList.add("show");
        }
    }
});

document.addEventListener("mousemove", (e) => {
    const tooltip = document.getElementById("graphs-tooltip");
    if (tooltip && tooltip.classList.contains("show")) {
        const pad = 12;
        let left = e.clientX + pad;
        let top = e.clientY + pad;
        const rect = tooltip.getBoundingClientRect();
        if (left + rect.width > window.innerWidth) {
            left = e.clientX - rect.width - pad;
        }
        if (top + rect.height > window.innerHeight) {
            top = e.clientY - rect.height - pad;
        }
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
    }
});

document.addEventListener("mouseout", (e) => {
    const target = (e.target as HTMLElement).closest("[data-tooltip]");
    if (target) {
        const tooltip = document.getElementById("graphs-tooltip");
        if (tooltip) {
            tooltip.classList.remove("show");
        }
    }
});
