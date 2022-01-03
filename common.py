import sly
import dataclasses
import enum
import random


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

    @property
    def hp(self):
        if self.max_hp is not None:
            return max(0, min(self.max_hp, self.max_hp - self.damage_taken))

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
