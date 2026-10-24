import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Layers, ArrowRight } from 'lucide-react';
import L from 'leaflet';
import { AcquisitionCase, PageView, ProjectInfo } from '../../types';
import type { FeatureCollection, GeoFeature } from '../../api/client';
import { RiskBadge } from '../common/RiskBadge';
import { IllustrativeBadge } from '../common/StatusChips';

interface GisMapViewProps {
  project: ProjectInfo;
  cases: AcquisitionCase[];
  features: FeatureCollection | null;
  selectedCase: AcquisitionCase;
  onSelectCase: (c: AcquisitionCase) => void;
  onNavigate: (page: PageView) => void;
}

const RISK_COLOR: Record<string, string> = { HIGH: '#e11d48', MEDIUM: '#f59e0b', LOW: '#10b981', UNRATED: '#64748b' };
const QUALITY_COLOR: Record<string, string> = { GOOD: '#2563eb', PARTIAL: '#f59e0b', POOR: '#94a3b8' };
const UNLINKED = '#9ca3af';

const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));

export const GisMapView: React.FC<GisMapViewProps> = ({ project, cases, features, selectedCase, onSelectCase, onNavigate }) => {
  const [activeCase, setActiveCase] = useState<AcquisitionCase>(selectedCase);
  const [selectedZone, setSelectedZone] = useState<string | null>(null);
  const [showCorridor, setShowCorridor] = useState(true);
  const [showUnlinked, setShowUnlinked] = useState(true);
  const [mapMode, setMapMode] = useState<'streets' | 'satellite' | 'dark'>('streets');
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const fittedRef = useRef(false);

  const caseByUid = useMemo(() => new Map(cases.map((c) => [c.uid, c])), [cases]);
  const all = features?.features ?? [];
  const parcels = all.filter((f) => f.properties.role !== 'alignment');
  const alignments = all.filter((f) => f.properties.role === 'alignment');
  const zones = Array.from(new Set(cases.map((c) => c.zone).filter((z) => z && !z.startsWith('Zone unknown')))).sort();

  const colorFor = (f: GeoFeature): string => {
    const c = f.properties.case_id ? caseByUid.get(f.properties.case_id) : undefined;
    if (!c) return UNLINKED;
    return project.isDemo || c.riskCategory !== 'UNRATED' ? RISK_COLOR[c.riskCategory] : QUALITY_COLOR[c.dataQuality];
  };

  // Hotspot: zone with the most high-risk (demo) or alignment-intersecting (uploaded) cases.
  const hotspot = useMemo(() => {
    const score = new Map<string, number>();
    for (const c of cases) {
      const hit = project.isDemo ? c.riskCategory === 'HIGH' : Boolean(c.spatial.intersects_alignment);
      if (hit) score.set(c.zone, (score.get(c.zone) ?? 0) + 1);
    }
    const best = [...score.entries()].sort((a, b) => b[1] - a[1])[0];
    return best ? { zone: best[0], count: best[1] } : null;
  }, [cases, project.isDemo]);

  useEffect(() => {
    if (!containerRef.current) return;
    const map = L.map(containerRef.current, { center: [28.465, 77.035], zoom: 12, zoomControl: true });
    const tiles = {
      streets: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      satellite: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      dark: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
    };
    L.tileLayer(tiles[mapMode], { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    fittedRef.current = false;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [mapMode]);

  useEffect(() => {
    const map = mapRef.current;
    const group = layerRef.current;
    if (!map || !group) return;
    group.clearLayers();

    if (showCorridor) {
      for (const a of alignments) {
        L.geoJSON(a as never, { style: { color: '#3b82f6', weight: 14, opacity: 0.25 } }).addTo(group);
        L.geoJSON(a as never, { style: { color: '#1d4ed8', weight: 3, dashArray: '8, 6', opacity: 0.9 } }).addTo(group);
      }
    }

    for (const f of parcels) {
      const linked = f.properties.case_id ? caseByUid.get(f.properties.case_id) : undefined;
      if (!linked && !showUnlinked) continue;
      const color = colorFor(f);
      const isSelected = linked?.uid === activeCase.uid;
      const layer = L.geoJSON(f as never, {
        style: { color: isSelected ? '#1e1b4b' : color, weight: isSelected ? 3 : 1.5, fillColor: color, fillOpacity: isSelected ? 0.65 : 0.4 },
      }).addTo(group);
      const p = f.properties;
      const label = linked
        ? `<strong>${escapeHtml(linked.id)}</strong> · ${escapeHtml(linked.villageName)}<br/>` +
          (linked.delayProbability !== null ? `${linked.isSynthetic ? 'Illustrative delay prob' : 'Delay risk'}: <b>${linked.delayProbability}%</b><br/>` : 'Prediction: not available<br/>')
        : '<strong>Parcel not linked to a case</strong><br/>No verified case match (or awaiting clarification).<br/>';
      layer.bindPopup(
        `<div style="font-family:Inter,sans-serif;font-size:11px;min-width:190px">${label}` +
          `Parcel: ${escapeHtml(p.parcel_id ?? '—')}<br/>Survey: ${escapeHtml(p.survey_numbers.join(', ') || '—')}<br/>` +
          (p.area_hectares !== null ? `Mapped area: ${p.area_hectares} ha<br/>` : '') +
          (p.intersects_alignment !== null ? `On alignment: ${p.intersects_alignment ? 'yes' : 'no'}<br/>` : '') +
          `<span style="color:#64748b">${p.synthetic ? 'Synthetic geometry' : `Source: ${escapeHtml(p.map_id)} · ${escapeHtml(p.layer)}`}</span></div>`,
      );
      if (linked) layer.on('click', () => {
        setActiveCase(linked);
        onSelectCase(linked);
      });
    }

    if (!fittedRef.current && all.length) {
      const bounds = L.geoJSON({ type: 'FeatureCollection', features: all } as never).getBounds();
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [24, 24] });
      fittedRef.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [features, activeCase, showCorridor, showUnlinked, mapMode, caseByUid]);

  const focusCase = (c: AcquisitionCase) => {
    setActiveCase(c);
    onSelectCase(c);
    if (mapRef.current && c.polygonCoords.length) mapRef.current.fitBounds(L.latLngBounds(c.polygonCoords), { maxZoom: 15 });
  };

  const unlinkedCount = parcels.filter((f) => !f.properties.case_id).length;
  const quick = [...cases].filter((c) => c.polygonCoords.length).slice(0, 4);

  return (
    <div className="space-y-6 pb-12">
      <div className="bg-white p-6 rounded-xl border border-slate-200/90 shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 flex items-center gap-1.5">
              <Layers className="h-3 w-3" />
              GIS Spatial Intelligence
            </span>
            {features?.synthetic ? <IllustrativeBadge text="Illustrative GIS Data" /> : (
              <span className="text-[11px] text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-md font-medium">Validated uploaded layers (EPSG:4326)</span>
            )}
          </div>
          <h1 className="text-2xl font-semibold text-slate-900 tracking-tight mt-1">Parcel-Level Risk Map</h1>
          <p className="text-xs md:text-sm text-slate-500 mt-0.5">
            {parcels.length} parcel feature(s){alignments.length ? ', corridor alignment shown' : ', no alignment layer'}
            {unlinkedCount ? ` • ${unlinkedCount} parcel(s) not linked to a case` : ''}.
          </p>
        </div>

        {zones.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold text-slate-500 mr-1">Zone Focus:</span>
            {zones.slice(0, 6).map((z) => (
              <button
                key={z}
                onClick={() => {
                  setSelectedZone(z);
                  const first = cases.find((c) => c.zone === z && c.polygonCoords.length);
                  if (first) focusCase(first);
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${selectedZone === z ? 'bg-blue-600 text-white shadow-xs' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'}`}
              >
                {z}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-8 bg-white p-3 rounded-xl border border-slate-200/90 shadow-sm flex flex-col">
          <div className="flex items-center justify-between pb-3 px-3 border-b border-slate-100 gap-2 flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-slate-800">Layers:</span>
              <button onClick={() => setShowCorridor(!showCorridor)} className={`text-[11px] font-semibold px-2.5 py-1 rounded-md border ${showCorridor ? 'bg-blue-50 border-blue-200 text-blue-700' : 'bg-slate-50 border-slate-200 text-slate-400'}`}>
                Alignment
              </button>
              <button onClick={() => setShowUnlinked(!showUnlinked)} className={`text-[11px] font-semibold px-2.5 py-1 rounded-md border ${showUnlinked ? 'bg-slate-100 border-slate-300 text-slate-700' : 'bg-slate-50 border-slate-200 text-slate-400'}`}>
                Unlinked parcels
              </button>
            </div>
            <div className="flex items-center gap-1 bg-slate-100 p-0.5 rounded-lg border border-slate-200 text-[11px] font-semibold">
              {(['streets', 'dark', 'satellite'] as const).map((m) => (
                <button key={m} onClick={() => setMapMode(m)} className={`px-2 py-0.5 rounded ${mapMode === m ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-600'}`}>
                  {m === 'dark' ? 'Voyager' : m[0].toUpperCase() + m.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div className="relative w-full h-[520px] rounded-xl overflow-hidden mt-3 bg-slate-100">
            <div ref={containerRef} className="w-full h-full" />
            <div className="absolute bottom-4 left-4 z-[500] bg-white/95 p-3 rounded-xl border border-slate-200 shadow-lg text-[11px] space-y-1.5">
              <span className="font-bold text-slate-900 uppercase tracking-wider block">Legend</span>
              {(project.isDemo
                ? [['HIGH risk (illustrative)', RISK_COLOR.HIGH], ['MEDIUM risk (illustrative)', RISK_COLOR.MEDIUM], ['LOW risk (illustrative)', RISK_COLOR.LOW]]
                : [['Good evidence', QUALITY_COLOR.GOOD], ['Partial evidence', QUALITY_COLOR.PARTIAL], ['Poor evidence', QUALITY_COLOR.POOR]]
              ).map(([label, color]) => (
                <div key={label} className="flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full" style={{ background: color }} />
                  <span className="font-semibold text-slate-700">{label}</span>
                </div>
              ))}
              <div className="flex items-center gap-2">
                <span className="h-3 w-3 rounded-full" style={{ background: UNLINKED }} />
                <span className="text-slate-600">Not linked to a case</span>
              </div>
            </div>
            {hotspot && (
              <div className="absolute top-4 right-4 z-[500] bg-rose-950/90 text-white px-3.5 py-2 rounded-xl border border-rose-500/50 shadow-xl max-w-xs space-y-1">
                <div className="flex items-center gap-1.5 text-xs font-bold text-rose-300">
                  <span className="h-2 w-2 rounded-full bg-rose-400 animate-ping" />
                  <span>{project.isDemo ? 'High-risk cluster (illustrative)' : 'Parcels on the alignment'}</span>
                </div>
                <p className="text-[11px] text-slate-300 leading-tight">
                  {hotspot.zone} has {hotspot.count} {project.isDemo ? 'high-risk case(s)' : 'case(s) whose parcels intersect the alignment'}.
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="lg:col-span-4 space-y-4">
          <div className="bg-white p-6 rounded-xl border border-slate-200/90 shadow-sm space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Selected Parcel Inspector</span>
              <RiskBadge level={activeCase.riskCategory} size="sm" />
            </div>
            <div>
              <h3 className="font-mono text-2xl font-black text-slate-900">CASE {activeCase.id}</h3>
              <p className="text-xs text-slate-500 mt-0.5">{activeCase.villageName} • {activeCase.zone}</p>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200/80 flex items-center justify-between">
              <div>
                <span className="text-[10px] uppercase font-bold text-slate-400 block">Delay Probability</span>
                <span className="font-mono text-3xl font-black" style={{ color: RISK_COLOR[activeCase.riskCategory] }}>
                  {activeCase.delayProbability === null ? '—' : `${activeCase.delayProbability}%`}
                </span>
                <span className="text-[10px] text-slate-500 block">{activeCase.prediction.status}</span>
              </div>
              <div className="text-right text-xs">
                <span className="text-slate-400 block text-[10px]">Mapped area</span>
                <span className="font-mono font-bold text-slate-800">
                  {activeCase.spatial.area_hectares_computed !== undefined ? `${activeCase.spatial.area_hectares_computed} ha` : activeCase.isSynthetic ? 'synthetic' : 'no geometry'}
                </span>
              </div>
            </div>
            <div className="space-y-2 text-xs">
              {[
                ['Legal Status', activeCase.legalStatus],
                ['Compensation', activeCase.compensationStatus],
                ['Approval Status', activeCase.approvalStatus],
                ['Survey No', activeCase.surveyNo],
                ['On alignment', activeCase.spatial.intersects_alignment === undefined || activeCase.spatial.intersects_alignment === null ? 'Unknown' : activeCase.spatial.intersects_alignment ? 'Yes' : 'No'],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between py-1.5 border-b border-slate-100 last:border-0">
                  <span className="text-slate-500">{k}:</span>
                  <span className="font-bold text-slate-800 text-right">{v}</span>
                </div>
              ))}
            </div>
            <button
              onClick={() => {
                onSelectCase(activeCase);
                onNavigate('case-details');
              }}
              className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 text-white p-3 rounded-xl text-xs font-bold shadow-md transition-all"
            >
              <span>View case details & evidence</span>
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>

          {quick.length > 0 && (
            <div className="bg-white p-4 rounded-xl border border-slate-200/90 text-xs space-y-2">
              <span className="font-bold text-slate-800 text-[11px] uppercase tracking-wider block">Quick Parcel Selection:</span>
              <div className="grid grid-cols-2 gap-2">
                {quick.map((c) => (
                  <button
                    key={c.uid}
                    onClick={() => focusCase(c)}
                    className={`p-2 rounded-lg text-left border transition-all ${activeCase.uid === c.uid ? 'bg-blue-50 border-blue-300 font-bold text-blue-900' : 'hover:bg-slate-50 border-slate-200 text-slate-700'}`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono">{c.id}</span>
                      <span className="text-[9px] px-1 rounded font-bold bg-slate-100 text-slate-700">
                        {c.delayProbability === null ? c.dataQuality : `${c.delayProbability}%`}
                      </span>
                    </div>
                    <div className="text-[10px] text-slate-500 truncate">{c.villageName}</div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
