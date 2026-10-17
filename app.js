import {createClient, escapeHtml as e, hoursLeft, expiryColor} from './core.js';

const $ = id => document.getElementById(id);
const state = {hospitals:[], stock:[], recommendations:[], reservations:[], selectedHospital:null, metrics:null};
let client, timer, generation = 0, map, markers = [], busy = false;
let mockData;
const colorHex = {red:'#c53743',amber:'#c48a1a',green:'#177c51'};
const nameOf = id => state.hospitals.find(item => item.hospitalId === id)?.name || id;
const empty = message => `<p class="empty">${e(message)}</p>`;
const formatTime = value => Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('en-GB',{timeZone:'UTC',dateStyle:'medium',timeStyle:'short'}) + ' UTC' : 'Unavailable';
const number = value => Number.isFinite(value) ? value.toLocaleString('en-US') : '—';
function table(headers, rows) { return `<table><thead><tr>${headers.map(item => `<th scope="col">${e(item)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`; }
function message(text) { $('notice').textContent = text; }

async function loadMock() {
  const names = ['hospitals','stock','recommendations','metrics','events','comparison','emergencySources','travelTimes'];
  const entries = await Promise.all(names.map(async name => {
    const response = await fetch(`mock/${name}.json`);
    if (!response.ok) throw new Error(`Cannot load mock/${name}.json`);
    return [name,await response.json()];
  }));
  return {...Object.fromEntries(entries),reservations:[]};
}

function renderMetrics() {
  const metrics = state.metrics;
  $('simClock').textContent = `Simulation: ${formatTime(metrics.simTime)}`;
  const cards = [['Available units',number(metrics.unitsAvailable)],['Expire within 24h',number(metrics.expiringIn24h)],['Wasted today',number(metrics.wastedToday)],['Shortages today',number(metrics.shortagesToday)],['Transfers today',number(metrics.transfersToday)],['Waste rate',Number.isFinite(metrics.wasteRate) ? `${(metrics.wasteRate*100).toFixed(1)}%` : '—']];
  $('metrics').innerHTML = cards.map(([label,value]) => `<div class="metric"><span>${e(label)}</span><strong>${e(value)}</strong></div>`).join('');
}

function hospitalStatus(hospitalId) {
  const units = state.stock.filter(unit => unit.hospitalId === hospitalId && unit.status === 'available');
  return units.length ? expiryColor(Math.min(...units.map(unit => hoursLeft(unit,state.metrics.simTime)))) : null;
}

function renderHospitals() {
  $('hospitalList').innerHTML = state.hospitals.map(hospital => `<button class="hospitalButton" data-hospital="${e(hospital.hospitalId)}" aria-pressed="${hospital.hospitalId === state.selectedHospital}">${e(hospital.name)}<span class="${hospitalStatus(hospital.hospitalId) || 'muted'}">● ${e(hospital.stockSummary.available)}</span></button>`).join('');
  const previous = $('requestHospital').value;
  $('requestHospital').innerHTML = state.hospitals.map(hospital => `<option value="${e(hospital.hospitalId)}">${e(hospital.name)}</option>`).join('');
  if (state.hospitals.some(hospital => hospital.hospitalId === previous)) $('requestHospital').value = previous;
  if (!window.L) {
    $('map').className = 'fallbackMap';
    $('map').textContent = 'Map tiles and markers require the Leaflet CDN. Use the hospital buttons below to explore all stock.';
    return;
  }
  if (!map) {
    map = L.map('map').setView([53.48,-2.28],10);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',maxZoom:18}).addTo(map);
  }
  markers.forEach(marker => marker.remove());
  markers = state.hospitals.map(hospital => {
    const marker = L.circleMarker([hospital.lat,hospital.lng],{radius:hospital.hospitalId === state.selectedHospital ? 13:10,color:'white',weight:2,fillOpacity:1,fillColor:colorHex[hospitalStatus(hospital.hospitalId)] || '#73868a'}).addTo(map);
    marker.bindTooltip(`${e(hospital.name)} · ${e(hospital.stockSummary.available)} available`);
    marker.on('click',() => selectHospital(hospital.hospitalId));
    return marker;
  });
}

function renderDetail() {
  $('hospitalTitle').textContent = nameOf(state.selectedHospital);
  const units = state.stock.filter(unit => unit.hospitalId === state.selectedHospital).sort((a,b) => Date.parse(a.expiresAt)-Date.parse(b.expiresAt));
  $('hospitalDetail').innerHTML = units.length ? table(['Unit / blood group','Time left','Status'], units.map(unit => {
    const hours = hoursLeft(unit,state.metrics.simTime);
    return `<tr><td>${e(unit.unitId)}<small>${e(unit.bloodGroup)}</small></td><td class="${expiryColor(hours)}">${e(hours.toFixed(1))}h<small>${e(formatTime(unit.expiresAt))}</small></td><td>${e(unit.status)}</td></tr>`;
  })) : empty('No active stock at this hospital.');
}

function selectHospital(hospitalId) {
  state.selectedHospital = hospitalId;
  renderHospitals(); renderDetail();
}

function renderRecommendations() {
  $('recommendations').innerHTML = state.recommendations.length ? table(['Unit','Route','Expiry / journey','Engine score','Action'],state.recommendations.map(item => `<tr><td>${e(item.unitId)}</td><td>${e(nameOf(item.fromHospitalId))} → ${e(nameOf(item.toHospitalId))}<small>${e(item.reason)}</small></td><td>${e(item.hoursToExpiry)}h / ${e(item.travelMinutes)} min</td><td>${e(item.score)}</td><td><button data-reserve="${e(item.unitId)}" ${busy?'disabled':''}>Reserve</button></td></tr>`)) : empty('No transfers recommended for current stock.');
  $('reservations').innerHTML = state.reservations.length ? state.reservations.map(item => `<div class="reservation"><span><strong>${e(item.reservationId)}</strong> · ${e(item.unitId)}<br>${e(nameOf(item.fromHospitalId))} → ${e(nameOf(item.toHospitalId))}<br>${e(item.status)}</span>${item.status === 'accepted' ? `<button data-complete="${e(item.reservationId)}" ${busy?'disabled':''}>Complete handoff</button>`:''}</div>`).join('') : empty('No reservations made in this session. Keep this page open until handoffs are complete.');
}

function renderEvents(events) {
  $('events').innerHTML = events.length ? events.map(event => `<li><strong>${e(event.type)}</strong> · ${e(event.unitId)} · ${e(nameOf(event.hospitalId))}<div>${e(event.detail)}</div><time datetime="${e(event.at)}">${e(formatTime(event.at))}</time></li>`).join('') : '<li>No events yet.</li>';
}

async function refresh(currentGeneration = generation) {
  const results = await Promise.all(['/hospitals','/stock','/recommendations','/metrics','/events?limit=50'].map(path => client(path)));
  if (generation !== currentGeneration) return;
  [state.hospitals,state.stock,state.recommendations,state.metrics] = results;
  if (!state.hospitals.some(hospital => hospital.hospitalId === state.selectedHospital)) state.selectedHospital = state.hospitals[0]?.hospitalId || null;
  renderMetrics(); renderHospitals(); renderDetail(); renderRecommendations(); renderEvents(results[4]);
  $('connectionStatus').textContent = $('mockToggle').checked ? '● Mock session · synthetic data' : '● API connected';
}

async function poll(currentGeneration) {
  try { await refresh(currentGeneration); }
  catch (error) { if (generation === currentGeneration) { $('connectionStatus').textContent = 'Connection failed · retrying'; message(`Refresh failed: ${error.message}. Previously displayed data may be stale.`); } }
  finally { if (generation === currentGeneration) timer = setTimeout(() => poll(currentGeneration),5000); }
}

function chart(title, metric, baseline, exchange) {
  const dates = [...new Set([...baseline.daily,...exchange.daily].map(day => day.date))].sort();
  if (!dates.length) return empty(`No daily ${title.toLowerCase()} data.`);
  const series = [baseline,exchange].map(result => new Map(result.daily.map(day => [day.date,day[metric]])));
  const maximum = Math.max(1,...series.flatMap(items => [...items.values()].filter(Number.isFinite)));
  const x = index => 42 + index / Math.max(1,dates.length-1)*430;
  const y = value => 156 - value/maximum*125;
  return `<div><h3>${e(title)}</h3><svg class="chart" viewBox="0 0 500 220" role="img" aria-label="${e(title)}: gray is no sharing, teal is exchange"><path d="M42 25 V156 H472" fill="none" stroke="#b5c5c7"/><text x="8" y="34">${e(maximum)}</text><text x="23" y="160">0</text>${series.map((items,index) => {
    // Missing days break the line instead of being fabricated as zero.
    const segments = []; let active = false;
    dates.forEach((date,dateIndex) => { const value=items.get(date); if (!Number.isFinite(value)) {active=false;return;} segments.push(`${active?'L':'M'}${x(dateIndex)},${y(value)}`); active=true; });
    return `<path d="${segments.join(' ')}" fill="none" stroke="${index?'#087b72':'#798c92'}" stroke-width="2.5"/>${dates.map((date,dateIndex) => Number.isFinite(items.get(date)) ? `<circle cx="${x(dateIndex)}" cy="${y(items.get(date))}" r="2" fill="${index?'#087b72':'#798c92'}"><title>${e(date)}: ${e(items.get(date))}</title></circle>`:'').join('')}`;
  }).join('')}<text x="42" y="180">${e(dates[0])}</text><text x="472" y="180" text-anchor="end">${e(dates.at(-1))}</text><text x="42" y="206">● No sharing</text><text x="180" y="206" style="fill:#087b72">● Exchange</text></svg></div>`;
}

async function loadComparison(currentGeneration = generation) {
  $('comparison').innerHTML = empty('Loading simulation results…');
  try {
    const result = await client('/simulation/results');
    if (currentGeneration !== generation) return;
    const baseline = result.noSharing, exchange = result.exchange;
    $('comparison').innerHTML = `<p class="muted">Seed ${e(result.seed)} · ${e(baseline.days)} days · Generated ${e(formatTime(result.generatedAt))}</p>` + table(['Metric','No sharing','Exchange'],[
      ['Units delivered',baseline.unitsDelivered,exchange.unitsDelivered],['Units transfused',baseline.unitsTransfused,exchange.unitsTransfused],['Units wasted',baseline.unitsWasted,exchange.unitsWasted],['Waste rate',`${(baseline.wasteRate*100).toFixed(2)}%`,`${(exchange.wasteRate*100).toFixed(2)}%`],['Shortage events',baseline.shortageEvents,exchange.shortageEvents],['Transfers',baseline.transfers,exchange.transfers]
    ].map(row => `<tr>${row.map(cell => `<td>${e(cell)}</td>`).join('')}</tr>`)) + `<div class="chartGrid">${chart('Daily waste','wasted',baseline,exchange)}${chart('Daily shortages','shortages',baseline,exchange)}</div>`;
  } catch (error) { if (currentGeneration === generation) $('comparison').innerHTML = empty(`Simulation results unavailable: ${error.message}`); }
}

async function switchMode() {
  clearTimeout(timer); generation++; busy = false;
  message(''); state.reservations = []; state.selectedHospital = null;
  $('emergencyResults').innerHTML = ''; $('metrics').innerHTML=''; $('hospitalList').innerHTML=''; $('hospitalDetail').innerHTML=''; $('recommendations').innerHTML=''; $('reservations').innerHTML=''; $('events').innerHTML='';
  if (map) {map.remove();map=null;markers=[];}
  $('map').textContent=''; $('map').className='';
  document.querySelector('.network .badge').textContent = $('mockToggle').checked ? 'Synthetic demo' : 'Live API';
  client = createClient({useMock:$('mockToggle').checked,mockData});
  $('connectionStatus').textContent = 'Connecting…';
  void loadComparison(generation);
  await poll(generation);
}

$('hospitalList').addEventListener('click',event => { const button=event.target.closest('[data-hospital]'); if(button) selectHospital(button.dataset.hospital); });
document.addEventListener('click',async event => {
  const button = event.target.closest('[data-reserve],[data-complete]');
  if (!button || busy) return;
  const currentGeneration = generation, request = client;
  busy = true; renderRecommendations(); $('mockToggle').disabled = true;
  try {
    if (button.dataset.reserve) {
      const item = state.recommendations.find(item => item.unitId === button.dataset.reserve);
      const reservation = await request('/reservations',{unitId:item.unitId,toHospitalId:item.toHospitalId});
      state.reservations.push(reservation); message(`Reserved ${reservation.unitId}. Complete the handoff when the unit arrives.`);
    } else {
      const reservation = await request(`/reservations/${encodeURIComponent(button.dataset.complete)}/complete`,{});
      state.reservations = state.reservations.map(item => item.reservationId === reservation.reservationId ? reservation : item);
      message(`Handoff completed for ${reservation.unitId}.`);
    }
  } catch (error) {
    message(error.status === 409 ? 'This unit is no longer available. Stock and recommendations are being refreshed.' : `Action failed: ${error.message}. If the connection was interrupted, the server may have accepted it; verify before retrying.`);
  } finally {
    busy=false; $('mockToggle').disabled=false; renderRecommendations();
    try {await refresh(currentGeneration);} catch(error) {message(`Unable to refresh stock: ${error.message}`);}
  }
});

$('emergencyForm').addEventListener('submit',async event => {
  event.preventDefault(); const currentGeneration=generation;
  const button=event.submitter; button.disabled=true;
  $('emergencyResults').innerHTML=empty('Finding compatible sources…');
  try {
    const unitsNeeded=Number($('requestUnits').value);
    if (!Number.isInteger(unitsNeeded) || unitsNeeded < 1) throw new Error('Enter a positive whole number of units');
    const sources=await client('/emergency',{hospitalId:$('requestHospital').value,bloodGroup:$('requestGroup').value,unitsNeeded});
    if (generation !== currentGeneration) return;
    $('emergencyResults').innerHTML=sources.length ? `<p>${e(sources.length)} source(s) returned for ${e(unitsNeeded)} requested unit(s).</p>`+table(['Rank / unit','Hospital','Group','Travel','Expiry','Penalty'],sources.map(source=>`<tr><td>${e(source.rank)} · ${e(source.unitId)}</td><td>${e(nameOf(source.hospitalId))}</td><td>${e(source.bloodGroup)}</td><td>${e(source.travelMinutes)} min</td><td>${e(source.hoursToExpiry)}h</td><td>${e(source.penalty)}</td></tr>`)) : empty('No compatible sources returned.');
  } catch(error) {if (generation===currentGeneration) $('emergencyResults').innerHTML=empty(`Search failed: ${error.message}`);}
  finally {button.disabled=false;}
});
$('reloadComparison').addEventListener('click',()=>loadComparison());
$('mockToggle').addEventListener('change',switchMode);

try {mockData=await loadMock(); await switchMode();}
catch(error) {message(`Dashboard startup failed: ${error.message}. Serve web/ over HTTP as described in README.md.`);}