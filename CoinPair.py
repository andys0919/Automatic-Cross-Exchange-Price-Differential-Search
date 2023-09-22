import asyncio
import json
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import font, ttk
import requests
import websocket
import threading

CEXs = ['binance', 'mexc', 'bybit', 'bitget', 'Gate', 'pionex']
DEFAULT_DIGITS = 12
DEFAULT_PRECISION = 4
DEFAULT_QTY_DIGITS = 8
PRECISION = 5
DISPLAY_DELAY = 2


class ProfileQuote:
    def __init__(self, name, tree, event_for_stop):
        self.name = name
        self.tree = tree
        self.event_for_stop = event_for_stop
        self.bids = {exchange: [] for exchange in CEXs}
        self.orderbook = {exchange: {'a': {}, 'b': {}} for exchange in CEXs}
        self.ws = {}
        self.all_bids_ready = {exchange: False for exchange in CEXs}
        self.update_tree_flag = False
        self.update_tree_time = time.time()

    async def initialize_exchange(self, exchange):
        config = {
            'binance': {
                'url': f"wss://fstream.binance.com/ws/{self.name.lower()}@depth5@100ms",
                'on_open_payload': None
            },
            'mexc': {
                'url': "wss://contract.mexc.com/ws",
                'on_open_payload': {"method": "sub.depth.full", "param": {"symbol": self.name.replace("USDT", "_USDT").upper(), "limit": 5}}
            },
            'bybit': {
                'url': "wss://stream.bybit.com/v5/public/linear",
                'on_open_payload': {"op": "subscribe", "args": [f"orderbook.200.{self.name.upper()}"]}
            },
            'bitget': {
                'url': "wss://ws.bitget.com/mix/v1/stream",
                'on_open_payload': {"op": "subscribe", "args": [{"instType": "MC", "channel": "books5", "instId": f"{self.name}"}]}
            },
            'Gate': {
                'url': "wss://fx-ws.gateio.ws/v4/ws/usdt",
                'on_open_payload': {"time": int(time.time()), "event": "subscribe", "channel": "futures.order_book", "payload": [f'{self.name[:-4]}_{self.name[-4:]}'.upper(), '5', '0']}
            },
            'pionex': {
                'url': "wss://stream.pionex.com/stream/v2",
                'on_open_payload': {"action": "subscribe", "channel": "order.book.grouped", "data": [{"exchange": "pionex.v2", "base": f'{self.name[:-4]}.PERP'.upper(), "quote": "USDT", "precisions": [{"limit": 4, "precision": str(1/10**PRECISION)}]}]}
            }
        }
        if exchange in config:
            await self.initialize_websockets(exchange, **config[exchange])

    async def initialize_websockets(self, exchange, url, on_open_payload=None):
        def on_close(ws):
            print(f'{exchange} websocket closed, reconnecting...')
            time.sleep(1)  # Avoid rapid reconnection
            asyncio.run(self.initialize_websockets(
                exchange, url, on_open_payload))

        self.ws[exchange] = websocket.WebSocketApp(
            url,
            on_open=lambda ws: ws.send(json.dumps(
                on_open_payload)) if on_open_payload else None,
            on_message=lambda ws, message: self.on_message(
                exchange, ws, message),
            on_close=on_close  # Add this line to handle websocket close event
        )
        threading.Thread(target=self.ws[exchange].run_forever).start()

        if exchange == 'mexc' or exchange == 'bitget':
            threading.Thread(target=self.send_heartbeat,
                             args=(exchange,), daemon=True).start()

    def send_heartbeat(self, exchange):
        while not self.event_for_stop.is_set():
            time.sleep(10)
            try:
                if exchange == 'mexc':
                    self.ws[exchange].send(json.dumps({"method": "ping"}))
                elif exchange == 'bitget':
                    self.ws[exchange].send("ping")

            except websocket.WebSocketConnectionClosedException:
                asyncio.run(self.initialize_exchange(exchange))

    def update_tree(self):
        if all(self.all_bids_ready.values()) and time.time() - self.update_tree_time >= DISPLAY_DELAY:
            self.update_tree_flag = True
            self.update_tree_time = time.time()

        if self.update_tree_flag:
            bid_prices = {exchange: float(
                self.bids[exchange][0][0]) for exchange in self.bids}
            self.update_tree_flag = False
            self.update_tree_values(bid_prices)

    def update_tree_values(self, bid_prices):
        max_bid = max(bid_prices.values())
        min_bid = min(bid_prices.values())
        base_price = (max_bid + min_bid) / 2
        difference = abs(max_bid - min_bid)
        percentage_difference = abs((difference / base_price) * 100)
        existing_item = next((child for child in self.tree.get_children()
                              if self.tree.item(child, "values")[0] == self.name), None)
        if existing_item:
            self.tree.item(
                existing_item, values=(self.name, *bid_prices.values(), round(percentage_difference, 3)), tags=("white_text", "fontsize"))
        else:
            self.tree.insert(
                "", tk.END, values=(self.name, *bid_prices.values(), round(percentage_difference, 3)), tags=("white_text", "fontsize"))

    def on_message(self, exchange, ws, message):
        data = json.loads(message)
        handlers = {
            'binance': lambda data: data.get("b", []),
            'mexc': lambda data: [[str(item[0]), item[1]] for item in data['data']['bids']] if data.get('channel') == 'push.depth.full' else [],
            'bybit': self.handle_bybit_message,
            'bitget': self.handle_bitget_message,
            'Gate': self.handle_gate_message,
            'pionex': self.handle_pionex_message
        }

        self.bids[exchange] = handlers[exchange](data)
        self.all_bids_ready[exchange] = bool(self.bids[exchange])  # 新增這一行

        self.tree.after(0, self.update_tree)  # 移動到這裡

    def handle_bitget_message(self, data):
        self.update_orderbook('bitget', data['data'][0])
        return [[price, qty] for price, qty in self.orderbook['bitget']['b'].items()]

    def handle_bybit_message(self, data):
        # print("bybit:" + json.dumps(data))
        if data['type'] == 'snapshot':
            self.update_orderbook('bybit', data['data'])
        else:
            self.process_incremental_data('bybit', data['data'])
        return sorted([[price, qty] for price, qty in self.orderbook['bybit']['b'].items()], reverse=True)

    def handle_gate_message(self, data):
        # print("gate:" + json.dumps(data))
        self.update_orderbook('Gate', data['result'])
        return sorted([[price, qty] for price, qty in self.orderbook['Gate']['b'].items()], reverse=True)

    def handle_pionex_message(self, data):
        # print("pionex:" + json.dumps(data))
        self.update_orderbook('pionex', data['data'][0])
        return [[price, qty] for price, qty in self.orderbook['pionex']['b'].items()]

    def update_orderbook(self, exchange, snapshot):
        if exchange == 'pionex':
            self.orderbook[exchange]['a'] = {str(item[0]): float(
                item[1]) for item in snapshot.get('a', [])}
            self.orderbook[exchange]['b'] = {str(item[0]): float(
                item[1]) for item in snapshot.get('d', [])}
        elif exchange == 'Gate':
            self.orderbook[exchange]['a'] = {str(item['p']): float(
                item['s']) for item in snapshot.get('asks', [])}
            self.orderbook[exchange]['b'] = {str(item['p']): float(
                item['s']) for item in snapshot.get('bids', [])}
        else:
            self.orderbook[exchange]['a'] = {str(item[0]): float(
                item[1]) for item in snapshot.get('asks', {})}
            self.orderbook[exchange]['b'] = {str(item[0]): float(
                item[1]) for item in snapshot.get('bids', {})}

    def process_incremental_data(self, exchange, incremental_data):
        for item in incremental_data.get('b', []):
            price, qty = str(item[0]), float(item[1])
            if qty == 0:
                self.orderbook[exchange]['b'].pop(price, None)
            else:
                self.orderbook[exchange]['b'][price] = qty


def get_usdt_future_trading_pairs_binance():
    response = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
    data = json.loads(response.text)
    return [pair['symbol'] for pair in data['symbols'] if pair['quoteAsset'] == 'USDT']


def filter_pairs_by_volume(pairs, min_volume):
    response = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr")
    data = json.loads(response.text)
    return [info['symbol'] for info in data if info['symbol'] in pairs and float(info['quoteVolume']) > min_volume]


def setup_treeview_style():
    style = ttk.Style()
    style.theme_use("default")
    style.configure("Treeview", background="#383838",
                    fieldbackground="#383838")
    style.map('Treeview', background=[('selected', '#4a90d9')])
    style.configure("Treeview", rowheight=25)
    style.configure("Treeview.Heading", background="#555555",
                    foreground="white", font=("Helvetica", 16, "bold"))
    style.map("Treeview", foreground=[("selected", "white")])


def stop_threads(event):
    event.set()


async def main():
    event_for_stop = threading.Event()

    root = tk.Tk()
    root.title("Trading Pairs Price Difference")
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)
    setup_treeview_style()
    customFont = font.Font(family="Helvetica", size=16)
    tree = ttk.Treeview(root, columns=("Pair", "Binance", "MEXC",
                                       "Bybit", "Bitget", "Gate", "Pionex", "Difference (%)"))
    tree.heading("#1", text="Pair")
    tree.heading("#2", text="Binance")
    tree.heading("#3", text="MEXC")
    tree.heading("#4", text="Bybit")
    tree.heading("#5", text="Bitget")
    tree.heading("#6", text="Gate")
    tree.heading("#7", text="Pionex")
    tree.heading("#8", text="Difference (%)")

    tree.tag_configure("fontsize", font=customFont)
    tree.tag_configure("white_text", foreground="white")
    tree.grid(row=0, column=0, sticky='news')

    with ThreadPoolExecutor(max_workers=10) as executor:
        pairs = get_usdt_future_trading_pairs_binance()
        high_volume_pairs = filter_pairs_by_volume(pairs, 100000000)
        print(high_volume_pairs)
        for symbol in high_volume_pairs:
            profile_quote = ProfileQuote(symbol, tree, event_for_stop)
            await asyncio.gather(
                *(profile_quote.initialize_exchange(exchange) for exchange in CEXs))

    root.protocol("WM_DELETE_WINDOW", lambda: (
        root.destroy(), stop_threads(event_for_stop)))
    root.mainloop()

if __name__ == "__main__":
    asyncio.run(main())
