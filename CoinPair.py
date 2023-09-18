import websocket
import json
import time
import threading

bids_binance = []
bids_mexc = []
current_pair_index = 0
trading_pairs = ["BTCUSDT", "ETHUSDT", "TRBUSDT"]


def on_message_binance(ws, message):
    global bids_binance
    try:
        data = json.loads(message)
        if "b" in data:
            bids_binance = data["b"]
            display_bid_difference(ws)
    except Exception as e:
        print(f'Error in binance websocket message: {str(e)}')


def on_message_mexc(ws, message):
    global bids_mexc
    try:
        data = json.loads(message)
        if data.get('channel') == 'push.depth.full':
            bids_mexc = [[str(item[0]), item[1]]
                         for item in data['data']['bids']]
            display_bid_difference(ws)
    except Exception as e:
        print(f'Error in mexc websocket message: {str(e)}')


def display_bid_difference(ws):
    global current_pair_index, bids_binance, bids_mexc
    try:
        if bids_binance and bids_mexc:
            bid_price_binance = float(bids_binance[0][0])
            bid_price_mexc = float(bids_mexc[0][0])
            difference = bid_price_binance - bid_price_mexc
            print(
                f"The bid price difference for {trading_pairs[current_pair_index]} between Binance {bid_price_binance} and MEXC {bid_price_mexc} is {difference}")
            bids_binance = []
            bids_mexc = []
            ws.close()
            current_pair_index += 1
            if current_pair_index < len(trading_pairs):
                initialize_websockets()
            else:
                print("Finished all trading pairs.")
                exit()
    except Exception as e:
        print(f'Error displaying bid difference: {str(e)}')


def on_open_binance(ws):
    global current_pair_index
    try:
        params = {
            "method": "SUBSCRIBE",
            "params": [
                f"{trading_pairs[current_pair_index].lower()}@depth5@100ms"
            ],
            "id": 1
        }
        ws.send(json.dumps(params))
        print("Binance WebSocket connected")
    except Exception as e:
        print(f'Error opening Binance websocket: {str(e)}')


def on_open_mexc(ws):
    global current_pair_index
    try:
        formatted_symbol = trading_pairs[current_pair_index].replace(
            "USDT", "_USDT").upper()
        data_to_send = {
            "method": "sub.depth.full",
            "param": {
                "symbol": formatted_symbol,
                "limit": 5
            }
        }
        ws.send(json.dumps(data_to_send))
        print("MEXC WebSocket connected")
    except Exception as e:
        print(f'Error opening MEXC websocket: {str(e)}')


def initialize_websockets():
    global current_pair_index
    current_pair = trading_pairs[current_pair_index]
    try:
        ws_binance = websocket.WebSocketApp(
            f"wss://fstream.binance.com/ws",
            on_message=on_message_binance,
        )
        ws_mexc = websocket.WebSocketApp(
            f"wss://contract.mexc.com/ws",
            on_message=on_message_mexc,
        )
        ws_binance.on_open = on_open_binance
        ws_mexc.on_open = on_open_mexc
        threading.Thread(target=ws_binance.run_forever).start()
        threading.Thread(target=ws_mexc.run_forever).start()
    except Exception as e:
        print(f'Error initializing websockets: {str(e)}')


if __name__ == "__main__":
    websocket.enableTrace(False)
    initialize_websockets()
