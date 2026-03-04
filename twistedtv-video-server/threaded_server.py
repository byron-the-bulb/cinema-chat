#!/usr/bin/env python3
import http.server
import socketserver
import os

PORT = 9000
os.chdir(os.path.dirname(os.path.abspath(__file__)))

class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

Handler = http.server.SimpleHTTPRequestHandler

with ThreadedHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
    print(f"Serving HTTP on port {PORT} with threading support...")
    httpd.serve_forever()
