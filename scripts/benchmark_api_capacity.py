#!/usr/bin/env python3
"""Local-only read benchmark. Never accepts a URL, invokes jobs or writes source data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import resource
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from api.market_data import MarketStore, market_chart, MarketChart, _chart_point
from api.feature_parity import market_exploration, forecast_context
from api.app import APISettings, _one_hour_report


def load_baseline(path, name):
    spec = importlib.util.spec_from_file_location('api.'+name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def median_call(call, runs):
    timings = []
    result = None
    for _ in range(runs):
        started = time.perf_counter(); result = call()
        timings.append(time.perf_counter()-started)
    return result, statistics.median(timings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True, help='Local snapshot directory; never a production URL')
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--baseline-market', type=Path)
    parser.add_argument('--baseline-exploration', type=Path)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10: parser.error('runs must be between 1 and 10')
    settings = APISettings.from_root(args.data_root.resolve())
    path = settings.market_silver
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    started = time.perf_counter(); store = MarketStore(path); coverage = store.coverage()
    cold = time.perf_counter()-started
    out = {'environment':{'os':platform.system(),'architecture':platform.machine(),'python':platform.python_version()},
           'local_only':True,'rows':coverage.row_count,'cold_index_seconds':cold,'runs':args.runs,'timings_seconds':{}}
    try:
        chart, elapsed = median_call(lambda: market_chart(store), args.runs)
        out['timings_seconds']['chart']=elapsed
        out['chart_points']=chart.row_count
        exploration, elapsed = median_call(lambda: market_exploration(store,None,None,1000),args.runs)
        out['timings_seconds']['exploration']=elapsed
        out['weather_points']=len(exploration.weather)
        _, elapsed = median_call(lambda: forecast_context(store,coverage.latest_observation),args.runs)
        out['timings_seconds']['forecast_context']=elapsed
        for key, file, function, expected in [
            ('chart',args.baseline_market,'market_chart',chart),
            ('exploration',args.baseline_exploration,'market_exploration',exploration),
        ]:
            if file:
                baseline=load_baseline(file,'_capacity_baseline_'+key)
                if key == 'chart':
                    # Use current contract classes so baseline accepts this store's coverage.
                    baseline.MarketChart = MarketChart
                    baseline._chart_point = _chart_point
                call=(lambda:baseline.market_chart(store)) if key=='chart' else (lambda:baseline.market_exploration(store,None,None,1000))
                result, elapsed=median_call(call,args.runs)
                assert result.model_dump()==expected.model_dump(), 'Baseline result mismatch'
                out['timings_seconds']['baseline_'+key]=elapsed
                out[key+'_source_parity']=True
                queries=[]
                store._connection.set_trace_callback(lambda _: queries.append(1))
                try:
                    call(); out['baseline_'+key+'_sql_statements']=len(queries)
                    queries.clear()
                    if key=='chart': market_chart(store)
                    else: market_exploration(store,None,None,1000)
                    out[key+'_sql_statements']=len(queries)
                finally:
                    store._connection.set_trace_callback(None)
        if settings.one_hour_forecast.is_file():
            report, elapsed=median_call(lambda:_one_hour_report(settings.one_hour_forecast),args.runs)
            out['one_hour_rows']=report.row_count
            out['one_hour_json_bytes']=len(report.model_dump_json().encode())
            out['timings_seconds']['one_hour_parse']=elapsed
        started=time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda i: market_chart(store) if i%2 else market_exploration(store,None,None,1000), range(8)))
        out['eight_reads_four_threads_wall_seconds']=time.perf_counter()-started
        out['concurrent_results']=len(results)
        usage=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        out['process_peak_rss_mib']=usage/(1024*1024 if platform.system()=='Darwin' else 1024)
        out['peak_scope']='Entire process high-water RSS including Python, pandas, baseline modules, index and retained results; not incremental API memory or EC2 capacity'
        assert hashlib.sha256(path.read_bytes()).hexdigest()==before
        out['source_unchanged']=True
        print(json.dumps(out,indent=2))
    finally:
        store.close()


if __name__=='__main__': main()
