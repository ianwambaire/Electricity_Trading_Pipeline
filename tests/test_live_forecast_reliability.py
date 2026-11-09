"""Offline reliability: controlled synthetic publications, no inference/network."""
import copy
from datetime import datetime, timedelta
import os

import pytest
import shared.forecast_publication as contract
import shared.forecast_availability as availability
from test_forecast_publication import fixture, encoded, storage, source, publisher, ISSUE, NOW
from test_forecast_source_consistency import make_client, write_bundle, signing, admin


def test_verified_late_pipeline_timing_has_no_artificial_13_minute_serving_window(tmp_path):
    # Same timing shape as the verified Nov 7 run: 14:00 issue, 16:47 completion.
    bundle=fixture()
    bundle['execution'].update(started_at=(ISSUE+timedelta(hours=2,minutes=45)).isoformat(),
                               issued_at=(ISSUE+timedelta(hours=2,minutes=47)).isoformat(),
                               completed_at=(ISSUE+timedelta(hours=2,minutes=47,seconds=51)).isoformat())
    bundle['provenance']['weather_acquired_at']=(ISSUE+timedelta(hours=2,minutes=46)).isoformat()
    root=storage(tmp_path);file,digest=source(tmp_path,bundle)
    publisher.publish(root,file,digest,None,lambda:ISSUE+timedelta(hours=2,minutes=48))
    before=(root/'releases'/digest/'bundle.json').read_bytes()
    for age in [3,4,12,23.999]:
        read=availability.read_active(root,ISSUE+timedelta(hours=age))
        assert read['forecasts']==bundle['forecasts']
        assert any(contract.time(row['target_time'])>ISSUE+timedelta(hours=age) for row in read['forecasts'])
    assert (root/'releases'/digest/'bundle.json').read_bytes()==before
    assert (root/'current').readlink().as_posix()=='releases/'+digest
    # Serving policy never admits a late new publication or rollback.
    with pytest.raises(contract.ExpiredPublication):
        publisher.publish(root,file,digest,digest,lambda:ISSUE+timedelta(hours=4))


@pytest.mark.parametrize('age',[24,24.000001,25,48])
def test_no_future_target_means_expired_at_exact_boundary(age):
    raw,digest=encoded(fixture())
    with pytest.raises(contract.ExpiredPublication):availability.validate(raw,digest,ISSUE+timedelta(hours=age))


def test_horizon_is_not_reset_by_completion_or_republication():
    raw,digest=encoded(fixture())
    availability.validate(raw,digest,ISSUE+timedelta(hours=24,microseconds=-1))
    with pytest.raises(contract.ExpiredPublication):availability.validate(raw,digest,ISSUE+timedelta(hours=24))
    with pytest.raises(contract.ExpiredPublication):contract.validate(raw,digest,ISSUE+timedelta(hours=3,microseconds=1))


def test_serving_never_rescues_stale_inference_or_future_execution():
    bundle=fixture();bundle['execution']['completed_at']=(ISSUE+timedelta(hours=3,seconds=1)).isoformat()
    raw,digest=encoded(bundle)
    with pytest.raises(contract.Withheld):availability.validate(raw,digest,ISSUE+timedelta(hours=4))
    raw,digest=encoded(fixture())
    with pytest.raises(contract.Withheld):availability.validate(raw,digest,ISSUE+timedelta(minutes=30))


@pytest.mark.parametrize('kind',['hash','feature','history','quarter','model','provenance','target'])
def test_all_integrity_guards_still_precede_horizon_expiry(kind):
    b=copy.deepcopy(fixture())
    if kind=='feature':b['inputs']['features']['hour']+=1
    if kind=='history':b['inputs']['load_history'].pop(next(iter(b['inputs']['load_history'])))
    if kind=='quarter':b['inputs']['generation_quarters'].pop()
    if kind=='model':b['model']['model_sha256']='0'*64
    if kind=='provenance':b['provenance']['weather_source']='synthetic'
    if kind=='target':b['forecasts'][-1]['target_time']=(ISSUE+timedelta(hours=25)).isoformat()
    raw,digest=encoded(b)
    if kind=='hash':digest='0'*64
    for age in [4,25]:
        with pytest.raises(contract.Withheld) as error:availability.validate(raw,digest,ISSUE+timedelta(hours=age))
        assert not isinstance(error.value,contract.ExpiredPublication)


def test_api_operations_and_admin_provenance_share_remaining_horizon(tmp_path,monkeypatch,signing):
    c,settings,root,clock,_=make_client(tmp_path,monkeypatch,signing)
    write_bundle(root,fixture());clock[0]=ISSUE+timedelta(hours=4)
    with c:
        result=c.get('/forecast/next24');assert result.status_code==200
        assert result.headers['cache-control']=='no-store'
        p=result.json()['publication']
        assert p['availability_policy']=='ISSUE_HORIZON_V1'
        assert contract.time(p['refresh_due_at'])==ISSUE+timedelta(hours=3)
        assert contract.time(p['expires_at'])==ISSUE+timedelta(hours=24)
        assert len(result.json()['forecasts'])==24
        summary=c.get('/operations/summary').json()
        assert summary['forecast_status']=='VALID'
        assert contract.time(summary['forecast_expires_at'])==contract.time(p['expires_at'])
        assert contract.time(summary['forecast_refresh_due_at'])==contract.time(p['refresh_due_at'])
        assert 'not a newly issued next 24 hours' in summary['forecast_reason']
        assert c.get('/admin/forecast/provenance',headers=admin(signing),params={'issue_time':p['issue_time'],'completed_at':p['completed_at']}).status_code==200
        clock[0]=ISSUE+timedelta(hours=24)
        assert c.get('/forecast/next24').status_code==503
        assert c.get('/operations/summary').json()['forecast_status']=='EXPIRED'


@pytest.mark.parametrize('kind',['missing','tampered','unsafe','dangling'])
def test_available_reader_never_substitutes_a_historical_release(tmp_path,kind):
    root=storage(tmp_path);file,digest=source(tmp_path,fixture())
    publisher.publish(root,file,digest,None,lambda:NOW)
    if kind=='missing':(root/'current').unlink()
    if kind=='tampered':(root/'releases'/digest/'bundle.json').write_bytes(b'{}')
    if kind=='unsafe':(root/'releases'/digest/'bundle.json').chmod(0o666)
    if kind=='dangling':(root/'current').unlink();(root/'current').symlink_to('releases/'+'0'*64)
    with pytest.raises(contract.Withheld):availability.read_active(root,ISSUE+timedelta(hours=4))


def test_expiry_is_rechecked_after_validation_at_actual_utc(monkeypatch):
    times=iter([ISSUE+timedelta(hours=24,microseconds=-1),ISSUE+timedelta(hours=24)])
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return next(times)
    monkeypatch.setattr(availability.dt,'datetime',Clock)
    raw,digest=encoded(fixture())
    with pytest.raises(contract.ExpiredPublication):availability.validate(raw,digest)


def test_pointer_change_during_read_never_mixes_two_bundles(tmp_path,monkeypatch):
    root=storage(tmp_path);one,first=source(tmp_path,fixture())
    publisher.publish(root,one,first,None,lambda:NOW)
    second_bundle=fixture(ISSUE+timedelta(hours=1));two,second=source(tmp_path,second_bundle)
    publisher.publish(root,two,second,first,lambda:NOW+timedelta(hours=1))
    (root/'current').unlink();(root/'current').symlink_to('releases/'+first)
    original=os.readlink;seen=[]
    def switch(path):
        target=original(path);seen.append(target)
        (root/'current').unlink();(root/'current').symlink_to('releases/'+second)
        return target
    monkeypatch.setattr(availability.os,'readlink',switch)
    result=availability.read_active(root,ISSUE+timedelta(hours=4))
    assert seen==['releases/'+first]
    assert result==fixture()
