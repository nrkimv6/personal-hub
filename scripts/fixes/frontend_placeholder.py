import http.server
import socketserver
import threading
import time

HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="3">
    <title>서버 준비 중</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            background-color: #f5f5f7;
            color: #1d1d1f;
        }
        .container {
            text-align: center;
            padding: 2rem;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            max-width: 400px;
            width: 90%;
        }
        .spinner {
            border: 4px solid rgba(0, 0, 0, 0.1);
            width: 36px;
            height: 36px;
            border-radius: 50%;
            border-left-color: #0071e3;
            animation: spin 1s linear infinite;
            margin-bottom: 1.5rem;
            display: inline-block;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        h1 { font-size: 1.5rem; margin-bottom: 0.5rem; font-weight: 600; }
        p { color: #86868b; line-height: 1.5; margin: 0.5rem 0; }
        .footer { font-size: 0.8rem; color: #b0b0b5; margin-top: 1.5rem; }
    </style>
</head>
<body>
    <div class="container">
        <div class="spinner"></div>
        <h1>서버 준비 중...</h1>
        <p>Vite 개발 서버를 초기화하고 있습니다.<br>잠시만 기다려 주시면 자동으로 연결됩니다.</p>
        <div class="footer">3초마다 자동으로 새로고침됩니다.</div>
    </div>
</body>
</html>
"""

class PlaceholderHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_CONTENT.encode("utf-8"))

    def log_message(self, format, *args):
        # Suppress logging to keep console clean
        pass

class PlaceholderServer:
    def __init__(self, port: int, logger=None):
        self.port = port
        self.server = None
        self.thread = None
        self.log = logger

    def start(self):
        if self.log:
            self.log.info(f"Starting placeholder server on port {self.port}...")
        
        # Allow port reuse to avoid \"Address already in use\" errors during rapid restarts
        socketserver.TCPServer.allow_reuse_address = True
        
        try:
            self.server = socketserver.TCPServer(("", self.port), PlaceholderHandler)
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            if self.log:
                self.log.info(f"Placeholder server started on port {self.port}")
            else:
                print(f"Placeholder server started on port {self.port}")
        except Exception as e:
            if self.log:
                self.log.error(f"Failed to start placeholder server: {e}")
            else:
                print(f"Failed to start placeholder server: {e}")

    def stop(self):
        if self.server:
            if self.log:
                self.log.info(f"Stopping placeholder server on port {self.port}...")
            _server = self.server
            self.server = None
            t = threading.Thread(target=_server.shutdown, daemon=True)
            t.start()
            t.join(timeout=3.0)
            if t.is_alive():
                if self.log:
                    self.log.warning("PlaceholderServer.shutdown() timed out — forcing server_close()")
            _server.server_close()

        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None

        if self.log:
            self.log.info("Placeholder server stopped")

def main():
    import sys
    port = 6101
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    
    server = PlaceholderServer(port)
    server.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()

if __name__ == "__main__":
    main()