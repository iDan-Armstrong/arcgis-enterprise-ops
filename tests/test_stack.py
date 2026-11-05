import subprocess
import sys

import pytest
from conftest import BASE, FakeSite, datastore_routes, fixture

from egisops import stack
from egisops.client import ServerAdmin
from egisops.findings import Severity

rdsops = pytest.importorskip("rdsops", reason="stack-compat's database side needs rdsops")
DB, PRO = stack.rdsops_hooks()


def snap(**kw):
    comps = kw.pop(
        "components",
        [
            ("Portal for ArcGIS", "11.5.0"),
            ("ArcGIS Server (hosting)", "11.5.0.5450"),
            ("ArcGIS Data Store (ds_a)", "11.5.0.5440"),
        ],
    )
    return stack.StackSnapshot(components=[stack.Component(n, v) for n, v in comps], **kw)


def by_code(findings, code):
    return [f for f in findings if f.code == code]


def test_release_names():
    assert stack.release("11.5.0.5450") == "11.5"
    assert stack.release("10.9.1") == "10.9.1"
    assert stack.release("12.1") == "12.1"


def test_matching_base_deployment_and_supported_database():
    f = stack.evaluate(
        snap(engine_version="16.8", postgis_version="3.5.2", pro_version="3.5.1"), DB, PRO
    )
    assert by_code(f, "STK001")[0].title == "3 component(s) on ArcGIS Enterprise 11.5"
    assert {x.code: x.severity for x in f}["CMP001"] == Severity.OK
    assert by_code(f, "STK004")[0].severity == Severity.OK
    assert max(x.severity for x in f) <= Severity.INFO


def test_half_finished_upgrade_fails_and_gives_the_order():
    f = stack.evaluate(
        snap(
            components=[
                ("Portal for ArcGIS", "12.1.0"),
                ("ArcGIS Server (hosting)", "11.5.0"),
                ("ArcGIS Data Store (ds_a)", "11.5.0"),
            ]
        ),
        DB,
        PRO,
    )
    mixed = by_code(f, "STK001")[0]
    assert mixed.severity == Severity.FAIL and "11.5, 12.1" in mixed.title
    assert "Portal for ArcGIS, Web Adaptor for Portal, the hosting server" in mixed.detail


def test_data_stores_on_different_releases():
    f = stack.evaluate(
        snap(
            components=[
                ("ArcGIS Server (hosting)", "11.5"),
                ("ArcGIS Data Store (ds_a)", "11.5.0"),
                ("ArcGIS Data Store (tcs_b)", "11.4.0"),
            ]
        ),
        DB,
        PRO,
    )
    assert by_code(f, "STK002")[0].severity == Severity.FAIL


def test_database_unsupported_for_the_release_comes_from_rdsops():
    f = stack.evaluate(snap(engine_version="17.7", postgis_version="3.5.2"), DB, PRO)
    cmp1 = by_code(f, "CMP001")[0]
    assert cmp1.severity == Severity.FAIL and "11.5" in cmp1.title


def test_upgrade_plan_direct_with_database_minor_first():
    f = stack.evaluate(snap(engine_version="16.8", postgis_version="3.5.2", target="12.1"), DB, PRO)
    plan = by_code(f, "STK005")[0]
    assert plan.severity == Severity.WARN
    assert "11.5 upgrades directly to 12.1" in plan.detail
    assert "CMP002 RDS 16.8 is below the certified minimum 16.11" in plan.detail
    assert "WebGISDR backup" in plan.detail and "retired at 12.0" in plan.detail
    assert "Companion ArcGIS Pro for 12.1: 3.7" in plan.detail


def test_upgrade_plan_needs_an_interim_release():
    f = stack.evaluate(
        snap(components=[("ArcGIS Server (hosting)", "10.9.1")], target="12.1"), DB, PRO
    )
    plan = by_code(f, "STK005")[0]
    assert plan.severity == Severity.WARN and "latest direct target is 11.5" in plan.detail


def test_pro_not_companion_and_no_database_given():
    f = stack.evaluate(snap(pro_version="3.3"), DB, PRO)
    assert by_code(f, "STK004")[0].severity == Severity.INFO
    assert by_code(f, "STK003")[0].severity == Severity.INFO


def test_gather_reads_server_and_data_store_releases():
    site = FakeSite(datastore_routes({("POST", "/admin/"): (200, fixture("admin_root.json"))}))
    admin = ServerAdmin(BASE, site)
    admin.login("siteadmin", "pw")
    s = stack.gather(admin, portal_version="11.5.0")
    names = [c.name for c in s.components]
    assert names[:2] == ["Portal for ArcGIS", "ArcGIS Server (hosting)"]
    # Esri's validate examples are 11.0 and 10.8 data stores: a mixed stack on purpose
    f = stack.evaluate(s, DB, PRO)
    assert by_code(f, "STK001")[0].severity == Severity.FAIL
    assert by_code(f, "STK002")[0].severity == Severity.FAIL


def test_without_rdsops_the_database_side_says_so():
    code = (
        "import sys; sys.modules['rdsops'] = None\n"
        "from egisops import stack\n"
        "db, pro = stack.rdsops_hooks()\n"
        "assert db is None and pro is None\n"
        "c = [stack.Component('ArcGIS Server (hosting)', '11.5')]\n"
        "s = stack.StackSnapshot(c, engine_version='16.8')\n"
        "f = stack.evaluate(s, db, pro)\n"
        "assert [x.code for x in f] == ['STK001', 'STK009'], [x.code for x in f]\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_tile_cache_store_blocks_the_jump_to_12():
    comps = [("ArcGIS Server (hosting)", "11.5"), ("ArcGIS Data Store (tcs_b)", "11.5.0")]
    plan = by_code(stack.evaluate(snap(components=comps, target="12.1"), DB, PRO), "STK005")[0]
    assert (
        plan.severity == Severity.WARN
        and "tile cache data store (ArcGIS Data Store (tcs_b))" in plan.detail
    )
