import websocket
import json
import time
import threading
import requests

profile_quote = {}


class ProfileQuote:

    def __init__(self, name):
        self.name = name
        self.bids_binance = []
        self.bids_mexc = []
        self.quote_records = []

    def on_message_binance(self, ws, message):
        try:
            data = json.loads(message)
            if "b" in data:
                self.bids_binance = data["b"]
                self.quote_records.append(
                    (self.name, "binance", self.bids_binance))
                self.bids_binance = []
                ws.close()
        except Exception as e:
            print(f'Error in binance websocket message: {str(e)}')

    def on_message_mexc(self, ws, message):
        try:
            data = json.loads(message)
            if data.get('channel') == 'push.depth.full':
                self.bids_mexc = [[str(item[0]), item[1]]
                                  for item in data['data']['bids']]
                self.quote_records.append(
                    (self.name, "mexc", self.bids_mexc))
                self.bids_mexc = []
                ws.close()
        except Exception as e:
            print(f'Error in mexc websocket message: {str(e)}')

    def on_open_binance(self, ws):
        params = {"method": "SUBSCRIBE",
                  "params": [f"{self.name.lower()}@depth5@100ms"],
                  "id": 1}
        ws.send(json.dumps(params))
        # print("Binance WebSocket connected")

    def on_open_mexc(self, ws):
        formatted_symbol = self.name.replace("USDT", "_USDT").upper()
        data_to_send = {"method": "sub.depth.full", "param": {
            "symbol": formatted_symbol, "limit": 5}}
        ws.send(json.dumps(data_to_send))
        # print("MEXC WebSocket connected")

    def initialize_websockets(self):
        ws_binance = websocket.WebSocketApp(f"wss://fstream.binance.com/ws",
                                            on_message=self.on_message_binance)
        ws_mexc = websocket.WebSocketApp(f"wss://contract.mexc.com/ws",
                                         on_message=self.on_message_mexc)
        ws_binance.on_open = self.on_open_binance
        ws_mexc.on_open = self.on_open_mexc
        threading.Thread(target=ws_binance.run_forever).start()
        threading.Thread(target=ws_mexc.run_forever).start()


def get_usdt_future_trading_pairs_binance():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    response = requests.get(url)
    data = json.loads(response.text)
    pairs = [pair['symbol']
             for pair in data['symbols'] if pair['quoteAsset'] == 'USDT']
    return pairs


def filter_pairs_by_volume(pairs, min_volume):
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    response = requests.get(url)
    data = json.loads(response.text)
    volume_pairs = [(info['symbol'], float(info['quoteVolume']))
                    for info in data if info['symbol'] in pairs and float(info['quoteVolume']) > min_volume]
    # Sort pairs by volume in descending order
    volume_pairs.sort(key=lambda x: x[1], reverse=True)
    return volume_pairs


if __name__ == "__main__":
    quote_records = []  # Initialize an empty list to store the quote records
    pairs = get_usdt_future_trading_pairs_binance()
    # Filter pairs with 24hr volume more than 100 million USDT
    high_volume_pairs = filter_pairs_by_volume(pairs, 100000000)
    trading_pairs = [pair[0]
                     for pair in high_volume_pairs]  # Update trading_pairs
    print(trading_pairs)
    websocket.enableTrace(False)
    for pair in trading_pairs:
        pq = ProfileQuote(pair)
        pq.initialize_websockets()
        profile_quote[pair] = pq

    time.sleep(10)  # Make sure finish all pairs

    for pair, pq in profile_quote.items():
        binance_bids = None
        mexc_bids = None

        for record in pq.quote_records:
            if record[1] == "binance":
                binance_bids = record[2]
            if record[1] == "mexc":
                mexc_bids = record[2]

        if binance_bids and mexc_bids:
            bid_price_binance = float(binance_bids[0][0])
            bid_price_mexc = float(mexc_bids[0][0])

            difference = abs(bid_price_binance - bid_price_mexc)
            base_price = (bid_price_binance + bid_price_mexc) / 2
            percentage_difference = abs((difference / base_price) * 100)

            print(
                f'The bid price difference for {pair} between Binance {bid_price_binance} and MEXC {bid_price_mexc} is {difference} = {round(percentage_difference,3)}%')

    print(f'Finished all trading pairs.')
