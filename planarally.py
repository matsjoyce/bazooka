import socketio, requests, re, uuid
from PyQt5 import QtCore, QtGui, QtWidgets


class PlanarAllyIntegration:
    def __init__(self, url, username, password, room, creatures):
        r = requests.post(f"{url}/api/login", json={"username": username, "password": password})
        r.raise_for_status()

        self.sio = socketio.Client(logger=True, engineio_logger=True)
        self.tokens = {}

        @self.sio.event(namespace="/planarally")
        def connect():
            self.sio.emit("Location.Load", namespace="/planarally")

        @self.sio.on("Board.Floor.Set", namespace="/planarally")
        def message(data):
            for layer in data["layers"]:
                if layer["name"] not in ("dm", "tokens"):
                    continue
                for shape in layer["shapes"]:
                    self.tokens[shape["uuid"]] = shape

            for creature in creatures:
                self.update_creature(creature)

        @self.sio.on("Shapes.Remove", namespace="/planarally")
        def message(data):
            for uuid in data["uuids"]:
                self.tokens.pop(uuid, None)

        @self.sio.on("Shape.Add", namespace="/planarally")
        def message(data):
            self.tokens[data["uuid"]] = data

        self.sio.connect(
            f"{url}/socket.io/?user={username}&room={room}",
            namespaces=["/planarally"],
            headers={"Cookie": f"AIOHTTP_SESSION={r.cookies['AIOHTTP_SESSION']}"},
            transports=["websocket"]
        )

    def close(self):
        self.sio.disconnect()

    def on_creature_change(self, index):
        self.update_creature(index.data(QtCore.Qt.UserRole))

    def update_creature(self, creature):
        creature_token_names = [m.groups() for t, _ in creature.tags if (m := re.match("pa:([^/:]+)(?:/(\d+))?(?::([\w,]+))?$", t))]
        if not creature_token_names:
            return
        name, badge, options = creature_token_names[0]
        has_badge = badge is not None
        badge = int(badge) - 1 if badge else 0
        options = options.split(",") if options else []
        print("Searching for PA token", name, badge, has_badge, options)

        for token in self.tokens.values():
            print((token.get("name"), token.get("badge"), token.get("show_badge")), (name, badge, has_badge))
            if (token.get("name"), token.get("badge"), token.get("show_badge")) == (name, badge, has_badge):
                print("Found", token)
                self.set_is_token(token)
                self.set_defeated(token, creature)
                if not any(t["name"] == "HP" for t in token["trackers"]):
                    print("Adding tracker")
                    self.add_hp_to_token(token)
                for tracker in token["trackers"]:
                    if tracker["name"] == "HP":
                        print("Updating tracker")
                        self.set_hp_on_token(tracker, token, creature, options)
                        break

                return

    def set_defeated(self, token, creature):
        creature_defeated = any(t in ("unconscious", "defeated") for t, _ in creature.tags)
        if creature_defeated != token["is_defeated"]:
            self.sio.emit(
                "Shape.Options.Defeated.Set",
                {
                    "shape": token["uuid"],
                    "value": creature_defeated
                },
                namespace="/planarally"
            )
            token["is_defeated"] = creature_defeated

    def set_is_token(self, token):
        if not token["is_token"]:
            self.sio.emit(
                "Shape.Options.Token.Set",
                {
                    "shape": token["uuid"],
                    "value": True
                },
                namespace="/planarally"
            )
            token["is_token"] = True

    def set_hp_on_token(self, tracker, token, creature, options):
        max_hp = creature.max_hp if creature.max_hp is not None else 1
        hp = creature.hp if creature.hp is not None else 1
        if creature.max_hp is None:
            color = "#FF00FF"
        elif hp == max_hp:
            color = "#00FFFF"
        elif hp > max_hp / 2:
            color = "#00FF00"
        else:
            color = "#FFAA00"
        if "acchp" not in options:
            if hp == 0:
                hp = 0
            elif hp <= max_hp / 2:
                hp = max_hp // 2
            else:
                hp = max_hp
        data = {
            "uuid": tracker["uuid"],
            "value": hp,
            "maxvalue": max_hp,
            "primary_color": color,
            "shape": token["uuid"]
        }

        self.sio.emit("Shape.Options.Tracker.Update", data, namespace="/planarally")

    def add_hp_to_token(self, token):
        tid = str(uuid.uuid4())
        data = {
            "uuid": tid,
            "visible": True,
            "name": "HP",
            "value": 0,
            "maxvalue": 0,
            "draw": True,
            "primary_color": "#00FF00",
            "secondary_color": "#888888",
            "shape": token["uuid"]
        }
        self.sio.emit("Shape.Options.Tracker.Create", data, namespace="/planarally")
        token["trackers"].append(data)
