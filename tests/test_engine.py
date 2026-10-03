"""The engine, checked against the mechanics the brief specifies."""

from pathlib import Path

import pytest

from lyo.engine import Engine
from lyo.lang.check import check

WORLD = Path(__file__).parent.parent / "world" / "kairos.md"


@pytest.fixture(scope="module")
def world():
    report = check(WORLD)
    assert report.ok
    return report.world


@pytest.fixture
def game(world):
    engine = Engine(world, seed=7)
    engine.register("u1", "Brynn", "Warrior")
    return engine


def texts(outcome):
    return " ".join(m.text for m in outcome.messages)


# ------------------------------------------------------------ registration

def test_starting_state_matches_the_class_kit(game):
    p = game.sim.players["u1"]
    assert (p.hp, p.max_hp, p.gold) == (20, 20, 10)
    assert p.stats == {"str": 8, "agi": 5, "int": 3}
    assert (p.mp, p.max_mp) == (5, 5)
    #  The kit equips on arrival: a Warrior is not holding an unused shield.
    assert p.equipped == {"weapon": "Iron Sword", "shield": "Wooden Shield"}
    assert p.inventory == {"Health Potion": 2}


def test_registering_twice_is_refused(game):
    assert game.register("u1", "Other", "Mage").refused


def test_unregistered_player_is_told_to_register(game):
    assert game.command("u9", "look").refused


# ------------------------------------------------------------------ combat

def test_attack_power_is_weapon_plus_half_the_scaling_stat(game):
    game.command("u1", "travel north")
    out = game.command("u1", "attack wolf")
    #  Iron Sword 4 + str 8 // 2 == 8
    assert "for 8" in texts(out)


def test_every_living_monster_retaliates(game):
    game.command("u1", "travel north")
    out = texts(game.command("u1", "attack wolf"))
    #  Goblin (3-2) + Wolf (6-2) == 5, reported once, with both named.
    assert "Goblin Scout and Dire Wolf" in out and ": 5." in out


def test_retaliation_is_silent_when_nothing_is_left(game):
    game.command("u1", "travel south")
    game.command("u1", "travel east")  # Kingsroad, one Bandit
    for _ in range(4):
        out = texts(game.command("u1", "attack bandit"))
    assert "Retaliation" not in out


def test_bare_hands_use_the_default_weapon(game):
    game.command("u1", "travel north")
    #  Fists 1 + str 8 // 2 == 5
    assert "for 5" in texts(game.command("u1", "attack hands goblin"))


def test_monster_health_is_shared_between_players(game):
    game.register("u2", "Selene", "Mage")
    for uid in ("u1", "u2"):
        game.command(uid, "travel north")
    game.command("u1", "attack wolf")
    wolf = game.sim.rooms["Whispering Woods"]["Dire Wolf"]
    assert wolf.hp == 10
    assert "leaving Dire Wolf on 3" in texts(game.command("u2", "attack wolf"))


def test_a_fallen_player_cannot_attack(game):
    game.command("u1", "travel north")
    game.sim.players["u1"].hp = 0
    assert game.command("u1", "attack wolf").refused


def test_casting_spends_magic_and_scales_off_intellect(game):
    game.register("u2", "Selene", "Mage")
    game.command("u2", "travel north")
    out = texts(game.command("u2", "cast goblin"))
    #  3 + int 9 // 2 == 7
    assert "for 7" in out
    assert game.sim.players["u2"].mp == 15


# -------------------------------------------------------------------- loot

def test_solo_kill_gives_everything_to_the_killer(game):
    game.command("u1", "travel north")
    for _ in range(3):
        game.command("u1", "attack wolf")
    p = game.sim.players["u1"]
    assert p.inventory.get("Wolf Pelt") == 1
    assert p.gold > 10


def test_contributors_share_gold_and_each_get_the_items(game):
    game.register("u2", "Selene", "Mage")
    for uid in ("u1", "u2"):
        game.command(uid, "travel north")
    before = {uid: game.sim.players[uid].gold for uid in ("u1", "u2")}
    game.command("u1", "attack wolf")   # u1 contributes
    game.command("u2", "attack wolf")   # u2 contributes
    game.command("u2", "attack wolf")   # u2 lands the kill

    for uid in ("u1", "u2"):
        p = game.sim.players[uid]
        assert p.inventory.get("Wolf Pelt") == 1, "items are not divided"
        assert p.gold > before[uid], "gold is shared with contributors"


def test_a_contributor_who_left_still_gets_a_share(game):
    game.register("u2", "Selene", "Mage")
    for uid in ("u1", "u2"):
        game.command(uid, "travel north")
    game.command("u1", "attack wolf")
    before = game.sim.players["u1"].gold
    game.command("u1", "travel south")  # walks away mid-fight
    for _ in range(3):
        game.command("u2", "attack wolf")
    assert game.sim.players["u1"].gold > before
    assert game.sim.players["u1"].inventory.get("Wolf Pelt") == 1


# ----------------------------------------------------------------- respawn

def test_respawn_waits_until_the_room_is_empty(game):
    game.register("u2", "Selene", "Mage")
    for uid in ("u1", "u2"):
        game.command(uid, "travel north")
    for _ in range(3):
        game.command("u1", "attack wolf")
    assert game.sim.rooms["Whispering Woods"]["Dire Wolf"].hp == 0

    game.command("u1", "travel south")
    game.command("u1", "travel north")  # u2 is still there, so nothing revives
    assert game.sim.rooms["Whispering Woods"]["Dire Wolf"].hp == 0

    for uid in ("u1", "u2"):
        game.command(uid, "travel south")
    game.command("u1", "travel north")  # now the room was empty
    assert game.sim.rooms["Whispering Woods"]["Dire Wolf"].hp == 18


# ---------------------------------------------------------------- items

def test_potions_work_and_are_refused_at_full_health(game):
    assert game.command("u1", "use potion").refused
    game.sim.players["u1"].hp = 5
    assert game.command("u1", "use potion")
    assert game.sim.players["u1"].hp == 13
    assert game.sim.players["u1"].inventory["Health Potion"] == 1


def test_mana_potions_work(game):
    game.register("u2", "Selene", "Mage")
    game.sim.players["u2"].mp = 4
    assert game.command("u2", "use mana potion")
    assert game.sim.players["u2"].mp == 12


def test_equipping_swaps_what_was_in_the_slot(game):
    p = game.sim.players["u1"]
    p.gold = 60
    game.command("u1", "buy buckler")
    game.command("u1", "equip buckler")
    assert p.equipped["shield"] == "Chipped Buckler"
    assert p.inventory.get("Wooden Shield") == 1, "the old shield comes back"


def test_shop_only_sells_what_it_stocks(game):
    game.sim.players["u1"].gold = 60
    assert game.command("u1", "buy chainmail").refused
    game.command("u1", "travel north")
    assert game.command("u1", "buy sling").refused


def test_resting_needs_an_inn(game):
    p = game.sim.players["u1"]
    p.hp, p.mp = 3, 0
    assert game.command("u1", "rest")
    assert (p.hp, p.mp) == (20, 5)
    assert game.command("u1", "rest").refused, "already rested"
    game.command("u1", "travel north")
    p.hp = 3
    assert game.command("u1", "rest").refused, "no inn in the woods"


# ---------------------------------------------------------------- growth

def test_attacking_grows_the_weapon_stat_and_being_hit_grows_health(game):
    game.command("u1", "travel north")
    game.command("u1", "attack wolf")
    p = game.sim.players["u1"]
    assert p.progress["str"] == 1
    assert p.progress["max_hp"] == 1


def test_casting_grows_the_spell_stat_and_max_magic(game):
    game.register("u2", "Selene", "Mage")
    game.command("u2", "travel north")
    game.command("u2", "cast wolf")
    p = game.sim.players["u2"]
    assert p.progress["int"] == 1
    assert p.progress["max_mp"] == 1


def test_a_track_raises_once_its_cost_is_paid(game):
    game.command("u1", "travel north")
    p = game.sim.players["u1"]
    for _ in range(5):
        game.command("u1", "attack wolf")
        p.hp = 20          # keep standing
        game.sim.rooms["Whispering Woods"]["Dire Wolf"].hp = 18
    #  max_hp costs 5 hits and raises by 2, topping up current health as well.
    assert p.max_hp == 22
    assert p.progress["max_hp"] == 0


# ----------------------------------------------------------------- duels

def _duel(game):
    game.register("u2", "Selene", "Mage")
    game.command("u1", "duel @u2")
    game.command("u2", "accept")
    return game.sim.duel_of("u1")


def test_a_duel_alternates_turns(game):
    duel = _duel(game)
    assert duel is not None and duel.turn == "u1"
    assert game.command("u2", "attack").refused, "not u2's turn"
    assert game.command("u1", "attack")
    assert game.sim.duel_of("u1").turn == "u2"


def test_duel_damage_is_reduced_by_armour(game):
    _duel(game)
    selene = game.sim.players["u2"]
    selene.equipped["shield"] = "Wooden Shield"   # 2 def
    before = selene.hp
    game.command("u1", "attack")
    assert before - selene.hp == 6, "8 attack less 2 defence"


def test_a_duel_ignores_the_room_and_nobody_hits_back(game):
    game.register("u2", "Selene", "Mage")
    for uid in ("u1", "u2"):
        game.command(uid, "travel north")   # a room full of monsters
    game.command("u1", "duel @u2")
    game.command("u2", "accept")
    before = game.sim.players["u1"].hp
    out = texts(game.command("u1", "attack"))
    assert "Retaliation" not in out
    assert game.sim.players["u1"].hp == before


def test_a_duel_ends_with_no_prize(game):
    _duel(game)
    game.sim.players["u2"].hp = 1
    out = texts(game.command("u1", "attack"))
    assert "no prize" in out
    assert game.sim.duel_of("u1") is None
    assert game.sim.players["u1"].gold == 10, "the winner gains nothing"


def test_declining_drops_the_challenge(game):
    game.register("u2", "Selene", "Mage")
    game.command("u1", "duel @u2")
    assert game.command("u2", "decline")
    assert game.sim.offers == []
    assert game.sim.duel_of("u1") is None


def test_a_challenge_expires(game):
    game.register("u2", "Selene", "Mage")
    game.command("u1", "duel @u2")
    notices = game.advance(61)
    assert any("expired" in m.text for m in notices)
    assert game.sim.offers == []
    assert game.command("u2", "accept").refused


def test_forfeiting_hands_the_win_over(game):
    _duel(game)
    out = texts(game.command("u1", "forfeit"))
    assert "Selene wins" in out
    assert game.sim.duel_of("u1") is None


def test_travel_is_blocked_inside_a_duel(game):
    _duel(game)
    assert game.command("u1", "travel north").refused


# ------------------------------------------------------------------ views

def test_look_reports_the_room(game):
    game.command("u1", "travel north")
    out = texts(game.command("u1", "look"))
    assert "Whispering Woods" in out
    assert "Goblin Scout (12/12)" in out


def test_unknown_command_is_reported_as_unknown(game):
    out = game.command("u1", "flibbertigibbet")
    assert out.unknown and not out.messages
