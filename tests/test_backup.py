import json
import os
import shutil
from datetime import UTC, datetime, timedelta

import pytest
from conftest import FIXTURES

from egisops import backup
from egisops.findings import Severity

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
SECRETS = ("Th3.Ad.Pass", "p0rtl.a.p", "<key>")


def by_code(findings, code):
    return [f for f in findings if f.code == code]


def props(name):
    return str(FIXTURES / name)


def touch(folder, name, hours_ago, size=1024**3):
    path = folder / name
    path.write_bytes(b"\0" * min(size, 16))
    if size > 16:
        with open(path, "r+b") as fh:
            fh.truncate(size)
    t = (NOW - timedelta(hours=hours_ago)).timestamp()
    os.utime(path, (t, t))
    return path


def write_props(tmp_path, text):
    p = tmp_path / "webgisdr.properties"
    p.write_text(text)
    return str(p)


def test_parse_properties_decodes_escapes_and_keeps_raw():
    decoded, raw = backup.parse_properties(
        "# comment\n! also comment\nSHARED_LOCATION = \\\\\\\\myserver\\\\tempbackups\n"
        "A=1\nB : two\nLONG = first \\\n    second\n"
    )
    assert decoded["SHARED_LOCATION"] == "\\\\myserver\\tempbackups"
    assert raw["SHARED_LOCATION"] == "\\\\\\\\myserver\\\\tempbackups"
    assert decoded["A"] == "1" and decoded["B"] == "two" and decoded["LONG"] == "first second"


def test_esri_filesystem_example_lints_as_documented():
    snap = backup.gather(props("webgisdr_filesystem.properties"))
    f = backup.evaluate(snap, NOW)
    assert by_code(f, "BAK001")[0].severity == Severity.OK
    assert not by_code(f, "BAK002") and not by_code(f, "BAK003")
    plain = by_code(f, "BAK004")[0]
    assert plain.severity == Severity.WARN and "PORTAL_ADMIN_PASSWORD" in plain.title
    # the UNC backup location is not readable here: said so, not ignored
    assert "--backups" in by_code(f, "BAK009")[0].detail


def test_esri_s3_and_azure_examples():
    f = backup.evaluate(backup.gather(props("webgisdr_s3.properties")), NOW)
    assert by_code(f, "BAK001")[0].title == "Properties complete for AmazonS3"
    assert by_code(f, "BAK006")[0].severity == Severity.INFO  # no SHARED_LOCATION
    assert "INCLUDE_OBJECT_STORE_CACHES is true" in by_code(f, "BAK007")[0].detail
    f = backup.evaluate(backup.gather(props("webgisdr_azure.properties")), NOW)
    missing = [x for x in by_code(f, "BAK001") if x.severity == Severity.FAIL][0]
    assert missing.evidence["missing"] == ["AZURE_BLOB_CREDENTIALTYPE"]


def test_secrets_never_appear_in_findings_or_json(tmp_path):
    for name in (
        "webgisdr_filesystem.properties",
        "webgisdr_s3.properties",
        "webgisdr_azure.properties",
    ):
        snap = backup.gather(props(name), backups_dir=str(tmp_path))
        text = json.dumps([x.to_dict() for x in backup.evaluate(snap, NOW)], default=str)
        text += json.dumps(backup.safe_properties(snap.properties))
        assert not any(s in text for s in SECRETS), name


def test_single_backslashes_fail(tmp_path):
    path = write_props(
        tmp_path,
        "PORTAL_ADMIN_URL = https://p.example.com:7443/arcgis\nPORTAL_ADMIN_USERNAME = a\n"
        "PORTAL_ADMIN_PASSWORD = x\nPORTAL_ADMIN_PASSWORD_ENCRYPTED = true\n"
        "BACKUP_STORE_PROVIDER = Filesystem\nBACKUP_LOCATION = \\\\fileserver\\backups\n",
    )
    f = backup.evaluate(backup.gather(path, backups_dir=str(tmp_path)), NOW)
    bad = by_code(f, "BAK003")[0]
    assert bad.severity == Severity.FAIL and "'\\\\fileserverbackups'" in bad.detail
    assert by_code(f, "BAK001")[0].title == "Properties complete for FileSystem"  # either case
    assert not by_code(f, "BAK004")  # encrypted after first run


def test_url_checks_and_mode(tmp_path):
    base = (
        "PORTAL_ADMIN_USERNAME = a\nPORTAL_ADMIN_PASSWORD = x\nBACKUP_STORE_PROVIDER = AmazonS3\n"
    )
    base += "S3_BUCKET = b\nS3_REGION = us-east-1\nS3_CREDENTIALTYPE = accessKey\n"
    path = write_props(tmp_path, base + "PORTAL_ADMIN_URL = http://p.example.com/portal\n")
    f = backup.evaluate(backup.gather(path), NOW)
    assert by_code(f, "BAK002")[0].severity == Severity.FAIL
    missing = [x for x in by_code(f, "BAK001") if x.severity == Severity.FAIL][0]
    assert missing.evidence["missing"] == ["S3_ACCESSKEY", "S3_SECRETKEY"]
    assert [x for x in by_code(f, "BAK004") if "access key" in x.title]
    path = write_props(
        tmp_path,
        base
        + "PORTAL_ADMIN_URL = https://gis.example.com/portal\nBACKUP_RESTORE_MODE = incremental\n",
    )
    f = backup.evaluate(backup.gather(path), NOW)
    assert by_code(f, "BAK002")[0].severity == Severity.WARN
    assert by_code(f, "BAK005")[0].severity == Severity.INFO


def test_backup_age_against_rpo(tmp_path):
    touch(tmp_path, "20261103-020000-EST-BACKUP.webgissite", 34)
    touch(tmp_path, "20261104-020000-EST-BACKUP.webgissite", 10)
    touch(tmp_path, "notes.txt", 1)
    snap = backup.gather(props("webgisdr_s3.properties"), backups_dir=str(tmp_path))
    f = by_code(backup.evaluate(snap, NOW), "BAK010")[0]
    assert f.severity == Severity.OK and f.title.startswith("Newest backup 10.0 hours old")
    for hours, sev in [(30, Severity.WARN), (80, Severity.FAIL)]:
        f = by_code(backup.evaluate(snap, NOW + timedelta(hours=hours)), "BAK010")[0]
        assert f.severity == sev, hours


def test_restore_picks_newest_by_modified_time_not_name(tmp_path):
    # Esri: a folder restore takes the newest file by last-modified time, not by name.
    touch(tmp_path, "20261104-020000-EST-BACKUP.webgissite", 50)
    touch(tmp_path, "copied-old.webgissite", 2)
    snap = backup.gather(props("webgisdr_s3.properties"), backups_dir=str(tmp_path))
    assert "copied-old.webgissite" in by_code(backup.evaluate(snap, NOW), "BAK010")[0].title


def test_empty_and_missing_backups(tmp_path):
    snap = backup.gather(props("webgisdr_s3.properties"), backups_dir=str(tmp_path))
    f = by_code(backup.evaluate(snap, NOW), "BAK010")
    assert f[0].severity == Severity.FAIL and f[0].title == "No backup files found"
    touch(tmp_path, "20261104-020000-EST-BACKUP.webgissite", 1, size=0)
    snap = backup.gather(props("webgisdr_s3.properties"), backups_dir=str(tmp_path))
    f = by_code(backup.evaluate(snap, NOW), "BAK010")
    assert [x.severity for x in f] == [Severity.WARN, Severity.FAIL]


def test_incremental_backups_name_the_last_full(tmp_path):
    touch(tmp_path, "20261101-020000-EST-FULL.webgissite", 80)
    touch(tmp_path, "20261104-020000-EST-INCREMENTAL.webgissite", 3)
    snap = backup.gather(props("webgisdr_s3.properties"), backups_dir=str(tmp_path))
    f = by_code(backup.evaluate(snap, NOW), "BAK010")[0]
    assert "Newest full backup: 20261101-020000-EST-FULL.webgissite" in f.detail


def test_output_files_success_failure_and_missing_backup(tmp_path):
    ok = tmp_path / "ok.json"
    shutil.copy(FIXTURES / "webgisdr_output_success.json", ok)
    os.utime(ok, (NOW.timestamp(), NOW.timestamp()))
    snap = backup.gather(props("webgisdr_s3.properties"), outputs=[str(ok)])
    f = by_code(backup.evaluate(snap, NOW), "BAK011")
    assert f[0].severity == Severity.OK and "00hr:13min:24sec" in f[0].title
    bad = tmp_path / "bad.json"
    shutil.copy(FIXTURES / "webgisdr_output_failure.json", bad)
    t = (NOW + timedelta(minutes=5)).timestamp()
    os.utime(bad, (t, t))
    snap = backup.gather(props("webgisdr_s3.properties"), outputs=[str(ok), str(bad)])
    f = by_code(backup.evaluate(snap, NOW), "BAK011")
    assert len(f) == 1 and f[0].severity == Severity.FAIL
    assert "ArcGIS Data Store (relational)" in f[0].title and "Unable to connect" in f[0].detail
    # a successful run whose file is not in the backup folder
    folder = tmp_path / "backups"
    folder.mkdir()
    touch(folder, "other.webgissite", 1)
    snap = backup.gather(
        props("webgisdr_s3.properties"), backups_dir=str(folder), outputs=[str(ok)]
    )
    f = by_code(backup.evaluate(snap, NOW), "BAK011")
    assert f[1].severity == Severity.WARN and "20221123-133229-PST-FULL.webgissite" in f[1].title


def test_unreadable_files_are_findings(tmp_path):
    snap = backup.gather(str(tmp_path / "nope.properties"), outputs=[str(tmp_path / "x.json")])
    f = backup.evaluate(snap, NOW)
    assert [x.code for x in f] == ["BAK009", "BAK009"]


@pytest.mark.parametrize("name", ["20221123-133229-PST-FULL.webgissite", "x.webgissite"])
def test_mode_from_name(name):
    assert backup.mode_from_name(name) == ("full" if "FULL" in name else None)
