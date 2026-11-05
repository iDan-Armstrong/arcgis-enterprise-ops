from dataclasses import replace
from datetime import UTC, datetime, timedelta

from conftest import BASE, DS_REL, FakeSite, datastore_routes, fixture

from egisops import datastore
from egisops.client import ServerAdmin
from egisops.findings import Severity

# The relational example's last backup is 1658732403060 (2022-07-25 07:00 UTC).
BACKUP = datetime.fromtimestamp(1658732403060 / 1000, tz=UTC)
NOW = BACKUP + timedelta(days=1)


def snapshot(overrides=None, machine=None):
    site = FakeSite(datastore_routes(overrides))
    admin = ServerAdmin(BASE, site)
    admin.login("siteadmin", "pw")
    return datastore.gather(admin, machine=machine), site


def by_code(findings, code):
    return [f for f in findings if f.code == code]


def test_documented_examples():
    snap, site = snapshot()
    assert [s.kind for s in snap.stores] == ["relational", "tileCache"]
    f = datastore.evaluate(snap, NOW)
    assert by_code(f, "DST000")[0].title == "2 data store(s) validated (relational, tile cache)"
    # unmanaged registered databases are not validated as data stores
    assert not any("database1" in r[1] for r in site.requests)
    # Esri's tile cache example says Healthy while listing an unavailable machine
    un = by_code(f, "DST002")[0]
    assert un.severity == Severity.WARN and un.title.endswith("1 of 3 machine(s) unavailable")
    assert "MACHINE3.EXAMPLE.COM" in un.detail
    assert not by_code(f, "DST001")
    assert by_code(f, "DST003")[0].severity == Severity.INFO
    b = by_code(f, "DST005")[0]
    assert b.severity == Severity.OK and b.title.endswith("newest backup 1.0 days old")


def test_find_items_requests():
    _, site = snapshot()
    finds = [r[2] for r in site.requests if r[1].endswith("/data/findItems")]
    assert {"parentPath": "/enterpriseDatabases", "types": "egdb"}.items() <= finds[0].items()
    assert finds[1]["parentPath"] == "/nosqlDatabases"


def test_stale_and_missing_backup():
    snap, _ = snapshot()
    f = by_code(datastore.evaluate(snap, BACKUP + timedelta(days=9)), "DST005")[0]
    assert f.severity == Severity.WARN and "7-day target" in f.detail
    v = fixture("validate_relational.json")
    v["datastore.lastbackup"] = -1
    snap, _ = snapshot({("POST", DS_REL): (200, v)})
    f = by_code(datastore.evaluate(snap, NOW), "DST005")[0]
    assert f.severity == Severity.WARN and "no backup recorded" in f.title


def test_primary_down_fails():
    v = fixture("validate_relational.json")
    v["machines"][0]["machine.isReachable"] = "false"
    v["machines"][0]["status"] = "Stopped"
    v["datastore.overallhealth"] = "Unhealthy"
    snap, _ = snapshot({("POST", DS_REL): (200, v)})
    f = datastore.evaluate(snap, NOW)
    assert by_code(f, "DST001")[0].severity == Severity.FAIL
    m = by_code(f, "DST002")[0]
    assert m.severity == Severity.FAIL and "not reachable, status Stopped" in m.title


def test_standby_down_warns_and_no_standby_info_goes_away():
    v = fixture("validate_relational.json")
    standby = dict(v["machines"][0], name="MACHINE2.EXAMPLE.COM", role="STANDBY")
    standby["db.isAccepting"] = "false"
    v["machines"].append(standby)
    snap, _ = snapshot({("POST", DS_REL): (200, v)})
    f = datastore.evaluate(snap, NOW)
    m = [x for x in by_code(f, "DST002") if "MACHINE2" in x.title][0]
    assert m.severity == Severity.WARN and "not accepting" in m.title
    assert not by_code(f, "DST003")


def test_lost_server_connection():
    v = fixture("validate_relational.json")
    v["datastore.hasValidServerConnection"] = "false"
    snap, _ = snapshot({("POST", DS_REL): (200, v)})
    f = by_code(datastore.evaluate(snap, NOW), "DST004")[0]
    assert f.severity == Severity.FAIL and "no valid connection" in f.title


def test_spatiotemporal_cluster():
    h = datastore.parse_validation(
        "/nosqlDatabases/AGSDataStore_bigdata_bds_123e45vf", fixture("validate_bigdata.json")
    )
    assert h.kind == "spatiotemporal"
    snap = datastore.DataStoreSnapshot(BASE, [h])
    assert by_code(datastore.evaluate(snap, NOW), "DST006")[0].severity == Severity.OK
    for status, shards, sev in [
        ("YELLOW", 0, Severity.WARN),
        ("RED", 4, Severity.FAIL),
        ("GREEN", 2, Severity.WARN),
    ]:
        d = replace(h, cluster_status=status, unassigned_shards=shards)
        f = by_code(datastore.evaluate(datastore.DataStoreSnapshot(BASE, [d]), NOW), "DST006")[0]
        assert f.severity == sev, status


def test_machine_name_missing_asks_for_flag():
    items = fixture("find_items_egdb.json")
    del items["items"][1]["info"]["machines"]
    snap, _ = snapshot(
        {
            ("POST", "/admin/data/findItems"): (
                200,
                lambda form: (
                    items if form.get("parentPath") == "/enterpriseDatabases" else {"items": []}
                ),
            )
        }
    )
    f = datastore.evaluate(snap, NOW)
    assert "--machine" in by_code(f, "DST009")[0].detail
    snap, _ = snapshot(
        {
            ("POST", "/admin/data/findItems"): (
                200,
                lambda form: (
                    items if form.get("parentPath") == "/enterpriseDatabases" else {"items": []}
                ),
            )
        },
        machine="MACHINE.EXAMPLE.COM",
    )
    assert len(snap.stores) == 1 and not snap.errors


def test_no_data_store_registered():
    snap, _ = snapshot({("POST", "/admin/data/findItems"): (200, {"items": []})})
    f = datastore.evaluate(snap, NOW)
    assert f[0].code == "DST000" and f[0].severity == Severity.WARN


def test_backup_time_in_seconds_is_accepted():
    v = fixture("validate_relational.json")
    v["datastore.lastbackup"] = 1658732403
    h = datastore.parse_validation("/enterpriseDatabases/x", v)
    assert h.last_backup == BACKUP.replace(microsecond=0)
