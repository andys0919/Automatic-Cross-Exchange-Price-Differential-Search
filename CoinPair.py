import websocket
import json
import threading
import requests
from concurrent.futures import ThreadPoolExecutor
import time

profile_quote = {}
all_data_received = threading.Event()
profile_quote_lock = threading.Lock()


class ProfileQuote:
    def __init__(self, name):
        self.name = name
        self.bids_binance = []
        self.bids_mexc = []
        self.data_received = threading.Event()

    def on_message_binance(self, ws, message):
        try:
            data = json.loads(message)
            if "b" in data:
                self.bids_binance = data["b"]
                ws.close()
                self.data_received.set()
                check_all_data_received()
        except Exception as e:
            print(f'Error in Binance websocket message: {str(e)}')

    def on_message_mexc(self, ws, message):
        try:
            data = json.loads(message)
            if data.get('channel') == 'push.depth.full':
                self.bids_mexc = [[str(item[0]), item[1]]
                                  for item in data['data']['bids']]
                ws.close()
                self.data_received.set()
                check_all_data_received()
        except Exception as e:
            print(f'Error in MEXC websocket message: {str(e)}')

    def initialize_websockets(self):
        ws_binance = websocket.WebSocketApp(f"wss://fstream.binance.com/ws/{self.name.lower()}@depth5@100ms",
                                            on_message=self.on_message_binance)
        ws_mexc = websocket.WebSocketApp(f"wss://contract.mexc.com/ws",
                                         on_message=self.on_message_mexc)

        ws_mexc.on_open = lambda ws: ws.send(json.dumps({
            "method": "sub.depth.full",
            "param": {
                "symbol": self.name.replace("USDT", "_USDT").upper(),
                "limit": 5
            }
        }))

        threading.Thread(target=ws_binance.run_forever).start()
        threading.Thread(target=ws_mexc.run_forever).start()


def check_all_data_received():
    if all(pq.data_received.is_set() for pq in profile_quote.values()):
        all_data_received.set()


def initialize_single_pair(pair):
    pq = ProfileQuote(pair)
    pq.initialize_websockets()
    with profile_quote_lock:
        profile_quote[pair] = pq


def get_usdt_future_trading_pairs_binance():
    response = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
    data = json.loads(response.text)
    return [pair['symbol'] for pair in data['symbols'] if pair['quoteAsset'] == 'USDT']


def filter_pairs_by_volume(pairs, min_volume):
    response = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr")
    data = json.loads(response.text)
    return [info['symbol'] for info in data if info['symbol'] in pairs and float(info['quoteVolume']) > min_volume]


if __name__ == "__main__":
    pairs = get_usdt_future_trading_pairs_binance()
    high_volume_pairs = filter_pairs_by_volume(pairs, 100000000)
    websocket.enableTrace(False)

    start_time = time.time()

    with ThreadPoolExecutor() as executor:
        executor.map(initialize_single_pair, high_volume_pairs)

    all_data_received.wait()

    for pair, pq in profile_quote.items():
        if pq.bids_binance and pq.bids_mexc:
            bid_price_binance = float(pq.bids_binance[0][0])
            bid_price_mexc = float(pq.bids_mexc[0][0])
            difference = abs(bid_price_binance - bid_price_mexc)
            base_price = (bid_price_binance + bid_price_mexc) / 2
            percentage_difference = abs((difference / base_price) * 100)

            print(
                f'The bid price difference for {pair} between Binance {bid_price_binance} and MEXC {bid_price_mexc} is {difference} = {round(percentage_difference, 3)}%')

    print(f'Finished all trading pairs.')
    end_time = time.time()
    elapsed_time = (end_time - start_time) * 1000  # 轉換成毫秒
    print(f"Total execution time: {elapsed_time:.2f} ms")
