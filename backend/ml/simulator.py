"""Physics-based simulation of satellite active-fire detection streams, used to train the classifier.

Why simulation: there is no public dataset that labels Indian FIRMS detections by source type
(gas flare, steel plant, coal fire, forest fire, crop burning). The model is therefore trained on
synthetic detection streams that follow published remote-sensing physics, and is then checked
against independent evidence on real FIRMS data (ml/evaluate_real.py). Simulated sources are
calibrated to the real VIIRS detections analysed for India (median FRP ~3 MW, industrial
sources detected mostly at night).

Physics and sensor model
- Sub-pixel fire mixing (Dozier 1981): L = p*B(lambda, T_fire) + (1 - p)*B(lambda, T_background),
  inverted to brightness temperatures for VIIRS I4 (3.74 um) / I5 (11.45 um) and MODIS 3.96 / 11.0 um.
- Point-spread function: each fire's signal is shared with neighbouring pixels (Gaussian spatial
  response), so strong or edge-of-pixel sources appear as clusters of adjacent detections.
- Reported FRP uses the MIR radiance method (Wooster et al. 2003): FRP = A * sigma * (L_MIR - L_bg) / a,
  with a fitted over 650-1350 K, so very hot gas flares are under-estimated as in real products.
- VIIRS I4 saturates at ~367 K, MODIS 4 um at ~500 K.
- Detection: probability rises with the MIR brightness-temperature anomaly; the daytime threshold is
  higher because of reflected sunlight (the reason industrial sources are mostly detected at night).
- Overpasses: Suomi NPP, NOAA-20 and NOAA-21 VIIRS ~13:30 / 01:30 local solar time (staggered),
  Terra MODIS ~10:30 / 22:30 and Aqua MODIS ~13:30 / 01:30; passes can be missed or cloud-obscured.
- Diurnal cycle: vegetation fires are fewer and much fainter at night, when rising humidity damps most fronts to
  low flames and smouldering. Real VIIRS night detections over Indian forests have a median FRP near 1 MW (April
  2024), about a fifth of the daytime median and as faint as many coal-fire pixels.

Industrial heat is not always persistent. Besides routine flares, furnaces, kilns and coal fires, the
scenes include flaring upsets (emergency or start-up flaring at plants whose routine flame is too
small to detect) and accidental fires inside plants, both usually seen on a single day. Plant
footprints include green belts, and vegetation also burns inside large plant and mine premises.

Every scene contains the primary source plus realistic confusers (crop fires around a refinery,
forest fires near a coal mine, brick kilns among fields, unmapped facilities).
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from shapely.geometry import Point, Polygon

from app.pipeline.features import FEATURE_COLUMNS, build_feature_table
from app.pipeline.geo_context import CONTEXT_CATEGORIES, ContextFeature, GeoContext
from app.pipeline.landcover import LANDCOVER_FEATURES

C1 = 1.191042e8  # W m-2 sr-1 um^4
C2 = 1.4387752e4  # um K
SIGMA = 5.670374e-8

# psf_scan / psf_track: standard deviation, in pixels, of a Gaussian approximation of the spatial response.
VIIRS = {"name": "VIIRS", "mir_um": 3.74, "tir_um": 11.45, "mir_sat": 367.0, "scan": (0.32, 0.78), "track": (0.36, 0.68),
         "psf_scan": (0.25, 0.40), "psf_track": (0.20, 0.32)}
MODIS = {"name": "MODIS", "mir_um": 3.96, "tir_um": 11.0, "mir_sat": 500.0, "scan": (1.0, 4.0), "track": (1.0, 2.0),
         "psf_scan": (0.40, 0.55), "psf_track": (0.25, 0.35)}

PLATFORMS = [
    # name, sensor, day local solar hour, night local solar hour, probability of a usable pass
    ("Suomi NPP", VIIRS, 13.5, 1.5, 0.9),
    ("NOAA-20", VIIRS, 12.7, 0.7, 0.9),
    ("NOAA-21", VIIRS, 14.3, 2.3, 0.9),
    ("Terra", MODIS, 10.5, 22.5, 0.75),
    ("Aqua", MODIS, 13.5, 1.5, 0.75),
]

LANDCOVER_GROUPS = ["tree", "shrub_grass", "crop", "built", "bare", "water_wetland"]
LANDCOVER_ALPHA = {
    # Environmental clearances in India require green belts (typically a third of the plant area),
    # so plant footprints mix tree cover with built-up and bare land.
    "industrial_site": [2.2, 1.0, 0.8, 5.0, 2.0, 0.5],
    "greenbelt": [4.0, 3.0, 0.6, 1.2, 1.0, 0.3],
    "kiln_yard": [0.3, 0.8, 3.0, 2.0, 3.0, 0.3],
    "mining_site": [1.0, 1.2, 0.6, 1.0, 5.0, 0.6],
    "well_pad": [1.5, 1.5, 2.0, 0.8, 2.5, 0.4],
    "forest": [7.0, 1.5, 0.8, 0.2, 0.4, 0.3],
    "scrub_grass": [1.0, 6.0, 1.2, 0.2, 1.5, 0.2],
    "cropland": [0.5, 0.8, 8.0, 0.6, 0.3, 0.3],
    "plantation": [3.5, 1.0, 3.5, 0.4, 0.2, 0.3],
    "desert": [0.2, 3.0, 0.8, 0.3, 5.0, 0.1],
    "coastal": [0.5, 1.0, 1.5, 2.0, 1.0, 3.0],
    "periurban": [0.8, 1.0, 3.0, 3.5, 0.8, 0.4],
}
# Dirichlet concentration multiplier; lower values give more varied footprints.
LANDCOVER_CONCENTRATION = {"industrial_site": 1.0, "greenbelt": 1.5, "mining_site": 1.0}

FAMILY_WEIGHTS = {
    "flare_refinery_mapped": 1.0,
    "flare_unmapped": 0.8,
    "flare_upset_mapped": 0.6,
    "flare_upset_unmapped": 0.3,
    "oil_field_wells": 0.6,
    "heavy_plant_mapped": 1.0,
    "heavy_plant_unmapped": 0.6,
    "industrial_fire_mapped": 0.4,
    "brick_kilns_cropland": 0.7,
    "coal_fire_mapped": 0.9,
    "coal_fire_unmapped": 0.5,
    "forest_fire": 1.0,
    "forest_fire_near_industry": 0.7,
    "vegetation_fire_on_premises": 0.35,
    "grass_scrub_fire": 0.5,
    "crop_burning": 1.0,
    "crop_burning_near_industry": 0.7,
    "plantation_burning": 0.4,
}

# Families that are hard by construction; reported separately in the evaluation.
HARD_FAMILIES = [
    "flare_unmapped",
    "flare_upset_unmapped",
    "heavy_plant_unmapped",
    "industrial_fire_mapped",
    "brick_kilns_cropland",
    "coal_fire_unmapped",
    "forest_fire_near_industry",
    "vegetation_fire_on_premises",
    "crop_burning_near_industry",
    "plantation_burning",
]


def planck(wavelength_um: float, temperature_k: float) -> float:
    return C1 / (wavelength_um ** 5 * math.expm1(C2 / (wavelength_um * temperature_k)))


def brightness_temperature(wavelength_um: float, radiance: float) -> float:
    return C2 / (wavelength_um * math.log1p(C1 / (wavelength_um ** 5 * radiance)))


def _mir_coefficient(wavelength_um: float) -> float:
    temps = np.linspace(650.0, 1350.0, 60)
    return float(np.mean([planck(wavelength_um, t) / t ** 4 for t in temps]))


MIR_COEFFICIENT = {"VIIRS": _mir_coefficient(VIIRS["mir_um"]), "MODIS": _mir_coefficient(MODIS["mir_um"])}


class LocalFrame:
    """Flat-earth frame (km) around a scene centre; adequate over tens of kilometres."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = 111.320 * math.cos(math.radians(lat0))
        self.ky = 110.574

    def to_latlon(self, x_km: float, y_km: float) -> Tuple[float, float]:
        return self.lat0 + y_km / self.ky, self.lon0 + x_km / self.kx

    def rectangle(self, cx: float, cy: float, width_km: float, height_km: float, angle: float = 0.0) -> Polygon:
        corners = []
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            x, y = dx * width_km / 2, dy * height_km / 2
            xr = x * math.cos(angle) - y * math.sin(angle)
            yr = x * math.sin(angle) + y * math.cos(angle)
            lat, lon = self.to_latlon(cx + xr, cy + yr)
            corners.append((lon, lat))
        return Polygon(corners)

    def point(self, x: float, y: float) -> Point:
        lat, lon = self.to_latlon(x, y)
        return Point(lon, lat)


@dataclass
class Fire:
    x: float
    y: float
    temperature: float
    area_m2: float
    label: str
    family: str


@dataclass
class SiteFootprint:
    """Physical extent of a source, used for land cover regardless of whether OSM maps it."""
    x: float
    y: float
    radius_km: float
    landcover: str


@dataclass
class Scene:
    scene_id: str
    family: str
    lat0: float
    lon0: float
    start: datetime
    days: int
    frame: LocalFrame
    generators: List = field(default_factory=list)
    features: List[ContextFeature] = field(default_factory=list)
    footprints: List[SiteFootprint] = field(default_factory=list)
    background: str = "cropland"
    landcover_missing: bool = False


# ---------------------------------------------------------------- source generators

class FlareSite:
    label = "gas_flare"

    def __init__(self, rng, x, y, n_flares, family, spread_km=0.6):
        self.family = family
        self.flares = [
            (x + rng.normal(0, spread_km / 2), y + rng.normal(0, spread_km / 2),
             rng.uniform(1400.0, 2000.0), float(np.clip(math.exp(rng.normal(math.log(4.0), 1.0)), 0.3, 400.0)))
            for _ in range(n_flares)
        ]
        self.on_probability = rng.uniform(0.5, 1.0)
        self._daily_state: Dict[Tuple[int, int], bool] = {}

    def fires_at(self, rng, day, local_hour, is_day):
        fires = []
        for idx, (fx, fy, temp, area) in enumerate(self.flares):
            key = (idx, day)
            if key not in self._daily_state:
                self._daily_state[key] = rng.random() < self.on_probability
            if self._daily_state[key]:
                fires.append(Fire(fx, fy, temp * rng.uniform(0.97, 1.03), area * rng.lognormal(0.0, 0.5), self.label, self.family))
        return fires


class FlaringUpset:
    """Emergency, start-up or maintenance flaring at a refinery, gas-processing, petrochemical or
    fertiliser plant. The routine flame is often too small to detect; during an upset large gas
    volumes go to the flare for hours to a couple of days, and the site shows up as a compact
    cluster of hot pixels with little or no detection history."""
    label = "gas_flare"

    def __init__(self, rng, x, y, family, days, spread_km):
        self.family = family
        n_stacks = int(rng.integers(1, 4))
        self.stacks = [
            (x + rng.normal(0, spread_km / 2), y + rng.normal(0, spread_km / 2), rng.uniform(1400.0, 2000.0),
             float(np.clip(math.exp(rng.normal(math.log(0.25), 0.9)), 0.02, 3.0)))
            for _ in range(n_stacks)
        ]
        self.routine_probability = rng.uniform(0.0, 0.9)
        self.events = []
        for _ in range(int(rng.integers(1, 3))):
            involved = rng.random(n_stacks) < 0.7
            if not involved.any():
                involved[int(rng.integers(0, n_stacks))] = True
            self.events.append({
                "start": rng.uniform(0.0, max(days - 0.25, 0.25)),
                "duration": float(np.clip(math.exp(rng.normal(math.log(0.4), 0.8)), 0.05, 2.5)),  # days
                "area": float(np.clip(math.exp(rng.normal(math.log(40.0), 1.1)), 3.0, 3000.0)),  # m2 of flame per stack
                "stacks": involved,
            })
        self._routine: Dict[Tuple[int, int], bool] = {}

    def fires_at(self, rng, day, local_hour, is_day):
        t = day + local_hour / 24.0
        fires = []
        for idx, (fx, fy, temp, area) in enumerate(self.stacks):
            key = (idx, day)
            if key not in self._routine:
                self._routine[key] = rng.random() < self.routine_probability
            flame = area * rng.lognormal(0.0, 0.5) if self._routine[key] else 0.0
            for event in self.events:
                if event["stacks"][idx] and event["start"] <= t <= event["start"] + event["duration"]:
                    flame += event["area"] * rng.lognormal(0.0, 0.4)
            if flame > 0.0:
                fires.append(Fire(fx, fy, temp * rng.uniform(0.97, 1.03), flame, self.label, self.family))
        return fires


class HeavyPlant:
    label = "heavy_industry"

    def __init__(self, rng, x, y, family, extent_km, n_spots, temp_range=(700.0, 1400.0), area_median=30.0, operate=(0.6, 1.0), wander=(0.0, 0.8)):
        self.family = family
        self.center, self.extent_km = (x, y), extent_km
        self.temp_range, self.area_median = temp_range, area_median
        self.spots = [
            (x + rng.uniform(-extent_km / 2, extent_km / 2), y + rng.uniform(-extent_km / 2, extent_km / 2),
             rng.uniform(*temp_range), float(np.clip(math.exp(rng.normal(math.log(area_median), 0.9)), 1.0, 2000.0)))
            for _ in range(n_spots)
        ]
        self.operate_probability = rng.uniform(*operate)
        # Slag dumping, coke pushing and ladle yards move around the works: hot spots that are not fixed.
        self.wander_rate = rng.uniform(*wander)

    def fires_at(self, rng, day, local_hour, is_day):
        fires = [
            Fire(sx, sy, temp, area * rng.lognormal(0.0, 0.4), self.label, self.family)
            for sx, sy, temp, area in self.spots
            if rng.random() < self.operate_probability
        ]
        for _ in range(rng.poisson(self.wander_rate)):
            fires.append(Fire(
                self.center[0] + rng.uniform(-self.extent_km / 2, self.extent_km / 2),
                self.center[1] + rng.uniform(-self.extent_km / 2, self.extent_km / 2),
                rng.uniform(*self.temp_range),
                float(np.clip(math.exp(rng.normal(math.log(self.area_median), 0.9)), 1.0, 2000.0)),
                self.label, self.family))
        return fires


class PlantFire:
    """Accidental fire inside industrial premises - storage tank, warehouse, conveyor or coal-yard
    fire: a single event lasting hours to about two days, cooler and larger than a flare."""

    def __init__(self, rng, x, y, label, family, days, extent_km):
        self.label, self.family = label, family
        self.x = x + rng.uniform(-extent_km / 2, extent_km / 2)
        self.y = y + rng.uniform(-extent_km / 2, extent_km / 2)
        self.start = rng.uniform(0.0, max(days - 0.25, 0.25))
        self.duration = float(np.clip(math.exp(rng.normal(math.log(0.35), 0.9)), 0.04, 2.5))  # days
        self.area = float(np.clip(math.exp(rng.normal(math.log(250.0), 1.2)), 10.0, 30000.0))  # m2 burning
        self.temperature = rng.uniform(800.0, 1250.0)
        self.parts = int(rng.integers(1, 5))
        self.radius_km = rng.uniform(0.05, 0.4)

    def fires_at(self, rng, day, local_hour, is_day):
        elapsed = day + local_hour / 24.0 - self.start
        if elapsed < 0 or elapsed > self.duration:
            return []
        return [
            Fire(self.x + rng.normal(0, self.radius_km), self.y + rng.normal(0, self.radius_km), self.temperature * rng.uniform(0.9, 1.1),
                 self.area / self.parts * rng.lognormal(0.0, 0.5), self.label, self.family)
            for _ in range(self.parts)
        ]


def _inside_any(x: float, y: float, exclusions) -> bool:
    return any(math.hypot(x - ex, y - ey) <= radius for ex, ey, radius in exclusions)


class CoalFireField:
    label = "mining_coal_fire"

    def __init__(self, rng, x, y, family, extent_km):
        self.family = family
        n_cells = int(rng.integers(6, 60))
        scale = rng.uniform(0.15, 0.7)
        self.cells = [
            (x + rng.uniform(-extent_km / 2, extent_km / 2), y + rng.uniform(-extent_km / 2, extent_km / 2),
             min(0.7, rng.beta(0.6, 3.0) * scale * 3), rng.uniform(600.0, 1000.0),
             float(np.clip(math.exp(rng.normal(math.log(35.0), 0.9)), 1.0, 3000.0)))
            for _ in range(n_cells)
        ]

    def fires_at(self, rng, day, local_hour, is_day):
        return [
            Fire(cx, cy, temp, area * rng.lognormal(0.0, 0.5), self.label, self.family)
            for cx, cy, prob, temp, area in self.cells
            if rng.random() < prob
        ]


class Wildfire:
    label = "wildfire"

    def __init__(self, rng, x, y, family, days, speed_median=1.0, area_median=70.0, exclusions=(), start_sd_km=1.5, duration_range=None):
        self.family = family
        self.exclusions = list(exclusions)  # industrial premises do not burn as vegetation
        self.events = []
        for _ in range(int(rng.integers(1, 3))):
            if duration_range:
                duration = rng.uniform(*duration_range)
            else:
                duration = 1.0 if rng.random() < 0.35 else rng.uniform(1.5, 7.0)
            start = rng.uniform(0, max(days - 0.5, 0.5))
            self.events.append({
                "x": x + rng.normal(0, start_sd_km), "y": y + rng.normal(0, start_sd_km),
                "start": start, "duration": duration,
                "speed": float(np.clip(math.exp(rng.normal(math.log(speed_median), 0.9)), 0.05, 12.0)),
                "angle": rng.uniform(0, 2 * math.pi), "lambda": rng.uniform(1.0, 10.0),
                "front0": rng.uniform(0.2, 1.0), "area_median": area_median, "vigorous_nights": {},
            })

    def fires_at(self, rng, day, local_hour, is_day):
        fires = []
        t = day + local_hour / 24.0
        for ev in self.events:
            elapsed = t - ev["start"]
            if elapsed < 0 or elapsed > ev["duration"]:
                continue
            # Diurnal fire cycle (Giglio 2007): activity peaks in the afternoon. At night about half as many fire elements burn,
            # most of them as low flames and smouldering - a smaller, cooler burning area - so night detections are faint but
            # still common, because the night detection threshold is much lower. On some nights a wind-driven or crown fire
            # keeps burning strongly.
            night = not 9.0 <= local_hour <= 18.0
            growth = min(1.0 + elapsed, 3.0)
            k = rng.poisson(ev["lambda"] * (0.5 if night else 1.0) * growth)
            cx = ev["x"] + ev["speed"] * elapsed * math.cos(ev["angle"])
            cy = ev["y"] + ev["speed"] * elapsed * math.sin(ev["angle"])
            length = ev["front0"] + 0.5 * ev["speed"] * elapsed
            if night and day not in ev["vigorous_nights"]:
                ev["vigorous_nights"][day] = rng.random() < 0.06
            for _ in range(k):
                along = rng.uniform(-length / 2, length / 2)
                px = cx - along * math.sin(ev["angle"]) + rng.normal(0, 0.15)
                py = cy + along * math.cos(ev["angle"]) + rng.normal(0, 0.15)
                if self.exclusions and _inside_any(px, py, self.exclusions):
                    continue
                area = float(np.clip(math.exp(rng.normal(math.log(ev["area_median"]), 1.1)), 5.0, 20000.0))
                temperature = rng.uniform(750.0, 1150.0)
                if night and ev["vigorous_nights"][day]:
                    area *= rng.uniform(0.5, 1.0)
                elif night:
                    area *= rng.uniform(0.12, 0.45)
                    temperature = rng.uniform(620.0, 900.0)
                fires.append(Fire(px, py, temperature, area, self.label, self.family))
        return fires


class CropFields:
    label = "agricultural"

    def __init__(self, rng, x, y, family, days, radius_km, n_fields, day_share=(0.85, 0.97), area_median=60.0, exclusions=()):
        self.family = family
        peak = rng.uniform(0, days)
        spread = rng.uniform(2.0, max(days / 2, 3.0))
        day_probability = rng.uniform(*day_share)
        self.fields = []
        previous = None
        for _ in range(n_fields):
            for _attempt in range(20):
                if previous is not None and rng.random() < 0.3:
                    fx, fy = previous[0] + rng.normal(0, 0.45), previous[1] + rng.normal(0, 0.45)
                else:
                    r = radius_km * math.sqrt(rng.random())
                    a = rng.uniform(0, 2 * math.pi)
                    fx, fy = x + r * math.cos(a), y + r * math.sin(a)
                if not _inside_any(fx, fy, exclusions):  # no fields inside industrial premises
                    break
            else:
                continue
            burn_day = int(np.clip(round(rng.normal(peak, spread)), 0, days - 1))
            if rng.random() < day_probability:
                start_hour = rng.normal(13.5, 1.5)
            else:
                start_hour = rng.uniform(19.0, 26.0)
            duration = rng.uniform(1.0, 5.0)
            area = float(np.clip(math.exp(rng.normal(math.log(area_median), 0.9)), 2.0, 5000.0))
            self.fields.append((fx, fy, burn_day, start_hour, duration, area, rng.uniform(700.0, 1000.0)))
            previous = (fx, fy)

    def fires_at(self, rng, day, local_hour, is_day):
        fires = []
        for fx, fy, burn_day, start, duration, area, temp in self.fields:
            hour = local_hour if day == burn_day else (local_hour + 24.0 if day == burn_day + 1 else None)
            if hour is not None and start <= hour <= start + duration:
                fires.append(Fire(fx, fy, temp, area * rng.lognormal(0.0, 0.3), self.label, self.family))
        return fires


# ---------------------------------------------------------------- scene assembly

def _dirichlet_landcover(rng: np.random.Generator, kind: str) -> Dict[str, float]:
    fractions = rng.dirichlet(np.array(LANDCOVER_ALPHA[kind]) * LANDCOVER_CONCENTRATION.get(kind, 2.0))
    return {f"lc_{g}": float(v) for g, v in zip(LANDCOVER_GROUPS, fractions)}


def _add_distractor_features(rng, scene: Scene, probability: float, min_km: float, max_km: float):
    if rng.random() >= probability:
        return
    for _ in range(int(rng.integers(1, 4))):
        r = rng.uniform(min_km, max_km)
        a = rng.uniform(0, 2 * math.pi)
        category = CONTEXT_CATEGORIES[int(rng.integers(0, len(CONTEXT_CATEGORIES)))]
        scene.features.append(ContextFeature(
            feature_id=f"sim/{scene.scene_id}/d{len(scene.features)}", name=None, category=category,
            subtype=category, geometry=scene.frame.rectangle(r * math.cos(a), r * math.sin(a), rng.uniform(0.3, 2.0), rng.uniform(0.3, 2.0)),
            source="simulated"))


def _polygon_feature(scene: Scene, category: str, subtype: str, cx: float, cy: float, w: float, h: float, angle: float = 0.0):
    scene.features.append(ContextFeature(
        feature_id=f"sim/{scene.scene_id}/f{len(scene.features)}", name=None, category=category, subtype=subtype,
        geometry=scene.frame.rectangle(cx, cy, w, h, angle), source="simulated"))


def _point_feature(scene: Scene, category: str, subtype: str, x: float, y: float):
    scene.features.append(ContextFeature(
        feature_id=f"sim/{scene.scene_id}/f{len(scene.features)}", name=None, category=category, subtype=subtype,
        geometry=scene.frame.point(x, y), source="simulated"))


def build_scene(family: str, seed: int) -> Scene:
    rng = np.random.default_rng(seed)
    lat0, lon0 = rng.uniform(9.0, 31.0), rng.uniform(70.0, 94.0)
    days = int(rng.integers(7, 31))
    start = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=int(rng.integers(0, 330)))
    scene = Scene(scene_id=f"{family}-{seed}", family=family, lat0=lat0, lon0=lon0, start=start, days=days,
                  frame=LocalFrame(lat0, lon0), landcover_missing=rng.random() < 0.1)

    if family in ("flare_refinery_mapped", "flare_unmapped"):
        w, h = rng.uniform(1.0, 4.0), rng.uniform(1.0, 3.0)
        scene.generators.append(FlareSite(rng, 0.0, 0.0, int(rng.integers(1, 5)), family, spread_km=min(w, h) * 0.6))
        scene.footprints.append(SiteFootprint(0.0, 0.0, max(w, h) / 2, "industrial_site"))
        scene.background = str(rng.choice(["cropland", "desert", "coastal", "periurban", "scrub_grass"]))
        if family == "flare_refinery_mapped":
            if rng.random() < 0.7:
                _polygon_feature(scene, "oil_gas", "refinery", 0.0, 0.0, w, h)
            else:
                for fx, fy, _, _ in scene.generators[0].flares:
                    _point_feature(scene, "oil_gas", "gas_flare", fx + rng.normal(0, 0.1), fy + rng.normal(0, 0.1))
            _add_distractor_features(rng, scene, 0.4, 2.0, 30.0)
        else:
            _add_distractor_features(rng, scene, 0.5, 8.0, 50.0)
        if rng.random() < 0.3:
            scene.generators.append(CropFields(rng, rng.uniform(-6, 6), rng.uniform(-6, 6), "crop_burning", days, rng.uniform(3, 8), int(rng.integers(5, 40)),
                                               exclusions=[(0.0, 0.0, max(w, h) * 0.75 + 0.3)]))

    elif family in ("flare_upset_mapped", "flare_upset_unmapped"):
        w, h = rng.uniform(1.5, 5.0), rng.uniform(1.0, 4.0)
        scene.generators.append(FlaringUpset(rng, 0.0, 0.0, family, days, spread_km=min(w, h) * 0.4))
        scene.footprints.append(SiteFootprint(0.0, 0.0, max(w, h) / 2, "industrial_site"))
        scene.background = str(rng.choice(["coastal", "periurban", "cropland", "forest", "plantation"]))
        if family == "flare_upset_mapped":
            if rng.random() < 0.65:
                _polygon_feature(scene, "oil_gas", "refinery", 0.0, 0.0, w, h)
            else:
                # OSM outlines often cover only part of a complex: the flare can sit just outside the mapped polygon.
                half, gap, a = rng.uniform(0.4, 1.5), rng.uniform(0.0, 1.0), rng.uniform(0, 2 * math.pi)
                category = str(rng.choice(["oil_gas", "heavy_industry"]))
                _polygon_feature(scene, category, category, (half + gap) * math.cos(a), (half + gap) * math.sin(a), 2 * half, 2 * half)
            _add_distractor_features(rng, scene, 0.5, 1.5, 20.0)
        else:
            _add_distractor_features(rng, scene, 0.5, 5.0, 50.0)
        if rng.random() < 0.3:
            scene.generators.append(CropFields(rng, rng.uniform(-6, 6), rng.uniform(-6, 6), "crop_burning", days, rng.uniform(3, 8), int(rng.integers(5, 40)),
                                               exclusions=[(0.0, 0.0, max(w, h) * 0.75 + 0.3)]))

    elif family == "oil_field_wells":
        n_sites = int(rng.integers(2, 6))
        scene.background = str(rng.choice(["plantation", "cropland", "forest", "desert"]))
        for _ in range(n_sites):
            x, y = rng.uniform(-4, 4), rng.uniform(-4, 4)
            scene.generators.append(FlareSite(rng, x, y, 1, family, spread_km=0.1))
            scene.footprints.append(SiteFootprint(x, y, 0.25, "well_pad"))
            if rng.random() < 0.6:
                _point_feature(scene, "oil_gas", "oil_gas_well", x + rng.normal(0, 0.1), y + rng.normal(0, 0.1))

    elif family in ("heavy_plant_mapped", "heavy_plant_unmapped"):
        extent = rng.uniform(0.8, 3.0)
        subtype = str(rng.choice(["steel", "thermal_power", "cement", "smelter"]))
        scene.generators.append(HeavyPlant(rng, 0.0, 0.0, family, extent, int(rng.integers(1, 7))))
        scene.footprints.append(SiteFootprint(0.0, 0.0, extent / 2 + 0.3, "industrial_site"))
        scene.background = str(rng.choice(["periurban", "cropland", "scrub_grass", "forest"]))
        if family == "heavy_plant_mapped":
            _polygon_feature(scene, "heavy_industry", subtype, 0.0, 0.0, extent + 0.4, extent + 0.4, rng.uniform(0, 1))
            if rng.random() < 0.2:
                _polygon_feature(scene, "mining", "coal_mine", rng.uniform(3, 10), rng.uniform(-5, 5), rng.uniform(2, 6), rng.uniform(2, 6))
            _add_distractor_features(rng, scene, 0.4, 3.0, 40.0)
        else:
            _add_distractor_features(rng, scene, 0.5, 8.0, 50.0)
        if rng.random() < 0.15:
            scene.generators.append(Wildfire(rng, rng.uniform(-8, 8), rng.uniform(-8, 8), "forest_fire", days, exclusions=[(0.0, 0.0, extent * 0.75 + 0.4)]))

    elif family == "industrial_fire_mapped":
        category = str(rng.choice(["oil_gas", "heavy_industry"], p=[0.45, 0.55]))
        label = "gas_flare" if category == "oil_gas" else "heavy_industry"
        extent = rng.uniform(1.0, 5.0)
        scene.footprints.append(SiteFootprint(0.0, 0.0, extent / 2 + 0.2, "industrial_site"))
        _polygon_feature(scene, category, category, 0.0, 0.0, extent + 0.4, extent + 0.4, rng.uniform(0, 1))
        scene.generators.append(PlantFire(rng, 0.0, 0.0, label, family, days, extent))
        if rng.random() < 0.5:
            # Some plants also have routinely detected heat (flares, furnaces); many (power, chemicals, storage) have none.
            if category == "oil_gas":
                scene.generators.append(FlareSite(rng, rng.normal(0, extent / 4), rng.normal(0, extent / 4), int(rng.integers(1, 4)),
                                                  "flare_refinery_mapped", spread_km=extent * 0.3))
            else:
                scene.generators.append(HeavyPlant(rng, 0.0, 0.0, "heavy_plant_mapped", extent * 0.6, int(rng.integers(1, 5))))
        scene.background = str(rng.choice(["periurban", "cropland", "coastal", "scrub_grass", "forest"]))
        _add_distractor_features(rng, scene, 0.4, 2.0, 30.0)

    elif family == "brick_kilns_cropland":
        scene.background = "cropland"
        for _ in range(int(rng.integers(1, 9))):
            x, y = rng.uniform(-4, 4), rng.uniform(-4, 4)
            scene.generators.append(HeavyPlant(rng, x, y, family, 0.08, 1, temp_range=(850.0, 1150.0), area_median=25.0, operate=(0.7, 0.95), wander=(0.0, 0.0)))
            scene.footprints.append(SiteFootprint(x, y, 0.2, "kiln_yard"))
            if rng.random() < 0.15:
                _point_feature(scene, "heavy_industry", "kiln", x, y)
        if rng.random() < 0.5:
            scene.generators.append(CropFields(rng, 0.0, 0.0, "crop_burning", days, rng.uniform(4, 10), int(rng.integers(10, 80)),
                                               exclusions=[(fp.x, fp.y, 0.3) for fp in scene.footprints]))

    elif family in ("coal_fire_mapped", "coal_fire_unmapped"):
        extent = rng.uniform(2.0, 6.0)
        scene.generators.append(CoalFireField(rng, 0.0, 0.0, family, extent))
        # Coal fires burn in mined, coal-bearing ground: the footprint reaches past the field's half-width by a pixel-location
        # margin, so only cells in the far corners of a large field take the land cover of the forest or fields around it.
        scene.footprints.append(SiteFootprint(0.0, 0.0, extent * 0.55 + 0.3, "mining_site"))
        scene.background = str(rng.choice(["forest", "scrub_grass", "cropland"]))
        if family == "coal_fire_mapped":
            _polygon_feature(scene, "mining", "coal_mine", 0.0, 0.0, extent + 0.5, extent + 0.5, rng.uniform(0, 1))
        if rng.random() < 0.4:
            px, py = rng.uniform(3, 15) * float(rng.choice([-1, 1])), rng.uniform(-6, 6)
            _polygon_feature(scene, "heavy_industry", "thermal_power", px, py, rng.uniform(1, 3), rng.uniform(1, 3))
        if rng.random() < 0.3:
            scene.generators.append(Wildfire(rng, rng.uniform(-10, 10), rng.uniform(-10, 10), "forest_fire", days))
        _add_distractor_features(rng, scene, 0.3, 5.0, 40.0)

    elif family in ("forest_fire", "forest_fire_near_industry", "grass_scrub_fire"):
        exclusions = []
        if family == "forest_fire_near_industry":
            r, a = rng.uniform(0.3, 4.0), rng.uniform(0, 2 * math.pi)
            category = str(rng.choice(["oil_gas", "heavy_industry", "mining"], p=[0.2, 0.45, 0.35]))
            if category == "mining" and rng.random() < 0.3:
                # Large mining leases contain forest, and forest fires do burn inside them.
                _polygon_feature(scene, "mining", "coal_mine", 0.0, 0.0, rng.uniform(3, 8), rng.uniform(3, 8))
            else:
                w = rng.uniform(0.5, 3.0)
                px, py = r * math.cos(a), r * math.sin(a)
                _polygon_feature(scene, category, category, px, py, w, w)
                scene.footprints.append(SiteFootprint(px, py, w / 2, "industrial_site" if category != "mining" else "mining_site"))
                exclusions.append((px, py, w * 0.75 + 0.2))
        else:
            _add_distractor_features(rng, scene, 0.3, 10.0, 50.0)
        if family == "grass_scrub_fire":
            scene.background = "scrub_grass"
            scene.generators.append(Wildfire(rng, 0.0, 0.0, family, days, speed_median=2.0, area_median=80.0, exclusions=exclusions))
        else:
            scene.background = "forest" if rng.random() < 0.8 else "scrub_grass"
            scene.generators.append(Wildfire(rng, 0.0, 0.0, family, days, exclusions=exclusions))

    elif family == "vegetation_fire_on_premises":
        # Large plants and mine leases enclose green belts and scrub that burn in the dry season.
        category = str(rng.choice(["heavy_industry", "oil_gas", "mining"], p=[0.55, 0.15, 0.3]))
        extent, core = rng.uniform(3.0, 8.0), rng.uniform(0.5, 1.5)
        _polygon_feature(scene, category, category, 0.0, 0.0, extent, extent)
        scene.footprints.append(SiteFootprint(0.0, 0.0, core, "mining_site" if category == "mining" else "industrial_site"))
        scene.footprints.append(SiteFootprint(0.0, 0.0, extent / 2, "greenbelt"))
        scene.background = str(rng.choice(["scrub_grass", "forest", "cropland"]))
        if rng.random() < 0.5:
            if category == "mining":
                scene.generators.append(CoalFireField(rng, 0.0, 0.0, "coal_fire_mapped", core * 1.5))
            elif category == "oil_gas":
                scene.generators.append(FlareSite(rng, 0.0, 0.0, int(rng.integers(1, 4)), "flare_refinery_mapped", spread_km=core * 0.5))
            else:
                scene.generators.append(HeavyPlant(rng, 0.0, 0.0, "heavy_plant_mapped", core * 1.2, int(rng.integers(1, 5))))
        r, a = rng.uniform(core + 0.4, max(extent / 2 - 0.2, core + 0.6)), rng.uniform(0, 2 * math.pi)
        # Fires on premises stay small and are put out by the plant's own fire service within hours to a day.
        scene.generators.append(Wildfire(rng, r * math.cos(a), r * math.sin(a), family, days, speed_median=0.4, area_median=40.0,
                                         exclusions=[(0.0, 0.0, core + 0.2)], start_sd_km=0.3, duration_range=(0.1, 1.0)))

    elif family in ("crop_burning", "crop_burning_near_industry", "plantation_burning"):
        scene.background = "plantation" if family == "plantation_burning" else "cropland"
        n_fields = int(rng.integers(5, 180) * days / 14) + 3
        exclusions = []
        if family == "crop_burning_near_industry":
            r, a = rng.uniform(0.3, 3.0), rng.uniform(0, 2 * math.pi)
            category = str(rng.choice(["oil_gas", "heavy_industry"], p=[0.4, 0.6]))
            w = rng.uniform(0.5, 3.0)
            px, py = r * math.cos(a), r * math.sin(a)
            _polygon_feature(scene, category, "refinery" if category == "oil_gas" else "sugar_or_kiln", px, py, w, w)
            scene.footprints.append(SiteFootprint(px, py, w / 2, "industrial_site"))
            exclusions.append((px, py, w * 0.75 + 0.2))
        else:
            _add_distractor_features(rng, scene, 0.3, 5.0, 50.0)
        scene.generators.append(CropFields(rng, 0.0, 0.0, family, days, rng.uniform(3, 12), n_fields,
                                           area_median=40.0 if family == "plantation_burning" else 60.0, exclusions=exclusions))
    else:
        raise ValueError(f"unknown family {family}")
    return scene


def _landcover_lookup(scene: Scene, seed: int) -> Callable[[float, float], Dict[str, float]]:
    cache: Dict[Tuple[int, int], Dict[str, float]] = {}
    missing = {name: float("nan") for name in LANDCOVER_FEATURES}
    missing["lc_available"] = 0.0

    def lookup(lat: float, lon: float) -> Dict[str, float]:
        if scene.landcover_missing:
            return missing
        key = (math.floor(lat / 0.003), math.floor(lon / 0.003))
        if key not in cache:
            cell_rng = np.random.default_rng(abs(hash((seed, key))) % (2 ** 32))
            if cell_rng.random() < 0.04:
                cache[key] = missing
            else:
                x = (lon - scene.lon0) * scene.frame.kx
                y = (lat - scene.lat0) * scene.frame.ky
                kind = scene.background
                for fp in scene.footprints:
                    if math.hypot(x - fp.x, y - fp.y) <= fp.radius_km:
                        kind = fp.landcover
                        break
                values = _dirichlet_landcover(cell_rng, kind)
                values["lc_available"] = 1.0
                cache[key] = values
        return cache[key]

    return lookup


def _psf_weights(offset: float, sigma: float) -> Tuple[float, float, float]:
    """Shares of a point source at `offset` (0-1 across its pixel) received by the previous, same and
    next pixel, for a Gaussian spatial response with standard deviation `sigma` pixels."""
    scale = sigma * math.sqrt(2.0)

    def cdf(x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / scale))

    return cdf(-offset) - cdf(-1.0 - offset), cdf(1.0 - offset) - cdf(-offset), cdf(2.0 - offset) - cdf(1.0 - offset)


def observe_scene(scene: Scene, seed: int) -> List[Dict]:
    rng = np.random.default_rng(seed + 1_000_003)
    humid = rng.random() < 0.45
    cloud_by_day = rng.beta(2.0, 2.0, scene.days) * (0.85 if humid else 0.3)
    t_day, t_night = rng.uniform(296.0, 318.0), rng.uniform(282.0, 300.0)
    use_modis = rng.random() < 0.6
    detections: List[Dict] = []

    for day in range(scene.days):
        for name, sensor, day_hour, night_hour, pass_probability in PLATFORMS:
            if sensor is MODIS and not use_modis:
                continue
            for is_day, local_hour in ((True, day_hour), (False, night_hour)):
                if rng.random() > pass_probability or rng.random() < cloud_by_day[day]:
                    continue
                local = local_hour + rng.normal(0, 0.2)
                fires: List[Fire] = []
                for generator in scene.generators:
                    fires.extend(generator.fires_at(rng, day, local, is_day))
                if not fires:
                    continue
                utc = scene.start + timedelta(days=day, hours=local - scene.lon0 / 15.0)
                scan, track = rng.uniform(*sensor["scan"]), rng.uniform(*sensor["track"])
                off_x, off_y = rng.uniform(0, scan), rng.uniform(0, track)
                sigma_scan, sigma_track = rng.uniform(*sensor["psf_scan"]), rng.uniform(*sensor["psf_track"])
                area_m2 = scan * track * 1e6
                wl4, wl5 = sensor["mir_um"], sensor["tir_um"]

                # Share every fire's signal with neighbouring pixels through the point-spread function.
                pixels: Dict[Tuple[int, int], List[float]] = {}  # fire area fraction, fire MIR radiance, fire TIR radiance
                dominant: Dict[Tuple[int, int], Tuple[float, Fire]] = {}
                for fire in fires:
                    u, v = (fire.x - off_x) / scan, (fire.y - off_y) / track
                    i0, j0 = math.floor(u), math.floor(v)
                    across, along = _psf_weights(u - i0, sigma_scan), _psf_weights(v - j0, sigma_track)
                    share = fire.area_m2 / area_m2
                    p4, p5 = planck(wl4, fire.temperature), planck(wl5, fire.temperature)
                    power = fire.area_m2 * fire.temperature ** 4
                    for di, w_across in zip((-1, 0, 1), across):
                        for dj, w_along in zip((-1, 0, 1), along):
                            weight = w_across * w_along
                            if weight < 1e-3:
                                continue
                            key = (i0 + di, j0 + dj)
                            acc = pixels.setdefault(key, [0.0, 0.0, 0.0])
                            acc[0] += weight * share
                            acc[1] += weight * share * p4
                            acc[2] += weight * share * p5
                            if key not in dominant or weight * power > dominant[key][0]:
                                dominant[key] = (weight * power, fire)

                t_surface = rng.normal(t_day if is_day else t_night, 2.5)
                t_mir_background = t_surface + (rng.uniform(4.0, 14.0) if is_day else -1.0)
                l4_bg, l5_bg = planck(wl4, t_mir_background), planck(wl5, t_surface)

                for (i, j), (fraction, fire_l4, fire_l5) in pixels.items():
                    fraction = min(fraction, 0.5)
                    l4 = (1 - fraction) * l4_bg + fire_l4
                    l5 = (1 - fraction) * l5_bg + fire_l5
                    t4 = brightness_temperature(wl4, l4) + rng.normal(0, 0.4)
                    t5 = brightness_temperature(wl5, l5) + rng.normal(0, 0.3)
                    anomaly = t4 - t_mir_background
                    if sensor is VIIRS:
                        threshold, floor = (16.0, 322.0) if is_day else (6.0, 298.0)
                    else:
                        threshold, floor = (10.0, 314.0) if is_day else (5.0, 296.0)
                    if t4 < floor:
                        continue
                    if rng.random() >= 1.0 / (1.0 + math.exp(-(anomaly - threshold) / 1.5)):
                        continue
                    frp = area_m2 * SIGMA * max(l4 - l4_bg, 0.0) / MIR_COEFFICIENT[sensor["name"]] / 1e6
                    frp *= rng.lognormal(0.0, 0.1)
                    source = dominant[(i, j)][1]
                    cx = (i + 0.5) * scan + off_x + rng.normal(0, 0.08)
                    cy = (j + 0.5) * track + off_y + rng.normal(0, 0.08)
                    lat, lon = scene.frame.to_latlon(cx, cy)
                    detections.append({
                        "latitude": lat,
                        "longitude": lon,
                        "acq_datetime": utc.strftime("%Y-%m-%dT%H:%MZ"),
                        "daynight": "D" if is_day else "N",
                        "frp": round(frp, 2),
                        "bright_mir": round(min(t4, sensor["mir_sat"]), 2),
                        "bright_tir": round(t5, 2),
                        "instrument": sensor["name"],
                        "satellite": name,
                        "scan": round(scan, 2),
                        "track": round(track, 2),
                        "label": source.label,
                        "family": source.family,
                        "scene_family": scene.family,
                        "scene_id": scene.scene_id,
                    })
    return detections


def simulate_scene_features(family: str, seed: int) -> List[Dict]:
    """Simulate one scene and return one feature row per detection (with label metadata)."""
    scene = build_scene(family, seed)
    detections = observe_scene(scene, seed)
    if not detections:
        return []
    context = GeoContext(scene.features)
    rows, evidence = build_feature_table(detections, context.lookup, _landcover_lookup(scene, seed), observation_days=scene.days)
    out = []
    for det, row, ev in zip(detections, rows, evidence):
        record = {name: row[name] for name in FEATURE_COLUMNS}
        record.update({
            "label": det["label"],
            "family": det["family"],
            "scene_family": det["scene_family"],
            "scene_id": det["scene_id"],
            "persistence_days": row["persistence_days"],
            "_evidence": ev,
        })
        out.append(record)
    return out


def simulate_dataset(n_scenes: int, seed: int = 7, families: Optional[Sequence[str]] = None) -> List[Dict]:
    rng = np.random.default_rng(seed)
    families = list(families or FAMILY_WEIGHTS)
    weights = np.array([FAMILY_WEIGHTS[f] for f in families], dtype=float)
    weights /= weights.sum()
    rows: List[Dict] = []
    for k in range(n_scenes):
        family = families[int(rng.choice(len(families), p=weights))]
        rows.extend(simulate_scene_features(family, seed * 100_000 + k))
    return rows
