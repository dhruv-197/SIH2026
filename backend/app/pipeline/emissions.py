"""Instantaneous emission-rate estimates for vegetation fires from fire radiative power (FRP).

Method
- Dry-matter combustion rate: 0.368 +/- 0.015 kg per MJ of fire radiative energy
  (Wooster, Roberts, Perry & Kaufman 2005, J. Geophys. Res. 110, D24311).
- CO2 emission factors, g CO2 per kg dry matter (Andreae & Merlet 2001, Global Biogeochem.
  Cycles 15, 955-966): tropical forest 1580, agricultural residues 1515.

The result is a rate at the moment of the satellite overpass, not a daily total.
The factors describe biomass burning only, so no estimate is produced for gas flares,
furnaces or coal fires - FRP from those sources does not measure biomass consumption.
"""
from typing import Any, Dict

COMBUSTION_KG_PER_MJ = 0.368
CO2_EMISSION_FACTOR_G_PER_KG = {"wildfire": 1580.0, "agricultural": 1515.0}

REFERENCES = [
    "Wooster et al. (2005) JGR 110, D24311 - FRP to biomass combustion rate",
    "Andreae & Merlet (2001) Global Biogeochemical Cycles 15, 955-966 - emission factors",
]


def estimate(class_code: str, frp_mw: float) -> Dict[str, Any]:
    if class_code not in CO2_EMISSION_FACTOR_G_PER_KG:
        return {
            "applicable": False,
            "note": "Not estimated: FRP-to-biomass factors only apply to vegetation fires.",
        }
    dry_matter_kg_per_h = max(frp_mw, 0.0) * 3600.0 * COMBUSTION_KG_PER_MJ  # MW = MJ/s
    co2_t_per_h = dry_matter_kg_per_h * CO2_EMISSION_FACTOR_G_PER_KG[class_code] / 1e6
    return {
        "applicable": True,
        "basis": "instantaneous rate at satellite overpass",
        "dry_matter_burned_t_per_h": round(dry_matter_kg_per_h / 1000.0, 2),
        "co2_t_per_h": round(co2_t_per_h, 2),
        "emission_factor_g_per_kg": CO2_EMISSION_FACTOR_G_PER_KG[class_code],
        "references": REFERENCES,
    }
