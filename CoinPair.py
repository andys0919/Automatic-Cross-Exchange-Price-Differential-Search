import websocket
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk, font
import requests
import time  # 載入time模組，用於實現心跳功能


class ProfileQuote:
    def __init__(self, name, tree):
        self.name = name
        self.bids_binance = []
        self.bids_mexc = []
        self.data_received = threading.Event()
        self.tree = tree

    def reconnect_websocket(self, ws, url, on_message):
        ws = websocket.WebSocketApp(url, on_message=on_message)
        threading.Thread(target=ws.run_forever).start()
        return ws

    def send_heartbeat(self, ws):
        while True:
            try:
                time.sleep(10)  # 每10秒發送一次心跳
                heartbeat_message = {"method": "ping"}
                ws.send(json.dumps(heartbeat_message))
            except websocket.WebSocketConnectionClosedException:
                print("Connection closed, attempting to reconnect...")
                ws = self.reconnect_websocket(ws, ws.url, self.on_message_mexc)

    def update_tree_item(self):
        bid_price_binance = self.bids_binance and float(
            self.bids_binance[0][0]) or None
        bid_price_mexc = self.bids_mexc and float(self.bids_mexc[0][0]) or None

        if bid_price_binance and bid_price_mexc:
            self.update_tree(bid_price_binance, bid_price_mexc)

    def update_tree(self, bid_price_binance, bid_price_mexc):
        difference = abs(bid_price_binance - bid_price_mexc)
        base_price = (bid_price_binance + bid_price_mexc) / 2
        percentage_difference = abs((difference / base_price) * 100)

        existing_item = next((child for child in self.tree.get_children(
        ) if self.tree.item(child, "values")[0] == self.name), None)

        if existing_item:
            self.tree.item(existing_item, values=(self.name, bid_price_binance,
                           bid_price_mexc, difference, round(percentage_difference, 3)), tags=("white_text", "fontsize"))
        else:
            self.tree.insert("", tk.END, values=(self.name, bid_price_binance, bid_price_mexc,
                             difference, round(percentage_difference, 3)), tags=("white_text", "fontsize"))

    def initialize_websockets(self):
        ws_binance = websocket.WebSocketApp(
            f"wss://fstream.binance.com/ws/{self.name.lower()}@depth5@100ms", on_message=self.on_message_binance)
        ws_mexc = websocket.WebSocketApp(
            f"wss://contract.mexc.com/ws", on_message=self.on_message_mexc)

        ws_mexc.on_open = lambda ws: ws.send(json.dumps({"method": "sub.depth.full", "param": {
                                             "symbol": self.name.replace("USDT", "_USDT").upper(), "limit": 5}}))

        threading.Thread(target=ws_binance.run_forever).start()
        threading.Thread(target=ws_mexc.run_forever).start()

        # 新增心跳線程
        heartbeat_thread = threading.Thread(
            target=self.send_heartbeat, args=(ws_mexc,))
        heartbeat_thread.daemon = True  # 設為守護線程，這樣主程序結束時線程也會終止
        heartbeat_thread.start()

    def on_message_binance(self, ws, message):
        data = json.loads(message)
        if "b" in data:
            self.bids_binance = data["b"]
            self.data_received.set()
            self.tree.after(0, self.update_tree_item)

    def on_message_mexc(self, ws, message):
        data = json.loads(message)
        if data.get('channel') == 'push.depth.full':
            self.bids_mexc = [[str(item[0]), item[1]]
                              for item in data['data']['bids']]
            self.data_received.set()
            self.tree.after(0, self.update_tree_item)


def initialize_single_pair(pair, tree):
    pq = ProfileQuote(pair, tree)
    pq.initialize_websockets()
    return pq


def get_usdt_future_trading_pairs_binance():
    response = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
    return [pair['symbol'] for pair in response.json()['symbols'] if pair['quoteAsset'] == 'USDT']


def filter_pairs_by_volume(pairs, min_volume):
    response = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr")
    return [info['symbol'] for info in response.json() if info['symbol'] in pairs and float(info['quoteVolume']) > min_volume]


def main():
    root = tk.Tk()
    root.title("Trading Pairs Price Difference")

    style = ttk.Style()
    style.theme_use("default")
    style.configure("Treeview", background="#383838",
                    fieldbackground="#383838")  # 設定背景色
    style.map('Treeview', background=[('selected', '#4a90d9')])  # 設定選中行的背景色
    style.configure("Treeview", rowheight=25)  # 設定行高
    style.configure("Treeview.Heading", background="#555555",
                    foreground="white", font=("Helvetica", 16, "bold"))  # 設定表頭
    style.map("Treeview", foreground=[("selected", "white")])  # 設定選中行字體顏色

    customFont = font.Font(family="Helvetica", size=16)

    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)
    tree = ttk.Treeview(root, columns=("Pair", "Binance",
                        "MEXC", "Difference", "Difference (%)"))
    tree.heading("#1", text="Pair")
    tree.heading("#2", text="Binance")
    tree.heading("#3", text="MEXC")
    tree.heading("#4", text="Difference")
    tree.heading("#5", text="Difference (%)")

    tree.tag_configure("fontsize", font=customFont)
    tree.tag_configure("white_text", foreground="white")  # 正確的用法

    tree.grid(row=0, column=0, sticky="nsew")

    pairs = get_usdt_future_trading_pairs_binance()
    high_volume_pairs = filter_pairs_by_volume(pairs, 100000000)

    profile_quotes = {}

    with ThreadPoolExecutor() as executor:
        profile_quotes = {pair: pq for pair, pq in zip(high_volume_pairs, executor.map(
            lambda pair: initialize_single_pair(pair, tree), high_volume_pairs))}

    root.mainloop()


if __name__ == "__main__":
    main()
