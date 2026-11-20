"""Browser regression: run with the project Python; requires local Microsoft Edge."""

def main():
    import base64
    import json
    import os
    import socket
    import struct
    import subprocess
    import tempfile
    import time
    import urllib.request
    from pathlib import Path

    folder = Path(tempfile.mkdtemp(prefix="multifilter-test-"))
    profile = tempfile.mkdtemp(prefix='edge-incomplete-cdp-', dir=folder)
    browser = subprocess.Popen([
        'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '--headless',
        '--disable-gpu', '--disable-extensions', '--disable-background-networking', '--no-first-run',
        '--remote-debugging-port=9342', '--user-data-dir='+profile, 'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

    def receive_exact(length):
        data = b''
        while len(data) < length:
            piece = channel.recv(length-len(data))
            if not piece:
                raise RuntimeError('CDP closed')
            data += piece
        return data

    sequence = 0
    def request(method, params=None):
        nonlocal sequence
        sequence += 1
        data = json.dumps({'id':sequence, 'method':method, 'params':params or {}}).encode()
        mask = os.urandom(4)
        size = len(data)
        header = bytes([0x81, 0x80 | size]) if size < 126 else bytes([0x81, 0xfe])+struct.pack('!H',size)
        channel.sendall(header+mask+bytes(v ^ mask[i%4] for i,v in enumerate(data)))
        while True:
            first, size = receive_exact(2)
            size &= 0x7f
            if size == 126:
                size = struct.unpack('!H',receive_exact(2))[0]
            elif size == 127:
                size = struct.unpack('!Q',receive_exact(8))[0]
            payload = receive_exact(size)
            if first & 0x0f != 1:
                continue
            result = json.loads(payload)
            if result.get('id') == sequence:
                if 'error' in result:
                    raise RuntimeError(result['error'])
                return result['result']

    try:
        for attempt in range(100):
            try:
                tabs = json.load(urllib.request.urlopen('http://127.0.0.1:9342/json',timeout=1))
                break
            except OSError:
                time.sleep(.1)
        tab = next(tab for tab in tabs if tab['type']=='page')
        from urllib.parse import urlsplit
        address = urlsplit(tab['webSocketDebuggerUrl'])
        channel = socket.create_connection((address.hostname,address.port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        channel.sendall((f'GET {address.path} HTTP/1.1\r\nHost: {address.netloc}\r\nUpgrade: websocket\r\n'
                         f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        response = b''
        while b'\r\n\r\n' not in response:
            response += channel.recv(1)
        assert response.startswith(b'HTTP/1.1 101 '), response
        import sys
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        import django
        django.setup()
        from django.template.loader import render_to_string
        controls = []
        for label in ("First", "Second"):
            controls.append(render_to_string("components/multifilter.html", {"filter": {
                "label": label, "name": label, "summary": "Toutes", "selected": [],
                "choices": [{"value": str(i), "label": "Option " + str(i), "checked": False} for i in range(30)]}}))
        css = (root / "static/css/app.css").read_text(encoding="utf-8") + (root / "static/css/workspace.css").read_text(encoding="utf-8")
        js = (root / "static/js/multifilter.js").read_text(encoding="utf-8")
        fixture = folder / "filters.html"
        fixture.write_text('<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1">'
            + '<style>' + css + '</style><form class="filter-bar review-filters">' + ''.join(controls)
            + '<button type="reset" id="reset" style="position:fixed;bottom:20px;left:20px;z-index:100">Reset</button></form><button id="outside" style="position:fixed;bottom:20px;right:20px;z-index:100">Outside</button>'
            + '<details id="unrelated" open><summary>Other disclosure</summary>Keep open</details>'
            + '<script>' + js + '</script>', encoding="utf-8")

        def evaluate(expression):
            result = request("Runtime.evaluate", {"expression": expression, "returnByValue": True})
            assert "exceptionDetails" not in result, result
            return result["result"].get("value")

        def check(expression):
            assert evaluate(expression), expression

        def activate(selector, touch=False):
            point = evaluate("(() => { const r = document.querySelector(" + json.dumps(selector)
                + ").getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()")
            if touch:
                request("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [point]})
                request("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            else:
                request("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": 1, **point})
                request("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": 1, **point})

        for mobile, width in ((False, 1440), (True, 390)):
            request("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1, "mobile": mobile})
            request("Emulation.setTouchEmulationEnabled", {"enabled": mobile})
            request("Page.navigate", {"url": fixture.as_uri()})
            for attempt in range(100):
                if evaluate("location.href === " + json.dumps(fixture.as_uri()) + " && document.readyState === 'complete'"):
                    break
                time.sleep(.05)
            else:
                raise AssertionError("Fixture failed to load")
            evaluate("window.menus = [...document.querySelectorAll('[data-multi-filter]')]")
            activate('[data-multi-filter]:nth-child(1) summary', mobile)
            check("menus[0].open && !menus[1].open")
            activate('[data-multi-filter]:nth-child(1) input[value="0"]', mobile)
            check("menus[0].open && menus[0].querySelector('input[value=\"0\"]').checked && !menus[0].querySelector('[data-filter-all]').checked")
            activate('[data-multi-filter]:nth-child(2) summary', mobile)
            check("!menus[0].open && menus[1].open")
            activate('#outside', mobile)
            check("!menus[0].open && !menus[1].open && document.querySelector('#unrelated').open")
            activate('[data-multi-filter]:nth-child(1) summary', mobile)
            check("menus[0].querySelector('input[value=\"0\"]').checked")
            evaluate("menus[0].querySelector('input[value=\"0\"]').focus()")
            request("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
            request("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
            check("!menus[0].open && document.activeElement === menus[0].querySelector('summary')")
            request("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"})
            request("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"})
            check("menus[0].open")
            evaluate("menus[1].open = true")
            time.sleep(.05)
            check("!menus[0].open && menus[1].open")
            # Interior search, multiple selection and scrolling must leave the menu open.
            evaluate("menus[1].querySelector('fieldset').insertAdjacentHTML('afterbegin', '<input type=search id=search>')")
            activate('#search', mobile)
            evaluate("document.querySelector('#search').value = 'Option'; menus[1].querySelector('fieldset').scrollTop = 100")
            check("menus[1].open && menus[1].querySelector('fieldset').scrollTop > 0")
            evaluate("menus[1].querySelector('fieldset').scrollTop = 0")
            activate('[data-multi-filter]:nth-child(2) input[value="0"]', mobile)
            activate('[data-multi-filter]:nth-child(2) input[value="1"]', mobile)
            check("menus[1].open && menus[1].querySelector('[data-filter-summary]').textContent.startsWith('2 ')")
            activate('[data-multi-filter]:nth-child(2) [data-filter-all]', mobile)
            check("menus[1].open && menus[1].querySelectorAll('input[type=checkbox]:checked').length === 1")
            activate('#reset', mobile)
            check("!menus[1].open && menus.every(m => m.querySelector('[data-filter-all]').checked)")
            print(('mobile touch' if mobile else 'desktop mouse') + ': all filter checks passed', flush=True)
    finally:
        browser.terminate()
        browser.wait(timeout=10)


if __name__ == "__main__":
    main()
