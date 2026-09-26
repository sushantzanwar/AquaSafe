import httpx

tests = [
    ("Chilika Lake, Odisha", 19.72, 85.32),
    ("Futala Lake, Nagpur",  21.154, 79.041),
    ("Dal Lake, Kashmir",    34.09, 74.87),
    ("Wular Lake, J&K",      34.35, 74.57),
]

for label, lat, lon in tests:
    query = """[out:json][timeout:20];
(
  way["natural"="water"](around:5000,""" + str(lat) + "," + str(lon) + """);
  way["water"](around:5000,""" + str(lat) + "," + str(lon) + """);
  way["landuse"="reservoir"](around:5000,""" + str(lat) + "," + str(lon) + """);
  relation["natural"="water"](around:5000,""" + str(lat) + "," + str(lon) + """);
  relation["water"](around:5000,""" + str(lat) + "," + str(lon) + """);
  relation["landuse"="reservoir"](around:5000,""" + str(lat) + "," + str(lon) + """);
);
out body geom;"""
    try:
        r = httpx.post("https://overpass-api.de/api/interpreter",
                       data={"data": query},
                       headers={"User-Agent": "AquaWatch/1.0"}, timeout=22)
        els = r.json().get("elements", [])
        has_way_geom   = [e for e in els if e.get("type") == "way" and e.get("geometry")]
        has_rel_geom   = [e for e in els if e.get("type") == "relation" and
                          any(m.get("geometry") for m in e.get("members", []))]
        names = list({e.get("tags", {}).get("name", "") for e in els
                      if e.get("tags", {}).get("name")})[:4]
        print(f"\n{label}")
        print(f"  HTTP {r.status_code} | total={len(els)} | ways_with_geom={len(has_way_geom)} | rels_with_geom={len(has_rel_geom)}")
        print(f"  Names: {names}")
    except Exception as ex:
        print(f"\n{label}: ERROR {ex}")
