fetch('/data/crypto/backtest_detailed.json').then(function(r){return r.json()}).then(function(d){
 window.BT={data:d};
 renderBacktest();
}).catch(function(e){document.getElementById('backtestView').innerHTML='数据加载失败: '+e.message});
fetch('/data/crypto/signals.json').then(function(r){return r.json()}).then(function(d){
 window.BT=window.BT||{};window.BT.signals=d;renderSignals();
}).catch(function(e){document.getElementById('signalsView').innerHTML='信号加载失败'});
