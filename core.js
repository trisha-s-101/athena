export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}

export function hoursLeft(unit, now) {
  return (Date.parse(unit.expiresAt) - Date.parse(now)) / 3600000;
}

export function expiryColor(hours) {
  return hours < 24 ? 'red' : hours < 72 ? 'amber' : 'green';
}

export class ApiError extends Error {
  constructor(status, code) { super(code); this.status = status; }
}

export function createClient({useMock, mockData, fetchFn = fetch}) {
  // Each mock session owns its state; writes never alter fixture files.
  const data = useMock ? structuredClone(mockData) : null;
  let reservationCount = 0;
  let eventCount = 100;
  function addEvent(type, unit, detail) {
    data.events.unshift({eventId:`E${String(++eventCount).padStart(6,'0')}`, type,
      unitId:unit.unitId, hospitalId:unit.hospitalId, at:data.metrics.simTime, detail});
  }
  return async function request(path, body) {
    if (!useMock) {
      const response = await fetchFn(`/api${path}`, {method:body === undefined ? 'GET':'POST',
        headers:body === undefined ? {} : {'Content-Type':'application/json'},
        body:body === undefined ? undefined : JSON.stringify(body), signal:AbortSignal.timeout(10000), cache:'no-store'});
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new ApiError(response.status, payload?.error || `http${response.status}`);
      if (payload === null) throw new Error('Invalid JSON response');
      return payload;
    }
    const [route, query] = path.split('?');
    let result;
    if (route === '/hospitals') result = data.hospitals.map(hospital => {
      const units = data.stock.filter(unit => unit.hospitalId === hospital.hospitalId && unit.status === 'available');
      return {...hospital, stockSummary:{available:units.length, expiringIn24h:units.filter(unit => hoursLeft(unit,data.metrics.simTime) < 24).length}};
    });
    else if (route === '/stock') result = data.stock.filter(unit => !['expired','transfused'].includes(unit.status) && (!new URLSearchParams(query).get('hospitalId') || unit.hospitalId === new URLSearchParams(query).get('hospitalId')));
    else if (route === '/metrics') {
      const units = data.stock.filter(unit => unit.status === 'available');
      result = {...data.metrics, unitsAvailable:units.length, expiringIn24h:units.filter(unit => hoursLeft(unit,data.metrics.simTime) < 24).length};
    }
    else if (route === '/events') result = data.events.slice(0,Number(new URLSearchParams(query).get('limit') || 50));
    else if (route === '/recommendations') result = data.recommendations.filter(item => data.stock.some(unit => unit.unitId === item.unitId && unit.status === 'available' && unit.hospitalId === item.fromHospitalId));
    else if (route === '/simulation/results') result = data.comparison;
    else if (route === '/reservations' && body) {
      const unit = data.stock.find(unit => unit.unitId === body.unitId);
      if (!unit || unit.status !== 'available') throw new ApiError(409,'unitNotAvailable');
      unit.status = 'reserved';
      result = {reservationId:`R${String(++reservationCount).padStart(6,'0')}`, unitId:unit.unitId, fromHospitalId:unit.hospitalId, toHospitalId:body.toHospitalId, status:'accepted', createdAt:data.metrics.simTime};
      data.reservations.push(result);
      addEvent('reservation',unit,'Mock reservation accepted');
    }
    else if (/^\/reservations\/[^/]+\/complete$/.test(route) && body) {
      const reservation = data.reservations.find(item => item.reservationId === route.split('/')[2]);
      if (!reservation) throw new ApiError(404,'reservationNotFound');
      if (reservation.status !== 'completed') {
        const unit = data.stock.find(item => item.unitId === reservation.unitId);
        unit.hospitalId = reservation.toHospitalId; unit.status = 'available'; reservation.status = 'completed';
        data.metrics.transfersToday++;
        addEvent('transfer',unit,'Mock transfer completed');
      }
      result = reservation;
    }
    else if (route === '/emergency' && body) {
      // Exact-match only: no clinical compatibility matrix is invented by the UI.
      result = data.emergencySources.map(source => {
        const unit = data.stock.find(unit => unit.unitId === source.unitId);
        return unit?.status === 'available' ? {...source,hospitalId:unit.hospitalId,hoursToExpiry:hoursLeft(unit,data.metrics.simTime)} : null;
      }).filter(source => source && source.hoursToExpiry > 0 && source.bloodGroup === body.bloodGroup && source.hospitalId !== body.hospitalId)
        .map(source => ({...source,travelMinutes:data.travelTimes.find(trip => trip.fromHospitalId === source.hospitalId && trip.toHospitalId === body.hospitalId)?.minutes}))
        .filter(source => Number.isFinite(source.travelMinutes)).sort((a,b) => a.travelMinutes-b.travelMinutes).map((source,index) => ({...source,rank:index+1}));
    }
    else throw new ApiError(404,'mockRouteNotFound');
    return structuredClone(result);
  };
}