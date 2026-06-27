import http.server
import os
import threading
import urllib.parse
from typing import Optional, Tuple

class LoopbackListener:
    """
    A self-contained loopback HTTP listener running in a daemon thread.
    Used for out-of-band callback verification (e.g. SSRF).
    """

    def __init__(self, host: str='127.0.0.1', port: int=0, fs_signature: str='', work_dir: str='') -> None:
        self.host = host
        self._port = port
        self.fs_signature = fs_signature
        self.work_dir = work_dir
        self._actual_port: Optional[int] = None
        self._server: Optional[http.server.HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._hits = []
        self._lock = threading.Lock()

    def start(self) -> 'LoopbackListener':
        """
        Starts the HTTPServer in a background daemon thread.
        """
        with self._lock:
            if self._server is not None:
                return self
            listener_self = self

            class RequestHandler(http.server.BaseHTTPRequestHandler):

                def log_message(self, format: str, *args) -> None:
                    pass

                def handle_incoming(self) -> None:
                    listener_self._record_request(self.path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain')
                    self.send_header('Content-Length', '2')
                    self.end_headers()
                    self.wfile.write(b'OK')

                def do_GET(self) -> None:
                    self.handle_incoming()

                def do_POST(self) -> None:
                    self.handle_incoming()

                def do_PUT(self) -> None:
                    self.handle_incoming()

                def do_DELETE(self) -> None:
                    self.handle_incoming()

                def do_HEAD(self) -> None:
                    listener_self._record_request(self.path)
                    self.send_response(200)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
            try:
                self._server = http.server.HTTPServer((self.host, self._port), RequestHandler)
                self._actual_port = self._server.server_address[1]
                self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
                self._thread.start()
            except Exception as e:
                pass
            return self

    def stop(self) -> None:
        """
        Stops the HTTPServer and joins the background thread. Idempotent.
        """
        with self._lock:
            if self._server is not None:
                try:
                    self._server.shutdown()
                    self._server.server_close()
                except Exception:
                    pass
                self._server = None
            if self._thread is not None:
                try:
                    self._thread.join(timeout=2.0)
                except Exception:
                    pass
                self._thread = None

    def __enter__(self) -> 'LoopbackListener':
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def _record_request(self, path: str) -> None:
        """
        Records the path thread-safely and writes the fs_signature sentinel file.
        """
        with self._lock:
            self._hits.append(path)
            if self.fs_signature:
                if self.work_dir:
                    file_path = os.path.join(self.work_dir, self.fs_signature)
                else:
                    file_path = self.fs_signature
                try:
                    parent = os.path.dirname(os.path.abspath(file_path))
                    os.makedirs(parent, exist_ok=True)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(path)
                except Exception:
                    pass

    @property
    def port(self) -> int:
        """
        Returns the actual port the server is listening on, or the configured port.
        """
        with self._lock:
            return self._actual_port if self._actual_port is not None else self._port

    @property
    def url(self) -> str:
        """
        Returns the base url of the listener.
        """
        return f'http://{self.host}:{self.port}/'

    def url_for(self, nonce: str) -> str:
        """
        Returns the url with the given nonce path/query.
        """
        stripped = nonce.lstrip('/')
        return f'http://{self.host}:{self.port}/{stripped}'

    @property
    def hits(self) -> Tuple[str, ...]:
        """
        Returns a tuple of all recorded request paths.
        """
        with self._lock:
            return tuple(self._hits)

    def received(self, nonce: str='') -> bool:
        """
        Checks if a request matching the given nonce has been received.
        If nonce is empty, checks if any request has been received.
        """
        with self._lock:
            if not nonce:
                return len(self._hits) > 0
            for hit in self._hits:
                if nonce in hit:
                    return True
                decoded_hit = urllib.parse.unquote(hit)
                if nonce in decoded_hit:
                    return True
            return False