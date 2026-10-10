"""Điểm khởi động: chạy `python app.py` để mở web ở http://127.0.0.1:5000"""

import os

from shop import create_app

app = create_app()

if __name__ == "__main__":
    # debug chỉ bật khi chạy trên máy mình (DEBUG=1 trong .env), KHÔNG bật khi chạy thật
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("DEBUG") == "1")
