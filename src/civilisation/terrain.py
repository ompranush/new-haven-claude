"""Procedural map: a river, farmland along it, forest, hills with ore, and a town centre.

Terrain codes are small ints so the map can be a numpy array and rendered as a heatmap.
"""
from __future__ import annotations
import random
import numpy as np

WATER, GRASS, FARMLAND, FOREST, ROCK, TOWN, ROAD = 0, 1, 2, 3, 4, 5, 6
SAND, SNOW, ASH, LAVA, DAM, RUIN = 7, 8, 9, 10, 11, 12
TERRAIN_NAMES = {WATER: "water", GRASS: "grass", FARMLAND: "farmland", FOREST: "forest",
                 ROCK: "hills", TOWN: "town", ROAD: "road", SAND: "sand", SNOW: "snow", ASH: "ash",
                 LAVA: "lava", DAM: "dam", RUIN: "ruins"}
LIVABLE = (GRASS, TOWN)


def _smooth_noise(rng: random.Random, w: int, h: int, passes: int = 4) -> np.ndarray:
    nprng = np.random.default_rng(rng.randint(0, 2**31 - 1))
    z = nprng.random((h, w))
    for _ in range(passes):
        z = (z + np.roll(z, 1, 0) + np.roll(z, -1, 0) + np.roll(z, 1, 1) + np.roll(z, -1, 1)) / 5
    z = (z - z.min()) / (z.max() - z.min() + 1e-9)
    return z


def generate(rng: random.Random, width: int, height: int) -> np.ndarray:
    grid = np.full((height, width), GRASS, dtype=np.int8)
    elev = _smooth_noise(rng, width, height)

    # river: a wandering vertical band
    x = rng.randint(width // 3, 2 * width // 3)
    for y in range(height):
        x = int(np.clip(x + rng.choice([-1, 0, 0, 1]), 2, width - 3))
        grid[y, max(0, x - 1):x + 2] = WATER

    # forests and hills from elevation
    grid[(elev > 0.72) & (grid == GRASS)] = ROCK
    grid[(elev > 0.55) & (elev <= 0.72) & (grid == GRASS)] = FOREST

    # farmland: grass within 5 tiles of water
    water_y, water_x = np.where(grid == WATER)
    for y in range(height):
        for xx in range(width):
            if grid[y, xx] == GRASS:
                d = np.min(np.abs(water_x - xx) + np.abs(water_y - y))
                if d <= 5 and rng.random() < 0.8:
                    grid[y, xx] = FARMLAND

    # town: a plaza on the drier side of the river
    cx = rng.choice([width // 4, 3 * width // 4])
    cy = height // 2
    grid[cy - 3:cy + 4, cx - 4:cx + 5] = TOWN
    grid[cy, :] = np.where(grid[cy, :] == WATER, WATER, ROAD)   # main street, with a ford
    grid[:, cx] = np.where(grid[:, cx] == WATER, WATER, ROAD)
    return grid


def find_tiles(grid: np.ndarray, kind: int):
    ys, xs = np.where(grid == kind)
    return list(zip(xs.tolist(), ys.tolist()))


# ---------------------------------------------------------------- the realm: five villages on one river
# Upstream to downstream. The river rises in the Sky mountains and ends in the Water village's lake,
# so every village downstream lives on whatever the villages above it leave in the channel.
REALM_ORDER = ["sky", "air", "earth", "fire", "water"]
REGION_W, REGION_H = 30, 30


def realm_regions():
    """(x0, y0, x1, y1) for each village, in REALM_ORDER. Top row runs west→east, bottom row east→west."""
    W, H = REGION_W, REGION_H
    return [(0, 0, W, H), (W, 0, 2 * W, H), (2 * W, 0, 3 * W, H),       # sky, air, earth
            (int(1.5 * W), H, 3 * W, 2 * H), (0, H, int(1.5 * W), 2 * H)]  # fire, water


def generate_realm(rng: random.Random):
    """One map for all five villages. Returns (grid, regions, river_path, town_centres)."""
    W, H = 3 * REGION_W, 2 * REGION_H
    regions = realm_regions()
    grid = np.full((H, W), GRASS, dtype=np.int8)
    elev = _smooth_noise(rng, W, H, passes=5)
    # the river: west→east along the top row, south through Earth's east side, then west along the bottom row
    path = []
    y = REGION_H // 2 + rng.randint(-3, 3)
    for x in range(2, 3 * REGION_W - 6):
        y = int(np.clip(y + rng.choice([-1, 0, 0, 0, 1]), 6, REGION_H - 7))
        path.append((x, y))
    x = 3 * REGION_W - 7
    for yy in range(y, REGION_H + REGION_H // 2):
        x = int(np.clip(x + rng.choice([-1, 0, 0, 1]), 3 * REGION_W - 10, 3 * REGION_W - 4))
        path.append((x, yy))
    y = REGION_H + REGION_H // 2
    for xx in range(x, 9, -1):
        y = int(np.clip(y + rng.choice([-1, 0, 0, 0, 1]), REGION_H + 6, 2 * REGION_H - 7))
        path.append((xx, y))
    for (px, py) in path:
        grid[max(0, py - 1):py + 1, max(0, px - 1):px + 1] = WATER
    # the lake at the end of the river
    lx, ly = path[-1]
    yy, xx = np.ogrid[:H, :W]
    grid[((xx - lx + 2) ** 2) / 36 + ((yy - ly) ** 2) / 20 <= 1] = WATER
    # element flavour
    for (x0, y0, x1, y1), el in zip(regions, REALM_ORDER):
        sub = elev[y0:y1, x0:x1]
        g = grid[y0:y1, x0:x1]
        land = g != WATER
        if el == "sky":            # high peaks, snow, pine
            g[land & (sub > 0.74)] = SNOW
            g[land & (sub > 0.62) & (sub <= 0.74)] = ROCK
            g[land & (sub > 0.42) & (sub <= 0.62)] = FOREST
        elif el == "air":          # open wind-swept plains, few trees, some bluffs
            g[land & (sub > 0.74)] = ROCK
            g[land & (sub > 0.66) & (sub <= 0.74)] = FOREST
        elif el == "earth":        # deep forest, rich soil, hills with ore
            g[land & (sub > 0.7)] = ROCK
            g[land & (sub > 0.45) & (sub <= 0.7)] = FOREST
        elif el == "fire":         # volcanic: ash fields, lava vents, black rock
            g[land & (sub > 0.78)] = LAVA
            g[land & (sub > 0.6) & (sub <= 0.78)] = ROCK
            g[land & (sub > 0.46) & (sub <= 0.6)] = ASH
        elif el == "water":        # marsh, beaches, the lake
            g[land & (sub > 0.72)] = FOREST
            near = np.zeros_like(land)
            wy, wx = np.where(g == WATER)
            for (a, b) in zip(wy, wx):
                near[max(0, a - 2):a + 3, max(0, b - 2):b + 3] = True
            g[land & near & (sub < 0.5)] = SAND
    # farmland along the water everywhere it is not rock, snow or lava
    wy, wx = np.where(grid == WATER)
    dist = np.full((H, W), 99, dtype=np.int16)
    for (a, b) in zip(wy, wx):
        y0_, y1_, x0_, x1_ = max(0, a - 5), min(H, a + 6), max(0, b - 5), min(W, b + 6)
        yy2, xx2 = np.ogrid[y0_:y1_, x0_:x1_]
        dist[y0_:y1_, x0_:x1_] = np.minimum(dist[y0_:y1_, x0_:x1_], np.abs(yy2 - a) + np.abs(xx2 - b))
    fertile = (grid == GRASS) & (dist <= 5)
    rnd = np.random.default_rng(rng.randint(0, 2 ** 31 - 1)).random((H, W))
    grid[fertile & (rnd < 0.75)] = FARMLAND
    # a town square in each village, away from the river, and roads between them
    centres = []
    for (x0, y0, x1, y1) in regions:
        best, best_d = None, -1
        for _ in range(60):
            cx, cy = rng.randint(x0 + 7, x1 - 8), rng.randint(y0 + 6, y1 - 7)
            d = int(dist[cy, cx])
            if 4 <= d <= 9 and grid[cy, cx] not in (WATER, LAVA) and d > best_d:
                best, best_d = (cx, cy), d
        cx, cy = best or ((x0 + x1) // 2, (y0 + y1) // 2)
        grid[cy - 3:cy + 4, cx - 4:cx + 5] = TOWN
        centres.append((cx, cy))
    for a, b in zip(centres, centres[1:]):
        _road(grid, a, b)
    return grid, regions, path, centres


def _road(grid, a, b):
    (x, y), (tx, ty) = a, b
    while (x, y) != (tx, ty):
        if x != tx:
            x += 1 if tx > x else -1
        elif y != ty:
            y += 1 if ty > y else -1
        if grid[y, x] not in (WATER, TOWN, DAM):
            grid[y, x] = ROAD


def region_of(regions, x: int, y: int) -> int:
    for i, (x0, y0, x1, y1) in enumerate(regions):
        if x0 <= x < x1 and y0 <= y < y1:
            return i
    return -1


def tiles_in(grid: np.ndarray, region, kinds):
    x0, y0, x1, y1 = region
    sub = grid[y0:y1, x0:x1]
    mask = np.isin(sub, kinds)
    ys, xs = np.where(mask)
    return list(zip((xs + x0).tolist(), (ys + y0).tolist()))
