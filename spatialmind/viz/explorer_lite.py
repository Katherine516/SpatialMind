import html
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from spatialmind.ingestion.labels import load_xenium_analysis_clusters
from spatialmind.schemas import SpatialDataset
from spatialmind.viz.renderers import PALETTE


class XeniumExplorerLiteViewer:
    """Builds a portable local review UI for Xenium cell maps and CSV exports."""

    def render(
        self,
        dataset: SpatialDataset,
        output_dir: str,
        dataset_path: Optional[str] = None,
        filename: str = "explorer_lite_viewer.html",
    ) -> str:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, filename)
        payload = self._payload(dataset, dataset_path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_html_document(payload))
        return path

    def _payload(self, dataset: SpatialDataset, dataset_path: Optional[str]) -> Dict[str, Any]:
        bounds = dataset.bounds()
        clusters = load_xenium_analysis_clusters(dataset_path) if dataset_path else {}
        labels = sorted({record.cell_type for record in dataset.records if record.cell_type})
        regions = sorted({record.region for record in dataset.records if record.region})
        cluster_names = sorted({value for value in clusters.values() if value}, key=_sort_key)
        metadata = dataset.metadata or {}
        source = dataset.sources[0] if dataset.sources else None
        assets = metadata.get("xenium_explorer_assets") if isinstance(metadata.get("xenium_explorer_assets"), dict) else {}
        asset_summary = [
            {
                "name": str(key),
                "exists": bool(value.get("exists")) if isinstance(value, dict) else False,
                "path": str(value.get("resolved_path") or value.get("relative_path") or "") if isinstance(value, dict) else "",
            }
            for key, value in sorted(assets.items())
        ]
        records = []
        for index, record in enumerate(dataset.records):
            cell_id = record.cell_id or str(index)
            records.append(
                {
                    "cell_id": cell_id,
                    "x": round(float(record.x), 4),
                    "y": round(float(record.y), 4),
                    "label": record.cell_type or "Unannotated cell",
                    "region": record.region or "",
                    "cluster": clusters.get(cell_id, ""),
                    "total": round(float(sum(record.genes.values())), 4),
                    "top_features": _top_features(record.genes),
                }
            )
        return {
            "sample_id": dataset.sample_id,
            "dataset_path": dataset_path or dataset.source_path,
            "source_path": dataset.source_path,
            "coordinate_system": dataset.coordinate_system,
            "records": records,
            "bounds": bounds,
            "labels": labels,
            "regions": regions,
            "clusters": cluster_names,
            "counts": {
                "records": len(dataset.records),
                "features": len(dataset.genes),
                "labels": dict(Counter(record.cell_type for record in dataset.records)),
                "regions": dict(Counter(record.region or "unassigned" for record in dataset.records)),
            },
            "metadata": {
                "run_name": metadata.get("run_name") or dataset.sample_id,
                "region_name": metadata.get("region_name") or "",
                "panel_name": metadata.get("panel_name") or "",
                "num_gene_targets": metadata.get("num_gene_targets") or len(dataset.genes),
                "experiment_xenium_path": metadata.get("experiment_xenium_path") or "",
                "image_path": source.image_path if source else "",
                "asset_summary": asset_summary,
            },
            "palette": PALETTE,
        }


def _top_features(genes: Dict[str, float], limit: int = 8) -> str:
    if not genes:
        return ""
    items = sorted(genes.items(), key=lambda item: item[1], reverse=True)
    return "; ".join("%s=%.3g" % (key, value) for key, value in items[:limit])


def _sort_key(value: str) -> Any:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _html_document(payload: Dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    title = "SpatialMind Explorer Lite - %s" % payload["sample_id"]
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>%s</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #1f2933;
      --muted: #5b6777;
      --line: #cbd5df;
      --panel: #ffffff;
      --page: #eef2f6;
      --accent: #1d6f8f;
      --accent-2: #a84656;
      --selected: #111827;
      --field: #f8fafc;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Arial, sans-serif; color: var(--ink); background: var(--page); }
    header { min-height: 58px; display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 12px 18px; background: #0f2530; color: #fff; }
    h1 { margin: 0; font-size: 19px; font-weight: 700; letter-spacing: 0; }
    header p { margin: 3px 0 0; color: #c8d5df; font-size: 12px; }
    main { display: grid; grid-template-columns: minmax(460px, 1fr) 360px; gap: 14px; padding: 14px; min-height: calc(100vh - 58px); }
    .viewer { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; min-width: 0; display: grid; grid-template-rows: auto minmax(360px, 1fr) auto; overflow: hidden; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; padding: 12px; border-bottom: 1px solid var(--line); background: #fbfcfe; }
    .field { display: grid; gap: 4px; min-width: 126px; }
    label { color: #40505f; font-size: 12px; font-weight: 700; }
    select, input, textarea { width: 100%%; border: 1px solid #b9c5d2; border-radius: 6px; background: var(--field); color: var(--ink); font: inherit; font-size: 13px; padding: 7px 8px; min-height: 34px; }
    button { border: 1px solid #9bb3c2; border-radius: 6px; background: #ffffff; color: #17313e; font-weight: 700; font-size: 13px; padding: 8px 10px; min-height: 34px; cursor: pointer; }
    button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    button.warn { background: var(--accent-2); border-color: var(--accent-2); color: #fff; }
    button:disabled { opacity: .45; cursor: default; }
    .plot-shell { display: grid; grid-template-columns: 28px minmax(0, 1fr); grid-template-rows: minmax(0, 1fr) 28px; padding: 12px; min-height: 0; }
    .axis-y { writing-mode: vertical-rl; transform: rotate(180deg); text-align: center; color: #415161; font-size: 12px; padding-top: 12px; }
    .axis-x { grid-column: 2; text-align: center; color: #415161; font-size: 12px; }
    .plot { position: relative; min-height: 360px; background: #fbfbf7; border: 1px solid #28323a; overflow: hidden; }
    svg { width: 100%%; height: 100%%; display: block; touch-action: none; }
    .selection-rect { fill: rgba(17, 24, 39, .08); stroke: #111827; stroke-width: 1.5; stroke-dasharray: 6 4; pointer-events: none; }
    .status { display: flex; justify-content: space-between; gap: 14px; padding: 9px 12px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; background: #fbfcfe; }
    aside { display: grid; grid-template-rows: auto auto minmax(150px, 1fr); gap: 14px; min-width: 0; }
    .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-width: 0; }
    .panel h2 { margin: 0 0 10px; font-size: 15px; }
    .metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .metric { border: 1px solid #d8e0e8; border-radius: 6px; padding: 8px; background: #fbfcfe; }
    .metric strong { display: block; font-size: 17px; }
    .metric span { display: block; color: var(--muted); font-size: 11px; margin-top: 2px; }
    .detail { display: grid; gap: 6px; font-size: 13px; }
    .detail code { overflow-wrap: anywhere; background: #edf2f7; padding: 2px 4px; border-radius: 4px; }
    .legend { display: grid; gap: 6px; max-height: 160px; overflow: auto; padding-right: 3px; }
    .legend-item { display: flex; align-items: center; gap: 7px; color: #2f3f4c; font-size: 12px; }
    .swatch { width: 11px; height: 11px; border-radius: 50%%; display: inline-block; flex: 0 0 11px; }
    .review-grid { display: grid; gap: 8px; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    textarea { min-height: 128px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
    .asset-list { max-height: 130px; overflow: auto; margin: 0; padding-left: 18px; color: var(--muted); font-size: 12px; }
    .asset-list code { color: var(--ink); }
    @media (max-width: 940px) {
      main { grid-template-columns: 1fr; }
      aside { grid-template-rows: auto; }
      .plot { min-height: 420px; }
    }
    @media (max-width: 560px) {
      main { padding: 8px; }
      header { align-items: flex-start; flex-direction: column; }
      .toolbar { display: grid; grid-template-columns: 1fr 1fr; }
      .field { min-width: 0; }
      button { width: 100%%; }
      .metrics { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>SpatialMind Explorer Lite</h1>
      <p id="subtitle"></p>
    </div>
    <div id="gateStatus"></div>
  </header>
  <main>
    <section class="viewer">
      <div class="toolbar">
        <div class="field">
          <label for="colorBy">Color</label>
          <select id="colorBy">
            <option value="label">Cell label</option>
            <option value="cluster">10x cluster</option>
            <option value="region">Region</option>
          </select>
        </div>
        <div class="field">
          <label for="labelFilter">Label</label>
          <select id="labelFilter"></select>
        </div>
        <div class="field">
          <label for="clusterFilter">Cluster</label>
          <select id="clusterFilter"></select>
        </div>
        <div class="field">
          <label for="cellSearch">Cell ID</label>
          <input id="cellSearch" placeholder="Search">
        </div>
        <button id="clearSelection">Clear</button>
      </div>
      <div class="plot-shell">
        <div class="axis-y">spatial2</div>
        <div class="plot"><svg id="plot" role="img" aria-label="Xenium spatial cell map"></svg></div>
        <div></div>
        <div class="axis-x">spatial1</div>
      </div>
      <div class="status">
        <span id="visibleStatus"></span>
        <span id="selectionStatus"></span>
      </div>
    </section>
    <aside>
      <section class="panel">
        <h2>Run</h2>
        <div class="metrics">
          <div class="metric"><strong id="recordCount">0</strong><span>cells loaded</span></div>
          <div class="metric"><strong id="featureCount">0</strong><span>features</span></div>
          <div class="metric"><strong id="labelCount">0</strong><span>labels</span></div>
          <div class="metric"><strong id="clusterCount">0</strong><span>clusters</span></div>
        </div>
      </section>
      <section class="panel">
        <h2>Selected Cell</h2>
        <div id="cellDetail" class="detail"></div>
      </section>
      <section class="panel">
        <h2>Review Export</h2>
        <div class="review-grid">
          <div class="field">
            <label for="regionName">Region</label>
            <input id="regionName" placeholder="tumor_core">
          </div>
          <div class="field">
            <label for="expertLabel">Expert label</label>
            <input id="expertLabel" placeholder="astrocyte">
          </div>
          <div class="field">
            <label for="confidence">Confidence</label>
            <input id="confidence" placeholder="0.90">
          </div>
          <div class="field">
            <label for="notes">Notes</label>
            <input id="notes" placeholder="reviewed in Explorer Lite">
          </div>
          <div class="actions">
            <button id="applyRegion" class="primary">Apply Region</button>
            <button id="applyLabel" class="primary">Apply Label</button>
            <button id="exportRegions">Export Regions</button>
            <button id="exportLabels">Export Labels</button>
          </div>
          <textarea id="csvPreview" aria-label="CSV preview"></textarea>
        </div>
      </section>
      <section class="panel">
        <h2>Legend</h2>
        <div id="legend" class="legend"></div>
      </section>
      <section class="panel">
        <h2>Assets</h2>
        <ul id="assets" class="asset-list"></ul>
      </section>
    </aside>
  </main>
  <script>
    const DATA = %s;
    const NS = 'http://www.w3.org/2000/svg';
    const state = {
      colorBy: 'label',
      labelFilter: 'all',
      clusterFilter: 'all',
      selected: new Set(),
      regionEdits: new Map(),
      labelEdits: new Map(),
      lastCell: null,
      dragStart: null,
      dragRect: null
    };
    const el = {
      subtitle: document.getElementById('subtitle'),
      gateStatus: document.getElementById('gateStatus'),
      plot: document.getElementById('plot'),
      colorBy: document.getElementById('colorBy'),
      labelFilter: document.getElementById('labelFilter'),
      clusterFilter: document.getElementById('clusterFilter'),
      cellSearch: document.getElementById('cellSearch'),
      clearSelection: document.getElementById('clearSelection'),
      visibleStatus: document.getElementById('visibleStatus'),
      selectionStatus: document.getElementById('selectionStatus'),
      recordCount: document.getElementById('recordCount'),
      featureCount: document.getElementById('featureCount'),
      labelCount: document.getElementById('labelCount'),
      clusterCount: document.getElementById('clusterCount'),
      cellDetail: document.getElementById('cellDetail'),
      regionName: document.getElementById('regionName'),
      expertLabel: document.getElementById('expertLabel'),
      confidence: document.getElementById('confidence'),
      notes: document.getElementById('notes'),
      applyRegion: document.getElementById('applyRegion'),
      applyLabel: document.getElementById('applyLabel'),
      exportRegions: document.getElementById('exportRegions'),
      exportLabels: document.getElementById('exportLabels'),
      csvPreview: document.getElementById('csvPreview'),
      legend: document.getElementById('legend'),
      assets: document.getElementById('assets')
    };

    function init() {
      el.subtitle.textContent = `${DATA.sample_id} · ${DATA.dataset_path || 'local dataset'} · ${DATA.coordinate_system}`;
      el.gateStatus.textContent = 'Review-only CSV preparation';
      el.recordCount.textContent = DATA.counts.records;
      el.featureCount.textContent = DATA.counts.features;
      el.labelCount.textContent = DATA.labels.length;
      el.clusterCount.textContent = DATA.clusters.length;
      fillSelect(el.labelFilter, ['all'].concat(DATA.labels), 'all');
      fillSelect(el.clusterFilter, ['all'].concat(DATA.clusters), 'all');
      renderAssets();
      bindEvents();
      render();
      showCell(DATA.records[0] || null);
    }

    function fillSelect(select, values, selected) {
      select.innerHTML = '';
      values.forEach(value => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value === 'all' ? 'All' : value;
        if (value === selected) option.selected = true;
        select.appendChild(option);
      });
    }

    function bindEvents() {
      el.colorBy.addEventListener('change', () => { state.colorBy = el.colorBy.value; render(); });
      el.labelFilter.addEventListener('change', () => { state.labelFilter = el.labelFilter.value; render(); });
      el.clusterFilter.addEventListener('change', () => { state.clusterFilter = el.clusterFilter.value; render(); });
      el.cellSearch.addEventListener('input', searchCell);
      el.clearSelection.addEventListener('click', () => { state.selected.clear(); render(); });
      el.applyRegion.addEventListener('click', applyRegion);
      el.applyLabel.addEventListener('click', applyLabel);
      el.exportRegions.addEventListener('click', exportRegions);
      el.exportLabels.addEventListener('click', exportLabels);
      el.plot.addEventListener('pointerdown', startDrag);
      el.plot.addEventListener('pointermove', updateDrag);
      el.plot.addEventListener('pointerup', endDrag);
      el.plot.addEventListener('pointerleave', endDrag);
    }

    function filteredRecords() {
      const search = el.cellSearch.value.trim().toLowerCase();
      return DATA.records.filter(record => {
        if (state.labelFilter !== 'all' && record.label !== state.labelFilter) return false;
        if (state.clusterFilter !== 'all' && record.cluster !== state.clusterFilter) return false;
        if (search && !record.cell_id.toLowerCase().includes(search)) return false;
        return true;
      });
    }

    function render() {
      const records = filteredRecords();
      el.plot.innerHTML = '';
      const box = viewBox();
      el.plot.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
      const background = document.createElementNS(NS, 'rect');
      background.setAttribute('x', '0');
      background.setAttribute('y', '0');
      background.setAttribute('width', box.width);
      background.setAttribute('height', box.height);
      background.setAttribute('fill', '#fbfbf7');
      el.plot.appendChild(background);
      const colorMap = buildColorMap(records);
      records.forEach(record => {
        const p = project(record, box);
        const circle = document.createElementNS(NS, 'circle');
        circle.setAttribute('cx', p.x.toFixed(2));
        circle.setAttribute('cy', p.y.toFixed(2));
        circle.setAttribute('r', state.selected.has(record.cell_id) ? '4.8' : '2.8');
        circle.setAttribute('fill', colorMap.get(colorValue(record)) || '#9aa6b2');
        circle.setAttribute('fill-opacity', state.selected.size && !state.selected.has(record.cell_id) ? '0.32' : '0.82');
        circle.setAttribute('stroke', state.selected.has(record.cell_id) ? '#111827' : 'none');
        circle.setAttribute('stroke-width', state.selected.has(record.cell_id) ? '1.4' : '0');
        circle.dataset.cellId = record.cell_id;
        circle.style.cursor = 'pointer';
        circle.addEventListener('click', event => {
          event.stopPropagation();
          if (event.shiftKey) toggleSelected(record.cell_id);
          else {
            state.selected.clear();
            state.selected.add(record.cell_id);
          }
          showCell(record);
          render();
        });
        circle.addEventListener('mouseenter', () => showCell(record));
        el.plot.appendChild(circle);
      });
      renderLegend(colorMap);
      el.visibleStatus.textContent = `${records.length} visible of ${DATA.records.length}`;
      el.selectionStatus.textContent = `${state.selected.size} selected`;
    }

    function viewBox() {
      return { width: 1000, height: 720 };
    }

    function project(record, box) {
      const spanX = Math.max(DATA.bounds.max_x - DATA.bounds.min_x, 1);
      const spanY = Math.max(DATA.bounds.max_y - DATA.bounds.min_y, 1);
      return {
        x: ((record.x - DATA.bounds.min_x) / spanX) * box.width,
        y: box.height - ((record.y - DATA.bounds.min_y) / spanY) * box.height
      };
    }

    function unproject(point, box) {
      const spanX = Math.max(DATA.bounds.max_x - DATA.bounds.min_x, 1);
      const spanY = Math.max(DATA.bounds.max_y - DATA.bounds.min_y, 1);
      return {
        x: DATA.bounds.min_x + (point.x / box.width) * spanX,
        y: DATA.bounds.min_y + ((box.height - point.y) / box.height) * spanY
      };
    }

    function pointerPoint(event) {
      const point = el.plot.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      return point.matrixTransform(el.plot.getScreenCTM().inverse());
    }

    function startDrag(event) {
      if (event.target.tagName === 'circle') return;
      state.dragStart = pointerPoint(event);
      state.dragRect = document.createElementNS(NS, 'rect');
      state.dragRect.setAttribute('class', 'selection-rect');
      el.plot.appendChild(state.dragRect);
      el.plot.setPointerCapture(event.pointerId);
    }

    function updateDrag(event) {
      if (!state.dragStart || !state.dragRect) return;
      const point = pointerPoint(event);
      const x = Math.min(state.dragStart.x, point.x);
      const y = Math.min(state.dragStart.y, point.y);
      const width = Math.abs(state.dragStart.x - point.x);
      const height = Math.abs(state.dragStart.y - point.y);
      state.dragRect.setAttribute('x', x.toFixed(2));
      state.dragRect.setAttribute('y', y.toFixed(2));
      state.dragRect.setAttribute('width', width.toFixed(2));
      state.dragRect.setAttribute('height', height.toFixed(2));
    }

    function endDrag(event) {
      if (!state.dragStart || !state.dragRect) return;
      const point = pointerPoint(event);
      const x1 = Math.min(state.dragStart.x, point.x);
      const x2 = Math.max(state.dragStart.x, point.x);
      const y1 = Math.min(state.dragStart.y, point.y);
      const y2 = Math.max(state.dragStart.y, point.y);
      const box = viewBox();
      const hits = filteredRecords().filter(record => {
        const p = project(record, box);
        return p.x >= x1 && p.x <= x2 && p.y >= y1 && p.y <= y2;
      });
      if (!event.shiftKey) state.selected.clear();
      hits.forEach(record => state.selected.add(record.cell_id));
      state.dragRect.remove();
      state.dragStart = null;
      state.dragRect = null;
      render();
    }

    function colorValue(record) {
      if (state.colorBy === 'cluster') return record.cluster || 'unassigned';
      if (state.colorBy === 'region') return state.regionEdits.get(record.cell_id)?.region || record.region || 'unassigned';
      return state.labelEdits.get(record.cell_id)?.expert_label || record.label || 'Unannotated cell';
    }

    function buildColorMap(records) {
      const values = Array.from(new Set(records.map(colorValue))).sort(naturalSort);
      const map = new Map();
      values.forEach((value, index) => map.set(value, DATA.palette[index %% DATA.palette.length]));
      return map;
    }

    function renderLegend(colorMap) {
      el.legend.innerHTML = '';
      colorMap.forEach((color, value) => {
        const item = document.createElement('div');
        item.className = 'legend-item';
        item.innerHTML = `<span class="swatch" style="background:${color}"></span><span>${escapeHtml(value)}</span>`;
        el.legend.appendChild(item);
      });
    }

    function renderAssets() {
      el.assets.innerHTML = '';
      const assets = DATA.metadata.asset_summary || [];
      if (!assets.length) {
        const li = document.createElement('li');
        li.textContent = 'No linked Explorer assets were listed.';
        el.assets.appendChild(li);
        return;
      }
      assets.forEach(asset => {
        const li = document.createElement('li');
        li.innerHTML = `${asset.exists ? 'present' : 'missing'}: <code>${escapeHtml(asset.name)}</code>`;
        el.assets.appendChild(li);
      });
    }

    function showCell(record) {
      state.lastCell = record;
      if (!record) {
        el.cellDetail.textContent = 'No cell loaded.';
        return;
      }
      const regionEdit = state.regionEdits.get(record.cell_id);
      const labelEdit = state.labelEdits.get(record.cell_id);
      el.cellDetail.innerHTML = `
        <div><strong>Cell</strong> <code>${escapeHtml(record.cell_id)}</code></div>
        <div><strong>Label</strong> ${escapeHtml(record.label)}</div>
        <div><strong>Cluster</strong> ${escapeHtml(record.cluster || 'unassigned')}</div>
        <div><strong>Region</strong> ${escapeHtml(regionEdit?.region || record.region || 'unassigned')}</div>
        <div><strong>x/y</strong> ${record.x}, ${record.y}</div>
        <div><strong>Total</strong> ${record.total}</div>
        <div><strong>Top features</strong> ${escapeHtml(record.top_features || 'none')}</div>
        ${labelEdit ? `<div><strong>Expert edit</strong> ${escapeHtml(labelEdit.expert_label)}</div>` : ''}
      `;
    }

    function toggleSelected(cellId) {
      if (state.selected.has(cellId)) state.selected.delete(cellId);
      else state.selected.add(cellId);
    }

    function searchCell() {
      const query = el.cellSearch.value.trim().toLowerCase();
      if (query) {
        const match = DATA.records.find(record => record.cell_id.toLowerCase().includes(query));
        if (match) {
          state.selected.clear();
          state.selected.add(match.cell_id);
          showCell(match);
        }
      }
      render();
    }

    function selectedRecords() {
      return DATA.records.filter(record => state.selected.has(record.cell_id));
    }

    function applyRegion() {
      const region = el.regionName.value.trim();
      if (!region || !state.selected.size) return;
      const confidence = el.confidence.value.trim();
      const notes = el.notes.value.trim();
      selectedRecords().forEach(record => state.regionEdits.set(record.cell_id, { region, region_confidence: confidence, notes }));
      preview(exportRegionCsv());
      render();
    }

    function applyLabel() {
      const expertLabel = el.expertLabel.value.trim();
      if (!expertLabel || !state.selected.size) return;
      const confidence = el.confidence.value.trim();
      const notes = el.notes.value.trim();
      selectedRecords().forEach(record => state.labelEdits.set(record.cell_id, { expert_label: expertLabel, confidence, notes }));
      preview(exportLabelCsv());
      render();
    }

    function exportRegions() {
      const csv = exportRegionCsv();
      preview(csv);
      download('cell_regions.csv', csv);
    }

    function exportLabels() {
      const csv = exportLabelCsv();
      preview(csv);
      download('expert_cell_labels.csv', csv);
    }

    function exportRegionCsv() {
      const rows = [['cell_id', 'region', 'region_confidence', 'notes']];
      DATA.records.forEach(record => {
        const edit = state.regionEdits.get(record.cell_id);
        if (edit) rows.push([record.cell_id, edit.region, edit.region_confidence || '', edit.notes || '']);
      });
      return toCsv(rows);
    }

    function exportLabelCsv() {
      const rows = [['cell_id', 'expert_label', 'confidence', 'notes']];
      DATA.records.forEach(record => {
        const edit = state.labelEdits.get(record.cell_id);
        if (edit) rows.push([record.cell_id, edit.expert_label, edit.confidence || '', edit.notes || '']);
      });
      return toCsv(rows);
    }

    function preview(csv) {
      el.csvPreview.value = csv;
    }

    function download(filename, content) {
      const blob = new Blob([content], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    }

    function toCsv(rows) {
      return rows.map(row => row.map(csvCell).join(',')).join('\\n') + '\\n';
    }

    function csvCell(value) {
      const text = String(value ?? '');
      if (/[",\\n]/.test(text)) return '"' + text.replace(/"/g, '""') + '"';
      return text;
    }

    function naturalSort(a, b) {
      const na = Number(a);
      const nb = Number(b);
      if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
      return String(a).localeCompare(String(b));
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
    }

    init();
  </script>
</body>
</html>
""" % (html.escape(title), data)
