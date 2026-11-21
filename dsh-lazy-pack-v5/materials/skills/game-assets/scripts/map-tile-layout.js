(function exposeMapTileLayout(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.MeowaMapTileLayout = api;
}(typeof globalThis === "object" ? globalThis : this, () => {
  const DEFAULT_TILE_SIZE = 64;
  const HD_ISOMETRIC_LOGICAL_SIDE_LENGTH = 372;
  const HD_ISOMETRIC_LOGICAL_TILE_WIDTH = HD_ISOMETRIC_LOGICAL_SIDE_LENGTH * 2;
  const HD_HEX_SIDE_LENGTH = 300;
  const HD_HEX_BOTTOM_LAYER_HEIGHT = 96;
  const HD_HEX_DISPLAY_SCALE = 0.25;
  const DUAL_GRID_ATLAS_BY_KEY = Object.freeze([
    [0, 3], [3, 3], [0, 0], [3, 2],
    [0, 2], [1, 2], [2, 3], [3, 1],
    [1, 3], [0, 1], [3, 0], [2, 0],
    [1, 0], [2, 2], [1, 1], [2, 1],
  ]);

  const requireTileSize = (tileSize) => {
    const value = Number(tileSize);
    if (!Number.isFinite(value) || value <= 0) {
      throw new TypeError("tileSize must be a positive number");
    }
    return value;
  };

  const isometricMetrics = (tileSize = DEFAULT_TILE_SIZE) => {
    const size = requireTileSize(tileSize);
    return {
      tileWidth: size * 2,
      tileHeight: size,
      halfWidth: size,
      halfHeight: size / 2,
    };
  };

  const isometricCenter = (column, row, options = {}) => {
    const metrics = isometricMetrics(options.tileSize);
    const originX = Number(options.originX || 0);
    const originY = Number(options.originY || 0);
    return {
      x: originX + (column - row) * metrics.halfWidth,
      y: originY + (column + row) * metrics.halfHeight,
    };
  };

  const isometricOffsets = (tileSize = DEFAULT_TILE_SIZE) => {
    const metrics = isometricMetrics(tileSize);
    return {
      axisA: [metrics.halfWidth, metrics.halfHeight],
      axisB: [-metrics.halfWidth, metrics.halfHeight],
      alignedHorizontal: [metrics.tileWidth, 0],
      alignedVertical: [0, metrics.tileHeight],
      tetraploidFootprint: [metrics.tileWidth * 2, metrics.tileHeight * 2],
    };
  };

  const hexMetrics = (tileSize = DEFAULT_TILE_SIZE) => {
    const side = requireTileSize(tileSize);
    return {
      side,
      width: side * 2,
      horizontalStride: Math.max(1, side * 2 - 1),
      rowStride: side,
      oddRowOffset: side,
    };
  };

  const hexCenter = (column, row, options = {}) => {
    const metrics = hexMetrics(options.tileSize);
    const originX = Number(options.originX || 0);
    const originY = Number(options.originY || 0);
    return {
      x: originX + column * metrics.horizontalStride + (row % 2) * metrics.oddRowOffset,
      y: originY + row * metrics.rowStride,
    };
  };

  const hexOffsets = (tileSize = DEFAULT_TILE_SIZE) => {
    const metrics = hexMetrics(tileSize);
    return {
      horizontal: [metrics.horizontalStride, 0],
      downRight: [metrics.oddRowOffset, metrics.rowStride],
      downLeft: [metrics.oddRowOffset - metrics.horizontalStride, metrics.rowStride],
      alignedVertical: [0, metrics.rowStride * 2],
    };
  };

  const hdIsometricAssetScale = (
    imageWidth,
    footprintSpan = 1,
    displayTileSize = DEFAULT_TILE_SIZE,
  ) => {
    const width = requireTileSize(imageWidth);
    const footprint = requireTileSize(footprintSpan);
    const displayWidth = requireTileSize(displayTileSize) * 2;
    const sourceTileWidth = Math.min(width / footprint, HD_ISOMETRIC_LOGICAL_TILE_WIDTH);
    return displayWidth / sourceTileWidth;
  };

  const hdHexMetrics = (displayScale = HD_HEX_DISPLAY_SCALE) => {
    const scale = requireTileSize(displayScale);
    const side = HD_HEX_SIDE_LENGTH * scale;
    return {
      side,
      width: side * 2,
      bottomLayerHeight: HD_HEX_BOTTOM_LAYER_HEIGHT * scale,
      horizontalStride: ((HD_HEX_SIDE_LENGTH * 2) - 1) * scale,
      rowStride: ((HD_HEX_SIDE_LENGTH * 1.5) - HD_HEX_BOTTOM_LAYER_HEIGHT) * scale,
      oddRowOffset: side,
      displayScale: scale,
    };
  };

  const hdHexCenter = (column, row, options = {}) => {
    const metrics = hdHexMetrics(options.displayScale);
    const originX = Number(options.originX || 0);
    const originY = Number(options.originY || 0);
    return {
      x: originX + column * metrics.horizontalStride + (row % 2) * metrics.oddRowOffset,
      y: originY + row * metrics.rowStride,
    };
  };

  const hdHexOffsets = (displayScale = HD_HEX_DISPLAY_SCALE) => {
    const metrics = hdHexMetrics(displayScale);
    return {
      horizontal: [metrics.horizontalStride, 0],
      downRight: [metrics.oddRowOffset, metrics.rowStride],
      downLeft: [metrics.oddRowOffset - metrics.horizontalStride, metrics.rowStride],
      alignedVertical: [0, metrics.rowStride * 2],
    };
  };

  const screenBoundsOverlap = (a, b) => (
    a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top
  );

  const isometricTileInFrontOf = (front, back) => (
    front.column >= back.column
    && front.row >= back.row
    && (front.column !== back.column || front.row !== back.row)
  );

  const isometricDepthRelation = (a, b) => {
    if (!screenBoundsOverlap(a.screenBounds, b.screenBounds)) return "none";
    let aInFront = false;
    let bInFront = false;
    for (const tileA of a.tiles) {
      for (const tileB of b.tiles) {
        if (isometricTileInFrontOf(tileB, tileA)) bInFront = true;
        if (isometricTileInFrontOf(tileA, tileB)) aInFront = true;
        if (aInFront && bInFront) return "conflict";
      }
    }
    if (bInFront) return "aBeforeB";
    if (aInFront) return "bBeforeA";
    return "none";
  };

  const sortIsometricDepthItems = (items) => {
    if (!Array.isArray(items)) throw new TypeError("items must be an array");
    if (items.length < 2) return [...items];
    const outgoing = Array.from({ length: items.length }, () => new Set());
    const incoming = Array.from({ length: items.length }, () => 0);
    const addEdge = (from, to) => {
      if (from === to || outgoing[from].has(to)) return;
      outgoing[from].add(to);
      incoming[to] += 1;
    };
    for (let left = 0; left < items.length - 1; left += 1) {
      for (let right = left + 1; right < items.length; right += 1) {
        const relation = isometricDepthRelation(items[left], items[right]);
        if (relation === "aBeforeB") addEdge(left, right);
        else if (relation === "bBeforeA") addEdge(right, left);
      }
    }
    const remaining = new Set(items.map((_, index) => index));
    const result = [];
    while (remaining.size) {
      const candidates = [...remaining];
      const available = candidates.filter((index) => incoming[index] === 0);
      const pool = available.length ? available : candidates;
      pool.sort((a, b) => (items[a].sortIndex - items[b].sortIndex) || a - b);
      const selected = pool[0];
      remaining.delete(selected);
      result.push(items[selected]);
      outgoing[selected].forEach((target) => { incoming[target] -= 1; });
    }
    return result;
  };

  const centerImageAt = (imageWidth, imageHeight, center) => ({
    x: Math.round(center.x - imageWidth / 2),
    y: Math.round(center.y - imageHeight / 2),
  });

  const dualGridTileKeyAt = (isFilled, displayColumn, displayRow) => {
    if (typeof isFilled !== "function") {
      throw new TypeError("isFilled must be a function");
    }
    let key = 0;
    if (isFilled(displayColumn - 1, displayRow - 1)) key += 1;
    if (isFilled(displayColumn - 1, displayRow)) key += 2;
    if (isFilled(displayColumn, displayRow - 1)) key += 4;
    if (isFilled(displayColumn, displayRow)) key += 8;
    return key;
  };

  const centeredImageBounds = (items, padding = 32) => {
    if (!Array.isArray(items) || items.length === 0) {
      throw new TypeError("items must contain at least one centered image");
    }
    const safePadding = Math.max(0, Number(padding) || 0);
    const left = Math.min(...items.map((item) => item.center.x - item.width / 2));
    const top = Math.min(...items.map((item) => item.center.y - item.height / 2));
    const right = Math.max(...items.map((item) => item.center.x + item.width / 2));
    const bottom = Math.max(...items.map((item) => item.center.y + item.height / 2));
    return {
      width: Math.max(1, Math.ceil(right - left + safePadding * 2)),
      height: Math.max(1, Math.ceil(bottom - top + safePadding * 2)),
      offsetX: safePadding - Math.floor(left),
      offsetY: safePadding - Math.floor(top),
    };
  };

  return Object.freeze({
    DEFAULT_TILE_SIZE,
    HD_ISOMETRIC_LOGICAL_SIDE_LENGTH,
    HD_ISOMETRIC_LOGICAL_TILE_WIDTH,
    HD_HEX_SIDE_LENGTH,
    HD_HEX_BOTTOM_LAYER_HEIGHT,
    HD_HEX_DISPLAY_SCALE,
    DUAL_GRID_ATLAS_BY_KEY,
    isometricMetrics,
    isometricCenter,
    isometricOffsets,
    hexMetrics,
    hexCenter,
    hexOffsets,
    hdIsometricAssetScale,
    hdHexMetrics,
    hdHexCenter,
    hdHexOffsets,
    isometricDepthRelation,
    sortIsometricDepthItems,
    centerImageAt,
    centeredImageBounds,
    dualGridTileKeyAt,
  });
}));
