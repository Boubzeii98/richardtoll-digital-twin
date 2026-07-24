"""
Phase 2a - Occupation du sol (Richard-Toll)
=============================================
Classification par indices spectraux Sentinel-2 (composite median, saison
seche) puis affinage de la classe "non-vegetalise" en croisant avec le bati
deja extrait en Phase 0 (Open Buildings) : plus fiable que d'essayer de
separer bati / sol nu uniquement par le spectre a 10m de resolution.

Classes de sortie :
  1 = Eau
  2 = Vegetation / agricole irrigue
  3 = Bati (confirme par intersection avec les empreintes Open Buildings)
  4 = Sol nu / friche potentiellement disponible

Sorties (dans le meme OUTPUT_DIR que la Phase 0, cote a cote avec le bati) :
  - s2_composite_richardtoll.tif     (composite RGB, controle visuel)
  - landuse_richardtoll_raw.tif      (classification brute, 3 classes)
  - landuse_richardtoll.tif          (classification affinee, 4 classes)

PREREQUIS : identiques a la Phase 0 (deja installes si extract_richardtoll.py
a tourne). Ce script reutilise ce fichier comme module (meme dossier requis).

A ajuster si besoin :
  - DATE_START / DATE_END : periode retenue pour le composite Sentinel-2.
    Par defaut la derniere saison seche (moins de nuages, distinction plus
    nette vegetation irriguee vs sol nu).
  - NDVI_VEG_THRESHOLD / NDWI_WATER_THRESHOLD : seuils de classification,
    a af finer en regardant le composite RGB si le resultat semble decale.
"""

import os

import ee
import geemap
import geopandas as gpd
import rasterio
from rasterio.features import rasterize

import extract_richardtoll as base  # reutilise AOI(), EE_PROJECT_ID, OUTPUT_DIR

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

DATE_START = "2025-12-01"   # debut de la derniere saison seche
DATE_END = "2026-05-31"     # fin de la derniere saison seche
CLOUD_MAX = 20               # % de nuage max autorise par scene

NDWI_WATER_THRESHOLD = 0.10
NDVI_VEG_THRESHOLD = 0.30

OUTPUT_DIR = base.OUTPUT_DIR
BUILDINGS_PATH = os.path.join(OUTPUT_DIR, "buildings_richardtoll.geojson")


# ----------------------------------------------------------------------
# 1. COMPOSITE SENTINEL-2
# ----------------------------------------------------------------------

def get_s2_composite(aoi_geom):
    ee.Initialize(project=base.EE_PROJECT_ID)
    ee_geom = ee.Geometry(aoi_geom.__geo_interface__)

    col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(ee_geom)
        .filterDate(DATE_START, DATE_END)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", CLOUD_MAX))
    )

    n = col.size().getInfo()
    print(f"  {n} scenes Sentinel-2 utilisees pour le composite")
    if n == 0:
        raise RuntimeError(
            "Aucune scene trouvee sur cette periode/ce seuil de nuages. "
            "Elargis DATE_START/DATE_END ou augmente CLOUD_MAX."
        )

    composite = col.median().clip(ee_geom)
    return composite


# ----------------------------------------------------------------------
# 2. CLASSIFICATION PAR INDICES
# ----------------------------------------------------------------------

def classify_landuse(composite, aoi_geom):
    ndvi = composite.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndwi = composite.normalizedDifference(["B3", "B8"]).rename("NDWI")

    landuse = (
        ee.Image(3)  # valeur par defaut : non-vegetalise (bati/sol nu)
        .where(ndvi.gt(NDVI_VEG_THRESHOLD), 2)   # vegetation / agricole
        .where(ndwi.gt(NDWI_WATER_THRESHOLD), 1)  # eau (priorite sur vegetation)
        .clip(ee.Geometry(aoi_geom.__geo_interface__))
        .rename("landuse")
        .toByte()
    )
    return landuse


def export_image(image, output_path, aoi_geom, scale=10):
    ee_geom = ee.Geometry(aoi_geom.__geo_interface__)
    geemap.ee_export_image(
        image, filename=output_path, scale=scale, region=ee_geom, file_per_band=False
    )
    print(f"  -> exporte : {output_path}")


# ----------------------------------------------------------------------
# 3. AFFINAGE AVEC LE BATI DEJA EXTRAIT (Phase 0)
# ----------------------------------------------------------------------

def refine_with_buildings(landuse_path, buildings_path, output_path):
    """Reclasse en 'Bati' (3) les pixels non-vegetalises qui intersectent
    une empreinte Open Buildings ; le reste devient 'Sol nu disponible' (4)."""
    if not os.path.exists(buildings_path):
        print(f"  ATTENTION : {buildings_path} introuvable, etape ignoree.")
        print("  (lance d'abord extract_richardtoll.py si pas deja fait)")
        return None

    gdf = gpd.read_file(buildings_path)

    with rasterio.open(landuse_path) as src:
        landuse = src.read(1)
        profile = src.profile
        transform = src.transform
        gdf_proj = gdf.to_crs(src.crs)

    building_mask = rasterize(
        [(geom, 1) for geom in gdf_proj.geometry if geom is not None],
        out_shape=landuse.shape,
        transform=transform,
        fill=0,
        dtype="uint8",
    )

    refined = landuse.copy()
    non_veg_mask = landuse == 3
    refined[non_veg_mask & (building_mask == 1)] = 3  # bati confirme
    refined[non_veg_mask & (building_mask == 0)] = 4  # sol nu disponible

    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(refined, 1)

    print(f"  -> occupation du sol affinee : {output_path}")
    return output_path


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("1) Emprise de travail (reprise de la Phase 0)...")
    aoi_geom, bounds = base.get_aoi()

    print("\n2) Composite Sentinel-2 (saison seche)...")
    composite = get_s2_composite(aoi_geom)

    s2_path = os.path.join(OUTPUT_DIR, "s2_composite_richardtoll.tif")
    export_image(composite.select(["B4", "B3", "B2"]), s2_path, aoi_geom)

    print("\n3) Classification par indices spectraux (NDVI/NDWI)...")
    landuse = classify_landuse(composite, aoi_geom)
    landuse_raw_path = os.path.join(OUTPUT_DIR, "landuse_richardtoll_raw.tif")
    export_image(landuse, landuse_raw_path, aoi_geom)

    print("\n4) Affinage bati vs sol nu (croisement avec Open Buildings)...")
    landuse_final_path = os.path.join(OUTPUT_DIR, "landuse_richardtoll.tif")
    refine_with_buildings(landuse_raw_path, BUILDINGS_PATH, landuse_final_path)

    print("\nTermine. Classes : 1=Eau  2=Vegetation/agricole  3=Bati  4=Sol nu disponible")
    print("Fichiers dans :", os.path.abspath(OUTPUT_DIR))


if __name__ == "__main__":
    main()
