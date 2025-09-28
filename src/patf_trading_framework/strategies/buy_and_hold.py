"""Buy and hold benchmark strategy for baseline comparisons."""

import backtrader as bt


class BuyAndHoldStrategy(bt.Strategy):
    """Simple buy-and-hold strategy that fully allocates capital on first bar."""

    params = (
        ("size_pct", 1.0),
    )

    def next(self):
        if not self.position:
            cash = self.broker.getcash()
            price = self.data.close[0]
            if price <= 0:
                return
            target_cash = cash * self.p.size_pct
            size = int(target_cash / price)
            if size > 0:
                self.buy(size=size)
