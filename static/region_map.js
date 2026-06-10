// ══ Region Map Module ══
// Country Name (ADMIN field) → DataCo Region mapping
const COUNTRY_NAME_TO_REGION = {
  // Western Europe
  'France':'Western Europe','Germany':'Western Europe','Netherlands':'Western Europe','Belgium':'Western Europe','Luxembourg':'Western Europe','Austria':'Western Europe','Switzerland':'Western Europe','Liechtenstein':'Western Europe','Monaco':'Western Europe',
  // Northern Europe
  'United Kingdom':'Northern Europe','Ireland':'Northern Europe','Iceland':'Northern Europe','Norway':'Northern Europe','Sweden':'Northern Europe','Finland':'Northern Europe','Denmark':'Northern Europe','Estonia':'Northern Europe','Latvia':'Northern Europe','Lithuania':'Northern Europe',
  // Southern Europe
  'Spain':'Southern Europe','Portugal':'Southern Europe','Italy':'Southern Europe','Greece':'Southern Europe','Croatia':'Southern Europe','Slovenia':'Southern Europe','Albania':'Southern Europe','Montenegro':'Southern Europe','North Macedonia':'Southern Europe','Macedonia':'Southern Europe','Bosnia and Herzegovina':'Southern Europe','Serbia':'Southern Europe','Republic of Serbia':'Southern Europe','Malta':'Southern Europe','Andorra':'Southern Europe','San Marino':'Southern Europe','Vatican':'Southern Europe','Cyprus':'Southern Europe','Kosovo':'Southern Europe',
  // Eastern Europe
  'Poland':'Eastern Europe','Czech Republic':'Eastern Europe','Czechia':'Eastern Europe','Slovakia':'Eastern Europe','Hungary':'Eastern Europe','Romania':'Eastern Europe','Bulgaria':'Eastern Europe','Ukraine':'Eastern Europe','Belarus':'Eastern Europe','Moldova':'Eastern Europe','Republic of Moldova':'Eastern Europe','Russia':'Eastern Europe','Russian Federation':'Eastern Europe',
  // Central America
  'Mexico':'Central America','Guatemala':'Central America','Belize':'Central America','Honduras':'Central America','El Salvador':'Central America','Nicaragua':'Central America','Costa Rica':'Central America','Panama':'Central America',
  // South America
  'Brazil':'South America','Argentina':'South America','Colombia':'South America','Peru':'South America','Venezuela':'South America','Chile':'South America','Ecuador':'South America','Bolivia':'South America','Paraguay':'South America','Uruguay':'South America','Guyana':'South America','Suriname':'South America','French Guiana':'South America',
  // Caribbean
  'Cuba':'Caribbean','Jamaica':'Caribbean','Haiti':'Caribbean','Dominican Republic':'Caribbean','Trinidad and Tobago':'Caribbean','The Bahamas':'Caribbean','Bahamas':'Caribbean','Barbados':'Caribbean','Grenada':'Caribbean','Antigua and Barbuda':'Caribbean','Saint Lucia':'Caribbean','Dominica':'Caribbean','Puerto Rico':'Caribbean',
  // USA → combined sub-regions
  'United States of America':'US_COMBINED','United States':'US_COMBINED',
  // Canada
  'Canada':'Canada',
  // North Africa
  'Morocco':'North Africa','Algeria':'North Africa','Tunisia':'North Africa','Libya':'North Africa','Egypt':'North Africa','Sudan':'North Africa','Mauritania':'North Africa','Western Sahara':'North Africa',
  // West Africa
  'Nigeria':'West Africa','Ghana':'West Africa','Ivory Coast':'West Africa',"Côte d'Ivoire":'West Africa','Senegal':'West Africa','Mali':'West Africa','Burkina Faso':'West Africa','Niger':'West Africa','Guinea':'West Africa','Sierra Leone':'West Africa','Liberia':'West Africa','Togo':'West Africa','Benin':'West Africa','Gambia':'West Africa','The Gambia':'West Africa','Guinea-Bissau':'West Africa','Guinea Bissau':'West Africa','Cape Verde':'West Africa','Cabo Verde':'West Africa',
  // Central Africa
  'Democratic Republic of the Congo':'Central Africa','Dem. Rep. Congo':'Central Africa','Republic of the Congo':'Central Africa','Republic of Congo':'Central Africa','Congo':'Central Africa','Cameroon':'Central Africa','Gabon':'Central Africa','Equatorial Guinea':'Central Africa','Chad':'Central Africa','Central African Republic':'Central Africa',
  // East Africa
  'Kenya':'East Africa','Tanzania':'East Africa','United Republic of Tanzania':'East Africa','Uganda':'East Africa','Ethiopia':'East Africa','Somalia':'East Africa','Somaliland':'East Africa','Rwanda':'East Africa','Burundi':'East Africa','Eritrea':'East Africa','Djibouti':'East Africa','Madagascar':'East Africa','Malawi':'East Africa','Mozambique':'East Africa','Zambia':'East Africa','Zimbabwe':'East Africa','South Sudan':'East Africa',
  // Southern Africa
  'South Africa':'Southern Africa','Namibia':'Southern Africa','Botswana':'Southern Africa','Eswatini':'Southern Africa','Swaziland':'Southern Africa','Lesotho':'Southern Africa','Angola':'Southern Africa',
  // West Asia
  'Turkey':'West Asia','Iraq':'West Asia','Iran':'West Asia','Saudi Arabia':'West Asia','United Arab Emirates':'West Asia','Israel':'West Asia','Jordan':'West Asia','Lebanon':'West Asia','Syria':'West Asia','Yemen':'West Asia','Oman':'West Asia','Kuwait':'West Asia','Qatar':'West Asia','Bahrain':'West Asia','Palestine':'West Asia','Georgia':'West Asia','Armenia':'West Asia','Azerbaijan':'West Asia',
  // Central Asia
  'Kazakhstan':'Central Asia','Uzbekistan':'Central Asia','Turkmenistan':'Central Asia','Kyrgyzstan':'Central Asia','Tajikistan':'Central Asia','Afghanistan':'Central Asia','Mongolia':'Central Asia',
  // South Asia
  'India':'South Asia','Pakistan':'South Asia','Bangladesh':'South Asia','Sri Lanka':'South Asia','Nepal':'South Asia','Bhutan':'South Asia','Maldives':'South Asia',
  // Southeast Asia
  'Indonesia':'Southeast Asia','Thailand':'Southeast Asia','Vietnam':'Southeast Asia','Philippines':'Southeast Asia','Malaysia':'Southeast Asia','Singapore':'Southeast Asia','Myanmar':'Southeast Asia','Cambodia':'Southeast Asia','Laos':'Southeast Asia','Brunei':'Southeast Asia','East Timor':'Southeast Asia','Timor-Leste':'Southeast Asia',
  // Eastern Asia
  'China':'Eastern Asia','Japan':'Eastern Asia','South Korea':'Eastern Asia','Republic of Korea':'Eastern Asia','North Korea':'Eastern Asia','Dem. Rep. Korea':'Eastern Asia','Taiwan':'Eastern Asia','Hong Kong':'Eastern Asia','Macau':'Eastern Asia',
  // Oceania
  'Australia':'Oceania','New Zealand':'Oceania','Papua New Guinea':'Oceania','Fiji':'Oceania','Solomon Islands':'Oceania','Vanuatu':'Oceania','Samoa':'Oceania','New Caledonia':'Oceania',
};

// ISO_A3 fallback
const ISO_TO_REGION = {
  'FRA':'Western Europe','DEU':'Western Europe','NLD':'Western Europe','BEL':'Western Europe','LUX':'Western Europe','AUT':'Western Europe','CHE':'Western Europe',
  'GBR':'Northern Europe','IRL':'Northern Europe','ISL':'Northern Europe','NOR':'Northern Europe','SWE':'Northern Europe','FIN':'Northern Europe','DNK':'Northern Europe','EST':'Northern Europe','LVA':'Northern Europe','LTU':'Northern Europe',
  'ESP':'Southern Europe','PRT':'Southern Europe','ITA':'Southern Europe','GRC':'Southern Europe','HRV':'Southern Europe','SVN':'Southern Europe','ALB':'Southern Europe','MNE':'Southern Europe','MKD':'Southern Europe','BIH':'Southern Europe','SRB':'Southern Europe','CYP':'Southern Europe','XKX':'Southern Europe',
  'POL':'Eastern Europe','CZE':'Eastern Europe','SVK':'Eastern Europe','HUN':'Eastern Europe','ROU':'Eastern Europe','BGR':'Eastern Europe','UKR':'Eastern Europe','BLR':'Eastern Europe','MDA':'Eastern Europe','RUS':'Eastern Europe',
  'MEX':'Central America','GTM':'Central America','BLZ':'Central America','HND':'Central America','SLV':'Central America','NIC':'Central America','CRI':'Central America','PAN':'Central America',
  'BRA':'South America','ARG':'South America','COL':'South America','PER':'South America','VEN':'South America','CHL':'South America','ECU':'South America','BOL':'South America','PRY':'South America','URY':'South America','GUY':'South America','SUR':'South America','GUF':'South America',
  'CUB':'Caribbean','JAM':'Caribbean','HTI':'Caribbean','DOM':'Caribbean','TTO':'Caribbean','BHS':'Caribbean','BRB':'Caribbean','PRI':'Caribbean',
  'USA':'US_COMBINED','CAN':'Canada',
  'MAR':'North Africa','DZA':'North Africa','TUN':'North Africa','LBY':'North Africa','EGY':'North Africa','SDN':'North Africa','MRT':'North Africa','ESH':'North Africa',
  'NGA':'West Africa','GHA':'West Africa','CIV':'West Africa','SEN':'West Africa','MLI':'West Africa','BFA':'West Africa','NER':'West Africa','GIN':'West Africa','SLE':'West Africa','LBR':'West Africa','TGO':'West Africa','BEN':'West Africa','GMB':'West Africa','GNB':'West Africa',
  'COD':'Central Africa','COG':'Central Africa','CMR':'Central Africa','GAB':'Central Africa','GNQ':'Central Africa','TCD':'Central Africa','CAF':'Central Africa',
  'KEN':'East Africa','TZA':'East Africa','UGA':'East Africa','ETH':'East Africa','SOM':'East Africa','RWA':'East Africa','BDI':'East Africa','ERI':'East Africa','DJI':'East Africa','MDG':'East Africa','MWI':'East Africa','MOZ':'East Africa','ZMB':'East Africa','ZWE':'East Africa','SSD':'East Africa',
  'ZAF':'Southern Africa','NAM':'Southern Africa','BWA':'Southern Africa','SWZ':'Southern Africa','LSO':'Southern Africa','AGO':'Southern Africa',
  'TUR':'West Asia','IRQ':'West Asia','IRN':'West Asia','SAU':'West Asia','ARE':'West Asia','ISR':'West Asia','JOR':'West Asia','LBN':'West Asia','SYR':'West Asia','YEM':'West Asia','OMN':'West Asia','KWT':'West Asia','QAT':'West Asia','BHR':'West Asia','GEO':'West Asia','ARM':'West Asia','AZE':'West Asia',
  'KAZ':'Central Asia','UZB':'Central Asia','TKM':'Central Asia','KGZ':'Central Asia','TJK':'Central Asia','AFG':'Central Asia','MNG':'Central Asia',
  'IND':'South Asia','PAK':'South Asia','BGD':'South Asia','LKA':'South Asia','NPL':'South Asia','BTN':'South Asia',
  'IDN':'Southeast Asia','THA':'Southeast Asia','VNM':'Southeast Asia','PHL':'Southeast Asia','MYS':'Southeast Asia','SGP':'Southeast Asia','MMR':'Southeast Asia','KHM':'Southeast Asia','LAO':'Southeast Asia','BRN':'Southeast Asia','TLS':'Southeast Asia',
  'CHN':'Eastern Asia','JPN':'Eastern Asia','KOR':'Eastern Asia','PRK':'Eastern Asia','TWN':'Eastern Asia',
  'AUS':'Oceania','NZL':'Oceania','PNG':'Oceania','FJI':'Oceania','SLB':'Oceania','VUT':'Oceania','NCL':'Oceania',
};

// Resolve a GeoJSON feature → DataCo region name
function resolveRegion(feature) {
  const admin = feature.properties.ADMIN || feature.properties.name || '';
  if (COUNTRY_NAME_TO_REGION[admin]) return COUNTRY_NAME_TO_REGION[admin];
  const iso = feature.properties.ISO_A3;
  if (iso && iso !== '-99' && ISO_TO_REGION[iso]) return ISO_TO_REGION[iso];
  return null;
}

let regionMap = null;
let regionGeoLayer = null;
let layerRegionCache = new Map();

function getRegionColor(pLate) {
  if (pLate == null) return '#d5dbdb';
  if (pLate >= 0.56) return '#c0392b';
  if (pLate >= 0.52) return '#e67e22';
  if (pLate >= 0.48) return '#f1c40f';
  return '#27ae60';
}

// Weighted average of all US sub-regions
function computeUSCombined(regionLookup) {
  const usKeys = Object.keys(regionLookup).filter(k =>
    k.includes('USA') || k.includes('US Center')
  );
  let totalCount = 0, weightedSum = 0;
  usKeys.forEach(k => {
    const rd = regionLookup[k];
    if (rd && rd.count) {
      totalCount += rd.count;
      weightedSum += rd.p_late * rd.count;
    }
  });
  if (totalCount === 0) return null;
  return {
    order_region: 'United States (綜合)',
    p_late: weightedSum / totalCount,
    count: totalCount,
    sub_regions: usKeys.map(k => regionLookup[k]).filter(Boolean)
  };
}

async function loadRegionalRisk() {
  const container = document.getElementById('regionRiskRankList');
  container.innerHTML = '載入中...';

  try {
    const data = await fetchRegions();
    if (!data || data.length === 0) {
      container.innerHTML = '<div style="color:var(--muted); font-size:12px;">無區域延遲數據</div>';
      return;
    }

    const countTag = document.getElementById('regionCountTag');
    if (countTag) countTag.textContent = `${data.length} 個地區`;

    // Build region lookup (both original & trimmed keys)
    const regionLookup = {};
    data.forEach(r => {
      regionLookup[r.order_region] = r;
      regionLookup[r.order_region.trim()] = r;
    });

    // Add US_COMBINED for the map
    const usCombined = computeUSCombined(regionLookup);
    if (usCombined) regionLookup['US_COMBINED'] = usCombined;

    // ── Render ranking list ──
    container.innerHTML = data.map((r, i) => {
      const pct = (r.p_late * 100).toFixed(1);
      const color = getRegionColor(r.p_late);
      const isHigh = r.p_late >= 0.56;
      const isMed = r.p_late >= 0.52;
      const statusClass = isHigh ? 'r-high' : isMed ? 'r-med' : 'r-low';
      const statusText = isHigh ? '高風險' : isMed ? '中風險' : r.p_late >= 0.48 ? '低風險' : '安全';

      return `
        <div class="region-rank-item" data-region="${r.order_region}" style="display:flex; align-items:center; gap:14px; padding:12px 14px; background:var(--card); border:1px solid var(--border); border-radius:8px; cursor:pointer; transition: all 0.2s;" onmouseenter="highlightMapRegion('${r.order_region.replace(/'/g,"\\'")}')" onmouseleave="resetMapHighlight()">
          <div style="font-family:'DM Mono',monospace; font-size:15px; font-weight:700; width:32px; text-align:center; color:${color};">#${i+1}</div>
          <div style="flex:1;">
            <div style="display:flex; justify-content:space-between; margin-bottom:5px; font-size:12.5px; font-weight:500;">
              <span>${r.order_region}</span>
              <span style="font-family:'DM Mono',monospace; font-weight:700; color:${color};">${pct}%</span>
            </div>
            <div style="height:7px; background:var(--bg); border-radius:4px; overflow:hidden; width:100%;">
              <div style="height:100%; width:${pct}%; background:${color}; border-radius:4px; transition:width 0.6s ease;"></div>
            </div>
            <div style="font-size:10px; color:var(--muted); margin-top:4px;">訂單數: ${r.count.toLocaleString()} 筆</div>
          </div>
          <span class="risk-pill ${statusClass}" style="font-size:10px;">${statusText}</span>
        </div>
      `;
    }).join('');

    // ── Render the Leaflet Map ──
    await initRegionMap(regionLookup);

  } catch (e) {
    container.innerHTML = `<div style="color:red; font-size:12px;">載入失敗: ${e.message}</div>`;
  }
}

async function initRegionMap(regionLookup) {
  const mapContainer = document.getElementById('regionMapContainer');
  if (!mapContainer) return;

  if (regionMap) { regionMap.remove(); regionMap = null; }
  layerRegionCache = new Map();

  regionMap = L.map('regionMapContainer', {
    center: [20, 15], zoom: 2.3, minZoom: 2, maxZoom: 6,
    zoomControl: true, scrollWheelZoom: true, worldCopyJump: true,
    maxBounds: [[-85, -200], [85, 200]], maxBoundsViscosity: 1.0
  });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd', maxZoom: 19
  }).addTo(regionMap);

  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', {
    subdomains: 'abcd', maxZoom: 19, pane: 'shadowPane'
  }).addTo(regionMap);

  try {
    const geoRes = await fetch('https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson');
    const geoData = await geoRes.json();

    regionGeoLayer = L.geoJSON(geoData, {
      style: feature => {
        const rn = resolveRegion(feature);
        const rd = rn ? regionLookup[rn] : null;
        return {
          fillColor: getRegionColor(rd ? rd.p_late : null),
          fillOpacity: rd ? 0.65 : 0.2,
          weight: 1, color: '#ffffff', opacity: 0.8
        };
      },
      onEachFeature: (feature, layer) => {
        const countryName = feature.properties.ADMIN || feature.properties.name || feature.properties.ISO_A3;
        const rn = resolveRegion(feature);
        const rd = rn ? regionLookup[rn] : null;

        if (rn) layerRegionCache.set(layer, rn);

        if (rd) {
          const pct = (rd.p_late * 100).toFixed(1);
          const displayRegion = rn === 'US_COMBINED' ? 'United States (East/West/Center/South)' : rd.order_region;
          let subInfo = '';
          if (rn === 'US_COMBINED' && rd.sub_regions) {
            subInfo = rd.sub_regions.map(sr =>
              `<div style="display:flex; justify-content:space-between; font-size:11px; color:#555;"><span>${sr.order_region.trim()}</span><span>${(sr.p_late*100).toFixed(1)}%</span></div>`
            ).join('');
            subInfo = '<div style="margin-top:6px; border-top:1px solid #eee; padding-top:6px;">' + subInfo + '</div>';
          }
          layer.bindTooltip(`
            <div style="font-family:'DM Sans','Noto Sans TC',sans-serif; min-width:200px;">
              <div style="font-weight:700; font-size:13px; margin-bottom:4px;">${countryName}</div>
              <div style="font-size:11px; color:#666; margin-bottom:6px;">📍 ${displayRegion}</div>
              <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:2px;">
                <span>平均延遲率</span>
                <span style="font-weight:700; color:${getRegionColor(rd.p_late)};">${pct}%</span>
              </div>
              <div style="display:flex; justify-content:space-between; font-size:12px;">
                <span>訂單數</span>
                <span style="font-weight:600;">${rd.count.toLocaleString()} 筆</span>
              </div>
              ${subInfo}
            </div>
          `, { sticky: true, className: 'region-tooltip' });
        } else {
          layer.bindTooltip(`
            <div style="font-family:'DM Sans','Noto Sans TC',sans-serif;">
              <div style="font-weight:700; font-size:13px;">${countryName}</div>
              <div style="font-size:11px; color:#999;">無配送資料</div>
            </div>
          `, { sticky: true, className: 'region-tooltip' });
        }

        layer.on('mouseover', function() {
          this.setStyle({ weight: 2.5, color: '#2c3e50', fillOpacity: 0.85 });
          this.bringToFront();
        });
        layer.on('mouseout', function() { regionGeoLayer.resetStyle(this); });
        layer.on('click', function() {
          regionMap.fitBounds(this.getBounds(), { padding: [40, 40], maxZoom: 5 });
        });
      }
    }).addTo(regionMap);

    setTimeout(() => { regionMap.invalidateSize(); }, 200);

  } catch (e) {
    console.error('GeoJSON load failed:', e);
    mapContainer.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted);font-size:13px;">地圖資料載入失敗，請檢查網路連線</div>';
  }
}

function highlightMapRegion(regionName) {
  if (!regionGeoLayer) return;
  const trimmed = regionName.trim();
  regionGeoLayer.eachLayer(layer => {
    const rn = layerRegionCache.get(layer);
    if (!rn) return;
    const isUSSubRegion = ['East of USA', 'West of USA', 'US Center', 'South of  USA', 'South of USA'].some(u => trimmed.includes(u.trim()));
    if (rn.trim() === trimmed || (isUSSubRegion && rn === 'US_COMBINED')) {
      layer.setStyle({ weight: 3, color: '#2c3e50', fillOpacity: 0.9 });
      layer.bringToFront();
    }
  });
}

function resetMapHighlight() {
  if (!regionGeoLayer) return;
  regionGeoLayer.eachLayer(layer => { regionGeoLayer.resetStyle(layer); });
}
