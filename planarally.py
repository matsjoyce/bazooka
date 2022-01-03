import socketio, requests, re, uuid
from PyQt5 import QtCore, QtGui, QtWidgets

from .common import Creature


class PlanarAllyIntegration:
    def __init__(self, url, username, password, room, creature_model):
        r = requests.post(f"{url}/api/login", json={"username": username, "password": password})
        r.raise_for_status()

        self.sio = socketio.Client(logger=True, engineio_logger=True)
        self.tokens = {}
        self.auto_add = False
        self.updating = False
        self.creature_model = creature_model

        self.creature_model.dataChanged.connect(self.update_all)
        self.creature_model.rowsInserted.connect(self.update_all)
        self.creature_model.rowsRemoved.connect(self.update_all)

        @self.sio.event(namespace="/planarally")
        def connect():
            self.sio.emit("Location.Load", namespace="/planarally")

        @self.sio.on("Location.Set", namespace="/planarally")
        def message(data):
            self.tokens.clear()
            self.update_all()

        @self.sio.on("Board.Floor.Set", namespace="/planarally")
        def message(data):
            for layer in data["layers"]:
                if layer["name"] not in ("dm", "tokens"):
                    continue
                for shape in layer["shapes"]:
                    self.tokens[shape["uuid"]] = shape

            self.update_all()

        @self.sio.on("Shapes.Remove", namespace="/planarally")
        def message(data):
            for uuid in data:
                self.tokens.pop(uuid, None)

            self.update_all()

        @self.sio.on("Shape.Add", namespace="/planarally")
        def message(data):
            self.tokens[data["uuid"]] = data

            self.update_all()

        @self.sio.on("Shape.Options.ShowBadge.Set", namespace="/planarally")
        def message(data):
            self.tokens[data["shape"]]["show_badge"] = data["value"]

            self.update_all()

        @self.sio.on("Shape.Options.Name.Set", namespace="/planarally")
        def message(data):
            print(self.tokens.keys())
            self.tokens[data["shape"]]["name"] = data["value"]

            self.update_all()

        self.sio.connect(
            f"{url}/socket.io/?user={username}&room={room}",
            namespaces=["/planarally"],
            headers={"Cookie": f"AIOHTTP_SESSION={r.cookies['AIOHTTP_SESSION']}"},
            transports=["websocket"]
        )


    def update_all(self):
        if self.updating:
            return

        self.updating = True
        creatures_by_name = {}

        for i in range(self.creature_model.rowCount()):
            idx = self.creature_model.index(i, 0)
            creature = idx.data(QtCore.Qt.UserRole)
            if not any(t == "pa" for t, _ in creature.tags):
                continue
            if creature.name.lower() not in creatures_by_name:
                creatures_by_name[creature.name.lower()] = (creature, idx)
            else:
                self.set_creature_tags(creature, idx, duplicate=True)

        tokens_by_name = {}
        duplicate_token_names = set()

        for token in self.tokens.values():
            if token.get("src") == "/static/img/spawn.png":
                continue
            token_name = token.get("name")
            if token.get("show_badge"):
                token_name += str(token.get("badge") + 1)
            if token_name not in tokens_by_name:
                tokens_by_name[token_name] = token
            else:
                duplicate_token_names.add(token_name)

        for token_name, token in sorted(tokens_by_name.items()):
            print(" -> Found", token_name, creatures_by_name.keys())
            if token_name.lower() in creatures_by_name:
                creature, idx = creatures_by_name.pop(token_name.lower())
            elif self.auto_add:
                creature = Creature(name=token_name, tags=[("pa", None)])

                item = QtGui.QStandardItem()
                item.setData(creature, QtCore.Qt.UserRole)
                self.creature_model.appendRow(item)
                idx = self.creature_model.index(self.creature_model.rowCount() - 1, 0)
            else:
                continue

            self.update_creature(token, creature, idx, duplicate_token=token_name in duplicate_token_names)

        for creature, idx in creatures_by_name.values():
            self.set_creature_tags(creature, idx, not_found=True)
        self.updating = False

    def close(self):
        self.sio.disconnect()

    def set_auto_add(self, value):
        self.auto_add = value
        self.update_all()

    def update_creature(self, token, creature, creature_idx, duplicate_token):
        self.set_creature_tags(creature, creature_idx, duplicate_token=duplicate_token)
        tags = {t for t, _ in creature.tags}
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

    def set_creature_tags(self, creature, idx, not_found=False, duplicate=False, duplicate_token=False):
        tags = [(t, d) for t, d in creature.tags if not t.startswith("pa-")]
        if not_found:
            tags.append(("pa-not-found", None))
        if duplicate:
            tags.append(("pa-duplicate", None))
        if duplicate_token:
            tags.append(("pa-duplicate-token", None))
        creature.tags = tags
        self.creature_model.itemFromIndex(idx).emitDataChanged()
