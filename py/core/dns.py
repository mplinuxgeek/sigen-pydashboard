"""Captive-portal DNS: answers every A query with our own AP address, so a phone's connectivity check lands on the setup page."""
import asyncio
import socket


def _reply(q, ip):
    """Build a response for DNS query q (bytes): same id/question, one A record -> ip."""
    if len(q) < 12:
        return None
    i = 12
    while i < len(q) and q[i]:
        i += q[i] + 1
    end = i + 5                                     # zero byte + qtype(2) + qclass(2)
    if end > len(q):
        return None
    qtype = q[i + 1] << 8 | q[i + 2]
    head = bytes([q[0], q[1], 0x81, 0x80]) + q[4:6]
    if qtype != 1:                                  # not A: empty answer
        return head + b"\x00\x00\x00\x00\x00\x00" + q[12:end]
    parts = bytes(int(x) for x in ip.split("."))
    return head + b"\x00\x01\x00\x00\x00\x00" + q[12:end] + b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + parts


class CaptiveDns:
    def __init__(self, ip):
        self.ip = ip
        self._sock = None
        self._stop = False

    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", 53))
        s.setblocking(False)
        self._sock = s
        self._stop = False
        asyncio.create_task(self._run())

    def stop(self):
        self._stop = True

    async def _run(self):
        s = self._sock
        while not self._stop:
            try:
                data, addr = s.recvfrom(512)
            except OSError:
                await asyncio.sleep_ms(40)
                continue
            r = _reply(data, self.ip)
            if r:
                try:
                    s.sendto(r, addr)
                except OSError:
                    pass
        s.close()
        self._sock = None
