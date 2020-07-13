#!/bin/python3

"""
Usage:
    init.py [<file>]
"""

import flyingcarpet
from PyQt5 import QtCore, QtGui, QtWidgets
import dataclasses
import pathlib
import datetime
import sly
import random
import json
import re
import traceback
import enum
import time


BASE_DIR = pathlib.Path("/home/matthew/D&D/Bazooka")
SAVES_DIR = BASE_DIR / "Saves"
SHEETS_DIR = BASE_DIR / "Sheets"
CONDITIONS = [
    "blinded",
    "charmed",
    "deafened",
    *[f"exhaustion-{i}" for i in range(1, 6)],
    "frightened",
    "grappled",
    "incapacitated",
    "invisible",
    "paralysed",
    "petrified",
    "poisoned",
    "prone",
    "restrained",
    "stunned",
    "unconscious"
]

OTHERS = [
    "dead",
    "readied-action",
    "used-reaction",
    "concentration"
]

DURATION_FOR_TAG = {
    "readied-action": 1,
    "used-reaction": 1
}

COLOR_FOR_TAG = {}
COLOR_FOR_TAG.update({c: QtCore.Qt.darkRed for c in CONDITIONS})
COLOR_FOR_TAG.update({o: QtCore.Qt.darkYellow for o in OTHERS})

TAG_COMPLETIONS = sorted(CONDITIONS + OTHERS)

LOADED_STAT_SHEETS = {}


def load_stat_from_sheet(sheet, name):
    if sheet not in LOADED_STAT_SHEETS:
        with open(SHEETS_DIR / (sheet + ".json")) as f:
            LOADED_STAT_SHEETS[sheet] = json.load(f)
    return LOADED_STAT_SHEETS[sheet][name]


class DEvalMode(enum.Enum):
    normal, average = range(2)


class DLexer(sly.Lexer):
    tokens = {NUMBER, D, PLUS, MINUS, LPAREN, RPAREN}

    NUMBER = r"\d+"
    D = "d"
    PLUS = r"\+"
    MINUS = "-"
    LPAREN = r"\("
    RPAREN = r"\)"

    ignore = r" \t"

    class LexerError(RuntimeError):
        pass

    def error(self, t):
        raise self.LexerError()


class DParser(sly.Parser):
    tokens = DLexer.tokens

    def __init__(self, mode):
        super().__init__()
        self.mode = mode

    @_("factor")
    def expr(self, p):
        return p.factor

    @_("expr PLUS factor")
    def expr(self, p):
        return p.expr + p.factor

    @_("expr MINUS factor")
    def expr(self, p):
        return p.expr - p.factor

    @_("atom")
    def factor(self, p):
        return p.atom

    @_("MINUS atom")
    def factor(self, p):
        return -p.atom

    @_("atom D atom")
    def factor(self, p):
        if not p.atom1:
            return 0
        if self.mode is DEvalMode.normal:
            return sum(random.randrange(1, p.atom1 + 1) for i in range(p.atom0))
        else:
            return p.atom0 * (p.atom1 + 1) / 2

    @_("NUMBER")
    def atom(self, p):
        return int(p.NUMBER)

    @_("LPAREN expr RPAREN")
    def atom(self, p):
        return p.expr

    class ParserError(RuntimeError):
        pass

    class EOFError(ParserError):
        pass

    def error(self, p):
        if not p:
            raise self.EOFError()
        raise self.ParserError()


def d_eval(str, mode=DEvalMode.normal):
    if not str:
        return None
    return int(DParser(mode).parse(DLexer().tokenize(str)))


@dataclasses.dataclass
class Creature:
    name: str = ""
    initiative: int = None
    evaluated_max_hp: int = None
    max_hp_generator: str = ""
    damage_taken: int = 0
    death_saves_success: int = 0
    death_saves_failure: int = 0
    tags: list = dataclasses.field(default_factory=list)
    completed_round: int = -1
    xp: int = None

    @property
    def max_hp(self):
        if self.evaluated_max_hp is None:
            self.evaluated_max_hp = d_eval(self.max_hp_generator)
            if self.evaluated_max_hp is not None:
                self.damage_taken = min(self.evaluated_max_hp, self.damage_taken)
        return self.evaluated_max_hp

    def apply_damage(self, damage):
        if self.max_hp is not None:
            self.damage_taken = min(self.max_hp, max(0, self.damage_taken + damage))
        else:
            self.damage_taken = max(0, self.damage_taken + damage)

    def start_turn(self):
        self.tags = [(n, None if t is None else (t - 1)) for n, t in self.tags if t is None or t > 1]

    def end_turn(self):
        pass

    def to_json(self):
        return self.__dict__

    @classmethod
    def from_json(cls, data):
        data.pop("hp", None)
        obj = cls(**data)
        obj.tags = [tuple(t) for t in obj.tags]
        return obj

    def clone(self):
        creature = self.from_json(self.to_json())
        creature.evaluated_max_hp = None
        return creature

    def __hash__(self):
        return id(self)


class DValidator(QtGui.QValidator):
    def __init__(self, *args, allow_empty=False):
        super().__init__(*args)
        self.allow_empty = allow_empty

    def validate(self, input, pos):
        if not input and self.allow_empty:
            return (QtGui.QValidator.Acceptable, input, pos)
        try:
            d_eval(input)
        except DLexer.LexerError:
            return (QtGui.QValidator.Invalid, input, pos)
        except DParser.EOFError:
            return (QtGui.QValidator.Intermediate, input, pos)
        except DParser.ParserError:
            return (QtGui.QValidator.Intermediate, input, pos)
        return (QtGui.QValidator.Acceptable, input, pos)


class CreatureDialog(QtWidgets.QDialog):
    def __init__(self, *args, title="Edit Creature", creature=None):
        super().__init__(*args)

        self.creature = creature or Creature()
        self.setWindowTitle(title)

        self.setLayout(QtWidgets.QGridLayout())

        self.name_label = QtWidgets.QLabel("Name:", self)
        self.layout().addWidget(self.name_label, 0, 0)

        self.name_edit = QtWidgets.QLineEdit(self.creature.name, self)
        self.layout().addWidget(self.name_edit, 0, 1)
        self.name_edit.textChanged.connect(self.set_ok_enabled)

        self.max_hp_label = QtWidgets.QLabel("Max HP:", self)
        self.layout().addWidget(self.max_hp_label, 1, 0)

        self.max_hp_edit = QtWidgets.QLineEdit(self.creature.max_hp_generator, self)
        self.max_hp_edit.setValidator(DValidator(self, allow_empty=True))
        self.layout().addWidget(self.max_hp_edit, 1, 1)
        self.max_hp_edit.textChanged.connect(self.set_ok_enabled)

        self.xp_label = QtWidgets.QLabel("XP:", self)
        self.layout().addWidget(self.xp_label, 2, 0)

        self.xp_edit = QtWidgets.QLineEdit(str(self.creature.xp) if self.creature.xp is not None else "", self)
        self.xp_edit.setValidator(QtGui.QIntValidator(0, 1000000, self))
        self.layout().addWidget(self.xp_edit, 2, 1)

        self.buttonbox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        self.layout().addWidget(self.buttonbox, 100, 0, 1, 2)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)

        self.set_ok_enabled()

    def set_ok_enabled(self):
        if not self.name_edit.text() or not self.max_hp_edit.hasAcceptableInput():
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        else:
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)

    def accept(self):
        self.creature.name = self.name_edit.text()
        self.creature.xp = int(self.xp_edit.text()) if self.xp_edit.text() else None
        if self.creature.max_hp_generator != self.max_hp_edit.text():
            self.creature.max_hp_generator = self.max_hp_edit.text()
            self.creature.evaluated_max_hp = None
        super().accept()


class DamageDialog(QtWidgets.QDialog):
    def __init__(self, *args, title=None, heal=False):
        super().__init__(*args)

        self.setWindowTitle(title if title is not None else ["Damage Creatures", "Heal Creatures"][heal])
        self.heal = heal

        self.setLayout(QtWidgets.QGridLayout())

        self.damage_label = QtWidgets.QLabel(["Damage:", "Healing:"][heal], self)
        self.layout().addWidget(self.damage_label, 0, 0)

        self.damage_edit = QtWidgets.QLineEdit(self)
        self.damage_edit.setValidator(DValidator(self))
        self.layout().addWidget(self.damage_edit, 0, 1)
        self.damage_edit.textChanged.connect(self.set_ok_enabled)

        self.buttonbox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        self.layout().addWidget(self.buttonbox, 100, 0, 1, 2)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)

        self.set_ok_enabled()

    def set_ok_enabled(self):
        if not self.damage_edit.hasAcceptableInput():
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        else:
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)

    def accept(self):
        self.damage = d_eval(self.damage_edit.text())
        if self.heal:
            self.damage *= -1
        super().accept()


class InitiativeDialog(QtWidgets.QDialog):
    def __init__(self, *args, title="Set Initiative"):
        super().__init__(*args)

        self.setWindowTitle(title)

        self.setLayout(QtWidgets.QGridLayout())

        self.initiative_label = QtWidgets.QLabel("Initiative:", self)
        self.layout().addWidget(self.initiative_label, 0, 0)

        self.initiative_edit = QtWidgets.QLineEdit(self)
        self.initiative_edit.setValidator(DValidator(self, allow_empty=True))
        self.layout().addWidget(self.initiative_edit, 0, 1)
        self.initiative_edit.textChanged.connect(self.set_ok_enabled)

        self.buttonbox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        self.layout().addWidget(self.buttonbox, 100, 0, 1, 2)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)

        self.set_ok_enabled()

    def set_ok_enabled(self):
        if not self.initiative_edit.hasAcceptableInput():
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        else:
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)

    def accept(self):
        self.initiative = d_eval(self.initiative_edit.text())
        super().accept()


class TagDialog(QtWidgets.QDialog):
    def __init__(self, *args, title="Add Tag", creature=None):
        super().__init__(*args)

        self.setWindowTitle(title)

        self.setLayout(QtWidgets.QGridLayout())

        self.name_label = QtWidgets.QLabel("Name:", self)
        self.layout().addWidget(self.name_label, 0, 0)

        self.name_edit = QtWidgets.QLineEdit(self)
        self.name_completer = QtWidgets.QCompleter(TAG_COMPLETIONS, self)
        self.name_completer.setModelSorting(QtWidgets.QCompleter.CaseSensitivelySortedModel)
        self.name_completer.activated.connect(self.on_completion_used)
        self.name_edit.setCompleter(self.name_completer)
        self.layout().addWidget(self.name_edit, 0, 1)
        self.name_edit.textChanged.connect(self.set_ok_enabled)

        self.rounds_label = QtWidgets.QLabel("Rounds:", self)
        self.layout().addWidget(self.rounds_label, 1, 0)

        self.rounds_edit = QtWidgets.QLineEdit(self)
        self.rounds_edit.setValidator(QtGui.QIntValidator(0, 1000000, self))
        self.layout().addWidget(self.rounds_edit, 1, 1)

        self.buttonbox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        self.layout().addWidget(self.buttonbox, 100, 0, 1, 2)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)

        self.set_ok_enabled()

    def set_ok_enabled(self):
        if not self.name_edit.hasAcceptableInput():
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        else:
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)

    def on_completion_used(self, text):
        self.rounds_edit.setText(str(DURATION_FOR_TAG.get(text, "")))

    def accept(self):
        self.tag = self.name_edit.text(), int(self.rounds_edit.text()) if self.rounds_edit.text() else None
        super().accept()


class TagRemoveDialog(QtWidgets.QDialog):
    def __init__(self, *args, title="Remove Tags", tags):
        super().__init__(*args)

        self.setWindowTitle(title)

        self.setLayout(QtWidgets.QGridLayout())

        self.tags_view = QtWidgets.QListView(self)
        self.tags_view.setModel(QtGui.QStandardItemModel(self))
        self.tags_view.selectionModel().selectionChanged.connect(self.set_ok_enabled)
        self.tags_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tags_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.layout().addWidget(self.tags_view, 0, 0)

        self.tags = sorted(tags)

        for tag, rounds in self.tags:
            self.tags_view.model().appendRow(QtGui.QStandardItem(tag if rounds is None else f"{tag}: {rounds}r"))

        self.buttonbox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        self.layout().addWidget(self.buttonbox, 100, 0)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)

        selection = QtCore.QItemSelection()
        selection.select(self.tags_view.model().index(0, 0), self.tags_view.model().index(0, 0))
        self.tags_view.selectionModel().select(selection, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows | QtCore.QItemSelectionModel.Clear)

        self.set_ok_enabled()

    def set_ok_enabled(self):
        if not self.tags_view.selectedIndexes():
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        else:
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)

    def accept(self):
        self.tags = [self.tags[idx.row()] for idx in self.tags_view.selectedIndexes()]
        super().accept()


class TimeWarpDialog(QtWidgets.QDialog):
    def __init__(self, *args, title="Time Warp", creature=None):
        super().__init__(*args)

        self.setWindowTitle(title)

        self.setLayout(QtWidgets.QGridLayout())

        self.time_label = QtWidgets.QLabel("Time:", self)
        self.layout().addWidget(self.time_label, 1, 0)

        self.time_edit = QtWidgets.QLineEdit(self)
        self.time_edit.setValidator(QtGui.QIntValidator(0, 1000000, self))
        self.time_edit.textChanged.connect(self.set_ok_enabled)
        self.layout().addWidget(self.time_edit, 1, 1)

        self.buttonbox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        self.layout().addWidget(self.buttonbox, 100, 0, 1, 2)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)

        self.set_ok_enabled()

    def set_ok_enabled(self):
        if not self.time_edit.hasAcceptableInput():
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        else:
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)

    def accept(self):
        self.time = int(self.time_edit.text())
        super().accept()


class QACDialog(QtWidgets.QDialog):
    def __init__(self, *args, title="QAC", creature=None):
        super().__init__(*args)

        self.setWindowTitle(title)

        self.setLayout(QtWidgets.QGridLayout())

        self.qac_edit = QtWidgets.QPlainTextEdit(self)
        self.qac_edit.textChanged.connect(self.set_ok_enabled)
        self.layout().addWidget(self.qac_edit, 0, 0)

        self.buttonbox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        self.layout().addWidget(self.buttonbox, 100, 0, 1, 2)
        self.buttonbox.accepted.connect(self.accept)
        self.buttonbox.rejected.connect(self.reject)

        self.set_ok_enabled()

    def set_ok_enabled(self):
        if not self.qac_edit.toPlainText():
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        else:
            self.buttonbox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)

    def accept(self):
        self.qac = self.qac_edit.toPlainText()
        super().accept()


class CreatureListDelegate(QtWidgets.QStyledItemDelegate):
    NAME_WIDTH = 250
    HP_WIDTH = 75
    INITIATIVE_WIDTH = 50
    TURN_MARKER_WIDTH = 24
    DEATH_SAVES_WIDTH = 40
    DEATH_SAVE_WIDTH = 10

    LARGE_FONT_SIZE = 18

    def sizeHint(self, option, index):
        return QtCore.QSize(option.rect.width(), 30)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtCore.Qt.black)
        creature = index.data(QtCore.Qt.UserRole)
        is_current = creature.completed_round < self.parent().current_round and self.parent().current_creature() is creature
        normal_font = painter.font()
        larger_font = QtGui.QFont(normal_font)
        larger_font.setPixelSize(self.LARGE_FONT_SIZE)
        metrics = QtGui.QFontMetricsF(normal_font)
        larger_metrics = QtGui.QFontMetricsF(larger_font)
        rect = option.rect
        along = 0
        if is_current:
            QtGui.QIcon.fromTheme("go-next-symbolic").paint(painter,
                                                            QtCore.QRect(rect.topLeft() + QtCore.QPoint(along, 0),
                                                                         rect.bottomLeft() + QtCore.QPoint(self.TURN_MARKER_WIDTH + along, 0)))

        along += self.TURN_MARKER_WIDTH
        if creature.initiative is not None:
            painter.setFont(larger_font)
            painter.drawText(QtCore.QRectF(rect.topLeft() + QtCore.QPoint(along, 0),
                                           rect.bottomLeft() + QtCore.QPoint(self.INITIATIVE_WIDTH + along, 0)),
                         QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter,
                         str(creature.initiative))
            painter.setFont(normal_font)

        along += self.INITIATIVE_WIDTH
        painter.drawText(QtCore.QRectF(rect.topLeft() + QtCore.QPoint(along, 0),
                                       rect.bottomLeft() + QtCore.QPoint(self.NAME_WIDTH + along, 0)),
                         QtCore.Qt.AlignVCenter,
                         metrics.elidedText(creature.name, QtCore.Qt.ElideMiddle, self.NAME_WIDTH))

        along += self.NAME_WIDTH
        if creature.max_hp is not None:
            hp = max(0, min(creature.max_hp, creature.max_hp - creature.damage_taken))
            ratio = hp / creature.max_hp if creature.max_hp else 0
            if hp <= 0:
                color = QtCore.Qt.red
            elif ratio <= 0.5:
                color = QtCore.Qt.darkYellow
            elif hp < creature.max_hp:
                color = QtCore.Qt.darkGreen
            else:
                color = QtCore.Qt.green

            painter.setPen(color)
            first_width = larger_metrics.width(str(hp))
            painter.setFont(larger_font)
            painter.drawText(QtCore.QRectF(rect.topLeft() + QtCore.QPointF(along, 0),
                                           rect.bottomLeft() + QtCore.QPointF(self.HP_WIDTH + along, 0)),
                             QtCore.Qt.AlignVCenter,
                             str(hp))
            painter.setFont(normal_font)
            painter.drawText(QtCore.QRectF(rect.topLeft() + QtCore.QPointF(along + first_width, (larger_metrics.height() - metrics.height()) / 2),
                                           rect.bottomLeft() + QtCore.QPointF(self.HP_WIDTH + along, 0)),
                             QtCore.Qt.AlignVCenter,
                             metrics.elidedText(f" / {creature.max_hp}", QtCore.Qt.ElideRight, self.HP_WIDTH - first_width))
        elif creature.damage_taken:
            painter.setPen(QtCore.Qt.darkRed)
            painter.drawText(QtCore.QRectF(rect.topLeft() + QtCore.QPointF(along, 0),
                                           rect.bottomLeft() + QtCore.QPointF(self.HP_WIDTH + along, 0)),
                             QtCore.Qt.AlignVCenter,
                             f"HP - {creature.damage_taken}")

        along += self.HP_WIDTH
        painter.setPen(QtCore.Qt.transparent)
        if creature.death_saves_success or creature.death_saves_failure:
            width_per_dot = self.DEATH_SAVE_WIDTH
            height_per_dot = rect.height() / 2
            dot_size = min(width_per_dot, height_per_dot) - 2
            for y in range(2):
                for x in range(3):
                    if x < (creature.death_saves_failure if y else creature.death_saves_success):
                        painter.setBrush(QtCore.Qt.darkRed if y else QtCore.Qt.darkGreen)
                    else:
                        painter.setBrush(QtGui.QColor(0, 0, 0, 30))
                    point = rect.topLeft() + QtCore.QPointF(along + width_per_dot * (x + 0.5), height_per_dot * (y + 0.5))
                    painter.drawEllipse(QtCore.QRectF(point - QtCore.QPointF(dot_size / 2, dot_size / 2),
                                                      point + QtCore.QPointF(dot_size / 2, dot_size / 2)))
            painter.setPen(QtCore.Qt.black)

        along += self.DEATH_SAVES_WIDTH

        remaining_width = rect.width() - along

        tags = []
        for name, time_left in creature.tags:
            if time_left is None:
                tags.append((name, COLOR_FOR_TAG.get(name, QtCore.Qt.darkGray)))
            else:
                tags.append((f"{name}: {time_left}r", COLOR_FOR_TAG.get(name, QtCore.Qt.darkGray)))
        if creature.xp:
            tags.append((f"XP: {creature.xp}", QtCore.Qt.darkBlue))

        if tags:
            tags.sort()
            height = metrics.height() + 4
            height_adj = (rect.height() - height) // 2
            along += 2
            widths = [metrics.width(t) for t, _ in tags]
            while sum(widths) + (len(tags) * 6) + 1 > remaining_width:
                widths[widths.index(max(widths))] -= 1

            for width, (text, color) in zip(widths, tags):
                trect = QtCore.QRectF(rect.topLeft() + QtCore.QPointF(along, 0),
                                      rect.bottomLeft() + QtCore.QPointF(width + 4 + along, 0))
                trect = trect.adjusted(0, height_adj, 0, -height_adj)
                painter.setBrush(color)
                painter.setPen(color)
                painter.drawRoundedRect(trect, 4, 4)
                painter.setPen(QtCore.Qt.white)
                painter.drawText(trect.adjusted(2, 0, -2, 0),
                                 QtCore.Qt.AlignVCenter,
                                 metrics.elidedText(text, QtCore.Qt.ElideRight, width))
                along += width + 6


class CreatureListSortModel(QtCore.QSortFilterProxyModel):
    def lessThan(self, left, right):
        lcreature, rcreature = left.data(QtCore.Qt.UserRole), right.data(QtCore.Qt.UserRole)
        if rcreature.initiative is None:
            return False
        if lcreature.initiative is None:
            return True
        if lcreature.initiative == rcreature.initiative:
            return lcreature.name < rcreature.name
        return lcreature.initiative < rcreature.initiative


class InitApp(flyingcarpet.App):
    NAME = "Bazooka"
    LAUNCHER_NAME = "bazooka"
    GENERIC_NAME = "Initiative Tracker"
    DESCRIPTION = "D&D Initiative and Combat Tracker"
    VERSION = (0, 1)
    ICON = "view-list-symbolic"
    CATEGORIES = set()
    SUBCATEGORIES = set()
    ADD_PREFIX = False

    def __init__(self, creatures=[], fname=None):
        super().__init__(maximized=True, with_toolbar=True)

        self.creature_list = QtWidgets.QListView(self)
        self.creature_model = QtGui.QStandardItemModel(self)
        self.creature_sort_model = CreatureListSortModel(self)
        self.creature_sort_model.setSourceModel(self.creature_model)
        self.creature_sort_model.sort(0, QtCore.Qt.DescendingOrder)
        self.creature_list.setModel(self.creature_sort_model)
        self.creature_list.setItemDelegate(CreatureListDelegate(self))
        self.creature_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.creature_list.setResizeMode(QtWidgets.QListView.Adjust)
        self.creature_list.setUniformItemSizes(True)
        self.creature_list.setAlternatingRowColors(True)
        self.creature_list.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.creature_list.doubleClicked.connect(self.edit_creature)
        self.centralWidget().layout().addWidget(self.creature_list)

        self.add_creature_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("list-add"), "Add Creature")
        self.add_creature_action.setShortcut(QtCore.Qt.Key_Insert)
        self.add_creature_action.triggered.connect(self.add_creature_dialog)
        self.toolBar.addAction(self.add_creature_action)

        self.clone_creature_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("list-add"), "Clone Creature")
        self.clone_creature_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.Key_C)
        self.clone_creature_action.triggered.connect(self.clone_selected_creature)
        self.toolBar.addAction(self.clone_creature_action)

        self.remove_creatures_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("list-remove"), "Remove Creatures")
        self.remove_creatures_action.setShortcut(QtCore.Qt.Key_Delete)
        self.remove_creatures_action.triggered.connect(self.remove_selected_creatures)
        self.toolBar.addAction(self.remove_creatures_action)

        self.damage_creatures_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("crosshairs"), "Damage Creatures")
        self.damage_creatures_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.Key_D)
        self.damage_creatures_action.triggered.connect(self.damage_selected_creatures)
        self.toolBar.addAction(self.damage_creatures_action)

        self.heal_creatures_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("smiley-add"), "Heal Creatures")
        self.heal_creatures_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.Key_H)
        self.heal_creatures_action.triggered.connect(lambda: self.damage_selected_creatures(heal=True))
        self.toolBar.addAction(self.heal_creatures_action)

        self.set_initiative_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("clock"), "Set Initiative")
        self.set_initiative_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.Key_I)
        self.set_initiative_action.triggered.connect(self.set_initiative_for_selected_creatures)
        self.toolBar.addAction(self.set_initiative_action)

        self.add_tag_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("tag"), "Add Tag")
        self.add_tag_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.Key_T)
        self.add_tag_action.triggered.connect(self.add_tag_to_selected_creatures)
        self.toolBar.addAction(self.add_tag_action)

        self.remove_tags_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("tag-delete"), "Remove Tags")
        self.remove_tags_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.Key_R)
        self.remove_tags_action.triggered.connect(self.remove_tags_from_selected_creatures)
        self.toolBar.addAction(self.remove_tags_action)

        self.next_turn_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("go-next-symbolic"), "Next Turn")
        self.next_turn_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.Key_N)
        self.next_turn_action.triggered.connect(self.next_turn)
        self.toolBar.addAction(self.next_turn_action)

        self.quikaddcode_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("format-text-code"), "QA Code")
        self.quikaddcode_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.Key_Insert)
        self.quikaddcode_action.triggered.connect(self.quikaddcode)
        self.toolBar.addAction(self.quikaddcode_action)

        self.toolBar.addSeparator()

        self.info_label = QtWidgets.QLabel(self)
        self.toolBar.addWidget(self.info_label)
        self.toolBar.setStyleSheet("QLabel { padding: 8px; }")

        self.info_timer = QtCore.QTimer(self)
        self.info_timer.timeout.connect(self.update_info_label)
        self.info_timer.start(60 * 1000)

        self.file_menu = QtWidgets.QMenu("File", self.menuBar)
        self.menuBar.addMenu(self.file_menu)

        self.open_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("document-open"), "Open")
        self.open_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.Key_O)
        self.open_action.triggered.connect(self.load)
        self.file_menu.addAction(self.open_action)

        self.save_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("document-save"), "Save")
        self.save_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.Key_S)
        self.save_action.triggered.connect(self.save)
        self.file_menu.addAction(self.save_action)

        self.file_menu.addSeparator()

        self.load_creatures_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("document-open"), "Load Creatures")
        self.load_creatures_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.SHIFT | QtCore.Qt.Key_O)
        self.load_creatures_action.triggered.connect(self.load_creatures)
        self.file_menu.addAction(self.load_creatures_action)

        self.advanced_menu = QtWidgets.QMenu("Advanced", self.menuBar)
        self.menuBar.addMenu(self.advanced_menu)

        self.remove_creatures_noxp_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("list-remove"), "Remove Creatures without granting XP")
        self.remove_creatures_noxp_action.setShortcut(QtCore.Qt.SHIFT | QtCore.Qt.Key_Delete)
        self.remove_creatures_noxp_action.triggered.connect(lambda: self.remove_selected_creatures(noxp=True))
        self.advanced_menu.addAction(self.remove_creatures_noxp_action)

        self.advanced_menu.addSeparator()

        self.add_death_save_success_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("emblem-success"), "Add Death Save Success")
        self.add_death_save_success_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.SHIFT | QtCore.Qt.Key_S)
        self.add_death_save_success_action.triggered.connect(lambda: self.add_death_save_to_selected_creatures(success=True))
        self.advanced_menu.addAction(self.add_death_save_success_action)

        self.add_death_save_failure_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("emblem-error"), "Add Death Save Failure")
        self.add_death_save_failure_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.SHIFT | QtCore.Qt.Key_F)
        self.add_death_save_failure_action.triggered.connect(lambda: self.add_death_save_to_selected_creatures(success=False))
        self.advanced_menu.addAction(self.add_death_save_failure_action)

        self.clear_death_saves_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("edit-clear-all"), "Clear Death Saves")
        self.clear_death_saves_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.SHIFT | QtCore.Qt.Key_C)
        self.clear_death_saves_action.triggered.connect(self.clear_death_saves_from_selected_creatures)
        self.advanced_menu.addAction(self.clear_death_saves_action)

        self.advanced_menu.addSeparator()

        self.time_warp_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("media-skip-forward-symbolic"), "Time Warp")
        self.time_warp_action.setShortcut(QtCore.Qt.CTRL | QtCore.Qt.SHIFT | QtCore.Qt.Key_T)
        self.time_warp_action.triggered.connect(self.time_warp)
        self.advanced_menu.addAction(self.time_warp_action)

        self.reset_start_time_action = QtWidgets.QAction(QtGui.QIcon.fromTheme("clock"), "Reset Timer")
        self.reset_start_time_action.triggered.connect(self.reset_start_time)
        self.advanced_menu.addAction(self.reset_start_time_action)

        self.ret_shortcut = QtWidgets.QShortcut(QtCore.Qt.Key_Return, self)
        self.ret_shortcut.activated.connect(self.edit_selected_creature)

        for creature in creatures:
            self.add_creature(creature)
        if fname is None:
            self.fname = str((SAVES_DIR / datetime.datetime.now().strftime("%H:%M %d-%m-%Y.json")).resolve())
            self._current_round = -1
            self.start_time = time.time()
            self.xp_gained = 0
        else:
            self.load(fname=fname)

    @property
    def fname(self):
        return self._fname

    @fname.setter
    def fname(self, value):
        self._fname = value
        self.setWindowTitle(f"{self.NAME} - {pathlib.Path(self.fname).stem}")

    @property
    def current_round(self):
        return self._current_round

    @current_round.setter
    def current_round(self, value):
        self._current_round = value
        self.update_info_label()

    @property
    def xp_gained(self):
        return self._xp_gained

    @xp_gained.setter
    def xp_gained(self, value):
        self._xp_gained = value
        self.update_info_label()

    @property
    def creatures(self):
        return [idx.data(QtCore.Qt.UserRole) for idx in self.creature_indexes]

    @property
    def creature_indexes(self):
        return [self.creature_sort_model.mapToSource(self.creature_sort_model.index(row, 0)) for row in range(self.creature_sort_model.rowCount())]

    @property
    def creatures_to_index(self):
        return {idx.data(QtCore.Qt.UserRole): idx for idx in self.creature_indexes}

    @property
    def selected_creatures(self):
        return [idx.data(QtCore.Qt.UserRole) for idx in self.creature_list.selectedIndexes()]

    @property
    def selected_creatures_to_index(self):
        return {idx.data(QtCore.Qt.UserRole): idx for idx in self.creature_list.selectedIndexes()}

    def update_info_label(self):
        round = self.current_round if self.current_round > 0 else "Not yet started"
        time_passed = time.time() - self.start_time
        h, m = divmod(int(time_passed) // 60, 60)
        self.info_label.setText(f"Round: {round} | XP: {self.xp_gained} | {h}:{m:02}")

    def to_json(self):
        return {
            "creatures": [creature.to_json() for creature in self.creatures],
            "current_round": self.current_round,
            "xp_gained": self.xp_gained,
            "start_time": self.start_time
        }

    def add_creature_dialog(self):
        dia = CreatureDialog()
        if dia.exec_():
            self.add_creature(dia.creature)

    def add_creature(self, creature):
        item = QtGui.QStandardItem()
        item.setData(creature, QtCore.Qt.UserRole)
        self.creature_model.appendRow(item)

    def clone_selected_creature(self):
        for creature in self.selected_creatures:
            self.add_creature(creature.clone())

    def remove_selected_creatures(self, noxp=False):
        for creature, idx in sorted(self.selected_creatures_to_index.items(), reverse=True, key=lambda x: x[1]):
            self.creature_model.removeRow(self.creature_sort_model.mapToSource(idx).row())
            if not noxp:
                self.xp_gained += creature.xp or 0

    def damage_selected_creatures(self, heal=False):
        scti = self.selected_creatures_to_index
        if not scti:
            return

        dia = DamageDialog(self, heal=heal)
        if dia.exec_():
            print("Damage =>", dia.damage)
            for creature, idx in scti.items():
                creature.apply_damage(dia.damage)
                self.creature_model.itemFromIndex(self.creature_sort_model.mapToSource(idx)).emitDataChanged()

    def set_initiative_for_selected_creatures(self):
        scti = self.selected_creatures_to_index
        if not scti:
            return

        dia = InitiativeDialog(self)
        if dia.exec_():
            print("Initiative =>", dia.initiative)
            idxes = []
            for creature, idx in [(c, self.creature_model.itemFromIndex(self.creature_sort_model.mapToSource(i))) for c, i in scti.items()]:
                creature.initiative = dia.initiative
                idx.emitDataChanged()

    def edit_selected_creature(self):
        selected_idxs = self.creature_list.selectedIndexes()
        if selected_idxs:
            self.edit_creature(selected_idxs[0])

    def edit_creature(self, idx):
        dia = CreatureDialog(self, creature=idx.data(QtCore.Qt.UserRole))
        if dia.exec_():
            self.creature_model.itemFromIndex(self.creature_sort_model.mapToSource(idx)).emitDataChanged()

    def current_creature(self, creatures=None):
        if self.current_round < 1:
            return None
        creatures = self.creatures if creatures is None else creatures
        creatures_in_initiative = [c for c in creatures if c.initiative is not None]
        if not creatures_in_initiative:
            return None
        creatures_that_have_yet_to_go = [c for c in creatures_in_initiative if c.completed_round < self.current_round]
        return max(creatures_that_have_yet_to_go, key=lambda c: c.initiative) if creatures_that_have_yet_to_go else None

    def next_turn(self):
        creatures = self.creatures_to_index
        if self.current_round > 0:
            current = self.current_creature(creatures.keys())
            if not current:
                return
            current.end_turn()
            current.completed_round = self.current_round
            self.creature_model.itemFromIndex(creatures[current]).emitDataChanged()
        else:
            if not any(c.initiative is not None for c in creatures):
                return
            self.current_round = 1

        current = self.current_creature(creatures.keys())
        if not current:
            self.current_round += 1
            current = self.current_creature(creatures.keys())
        current.start_turn()
        self.creature_model.itemFromIndex(creatures[current]).emitDataChanged()
        self.select_indexes([self.creature_sort_model.mapFromSource(creatures[current])])

    def select_indexes(self, idxs, clear=True):
        selection = QtCore.QItemSelection()
        for index in idxs:
            selection.select(index, index)
        self.creature_list.selectionModel().select(selection, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows | (QtCore.QItemSelectionModel.Clear & clear))

    def add_tag_to_selected_creatures(self):
        scti = self.selected_creatures_to_index
        if not scti:
            return

        dia = TagDialog(self)
        if not dia.exec_():
            return

        for creature, idx in scti.items():
            if dia.tag not in creature.tags:
                creature.tags.append(dia.tag)
            self.creature_model.itemFromIndex(self.creature_sort_model.mapToSource(idx)).emitDataChanged()

    def remove_tags_from_selected_creatures(self):
        scti = self.selected_creatures_to_index
        if not scti:
            return

        tags = set.intersection(*[set(c.tags) for c in scti])
        if not tags:
            return

        dia = TagRemoveDialog(self, tags=tags)
        if not dia.exec_():
            return

        for creature, idx in scti.items():
            for tag in dia.tags:
                creature.tags.remove(tag)
            self.creature_model.itemFromIndex(self.creature_sort_model.mapToSource(idx)).emitDataChanged()

    def add_death_save_to_selected_creatures(self, success=True):
        for creature, idx in self.selected_creatures_to_index.items():
            if success:
                creature.death_saves_success = min(3, creature.death_saves_success + 1)
            else:
                creature.death_saves_failure = min(3, creature.death_saves_failure + 1)
            self.creature_model.itemFromIndex(self.creature_sort_model.mapToSource(idx)).emitDataChanged()

    def clear_death_saves_from_selected_creatures(self):
        for creature, idx in self.selected_creatures_to_index.items():
            creature.death_saves_success = creature.death_saves_failure = 0
            self.creature_model.itemFromIndex(self.creature_sort_model.mapToSource(idx)).emitDataChanged()

    def time_warp(self):
        dia = TimeWarpDialog(self)
        if not dia.exec_():
            return

        cl = len([c for c in self.creatures if c.initiative is not None])

        for _ in range(dia.time):
            for _ in range(cl):
                self.next_turn()

    def reset_start_time(self):
        self.start_time = time.time()
        self.update_info_label()

    def load(self, *, fname=None):
        if fname is None:
            fname = QtWidgets.QFileDialog.getOpenFileName(self, "Open", str(pathlib.Path(self.fname).parent), "Json Files (*.json)")[0]
            if not fname:
                return

        self.fname = fname
        with open(fname) as f:
            data = json.load(f)

        self.creature_model.clear()
        for creature in data["creatures"]:
            self.add_creature(Creature.from_json(creature))
        self.current_round = data.get("current_round", 1)
        self.xp_gained = data.get("xp_gained", 0)
        self.start_time = data.get("start_time", time.time())
        self.update_info_label()

    def load_creatures(self):
        fname = QtWidgets.QFileDialog.getOpenFileName(self, "Open", str(pathlib.Path(self.fname).parent), "Json Files (*.json)")[0]
        if not fname:
            return

        with open(fname) as f:
            data = json.load(f)

        for creature in data["creatures"]:
            creature = Creature.from_json(creature)
            creature.hp = creature.initiative = None
            creature.death_saves_success = creature.death_saves_failure = 0
            creature.completed_round = -1
            self.add_creature(creature)

    def save(self):
        fname = QtWidgets.QFileDialog.getSaveFileName(self, "Save", self.fname, "Json Files (*.json)")
        if fname[0]:
            self.fname = fname[0]
            with open(fname[0], "w") as f:
                json.dump(self.to_json(), f, indent=4)

    def quikaddcode(self):
        dia = QACDialog(self)
        if not dia.exec_():
            return
        code = [x.strip() for x in re.split("[;\n]", dia.qac) if x.strip()]
        code = [(x[0], x[1:].strip()) for x in code]
        creatures = []
        hp_de_mode = DEvalMode.normal
        try:
            for op, arg in code:
                if op == "a":
                    creatures.append(Creature(name=arg))
                elif op == "h":
                    val = d_eval(arg, mode=hp_de_mode)
                    if hp_de_mode is DEvalMode.normal:
                        creatures[-1].max_hp_generator = arg
                    else:
                        creatures[-1].max_hp_generator = str(val)
                elif op == "i":
                    creatures[-1].initiative = d_eval(arg)
                elif op == "x":
                    creatures[-1].xp = int(arg)
                elif op == "c":
                    for _ in range(int(arg)):
                        creatures.append(creatures[-1].clone())
                elif op == "t":
                    if ":" in arg:
                        tag, rounds = arg.split(":", 1)
                        rounds = int(rounds)
                    else:
                        tag, rounds = arg, None
                    creatures[-1].tags.append((tag, rounds))
                elif op == "s":
                    sheet, name = arg.split(":", 1)
                    data = load_stat_from_sheet(sheet, name)
                    tags = []
                    for tag in data.get("tags", []):
                        if ":" in tag:
                            tag, rounds = tag.split(":", 1)
                            rounds = int(rounds)
                        else:
                            tag, rounds = tag, None
                        tags.append((tag, rounds))
                    init = d_eval(data.get("init"))
                    hp = data["hp"] if hp_de_mode is DEvalMode.normal else str(d_eval(data["hp"], mode=hp_de_mode))
                    creatures.append(Creature(name=name, max_hp_generator=hp, xp=data.get("xp"), initiative=init, tags=tags))
                elif op == "e":
                    if arg == "hn":
                        hp_de_mode = DEvalMode.normal
                    elif arg == "ha":
                        hp_de_mode = DEvalMode.average

        except Exception:
            QtWidgets.QMessageBox.warning(self, "QAC Failed", "".join(traceback.format_exc()), QtWidgets.QMessageBox.Ok)
        else:
            for creature in creatures:
                if not creature.max_hp_generator:
                    creature.max_hp_generator = "1"
                self.add_creature(creature)


if __name__ == "__main__":
    import docopt
    import json

    args = docopt.docopt(__doc__)

    InitApp(fname=args["<file>"]).run()
