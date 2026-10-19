from collections import Counter
from datetime import date

from core.normalize import GroupMatcher, contact_key
from core.reconcile import DASH, fill_gap_table, gap, verification_vs_visit


def test_gap_one_sided():
    assert gap(5, 3) == 2 and gap(3, 5) == 0 and gap(DASH, 1) == DASH


def test_fill_gap_red_and_total():
    t = fill_gap_table("t", "门店", [("a", "A店"), ("b", "B店")], [(["phone"], "电话数"), (["chat"], "后台咨询数")],
                       {"a": Counter(phone=2, chat=1), "b": Counter(phone=1)}, {"a": 1, "b": 3}, total_row=True)
    assert t.rows[0][-1] == 2 and (0, 4) in t.red_cells
    assert t.rows[1][-1] == 0 and (1, 4) not in t.red_cells
    assert t.rows[-1] == ["合计", 3, 1, 4, 2]


def test_matrix_both_cells_red_no_cross_store_offset():
    d = [date(2026, 1, 1)]
    ver = {d[0]: Counter(a=2, b=0)}
    vis = {d[0]: Counter(a=1, b=1)}
    _, by_day, mx = verification_vs_visit("x", "门店", [("a", "A"), ("b", "B")], ver, vis, d)
    assert by_day.rows[0][3] == 1            # not 2-2=0: stores don't offset each other
    assert {(0, 1), (0, 2)} <= mx.red_cells and (0, 3) not in mx.red_cells


def test_group_matcher_alias_and_ambiguity():
    m = GroupMatcher([{"id": "a", "name": "A店", "aliases": ["一号"]}, {"id": "b", "name": "B店"}])
    assert m.match("一号") == "a" and m.match("城市A店旗舰") == "a" and m.match("A店B店") is None


def test_contact_key_normalizes_and_hides():
    assert contact_key("100-0000-0001") == contact_key("10000000001")
    assert "10000000001" not in contact_key("10000000001")
