import json
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import font, ttk

import requests
import websocket


class ProfileQuote:
    def __init__(self, name, tree):
        self.name = name
        self.tree = tree
        self.bids = {'binance': [], 'mexc': [], 'bybit': [], 'bitget': []}
        self.orderbook = {'bybit': {'a': {}, 'b': {}},
                          'bitget': {'a': {}, 'b': {}}}
        self.ws = {}

    def initialize_exchange(self, exchange):
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
            }
        }
        if exchange in config:
            self.initialize_websockets(exchange, **config[exchange])

    def initialize_websockets(self, exchange, url, on_open_payload=None):
        self.ws[exchange] = websocket.WebSocketApp(
            url, on_message=lambda ws, message: self.on_message(exchange, ws, message))
        if on_open_payload:
            self.ws[exchange].on_open = lambda ws: ws.send(
                json.dumps(on_open_payload))
        threading.Thread(target=self.ws[exchange].run_forever).start()
        if exchange == 'mexc':
            threading.Thread(target=self.send_heartbeat,
                             args=(exchange,), daemon=True).start()

    def send_heartbeat(self, exchange):
        while True:
            time.sleep(10)
            try:
                self.ws[exchange].send(json.dumps({"method": "ping"}))
            except websocket.WebSocketConnectionClosedException:
                self.initialize_exchange(exchange)

    def update_tree(self):
        bid_prices = {exchange: float(
            self.bids[exchange][0][0]) if self.bids[exchange] else None for exchange in self.bids}
        if all(bid_prices.values()):
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
            'bitget': self.handle_bitget_message
        }

        self.bids[exchange] = handlers[exchange](data)

        self.tree.after(0, self.update_tree)

    def handle_bitget_message(self, data):
        self.update_orderbook('bitget', data['data'][0])
        return [[price, qty] for price, qty in self.orderbook['bitget']['b'].items()]

    def handle_bybit_message(self, data):
        if data['type'] == 'snapshot':
            self.update_orderbook('bybit', data['data'])
        else:
            self.process_incremental_data('bybit', data['data'])
        return sorted([[price, qty] for price, qty in self.orderbook['bybit']['b'].items()], reverse=True)

    def update_orderbook(self, exchange, snapshot):
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


def get_filtered_pairs(min_volume):
    response = requests.get(
        "https://fapi.binance.com/fapi/v1/ticker/24hr")
    return [info['symbol'] for info in response.json() if float(info['quoteVolume']) > min_volume]


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


def main():
    root = tk.Tk()
    root.title("Trading Pairs Price Difference")
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)

    setup_treeview_style()
    customFont = font.Font(family="Helvetica", size=16)
    tree = ttk.Treeview(root, columns=("Pair", "Binance",
                                       "MEXC", "Bybit", "Bitget", "Difference (%)"))
    tree.heading("#1", text="Pair")
    tree.heading("#2", text="Binance")
    tree.heading("#3", text="MEXC")
    tree.heading("#4", text="Bybit")
    tree.heading("#5", text="Bitget")
    tree.heading("#6", text="Difference (%)")

    tree.tag_configure("fontsize", font=customFont)
    tree.tag_configure("white_text", foreground="white")
    tree.grid(row=0, column=0, sticky='news')

    with ThreadPoolExecutor(max_workers=10) as executor:
        filtered_pairs = get_filtered_pairs(min_volume=100000000)
        for symbol in filtered_pairs:
            profile_quote = ProfileQuote(symbol, tree)
            executor.map(profile_quote.initialize_exchange, [
                         "binance", "mexc", "bybit", "bitget"])

    root.mainloop()


if __name__ == "__main__":
    main()
