from enum import Enum

from flask import Flask, request, jsonify
import time
import sqlite3
import uuid


# TODO:
# trade history


class Side(Enum):
    LONG = "long"
    SHORT = "short"


class Market:
    def __init__(self, name, bid: float = 0, mid: float = 0, ask: float = 0, daily_change_percent: float = 0):
        self.name = name
        self.bid = bid
        self.mid = mid
        self.ask = ask
        self.daily_change_percent = daily_change_percent
        # If the market is not USDJPY, the base currency is USD and the quote currency is the second currency
        # in the pair. Otherwise, the base currency is JPY and the quote currency is USD.
        self.base_currency = "USD" if name != "USDJPY" else "JPY"
        self.quote_currency = name[:3] if name != "USDJPY" else name[3:]

    def update_prices(self, bid, mid, ask, daily_change_percent):
        self.bid = bid
        self.mid = mid
        self.ask = ask
        self.daily_change_percent = daily_change_percent


class MarketCollection:
    def __init__(self):
        self.markets = {}

    def add_market(self, market: Market):
        self.markets[market.name] = market

    def get_market(self, name) -> Market:
        return self.markets.get(name)

    def update_markets(self, prices: dict):
        for name, price_data in prices.items():
            market = self.get_market(name)
            if market:
                market.update_prices(**price_data)


class APIServer:
    DEFAULT_BUYING_POWER = 100.0

    def __init__(self):
        # Initialize the Flask app within the class
        self.app = Flask(__name__)
        self.db_file = "forex_trading.db"
        self.init_database()

        self.market_collection = MarketCollection()

        self.markets = ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD"]
        for market in self.markets:
            self.market_collection.add_market(Market(market))

        self.app.add_url_rule('/price', 'get_price', self.get_price, methods=['GET'])

        self.app.add_url_rule('/account/<username>', 'get_account', self.get_account, methods=['GET'])
        self.app.add_url_rule('/account/<username>', 'create_account', self.create_account, methods=['POST'])

        self.app.add_url_rule('/leaderboard', 'get_leaderboard', self.get_leaderboard, methods=['GET'])
        self.app.add_url_rule('/account/<username>/reset', 'reset_account', self.reset_account, methods=['POST'])

        self.app.add_url_rule('/account/<username>/trade', 'create_trade', self.create_trade, methods=['POST'])

        self.app.add_url_rule('/order/create', 'create_order', self.create_order, methods=['POST'])
        self.app.add_url_rule('/order/retrieve/<trade_id>', 'retrieve_orders', self.retrieve_orders, methods=['GET'])
        self.app.add_url_rule('/order/cancel/<order_id>', 'cancel_order', self.cancel_order, methods=['DELETE'])

    def init_database(self):
        # Initialize the SQLite database and create tables if they don't exist
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # Create accounts table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                buying_power REAL DEFAULT {self.DEFAULT_BUYING_POWER},
                nav REAL DEFAULT {self.DEFAULT_BUYING_POWER}
            );
        ''')

        # Create trades table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                username TEXT,
                market TEXT,
                trade_type TEXT,
                entry_price REAL,
                units INTEGER,
                reserved_units INTEGER DEFAULT 0,  -- include here
                FOREIGN KEY (username) REFERENCES accounts (username)
            );
        ''')

        # Create orders table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                trade_id TEXT,
                order_type TEXT,
                units INTEGER,
                limit_price REAL,
                FOREIGN KEY (trade_id) REFERENCES trades (trade_id)
            );
        ''')

        conn.commit()
        conn.close()

    def update_prices(self):
        # TODO: pull prices from OANDA API
        # Hard-coded bid and ask prices for popular trading pairs
        prices = {
            "EURUSD": {"bid": 1.1234, "mid": 1.1235, "ask": 1.1236, "daily_change_percent": 0.023},
            "USDJPY": {"bid": 110.25, "mid": 110.265, "ask": 110.28, "daily_change_percent": -0.25},
            "GBPUSD": {"bid": 1.3012, "mid": 1.30135, "ask": 1.3015, "daily_change_percent": 0.12},
            "AUDUSD": {"bid": 0.7100, "mid": 0.71015, "ask": 0.7103, "daily_change_percent": 0.03},
            "USDCAD": {"bid": 1.2500, "mid": 1.25015, "ask": 1.2503, "daily_change_percent": -0.07},
        }
        self.market_collection.update_markets(prices)

        # For each account, update the NAV based on the current market price

        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # Retrieve all accounts
        cursor.execute("SELECT username, buying_power FROM accounts")
        accounts = cursor.fetchall()

        for account in accounts:
            username = account[0]
            buying_power = account[1]

            # Calculate NAV based on the positions (trades) of the account
            cursor.execute("SELECT SUM(units * entry_price) FROM trades WHERE username = ?", (username,))
            total_positions = cursor.fetchone()[0] or 0.0  # If no positions, default to 0

            # Update NAV for the account
            nav = buying_power + total_positions
            cursor.execute("UPDATE accounts SET nav = ? WHERE username = ?", (nav, username))

        return

    def cancel_order(self, order_id):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # Retrieve the order and associated trade
        cursor.execute("SELECT trade_id, units FROM orders WHERE order_id = ?", (order_id,))
        order_data = cursor.fetchone()
        if not order_data:
            conn.close()
            return jsonify({"error": "Order not found"}), 404

        trade_id = order_data[0]
        order_units = order_data[1]

        # Retrieve the trade's reserved_units
        cursor.execute("SELECT reserved_units FROM trades WHERE trade_id = ?", (trade_id,))
        trade_data = cursor.fetchone()
        if not trade_data:
            conn.close()
            return jsonify({"error": "Associated trade not found"}), 404

        reserved_units = trade_data[0]

        # Check if the order can be canceled (order units <= reserved units)
        if order_units > reserved_units:
            conn.close()
            return jsonify({"error": "Order cannot be canceled, units are reserved"}), 400

        # Update the reserved_units in the trade
        new_reserved_units = reserved_units - order_units
        cursor.execute("UPDATE trades SET reserved_units = ? WHERE trade_id = ?", (new_reserved_units, trade_id))

        # Delete the order
        cursor.execute("DELETE FROM orders WHERE order_id = ?", (order_id,))

        conn.commit()
        conn.close()

        return jsonify({"message": "Order canceled successfully"}), 200

    def retrieve_orders(self, trade_id):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # Retrieve orders for the given trade_id
        cursor.execute("SELECT * FROM orders WHERE trade_id = ?", (trade_id,))
        orders = cursor.fetchall()

        conn.close()

        if not orders:
            return jsonify({"message": "No orders found for the trade"}), 200

        order_list = []
        for order in orders:
            order_info = {
                "order_id": order[0],
                "trade_id": order[1],
                "order_type": order[2],
                "units": order[3],
                "limit_price": order[4]
            }
            order_list.append(order_info)

        return jsonify(order_list), 200

    def create_order(self):
        trade_id = request.args.get('trade_id')
        order_type = request.args.get('order_type')  # 'market' or 'limit'
        units = int(request.args.get('units'))
        limit_price = None if order_type == 'market' else float(request.args.get('limit_price'))

        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        # Check if enough units are available in the trade
        cursor.execute("SELECT units, reserved_units FROM trades WHERE trade_id = ?", (trade_id,))
        trade = cursor.fetchone()
        if not trade or trade[0] - trade[1] < units:
            return jsonify({"error": "Not enough units available in the trade"}), 400

        # Update reserved units
        new_reserved_units = trade[1] + units
        cursor.execute("UPDATE trades SET reserved_units = ? WHERE trade_id = ?", (new_reserved_units, trade_id))

        # Create the order
        order_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO orders (order_id, trade_id, order_type, units, limit_price) VALUES (?, ?, ?, ?, ?)",
                       (order_id, trade_id, order_type, units, limit_price))

        conn.commit()
        conn.close()

        return jsonify({"message": "Order created successfully", "order_id": order_id}), 201

    def create_trade(self, username):
        market_name = request.args.get('market')
        side = request.args.get('side')
        units = request.args.get('units')

        try:
            market = self.market_collection.get_market(market_name)
        except ValueError:
            return jsonify({"error": "Invalid market"}), 400

        # Validate and convert entry_price and units
        try:
            units = int(units)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid entry price or units"}), 400

        # Validate trade type against the enum
        if side not in [s.value for s in Side]:
            return jsonify({"error": "Invalid trade type"}), 400

        # For now, all entry orders are market orders which fill instantly at mid price.
        entry_price = market.mid
        trade_cost = entry_price * units  # Modify this according to your cost calculation logic

        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        cursor.execute("SELECT buying_power FROM accounts WHERE username=?", (username,))
        account = cursor.fetchone()
        if not account:
            return jsonify({"error": "Account not found"}), 404

        if account[0] < trade_cost:
            return jsonify({"error": "Insufficient buying power"}), 400

        new_buying_power = account[0] - trade_cost
        trade_id = str(uuid.uuid4())

        cursor.execute("INSERT INTO trades (trade_id, username, market, side, entry_price, units) VALUES (?, ?, ?, ?, ?, ?)",
                       (trade_id, username, market, side, entry_price, units))
        cursor.execute("UPDATE accounts SET buying_power = ? WHERE username = ?", (new_buying_power, username))

        conn.commit()
        conn.close()

        return jsonify({"message": "Trade created successfully", "trade_id": trade_id}), 201

    def get_leaderboard(self):
        """Endpoint to retrieve a leaderboard page."""
        try:
            page = int(request.args.get('page', 1))
            amount_per_page = int(request.args.get('amount_per_page', 10))
        except ValueError:
            return jsonify({"error": "Invalid page or amount_per_page parameters"}), 400

        if page < 1 or amount_per_page < 1:
            return jsonify({"error": "Page and amount_per_page must be positive integers"}), 400

        offset = (page - 1) * amount_per_page

        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT username, nav FROM accounts ORDER BY nav DESC LIMIT ? OFFSET ?", (amount_per_page, offset))
        results = cursor.fetchall()
        conn.close()

        leaderboard = [{username: nav} for username, nav in results]
        return jsonify(leaderboard)

    def reset_account(self, username):
        """Endpoint to reset account's buying power and NAV to default values."""
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute("UPDATE accounts SET buying_power = ?, nav = ? WHERE username = ?",
                       (self.DEFAULT_BUYING_POWER, self.DEFAULT_BUYING_POWER, username))
        if cursor.rowcount == 0:
            conn.close()
            return jsonify({"error": "Account not found"}), 404

        conn.commit()
        conn.close()
        return jsonify({"message": f"Account for {username} has been reset successfully"}), 200

    def get_account(self, username):
        # Retrieve account data by username
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE username=?", (username,))
        account_data = cursor.fetchone()
        conn.close()

        if account_data:
            account_info = {
                "id": account_data[0],
                "username": account_data[1],
                "buying_power": account_data[2],
                "nav": account_data[3]
            }
            return jsonify(account_info)
        else:
            return jsonify({"error": "Account not found"}), 404

    def create_account(self, username):
        # Create a new user with a username
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()

        try:
            cursor.execute("INSERT INTO accounts (username) VALUES (?)", (username,))
            conn.commit()
            conn.close()
            return jsonify({"message": f"Account for {username} created successfully"}), 201
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({"error": "Username already exists"}), 400

    def get_price(self):
        """Endpoint to retrieve the price based on the pair and type ('bid' or 'ask')."""
        pair = request.args.get('pair')
        price_type = request.args.get('type')

        try:
            market = self.market_collection.get_market(pair)
        except ValueError:
            return jsonify({"error": "Invalid market"}), 400

        if price_type not in ['bid', 'mid', 'ask']:
            return jsonify({"error": "Invalid price type"}), 400

        return jsonify({price_type: getattr(market, price_type)})

    def run(self, port=5000):
        """Method to run the Flask app."""
        self.app.run(debug=True, port=port)


if __name__ == '__main__':
    PORT = 7654
    api_server = APIServer()
    api_server.run(port=PORT)
