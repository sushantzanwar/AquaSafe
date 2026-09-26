import { useMemo } from "react";
import { GeoJSON, MapContainer, TileLayer } from "react-leaflet";
import type { LatLngExpression } from "leaflet";
import type { GeoJsonObject } from "geojson";
import type { GeoJsonFeatureCollection } from "../types/analysis";

function computeCenter(
  geojson: GeoJsonFeatureCollection
): LatLngExpression {
  const coords = geojson.features[0]?.geometry.coordinates[0] ?? [];
  if (coords.length === 0) return [21.13, 79.04];

  const lats = coords.map((c) => c[1]);
  const lngs = coords.map((c) => c[0]);
  const avg = (arr: number[]) => arr.reduce((a, b) => a + b, 0) / arr.length;
  return [avg(lats), avg(lngs)];
}

export function WaterMap({ geojson }: { geojson: GeoJsonFeatureCollection }) {
  const center = useMemo(() => computeCenter(geojson), [geojson]);

  return (
    <div className="h-80 overflow-hidden rounded-xl border border-slate-800">
      <MapContainer
        center={center}
        zoom={13}
        scrollWheelZoom={false}
        style={{ width: "100%", height: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <GeoJSON
          key={JSON.stringify(geojson)}
          data={geojson as unknown as GeoJsonObject}
          style={{ color: "#3ac5ff", weight: 2, fillOpacity: 0.25 }}
        />
      </MapContainer>
    </div>
  );
}
