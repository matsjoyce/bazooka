import socketio, requests, re, uuid
from PyQt5 import QtCore, QtGui, QtWidgets


class PlanarAllyIntegration:
    def __init__(self, url, username, password, room, creature_model):
        r = requests.post(f"{url}/api/login", json={"username": username, "password": password})
        r.raise_for_status()

        self.sio = socketio.Client(logger=True, engineio_logger=True)
        self.tokens = {}

        def update_all():
            creatures = [creature_model.index(i, 0).data(QtCore.Qt.UserRole) for i in range(creature_model.rowCount())]
            for creature in creatures:
                self.update_creature(creature)

        creature_model.dataChanged.connect(update_all)

        @self.sio.event(namespace="/planarally")
        def connect():
            self.sio.emit("Location.Load", namespace="/planarally")

        @self.sio.on("Board.Floor.Set", namespace="/planarally")
        def message(data):
            self.tokens.clear()
            for layer in data["layers"]:
                if layer["name"] not in ("dm", "tokens"):
                    continue
                for shape in layer["shapes"]:
                    self.tokens[shape["uuid"]] = shape

            update_all()

        @self.sio.on("Shapes.Remove", namespace="/planarally")
        def message(data):
            for uuid in data:
                self.tokens.pop(uuid, None)

            update_all()

        @self.sio.on("Shape.Add", namespace="/planarally")
        def message(data):
            self.tokens[data["uuid"]] = data

            update_all()

        @self.sio.on("Shape.Options.ShowBadge.Set", namespace="/planarally")
        def message(data):
            self.tokens[data["shape"]]["show_badge"] = data["value"]

            update_all()

        @self.sio.on("Shape.Options.Name.Set", namespace="/planarally")
        def message(data):
            self.tokens[data["shape"]]["name"] = data["value"]

            update_all()

        self.sio.connect(
            f"{url}/socket.io/?user={username}&room={room}",
            namespaces=["/planarally"],
            headers={"Cookie": f"AIOHTTP_SESSION={r.cookies['AIOHTTP_SESSION']}"},
            transports=["websocket"]
        )

    def close(self):
        self.sio.disconnect()

    def update_creature(self, creature):
        tags = {t for t, _ in creature.tags}
        if "pa" not in tags:
            return

        print("Searching for PA token", creature.name, tags)

        for token in self.tokens.values():
            token_name = token.get("name")
            if token.get("show_badge"):
                token_name += str(token.get("badge") + 1)
            print(" -> Found", token_name)
            if token_name.lower() == creature.name.lower():
                print("Found", token)
                self.set_is_token(token)
                self.set_defeated(token, creature)
                self.set_side_data(token, tags)
                for tracker in token["trackers"]:
                    if tracker["name"] == "HP":
                        print("Updating tracker")
                        self.set_hp_on_token(tracker, token, creature, tags)
                        break
                else:
                    print("Adding tracker")
                    self.add_hp_to_token(token, creature, tags)

                for auras in token["auras"]:
                    if auras["name"] == "Vision":
                        print("Updating aura")
                        self.set_vision_on_token(auras, token, creature, tags)
                        break
                else:
                    print("Adding aura")
                    self.add_vision_to_token(token, creature, tags)

                return

    def set_defeated(self, token, creature):
        creature_defeated = any(t in ("unconscious", "defeated", "dead") for t, _ in creature.tags)
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

    def set_side_data(self, token, tags):
        sides = [i for i in range(10) if f"side-{i+1}" in tags]
        if not sides:
            return
        side = sides[0]
        color = [
            "rgb(12, 97, 20)", # dark green
            "rgb(255, 215, 0)", # yellow
            "rgb(32, 220, 219)", # cyan
            "rgb(0, 2, 195)", # dark blue
            "rgb(143, 0, 195)", # purple
            "rgb(109, 59, 0)", # brown
            "rgb(255, 147, 0)", # orange
            "rgb(255, 255, 255)", # white
            "rgb(0, 0, 0)", # black
            "rgb(148, 148, 148)", # grey
        ]
        if token["fill_colour"] != color[side]:
            self.sio.emit(
                "Shape.Options.FillColour.Set",
                {
                    "shape": token["uuid"],
                    "value": color[side]
                },
                namespace="/planarally"
            )
            token["fill_colour"] = color

    def set_hp_on_token(self, tracker, token, creature, tags):
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
        if "acchp" not in tags:
            if hp == 0:
                hp = 0
            elif hp <= max_hp / 2:
                hp = 1
            else:
                hp = 2
            max_hp = 2
        data = {
            "uuid": tracker["uuid"],
            "value": hp,
            "maxvalue": max_hp,
            "primary_color": color,
            "shape": token["uuid"]
        }

        self.sio.emit("Shape.Options.Tracker.Update", data, namespace="/planarally")

    def add_hp_to_token(self, token, creature, tags):
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
        self.set_hp_on_token(data, token, creature, tags)

    def set_vision_on_token(self, aura, token, creature, tags):
        range_ = None
        color = "rgba(0,0,0,0)"
        public = False
        if "darkvision-0" in tags:
            range_ = 0, 0
        elif "darkvision-60" in tags:
            range_ = 55, 5
        elif "darkvision-120" in tags:
            range_ = 115, 5
        elif "torch" in tags:
            range_ = 20, 20
            color = "rgba(255, 186, 0, 0.5)" # orangey
            public = True

        data = {
            "uuid": aura["uuid"],
            "active": range_ is not None,
            "value": 0 if range_ is None else range_[0],
            "dim": 0 if range_ is None else range_[1],
            "colour": color,
            "visible": public,
            "shape": token["uuid"]
        }

        self.sio.emit("Shape.Options.Aura.Update", data, namespace="/planarally")
        pass

    def add_vision_to_token(self, token, creature, tags):
        aid = str(uuid.uuid4())
        data = {
            "uuid": aid,
            "active": True,
            "vision_source": True,
            "visible": False, # Private to that character
            "name": "Vision",
            "value": 0,
            "dim": 0,
            "colour": "rgba(0,0,0,0)",
            "border_colour": "rgba(0,0,0,0)",
            "angle": 360,
            "direction": 0,
            "shape": token["uuid"]
        }
        self.sio.emit("Shape.Options.Aura.Create", data, namespace="/planarally")
        token["auras"].append(data)
        self.set_vision_on_token(data, token, creature, tags)
        pass
