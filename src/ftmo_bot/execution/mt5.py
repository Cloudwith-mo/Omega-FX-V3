"""MT5 broker adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ftmo_bot.execution.broker import BrokerAdapter
from ftmo_bot.execution.models import BrokerOrder, ExecutionOrder, Position, SymbolSpec

try:  # pragma: no cover - optional dependency
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - optional dependency
    mt5 = None


class MT5Broker(BrokerAdapter):
    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        path: str | None = None,
        magic: int = 901003,
        deviation: int = 10,
        filling_mode: str = "fok",
        time_type: str = "gtc",
    ) -> None:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 package is not installed")
        self.login = login
        self.password = password
        self.server = server
        self.magic = magic
        self.deviation = deviation
        self.filling_mode = filling_mode.lower()
        self.time_type = time_type.lower()
        if not mt5.initialize(login=login, password=password, server=server, path=path):
            raise RuntimeError("Failed to initialize MetaTrader5")

        filling_map = {
            "fok": mt5.ORDER_FILLING_FOK,
            "ioc": mt5.ORDER_FILLING_IOC,
            "return": mt5.ORDER_FILLING_RETURN,
        }
        time_map = {
            "gtc": mt5.ORDER_TIME_GTC,
            "day": mt5.ORDER_TIME_DAY,
            "spec": mt5.ORDER_TIME_SPECIFIED,
            "spec_gtd": mt5.ORDER_TIME_SPECIFIED_DAY,
        }
        self._type_filling = filling_map.get(self.filling_mode, mt5.ORDER_FILLING_FOK)
        self._type_time = time_map.get(self.time_type, mt5.ORDER_TIME_GTC)

    @staticmethod
    def _pip_size_from_info(info) -> float:
        point = float(info.point) if getattr(info, "point", 0) else 0.0
        digits = int(info.digits) if getattr(info, "digits", None) is not None else 0
        if point <= 0 and digits > 0:
            point = 10 ** (-digits)
        if digits in (3, 5):
            return point * 10.0
        return point or 0.0001

    def place_order(self, order: ExecutionOrder) -> BrokerOrder:
        symbol_info = mt5.symbol_info(order.symbol)
        if symbol_info is None:
            raise RuntimeError(f"Unknown symbol {order.symbol}")
        if not symbol_info.visible:
            mt5.symbol_select(order.symbol, True)

        tick = mt5.symbol_info_tick(order.symbol)
        if tick is None:
            raise RuntimeError(f"No tick data for {order.symbol}")

        side = order.side.lower()
        if side == "buy":
            order_type = mt5.ORDER_TYPE_BUY
            price = order.price or tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = order.price or tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": order.symbol,
            "volume": float(order.volume),
            "type": order_type,
            "price": float(price),
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": order.client_order_id,
            "type_time": self._type_time,
            "type_filling": self._type_filling,
        }

        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError("MT5 order_send returned None")

        status = "rejected"
        if result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
            status = "filled" if result.retcode == mt5.TRADE_RETCODE_DONE else "partial"
        elif result.retcode == mt5.TRADE_RETCODE_PLACED:
            status = "submitted"

        broker_order_id = str(result.order or result.deal or result.request_id)
        return BrokerOrder(
            broker_order_id=broker_order_id,
            client_order_id=order.client_order_id,
            status=status,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            time=datetime.now().astimezone(),
            price=price,
        )

    def cancel_order(self, broker_order_id: str) -> None:
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": int(broker_order_id),
        }
        result = mt5.order_send(request)
        if result is None or result.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
            raise RuntimeError(f"Failed to cancel order {broker_order_id}")

    def modify_order(self, broker_order_id: str, price: float | None = None) -> None:
        if price is None:
            raise ValueError("price is required for modify_order")
        request = {
            "action": mt5.TRADE_ACTION_MODIFY,
            "order": int(broker_order_id),
            "price": float(price),
        }
        result = mt5.order_send(request)
        if result is None or result.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
            raise RuntimeError(f"Failed to modify order {broker_order_id}")

    def list_open_orders(self) -> Iterable[BrokerOrder]:
        orders = mt5.orders_get() or []
        mapped: list[BrokerOrder] = []
        for order in orders:
            mapped.append(
                BrokerOrder(
                    broker_order_id=str(order.ticket),
                    client_order_id=order.comment or str(order.ticket),
                    status="open",
                    symbol=order.symbol,
                    side="buy" if order.type == mt5.ORDER_TYPE_BUY else "sell",
                    volume=float(order.volume_current),
                    time=datetime.fromtimestamp(order.time_setup).astimezone(),
                    price=float(order.price_open),
                )
            )
        return mapped

    def list_positions(self) -> Iterable[Position]:
        positions = mt5.positions_get() or []
        mapped: list[Position] = []
        for position in positions:
            mapped.append(
                Position(
                    symbol=position.symbol,
                    side="buy" if position.type == mt5.POSITION_TYPE_BUY else "sell",
                    volume=float(position.volume),
                    entry_price=float(position.price_open),
                    unrealized_pnl=float(position.profit),
                )
            )
        return mapped

    def ping(self) -> bool:
        if mt5 is None:
            return False
        return mt5.terminal_info() is not None

    def get_symbol_spec(self, symbol: str) -> SymbolSpec | None:
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        if not info.visible:
            mt5.symbol_select(symbol, True)

        pip_size = self._pip_size_from_info(info)
        tick_size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
        if tick_size <= 0:
            tick_size = float(getattr(info, "point", 0.0) or 0.0)
        tick_value = float(getattr(info, "trade_tick_value", 0.0) or 0.0)
        pip_value = 0.0
        if tick_size > 0 and tick_value > 0 and pip_size > 0:
            pip_value = (tick_value / tick_size) * pip_size

        return SymbolSpec(
            symbol=symbol,
            pip_size=pip_size,
            pip_value_usd_per_lot=pip_value,
            min_lot=float(getattr(info, "volume_min", 0.01) or 0.01),
            lot_step=float(getattr(info, "volume_step", 0.01) or 0.01),
            max_lot=float(getattr(info, "volume_max", 100.0) or 100.0),
            tick_size=tick_size or None,
            tick_value=tick_value or None,
            digits=int(getattr(info, "digits", 0) or 0),
            contract_size=float(getattr(info, "trade_contract_size", 0.0) or 0.0),
        )
