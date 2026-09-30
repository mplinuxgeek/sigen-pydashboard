"""Network registry: features that provide a link (ethernet, wifi, ...) register here; everything that
just *uses* the network (Shelly discovery, NTP, the HTTP API, ...) asks this module instead of reaching
into a specific interface feature.

    app.network.register("eth", is_up=lambda: ..., ifconfig=lambda: (ip, mask, gw, dns), priority=10, status=fn)
    app.network.up()            any link up?
    app.network.primary()       best link that is up (lowest priority number) or None
    app.network.addresses()     IPs of every link that is up
    app.network.urls(port=80)   http://ip/ for every link that is up
    app.network.status()        {iface: {label: text}} for diagnostics / the API
"""


class Network:
    def __init__(self):
        self._ifaces = {}

    def register(self, name, is_up, ifconfig, priority=50, status=None):
        """is_up() -> bool; ifconfig() -> (ip, netmask, gateway, dns) (only called while up);
        status() -> {label: text | (text, colour)} optional, for diagnostics."""
        self._ifaces[name] = {"up": is_up, "ifconfig": ifconfig, "prio": priority, "status": status}

    def _up_list(self):
        out = []
        for name, i in self._ifaces.items():
            try:
                if i["up"]():
                    out.append((i["prio"], name, i))
            except Exception:
                pass
        out.sort(key=lambda t: (t[0], t[1]))
        return out

    def up(self):
        return bool(self._up_list())

    def primary(self):
        """{'name', 'ip', 'mask', 'gw', 'dns'} of the preferred link that is up, else None."""
        for _prio, name, i in self._up_list():
            try:
                ip, mask, gw, dns = i["ifconfig"]()
            except Exception:
                continue
            return {"name": name, "ip": ip, "mask": mask, "gw": gw, "dns": dns}
        return None

    def addresses(self):
        out = []
        for _prio, _name, i in self._up_list():
            try:
                out.append(i["ifconfig"]()[0])
            except Exception:
                pass
        return out

    def urls(self, port=80):
        suffix = "" if port == 80 else ":%d" % port
        return ["http://%s%s/" % (ip, suffix) for ip in self.addresses()]

    def names(self):
        return sorted(self._ifaces, key=lambda n: (self._ifaces[n]["prio"], n))

    def status(self):
        out = {}
        for name in self.names():
            fn = self._ifaces[name]["status"]
            if fn:
                try:
                    out[name] = {k: (v[0] if isinstance(v, tuple) else v) for k, v in fn().items()}
                except Exception as e:
                    out[name] = {"error": repr(e)}
        return out
