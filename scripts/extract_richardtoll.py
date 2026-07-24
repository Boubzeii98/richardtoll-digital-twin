"""
Phase 0 - Jumeau numerique de Richard-Toll
============================================
Extraction des donnees de base :
  1. Batiments  -> Google Open Buildings v3 (via Google Earth Engine)
  2. Terrain    -> Copernicus DEM GLO-30 (via le bucket AWS public, sans compte requis)

Sorties (dans OUTPUT_DIR) :
  - buildings_richardtoll.geojson   (empreintes batiments + hauteur estimee)
  - dem_richardtoll.tif             (MNT brut, mosaique si plusieurs tuiles)
  - dem_richardtoll_clip.tif        (MNT decoupe sur l'emprise exacte)

PREREQUIS (a installer localement, pas dans ce sandbox) :
    pip install earthengine-api geemap geopandas shapely rasterio boto3

  Earth Engine : necessite un compte Google Earth Engine (gratuit, non
  commercial / recherche). Si tu as deja fait ta classification Sentinel-2,
  tu es deja inscrit. Sinon : https://code.earthengine.google.com/register
  Puis lancer une fois : `earthengine authenticate` (ou `ee.Authenticate()`
  en Python) avant d'executer ce script.

UTILISATION :
  - Par defaut le script utilise une bbox large autour de Richard-Toll.
  - Si tu as deja exporte ta delimitation PPGIS en GeoJSON (polygone),
    mets son chemin dans BOUNDARY_GEOJSON ci-dessous : le decoupage sera
    alors plus precis (et le DEM sera clippe sur ce polygone, pas la bbox).
"""

import json
import math
import os

import ee
import geemap
import geopandas as gpd
from shapely.geometry import box

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

# Dossier ou se trouve CE script, quel que soit le dossier de travail actif
# dans Spyder (le champ en haut a droite de la fenetre). Ca evite d'avoir a
# lancer le script depuis un dossier precis : les sorties vont toujours
# a cote du .py, ou que tu l'ouvres depuis Spyder.
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # Fallback si execute ligne par ligne dans la console (pas de __file__)
    SCRIPT_DIR = os.getcwd()

OUTPUT_DIR = os.path.join(SCRIPT_DIR, "richardtoll_data")

# Mets ici le chemin vers TA delimitation PPGIS si tu l'as en GeoJSON.
# Chemin relatif -> resolu par rapport au dossier du script (SCRIPT_DIR).
# Chemin absolu (ex: r"T:\Demba\...\boundary.geojson") -> utilise tel quel.
# Laisse a None pour utiliser la bbox par defaut ci-dessous.
BOUNDARY_GEOJSON = None  # ex: "richard_toll_admin_boundary.geojson"
if BOUNDARY_GEOJSON and not os.path.isabs(BOUNDARY_GEOJSON):
    BOUNDARY_GEOJSON = os.path.join(SCRIPT_DIR, BOUNDARY_GEOJSON)

# Bbox par defaut (large, couvre la commune + une marge de securite)
# Richard-Toll : centre ~16.4625 N / -15.700 W ; commune ~11.6 km2
BBOX_RICHARD_TOLL = {
    "min_lon": -15.75,
    "max_lon": -15.62,
    "min_lat": 16.40,
    "max_lat": 16.52,
}

# Seuil de confiance Open Buildings (0-1). 0.7 = recommandation Google
# pour un usage cartographique standard.
OPEN_BUILDINGS_CONFIDENCE_MIN = 0.7

# ID du Cloud Project associe a ton compte Earth Engine (obligatoire
# depuis 2024). Visible sur https://console.cloud.google.com juste a
# cote de "ID du projet", ou sur https://code.earthengine.google.com.
EE_PROJECT_ID = "project-20244211-196d-4973-ad3"


# ----------------------------------------------------------------------
# EMPRISE (AOI)
# ----------------------------------------------------------------------

def get_aoi():
    """Retourne (geometrie_shapely, bounds) de l'emprise de travail."""
    if BOUNDARY_GEOJSON and os.path.exists(BOUNDARY_GEOJSON):
        gdf = gpd.read_file(BOUNDARY_GEOJSON)
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
        geom = gdf.union_all() if hasattr(gdf, "union_all") else gdf.unary_union
        return geom, tuple(gdf.total_bounds)  # (minx, miny, maxx, maxy)

    b = BBOX_RICHARD_TOLL
    geom = box(b["min_lon"], b["min_lat"], b["max_lon"], b["max_lat"])
    return geom, (b["min_lon"], b["min_lat"], b["max_lon"], b["max_lat"])


# ----------------------------------------------------------------------
# 1. BATIMENTS (Google Open Buildings v3 via Earth Engine)
# ----------------------------------------------------------------------

def extract_buildings(aoi_geom, output_path):
    """Exporte les empreintes de batiments Open Buildings sur l'AOI."""
    ee.Initialize(project=EE_PROJECT_ID)

    ee_geom = ee.Geometry(json.loads(json.dumps(aoi_geom.__geo_interface__)))

    buildings = (
        ee.FeatureCollection("GOOGLE/Research/open-buildings/v3/polygons")
        .filterBounds(ee_geom)
        .filter(ee.Filter.gte("confidence", OPEN_BUILDINGS_CONFIDENCE_MIN))
    )

    count = buildings.size().getInfo()
    print(f"  {count} batiments trouves (confiance >= {OPEN_BUILDINGS_CONFIDENCE_MIN})")

    geemap.ee_export_vector(buildings, output_path)
    print(f"  -> exporte : {output_path}")
    return output_path


def estimate_height(geojson_path, output_path):
    """
    Ajoute une hauteur estimee (m) par classe de surface au sol.
    Open Buildings ne fournit PAS de hauteur : ceci est une valeur
    PLACEHOLDER a affiner plus tard (releves terrain, photos, Kompsat/
    imagerie stereo, ou dire d'expert local par quartier).
    """
    gdf = gpd.read_file(geojson_path)

    def h(area_m2):
        if area_m2 < 60:
            return 4.0    # habitat individuel R+0 / R+1
        elif area_m2 < 200:
            return 6.5    # habitat R+1/R+2, petit commerce
        else:
            return 9.0    # equipement / batiment institutionnel ou industriel

    area_col = "area_in_meters" if "area_in_meters" in gdf.columns else None
    if area_col is None:
        # calcul de secours si le champ n'existe pas (projection metrique locale)
        gdf_m = gdf.to_crs(32628)  # UTM 28N (couvre le Senegal)
        gdf["area_in_meters"] = gdf_m.geometry.area
        area_col = "area_in_meters"

    gdf["height_m"] = gdf[area_col].apply(h)
    gdf["height_source"] = "estimation_placeholder"

    gdf.to_file(output_path, driver="GeoJSON")
    print(f"  -> hauteurs estimees ajoutees : {output_path}")
    return output_path


# ----------------------------------------------------------------------
# 2. TERRAIN (Copernicus DEM GLO-30, bucket AWS public)
# ----------------------------------------------------------------------

def get_dem_tile_ids(bounds):
    """Calcule les identifiants de tuiles Copernicus DEM GLO-30 (grille 1 degre)
    couvrant la bbox donnee (minx, miny, maxx, maxy)."""
    minx, miny, maxx, maxy = bounds
    tiles = []
    for lat in range(math.floor(miny), math.floor(maxy) + 1):
        for lon in range(math.floor(minx), math.floor(maxx) + 1):
            ns = f"N{lat:02d}" if lat >= 0 else f"S{abs(lat):02d}"
            ew = f"E{lon:03d}" if lon >= 0 else f"W{abs(lon):03d}"
            tile_id = f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"
            tiles.append(tile_id)
    return tiles


def download_dem(bounds, output_dir):
    """Telecharge les tuiles Copernicus DEM GLO-30 necessaires depuis le
    bucket public AWS (aucune cle/compte requis)."""
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    from botocore.exceptions import ClientError

    bucket = "copernicus-dem-30m"
    s3 = boto3.client("s3", region_name="eu-central-1", config=Config(signature_version=UNSIGNED))

    tile_ids = get_dem_tile_ids(bounds)
    local_paths = []

    for tile_id in tile_ids:
        key = f"{tile_id}/{tile_id}.tif"
        local_path = os.path.join(output_dir, f"{tile_id}.tif")
        try:
            print(f"  Telechargement {key} ...")
            s3.download_file(bucket, key, local_path)
            local_paths.append(local_path)
        except ClientError as e:
            print(f"  ATTENTION : tuile introuvable ({key}).")
            print(f"  Verifie le nom exact avec :")
            print(f"    aws s3 ls --no-sign-request s3://{bucket}/ | grep {tile_id[:25]}")
            raise e

    return local_paths


def merge_and_clip_dem(tile_paths, aoi_geom, output_raw, output_clip):
    """Mosaique les tuiles DEM (si plusieurs) puis decoupe sur l'AOI."""
    import rasterio
    from rasterio.mask import mask
    from rasterio.merge import merge

    if len(tile_paths) == 1:
        raw_path = tile_paths[0]
    else:
        srcs = [rasterio.open(p) for p in tile_paths]
        mosaic, transform = merge(srcs)
        meta = srcs[0].meta.copy()
        meta.update(
            {
                "height": mosaic.shape[1],
                "width": mosaic.shape[2],
                "transform": transform,
            }
        )
        with rasterio.open(output_raw, "w", **meta) as dst:
            dst.write(mosaic)
        for s in srcs:
            s.close()
        raw_path = output_raw

    with rasterio.open(raw_path) as src:
        out_image, out_transform = mask(src, [aoi_geom.__geo_interface__], crop=True)
        out_meta = src.meta.copy()
        out_meta.update(
            {
                "height": out_image.shape[1],
                "width": out_image.shape[2],
                "transform": out_transform,
            }
        )
        with rasterio.open(output_clip, "w", **out_meta) as dst:
            dst.write(out_image)

    print(f"  -> MNT decoupe : {output_clip}")
    return output_clip


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("1) Emprise de travail...")
    aoi_geom, bounds = get_aoi()
    print(f"   bounds = {bounds}")

    print("\n2) Extraction des batiments (Open Buildings / Earth Engine)...")
    buildings_raw = os.path.join(OUTPUT_DIR, "buildings_raw.geojson")
    extract_buildings(aoi_geom, buildings_raw)

    buildings_final = os.path.join(OUTPUT_DIR, "buildings_richardtoll.geojson")
    estimate_height(buildings_raw, buildings_final)

    print("\n3) Telechargement du MNT (Copernicus DEM GLO-30)...")
    tile_paths = download_dem(bounds, OUTPUT_DIR)

    print("\n4) Mosaique + decoupe du MNT sur l'emprise...")
    dem_raw = os.path.join(OUTPUT_DIR, "dem_richardtoll.tif")
    dem_clip = os.path.join(OUTPUT_DIR, "dem_richardtoll_clip.tif")
    merge_and_clip_dem(tile_paths, aoi_geom, dem_raw, dem_clip)

    print("\nTermine. Fichiers disponibles dans :", os.path.abspath(OUTPUT_DIR))
    print(" -", buildings_final)
    print(" -", dem_clip)


if __name__ == "__main__":
    main()
