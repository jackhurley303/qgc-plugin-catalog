import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


ENTRY_SCHEMA = _load(ROOT / "schema" / "entry.schema.json")
INDEX_SCHEMA = _load(ROOT / "schema" / "index.schema.json")

# The index schema refers to "entry.schema.json" by relative name.
_REGISTRY = Registry().with_resource(
    ENTRY_SCHEMA["$id"].rsplit("/", 1)[0] + "/entry.schema.json",
    Resource.from_contents(ENTRY_SCHEMA),
)


def _entry_errors(entry: dict) -> list[str]:
    return [e.message for e in Draft202012Validator(ENTRY_SCHEMA).iter_errors(entry)]


def _index_errors(index: dict) -> list[str]:
    validator = Draft202012Validator(INDEX_SCHEMA, registry=_REGISTRY)
    return [e.message for e in validator.iter_errors(index)]


def _good(name: str) -> dict:
    return _load(FIXTURES / f"good-{name}.json")


def _first_package(entry: dict) -> dict:
    return next(iter(entry["versions"][0]["packages"].values()))


def _drop_sha256(entry: dict) -> None:
    del _first_package(entry)["sha256"]


def _any_on_sdk(entry: dict) -> None:
    packages = entry["versions"][0]["packages"]
    packages["any"] = packages.pop("macos-universal")


def _unknown_platform_key(entry: dict) -> None:
    packages = entry["versions"][0]["packages"]
    packages["freebsd-x64"] = packages.pop("macos-universal")


def _unknown_entry_field(entry: dict) -> None:
    entry["sumary"] = "typo"


def _unknown_version_field(entry: dict) -> None:
    entry["versions"][0]["note"] = "typo"


def _unknown_package_field(entry: dict) -> None:
    _first_package(entry)["md5"] = "abc"


def _prerelease_version(entry: dict) -> None:
    entry["versions"][0]["version"] = "1.0.0-beta1"


def _uppercase_sha256(entry: dict) -> None:
    package = _first_package(entry)
    package["sha256"] = package["sha256"].upper()


def _http_package_url(entry: dict) -> None:
    package = _first_package(entry)
    package["url"] = package["url"].replace("https://", "http://")


def _zero_size(entry: dict) -> None:
    _first_package(entry)["size"] = 0


def _no_apiversion(entry: dict) -> None:
    del entry["versions"][0]["apiVersion"]


def _no_versions(entry: dict) -> None:
    entry["versions"] = []


def _no_packages(entry: dict) -> None:
    entry["versions"][0]["packages"] = {}


def _non_github_repository(entry: dict) -> None:
    entry["repository"] = "https://gitlab.com/example-author/hello-sdk"


def _bad_tier(entry: dict) -> None:
    entry["versions"][0]["tier"] = "internal"


def _no_host_min(entry: dict) -> None:
    del entry["versions"][0]["hostVersion"]["min"]


SDK_REFUSALS = [
    pytest.param(_drop_sha256, "'sha256' is a required", id="missing-sha256"),
    pytest.param(_any_on_sdk, "'any' should not be valid", id="any-on-sdk-tier"),
    pytest.param(_unknown_platform_key, "'freebsd-x64' is not one of", id="unknown-platform-key"),
    pytest.param(_unknown_entry_field, "'sumary' was unexpected", id="unknown-entry-field"),
    pytest.param(_unknown_version_field, "'note' was unexpected", id="unknown-version-field"),
    pytest.param(_unknown_package_field, "'md5' was unexpected", id="unknown-package-field"),
    pytest.param(_prerelease_version, "'1.0.0-beta1' does not match", id="prerelease-version"),
    pytest.param(_uppercase_sha256, "does not match '^[0-9a-f]{64}$'", id="uppercase-sha256"),
    pytest.param(_http_package_url, "does not match '^https://'", id="http-package-url"),
    pytest.param(_zero_size, "less than the minimum of 1", id="zero-size"),
    pytest.param(_no_apiversion, "'apiVersion' is a required", id="sdk-without-apiversion"),
    pytest.param(_no_versions, "should be non-empty", id="no-versions"),
    pytest.param(_no_packages, "should be non-empty", id="no-packages"),
    pytest.param(_non_github_repository, "gitlab.com", id="non-github-repository"),
    pytest.param(_bad_tier, "'internal' is not one of", id="unknown-tier"),
    pytest.param(_no_host_min, "'min' is a required", id="missing-host-min"),
]


def _bad_host_max(entry: dict) -> None:
    entry["versions"][0]["hostVersion"]["max"] = "six"


def _bad_released(entry: dict) -> None:
    entry["versions"][0]["released"] = "10/02/2026"


def _zero_apiversion(entry: dict) -> None:
    entry["versions"][0]["apiVersion"] = 0


def _float_apiversion(entry: dict) -> None:
    entry["versions"][0]["apiVersion"] = 2.5


def _http_icon(entry: dict) -> None:
    entry["icon"] = "http://example.org/icon.svg"


def _zero_qml_apiversion(entry: dict) -> None:
    entry["versions"][0]["qmlApiVersion"] = 0


def _qml_without_packages(entry: dict) -> None:
    entry["versions"][0]["packages"] = {}


def _qml_drop_sha256(entry: dict) -> None:
    del entry["versions"][0]["packages"]["any"]["sha256"]


QML_REFUSALS = [
    pytest.param(_bad_host_max, "'six' does not match", id="bad-host-max"),
    pytest.param(_bad_released, "'10/02/2026' does not match", id="bad-released-date"),
    pytest.param(_zero_apiversion, "less than the minimum of 1", id="zero-apiversion"),
    pytest.param(_float_apiversion, "is not of type 'integer'", id="float-apiversion"),
    pytest.param(_http_icon, "does not match '^https://'", id="http-icon"),
    pytest.param(_zero_qml_apiversion, "less than the minimum of 1", id="zero-qmlapiversion"),
    pytest.param(_qml_without_packages, "should be non-empty", id="qml-no-packages"),
    pytest.param(_qml_drop_sha256, "'sha256' is a required", id="qml-missing-sha256"),
]


@pytest.mark.parametrize(("mutate", "expected"), QML_REFUSALS)
def test_bad_qml_entry_is_refused(mutate, expected):
    entry = copy.deepcopy(_good("qml"))
    mutate(entry)
    assert expected in "\n".join(_entry_errors(entry))


VERIFICATION_SCHEMA = _load(ROOT / "schema" / "verification.schema.json")


@pytest.mark.parametrize(
    "schema",
    [ENTRY_SCHEMA, INDEX_SCHEMA, VERIFICATION_SCHEMA],
    ids=["entry", "index", "verification"],
)
def test_schema_is_itself_valid(schema):
    Draft202012Validator.check_schema(schema)


VERIFIED = {"reviewer": "jackhurley303", "date": "2026-10-04", "method": "maintainer-build"}


def test_index_package_may_carry_verified():
    entry = _good("sdk")
    _first_package(entry)["verified"] = dict(VERIFIED, method="attestation")
    index = {"schemaVersion": 1, "generated": "2026-10-04", "plugins": [entry]}
    assert _index_errors(index) == []


@pytest.mark.parametrize(
    ("verified", "expected"),
    [
        (True, "is not of type 'object'"),
        ({**VERIFIED, "method": "trust-me"}, "is not one of"),
        ({**VERIFIED, "reviewer": ""}, "does not match"),
        ({k: v for k, v in VERIFIED.items() if k != "date"}, "'date' is a required property"),
        ({**VERIFIED, "sourceCommit": "x"}, "Additional properties are not allowed"),
    ],
)
def test_malformed_verified_is_refused(verified, expected):
    entry = _good("sdk")
    _first_package(entry)["verified"] = verified
    assert expected in "\n".join(_entry_errors(entry))


@pytest.mark.parametrize("name", ["qml", "sdk"])
def test_good_entry_passes(name):
    assert _entry_errors(_good(name)) == []


@pytest.mark.parametrize(("mutate", "expected"), SDK_REFUSALS)
def test_bad_sdk_entry_is_refused(mutate, expected):
    entry = copy.deepcopy(_good("sdk"))
    mutate(entry)
    assert expected in "\n".join(_entry_errors(entry))


def test_qml_version_may_omit_apiversion():
    entry = _good("qml")
    assert "apiVersion" not in entry["versions"][0]
    assert _entry_errors(entry) == []


def test_qml_version_may_use_a_platform_key():
    entry = _good("qml")
    packages = entry["versions"][0]["packages"]
    packages["linux-x64"] = packages.pop("any")
    assert _entry_errors(entry) == []


def test_qml_version_rejects_unknown_platform_key():
    entry = _good("qml")
    packages = entry["versions"][0]["packages"]
    packages["freebsd-x64"] = packages.pop("any")
    assert _entry_errors(entry) != []


def test_optional_fields_may_be_absent():
    entry = _good("sdk")
    for field in ("homepage", "icon", "screenshots"):
        assert field not in entry
    assert _entry_errors(entry) == []


RELEASE_REPO = "https://github.com/example-author/hello-releases"


def _closed(entry: dict) -> dict:
    del entry["repository"]
    entry["releaseRepository"] = RELEASE_REPO
    return entry


def test_entry_with_only_a_release_repository_passes():
    assert _entry_errors(_closed(_good("qml"))) == []


def test_entry_with_both_repositories_passes():
    entry = _good("qml")
    entry["releaseRepository"] = RELEASE_REPO
    assert _entry_errors(entry) == []


def test_entry_with_neither_repository_is_refused():
    entry = _closed(_good("qml"))
    del entry["releaseRepository"]
    assert "is not valid under any of the given schemas" in "\n".join(_entry_errors(entry))


def test_non_github_release_repository_is_refused():
    entry = _closed(_good("qml"))
    entry["releaseRepository"] = "https://gitlab.com/example-author/hello-releases"
    assert "gitlab.com" in "\n".join(_entry_errors(entry))


def test_release_repository_with_a_path_is_refused():
    entry = _closed(_good("qml"))
    entry["releaseRepository"] = RELEASE_REPO + "/releases"
    assert "does not match" in "\n".join(_entry_errors(entry))


@pytest.mark.parametrize("field", ["repository", "releaseRepository"])
def test_repository_with_a_git_suffix_is_refused(field):
    entry = _good("qml")
    entry[field] = "https://github.com/example-author/hello-qml.git"
    assert "should not be valid under" in "\n".join(_entry_errors(entry))


def _index(*entries: dict) -> dict:
    return {"schemaVersion": 1, "generated": "2026-10-03", "plugins": list(entries)}


def test_good_index_passes():
    assert _index_errors(_index(_good("qml"), _good("sdk"))) == []


def test_empty_index_passes():
    assert _index_errors(_index()) == []


def test_index_with_schema_version_2_is_refused():
    index = _index(_good("qml"))
    index["schemaVersion"] = 2
    assert _index_errors(index) != []


def test_index_with_unknown_field_is_refused():
    index = _index(_good("qml"))
    index["extra"] = True
    assert _index_errors(index) != []


def test_index_without_generated_is_refused():
    index = _index(_good("qml"))
    del index["generated"]
    assert _index_errors(index) != []


def test_index_refuses_a_bad_entry():
    entry = _good("sdk")
    _drop_sha256(entry)
    assert _index_errors(_index(entry)) != []
