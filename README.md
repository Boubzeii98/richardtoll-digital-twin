# Richard-Toll — Jumeau numérique

Jumeau numérique géospatial de Richard-Toll (Sénégal), à l'appui de la
décision urbaine et de l'aménagement — construit en briques successives à
partir de données ouvertes (Google Open Buildings, Copernicus DEM,
Sentinel-2) et enrichi progressivement selon une logique multicritère
inspirée du modèle REGREEN.

## État d'avancement

- ✅ **Phase 0** — Extraction bâti (Open Buildings v3) + MNT (Copernicus DEM GLO-30)
- ✅ **Phase 1** — Prévisualisation 3D interactive (MapLibre GL JS), vues réaliste et analytique
- 🔄 **Phase 2** — Couches de décision multicritère :
  - ✅ 2a. Occupation du sol (classification Sentinel-2 + croisement bâti)
  - ⏳ 2b. Risque d'inondation
  - ⏳ 2c. Disponibilité foncière
  - ⏳ 2d. Proximité équipements/voirie

## Structure du dépôt

```
richardtoll-digital-twin/
├── scripts/
│   ├── extract_richardtoll.py   # Phase 0 : bâti + MNT
│   └── landuse_richardtoll.py   # Phase 2a : occupation du sol
└── docs/
    ├── index.html                    # prévisualisation 3D (servie par GitHub Pages)
    └── buildings_richardtoll.geojson # bâti + hauteur estimée
```

## Lancer les scripts (Spyder ou tout Python 3.10+)

```bash
pip install -r requirements.txt
```

Authentification Earth Engine (une fois) :
```python
import ee
ee.Authenticate()
```

Puis, dans l'ordre :
```bash
python scripts/extract_richardtoll.py
python scripts/landuse_richardtoll.py
```

Les sorties arrivent dans `richardtoll_data/` (créé à côté des scripts, non
versionné sur GitHub — voir `.gitignore`).

## Voir la prévisualisation 3D en ligne

Une fois GitHub Pages activé sur ce dépôt (Settings → Pages → branche
`main`, dossier `/docs`) :

```
https://<ton-pseudo-github>.github.io/richardtoll-digital-twin/
```

## Notes méthodologiques

- **Hauteurs de bâtiment** : estimées par classe de surface au sol (Open
  Buildings ne fournit pas de hauteur réelle) — à affiner en Phase 2 avec
  des relevés terrain ciblés sur les bâtiments-clés.
- **Occupation du sol** : classification par seuils NDVI/NDWI sur composite
  Sentinel-2 saison sèche, avec la classe "non-végétalisé" affinée en
  croisant avec le bâti déjà extrait (bâti confirmé vs. sol nu disponible).
- **MNT** : Copernicus DEM GLO-30 (résolution 30m, référentiel vertical
  EGM2008) — suffisant pour les critères de pente/priorisation, pas pour
  une modélisation hydraulique fine (casier/H-V-S).
