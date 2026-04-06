# Mach Aquila Backtester

Session range breakout strategy backtester for Hyperliquid perps.

## Setup

```bash
git clone https://github.com/0xmondaye/mach-backtest.git
cd mach-backtest
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`.

## CLI

```bash
python -c "
from src.data.cache import get_candles
from src.backtest.engine import run_backtest
from src.utils.config_loader import load_config

config = load_config()
config['backtest']['start_date'] = '2025-01-01'
config['backtest']['end_date'] = '2025-04-01'

data = {}
for asset in ['BTC', 'ETH', 'SOL']:
    data[asset] = get_candles(asset, '4h', '2025-01-01', '2025-04-01', source='binance')

result = run_backtest(config, data)
for asset, m in result.asset_metrics.items():
    print(f'{asset}: {m.total_trades} trades, {m.win_rate:.1f}% win, \${m.total_pnl:.2f} PnL')
"
```

## Bundled Data

Pre-loaded OHLCV data in `data/cache/`:
- BTC/ETH/SOL 4h: Apr 2024 → Apr 2026 (2 years)
- BTC/ETH/SOL 1m: Jan 2026 → Apr 2026 (3 months)
