"""Procedural map: a river, farmland along it, forest, hills with ore, and a town centre.

Terrain codes are small ints so the map can be a numpy array and rendered as a heatmap.
"""
from __future__ import annotations
import random
import numpy as np

WATER, GRASS, FARMLAND, FOREST, ROCK, TOWN, ROAD = 0, 1, 2, 3, 4, 5, 6
TERRAIN_NAMES = {WATER: "water", GRASS: "grass", FARMLAND: "farmland", FOREST: "forest",
                 ROCK: "hills", TOWN: "town", ROAD: "road"}


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
