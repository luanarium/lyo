"""The resolve pass: binding names, and complaining usefully."""

from pathlib import Path

from gamebot.lang.check import check
from gamebot.lang.parser import parse
from gamebot.lang.resolve import ERROR, WARNING, resolve
from gamebot.lang.source import Source

WORLD = Path(__file__).parent.parent / "world"


def _resolve(text: str):
    source = Source(origin="t.game", text=text, raw=text)
    return resolve(parse(text), source)


PRELUDE = '''game "T":
  players start at "Home" with 20 hp, 10 gold

item "Fists" is the default weapon:
  1 damage scaling str

item "Clothes" is the default body armor:
  0 def

track str:
  advances when attacking with a weapon scaling str
  next point costs 5 uses
  raises str by 1
'''


def test_shipped_world_resolves_without_errors():
    report = check(WORLD / "kairos.md")
    assert report.ok, [d.format(report.source) for d in report.errors]
    assert report.world is not None


def test_shipped_world_counts():
    world = check(WORLD / "kairos.md").world
    assert len(world.locations) == 6
    assert len(world.monsters) == 5
    assert len(world.items) == 34
    assert len(world.classes) == 4
    assert len(world.tracks) == 5
    assert world.start_at.name == "Oakhaven Village"
    assert world.start_with == {"hp": 20, "gold": 10}


def test_every_drop_is_collected():
    """A bare `drops "X"` has no range and no chance; it must still count."""
    world = check(WORLD / "kairos.md").world
    goblin = world.monsters["Goblin Scout"]
    assert goblin.gold == (2, 5)
    assert {d.ref.name: d.chance for d in goblin.drops} == {
        "Goblin Ear": 100, "Rusty Cleaver": 10,
    }
    dragon = world.monsters["Young Red Dragon"]
    scale = next(d for d in dragon.drops if d.ref.name == "Dragon Scale")
    assert (scale.low, scale.high) == (1, 3)


def test_order_does_not_matter():
    """A location may name a monster declared further down the document."""
    result = _resolve(PRELUDE + '''
location "Home":
  spawns "Rat"

monster "Rat":
  3 hp, 1 str
  drops 1 to 2 gold
''')
    assert result.ok, [d.message for d in result.errors]


def test_unknown_name_suggests_a_near_miss():
    result = _resolve(PRELUDE + '''
location "Home":
  spawns "Dire Wolfe"

monster "Dire Wolf":
  18 hp, 6 str
  drops 1 to 2 gold
''')
    (bad,) = [d for d in result.diagnostics if d.code == "unknown-monster"]
    assert 'did you mean "Dire Wolf"' in bad.message


def test_two_way_exits_are_inferred_and_conflicts_caught():
    ok = _resolve(PRELUDE + '''
location "Home":
  north to "Field"

location "Field":
  "Open ground."
''')
    assert ok.ok
    field = ok.world.locations["Field"]
    assert [(e.direction, e.target.name, e.implied_from) for e in field.exits] == [
        ("south", "Home", "Home")
    ]

    clash = _resolve(PRELUDE + '''
location "Home":
  north to "Field"
  north to "Cave"

location "Field":
  "Open ground."

location "Cave":
  "Dark."
''')
    assert any(d.code == "exit-conflict" for d in clash.errors)


def test_one_way_exit_infers_no_return():
    result = _resolve(PRELUDE + '''
location "Home":
  one way north to "Pit"

location "Pit":
  "No way back."
''')
    assert result.world.locations["Pit"].exits == []


def test_duplicate_declaration_is_an_error():
    result = _resolve(PRELUDE + '''
location "Home":
  "Once."

location "Home":
  "Twice."
''')
    assert any(d.code == "duplicate" for d in result.errors)


def test_unpriced_shop_stock_is_an_error():
    result = _resolve(PRELUDE + '''
location "Home":
  has shop

item "Rock" is a weapon:
  1 damage scaling str

shop at "Home":
  stocks "Rock"
''')
    assert any(d.code == "unpriced" for d in result.errors)


def test_shop_without_the_feature_is_an_error():
    result = _resolve(PRELUDE + '''
location "Home":
  "No shop declared."

item "Rock" is a weapon:
  1 damage scaling str
  costs 2 gold

shop at "Home":
  stocks "Rock"
''')
    assert any(d.code == "shop-without-feature" for d in result.errors)


def test_orphan_item_is_only_a_warning():
    result = _resolve(PRELUDE + '''
location "Home":
  "Nothing here."

item "Unobtainable" is a weapon:
  1 damage scaling str
''')
    orphans = [d for d in result.diagnostics if d.code == "orphan-item"]
    assert [d.severity for d in orphans] == [WARNING]
    assert result.ok


def test_unknown_placeholder_is_flagged():
    result = _resolve(PRELUDE + '''
location "Home":
  "Here."

verb wave:
  public
  say "{playr} waves."
''')
    (bad,) = [d for d in result.diagnostics if d.code == "unknown-placeholder"]
    assert 'did you mean "player"' in bad.message


def test_syntax_error_is_reported_as_a_diagnostic_not_an_exception(tmp_path):
    broken = tmp_path / "broken.game"
    broken.write_text('item "X" is a weapon:\n  @@@\n')
    report = check(broken)
    assert [d.code for d in report.errors] == ["syntax"]
    assert report.world is None
