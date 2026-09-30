import { Shape, Point } from "./types";

export interface BoundingBox {
    x: number;
    y: number;
    width: number;
    height: number;
}

export function getShapePixelBounds(shape: Shape, imgW: number, imgH: number): BoundingBox {
    switch (shape.type) {
        case "rect":
            return {
                x: shape.left * imgW,
                y: shape.top * imgH,
                width: shape.width * imgW,
                height: shape.height * imgH,
            };
        case "ellipse":
            return {
                x: (shape.left - shape.rx) * imgW,
                y: (shape.top - shape.ry) * imgH,
                width: shape.rx * 2 * imgW,
                height: shape.ry * 2 * imgH,
            };
        case "polygon": {
            if (shape.points.length === 0) {
                return { x: shape.left * imgW, y: shape.top * imgH, width: 0, height: 0 };
            }
            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            for (const p of shape.points) {
                const px = p.x * imgW;
                const py = p.y * imgH;
                if (px < minX) minX = px;
                if (py < minY) minY = py;
                if (px > maxX) maxX = px;
                if (py > maxY) maxY = py;
            }
            return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
        }
        case "text":
            return {
                x: shape.left * imgW,
                y: shape.top * imgH,
                width: 100 * (shape.scale || 1),
                height: 30 * (shape.scale || 1),
            };
    }
}

export function getCombinedBounds(shapes: Shape[], imgW: number, imgH: number): BoundingBox | null {
    if (shapes.length === 0) return null;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const s of shapes) {
        const b = getShapePixelBounds(s, imgW, imgH);
        if (b.x < minX) minX = b.x;
        if (b.y < minY) minY = b.y;
        if (b.x + b.width > maxX) maxX = b.x + b.width;
        if (b.y + b.height > maxY) maxY = b.y + b.height;
    }
    return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}
