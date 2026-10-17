import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createClient,expiryColor,hoursLeft,escapeHtml,seedSummary} from '../core.js';

async function fixtures() {
  const names=['hospitals','stock','recommendations','metrics','events','comparison','emergencySources','travelTimes'];
  return {...Object.fromEntries(await Promise.all(names.map(async name=>[name,JSON.parse(await readFile(new URL(`../mock/${name}.json`,import.meta.url),'utf8'))]))),reservations:[]};
}

test('one reservation succeeds, duplicate conflicts, completion moves stock',async()=>{
  const source=await fixtures(), request=createClient({useMock:true,mockData:source});
  const body={unitId:'U000001',toHospitalId:'H02'};
  const results=await Promise.allSettled([request('/reservations',body),request('/reservations',body)]);
  assert.equal(results.filter(item=>item.status==='fulfilled').length,1);
  assert.equal(results.find(item=>item.status==='rejected').reason.status,409);
  const reservation=results.find(item=>item.status==='fulfilled').value;
  assert.equal((await request('/recommendations')).some(item=>item.unitId===body.unitId),false);
  const completed=await request(`/reservations/${reservation.reservationId}/complete`,{});
  assert.equal(completed.status,'completed');
  const unit=(await request('/stock?hospitalId=H02')).find(item=>item.unitId===body.unitId);
  assert.equal(unit.status,'available');
  const transfers=(await request('/metrics')).transfersToday;
  await request(`/reservations/${reservation.reservationId}/complete`,{});
  assert.equal((await request('/metrics')).transfersToday,transfers);
  const sources=await request('/emergency',{hospitalId:'H02',bloodGroup:'O-',unitsNeeded:2});
  assert.equal(sources.some(source=>source.unitId===body.unitId),false);
  assert.equal(source.stock[0].hospitalId,'H01');
});

test('emergency excludes own, other blood groups and reserved units; ranks by travel',async()=>{
  const request=createClient({useMock:true,mockData:await fixtures()});
  await request('/reservations',{unitId:'U000001',toHospitalId:'H02'});
  const sources=await request('/emergency',{hospitalId:'H02',bloodGroup:'O-',unitsNeeded:2});
  assert.ok(sources.length>0);
  sources.forEach((source,index)=>{
    assert.notEqual(source.hospitalId,'H02'); assert.notEqual(source.unitId,'U000001');
    assert.equal(source.bloodGroup,'O-'); assert.equal(source.rank,index+1);
    if(index) assert.ok(source.travelMinutes>=sources[index-1].travelMinutes);
  });
});

test('real API sends exact contract paths and bodies; preserves 409 error',async()=>{
  const calls=[];
  const request=createClient({useMock:false,fetchFn:async(path,options)=>{
    calls.push([path,options]); return {ok:false,status:409,json:async()=>({error:'unitNotAvailable'})};
  }});
  await assert.rejects(request('/reservations',{unitId:'U000001',toHospitalId:'H02'}),error=>error.status===409&&error.message==='unitNotAvailable');
  assert.equal(calls[0][0],'/api/reservations');
  assert.equal(calls[0][1].method,'POST');
  assert.deepEqual(JSON.parse(calls[0][1].body),{unitId:'U000001',toHospitalId:'H02'});
});

test('UTC expiry boundaries and escaping API text',()=>{
  assert.equal(hoursLeft({expiresAt:'2026-01-06T12:00:00Z'},'2026-01-05T12:00:00Z'),24);
  assert.equal(expiryColor(23.99),'red'); assert.equal(expiryColor(24),'amber');
  assert.equal(expiryColor(72),'green');
  assert.equal(escapeHtml('<img onerror="bad">'), '&lt;img onerror=&quot;bad&quot;&gt;');
});

test('fixtures respect five-day shelf life and comparison totals',async()=>{
  const data=await fixtures();
  data.stock.forEach(unit=>assert.equal(Date.parse(unit.expiresAt)-Date.parse(unit.collectedAt),5*86400000));
  for(const policy of ['noSharing','exchange']) {
    const result=data.comparison[policy];
    assert.equal(result.daily.length,result.days);
    assert.equal(result.daily.reduce((sum,day)=>sum+day.wasted,0),result.unitsWasted);
    assert.equal(result.daily.reduce((sum,day)=>sum+day.shortages,0),result.shortageEvents);
    assert.equal(result.daily.reduce((sum,day)=>sum+day.transfers,0),result.transfers);
  }
});

test('multi-seed statistics become error-bar rows; single-seed results give none',async()=>{
  const data=await fixtures();
  const summary=seedSummary(data.comparison);
  assert.equal(summary.seedCount,10);
  assert.deepEqual(summary.metrics.map(metric=>metric.label),['Waste rate','Shortage events','Transfers']);
  const waste=summary.metrics[0];
  assert.equal(waste.unit,'%'); assert.ok(Math.abs(waste.exchange.mean-1.6)<1e-9);
  assert.deepEqual(summary.metrics[2].noSharing,{mean:0,stdDev:0,min:0,max:0});
  assert.equal(seedSummary({seed:42,noSharing:{},exchange:{}}),null);
});

test('mock benchmark route returns the results, or 404 before any run',async()=>{
  const benchmark=JSON.parse(await readFile(new URL('../mock/benchmark.json',import.meta.url),'utf8'));
  const withResults=createClient({useMock:true,mockData:{...await fixtures(),benchmark}});
  assert.equal((await withResults('/benchmark/results')).reserveRace.accepted,1);
  const withoutResults=createClient({useMock:true,mockData:await fixtures()});
  await assert.rejects(withoutResults('/benchmark/results'),error=>error.status===404&&error.message==='benchmarkNotFound');
});
