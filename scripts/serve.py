#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简静态服务器：把审阅板等本地文件用系统浏览器打开。

用法:
  python3 serve.py [--port=8000] [--file=review-board.html] [--no-browser]
默认服务当前目录；不传 --no-browser 时尝试自动打开默认浏览器。
审阅板请用系统浏览器打开（不要用 WorkBuddy 内置预览面板），本地存储才持久、复制/下载才正常。
"""
import http.server, socketserver, webbrowser, os, argparse

ap = argparse.ArgumentParser()
ap.add_argument('--port', type=int, default=8000)
ap.add_argument('--file', default=None)
ap.add_argument('--no-browser', action='store_true')
args = ap.parse_args()

os.chdir(os.getcwd())
Handler = http.server.SimpleHTTPRequestHandler
httpd = socketserver.TCPServer(('127.0.0.1', args.port), Handler)
url = f'http://127.0.0.1:{args.port}/' + (args.file or '')
print('服务已启动:', url)
print('在系统浏览器中打开上面的链接审阅；Ctrl+C 停止。')
if not args.no_browser:
    try:
        webbrowser.open(url)
    except Exception:
        pass
try:
    httpd.serve_forever()
except KeyboardInterrupt:
    print('\n已停止')
    httpd.shutdown()
